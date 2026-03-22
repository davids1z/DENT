"""
Content Validation Module: OCR + OIB/IBAN/JIR/ZKI validation for Croatian documents.

Extracts text from documents (embedded or via OCR for scanned PDFs) and validates
Croatian personal/financial identifiers and invoice integrity:

- OIB (Personal Identification Number): ISO 7064 MOD 11,10 check
- IBAN (International Bank Account Number): ISO 7064 MOD-97-10 check
- JIR (Jedinstveni Identifikator Racuna): UUID format validation
- ZKI (Zastitni Kod Izdavatelja): 32-char hex validation
- QR code cross-validation against JIR in text
- Mathematical consistency: line-item sum vs total
- Temporal consistency: text dates vs metadata dates

Invalid identifiers or mathematical inconsistencies are strong indicators of forgery.
"""

import io
import logging
import re
import time
import zipfile
from datetime import datetime, timezone
from xml.etree import ElementTree

from ..base import AnalyzerFinding, BaseAnalyzer, ModuleResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------
_FITZ_AVAILABLE = False
try:
    import fitz

    _FITZ_AVAILABLE = True
except ImportError:
    pass

_TESSERACT_AVAILABLE = False
try:
    import pytesseract

    _TESSERACT_AVAILABLE = True
except ImportError:
    logger.info("pytesseract not installed — OCR disabled for content validation")

_PIL_AVAILABLE = False
try:
    from PIL import Image

    _PIL_AVAILABLE = True
except ImportError:
    pass

_PYZBAR_AVAILABLE = False
try:
    from pyzbar.pyzbar import decode as decode_qr

    _PYZBAR_AVAILABLE = True
except ImportError:
    logger.info("pyzbar not installed — QR code validation disabled")

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------
_OIB_PATTERN = re.compile(r"\b(\d{11})\b")
_IBAN_PATTERN = re.compile(r"\b(HR\d{19})\b", re.IGNORECASE)

# JIR: UUID format (8-4-4-4-12 hex)
_JIR_PATTERN = re.compile(
    r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b",
    re.IGNORECASE,
)

# ZKI: 32-char hex string (MD5-like)
_ZKI_PATTERN = re.compile(r"\b([0-9a-f]{32})\b", re.IGNORECASE)

# Croatian invoice keywords
_INVOICE_KEYWORDS = re.compile(
    r"\b(ra[cč]un|faktura|r-\d|ra[cč]un\s*br|invoice)\b", re.IGNORECASE
)

# Amount pattern: 1.234,56 or 1,234.56 with optional currency
_AMOUNT_PATTERN = re.compile(
    r"(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})\s*(?:EUR|HRK|kn|€)?",
    re.IGNORECASE,
)

# Total keywords (Croatian + English)
_TOTAL_KEYWORDS = re.compile(
    r"\b(ukupno|total|za\s*platiti|iznos|sveukupno|suma|grand\s*total|subtotal)\b",
    re.IGNORECASE,
)

# VAT/PDV patterns
_VAT_PATTERN = re.compile(
    r"\b(?:PDV|VAT|porez)\s*(?:\(?\s*(\d{1,2})\s*%\s*\)?)",
    re.IGNORECASE,
)

# Date pattern: DD.MM.YYYY or DD/MM/YYYY
_DATE_PATTERN = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")


# ---------------------------------------------------------------------------
# Validation algorithms
# ---------------------------------------------------------------------------


def validate_oib(oib: str) -> bool:
    """Validate Croatian OIB using ISO 7064 MOD 11,10.

    Algorithm (iterative over first 10 digits):
      1. remainder = (remainder + digit) % 10; if 0 → 10
      2. remainder = (remainder * 2) % 11
      3. check = 11 - remainder; if 10 → 0
      4. Valid iff check == 11th digit.
    """
    if len(oib) != 11 or not oib.isdigit():
        return False

    remainder = 10
    for i in range(10):
        remainder = (remainder + int(oib[i])) % 10
        if remainder == 0:
            remainder = 10
        remainder = (remainder * 2) % 11

    check = 11 - remainder
    if check == 10:
        check = 0

    return check == int(oib[10])


def validate_iban_hr(iban: str) -> bool:
    """Validate Croatian IBAN using ISO 7064 MOD-97-10.

    Format: HR + 2 check digits + 17 digits = 21 chars.
    1. Move first 4 chars to end.
    2. Replace letters with numbers (A=10 … Z=35).
    3. Result mod 97 must equal 1.
    """
    iban = iban.upper().replace(" ", "")

    if len(iban) != 21:
        return False
    if not iban.startswith("HR"):
        return False
    if not iban[2:].isdigit():
        return False

    # Move first 4 chars to end
    rearranged = iban[4:] + iban[:4]

    # Replace letters with numbers
    numeric_str = ""
    for ch in rearranged:
        if ch.isdigit():
            numeric_str += ch
        elif ch.isalpha():
            numeric_str += str(ord(ch) - ord("A") + 10)
        else:
            return False

    return int(numeric_str) % 97 == 1


def _parse_amount(amount_str: str) -> float | None:
    """Parse a European-format amount string to float.

    Handles: 1.234,56 → 1234.56 and 1,234.56 → 1234.56
    """
    s = amount_str.strip()
    if not s:
        return None

    # Determine format: last separator is decimal
    dot_pos = s.rfind(".")
    comma_pos = s.rfind(",")

    if comma_pos > dot_pos:
        # European: 1.234,56
        s = s.replace(".", "").replace(",", ".")
    else:
        # US/UK: 1,234.56
        s = s.replace(",", "")

    try:
        val = float(s)
        return val if val > 0 else None
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_trivial_number(s: str) -> bool:
    """Filter 11-digit sequences that are clearly not OIBs."""
    if len(set(s)) == 1:
        return True
    if s in ("01234567890", "12345678901", "00000000000"):
        return True
    return False


def _mask_oib(oib: str) -> str:
    """Mask OIB for evidence storage: show first 3 and last 2 digits."""
    return oib[:3] + "******" + oib[-2:]


def _mask_iban(iban: str) -> str:
    """Mask IBAN for evidence storage: show HR + first 4 and last 4."""
    return iban[:6] + "***********" + iban[-4:]


def _parse_pdf_date(date_str: str | None) -> datetime | None:
    """Parse a PDF date string (D:YYYYMMDDHHmmSS) into datetime."""
    if not date_str:
        return None
    s = date_str.strip()
    if s.startswith("D:"):
        s = s[2:]
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y%m%d"):
        try:
            clean = re.split(r"[+\-Z]", s)[0]
            return datetime.strptime(clean, fmt).replace(tzinfo=timezone.utc)
        except (ValueError, IndexError):
            continue
    return None


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class ContentValidationAnalyzer(BaseAnalyzer):
    """OCR text extraction + OIB/IBAN/JIR/ZKI validation for Croatian documents."""

    MODULE_NAME = "content_validation"
    MODULE_LABEL = "Validacija sadrzaja (OIB/IBAN)"

    def __init__(self, ocr_lang: str = "hrv+eng") -> None:
        self._ocr_lang = ocr_lang

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        """Content validation is not applicable to standalone images."""
        return self._make_result([], 0)

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        start = time.monotonic()
        findings: list[AnalyzerFinding] = []

        try:
            fn_lower = filename.lower()
            used_ocr = False

            if fn_lower.endswith(".pdf"):
                text, used_ocr = self._extract_text_from_pdf(doc_bytes)
            elif fn_lower.endswith(".docx"):
                text = self._extract_text_from_docx(doc_bytes)
            elif fn_lower.endswith(".xlsx"):
                text = self._extract_text_from_xlsx(doc_bytes)
            else:
                return self._make_result([], int((time.monotonic() - start) * 1000))

            if not text or not text.strip():
                return self._make_result([], int((time.monotonic() - start) * 1000))

            # Informational: OCR was used
            if used_ocr:
                findings.append(
                    AnalyzerFinding(
                        code="CONTENT_OCR_USED",
                        title="Tekst ekstrahiran putem OCR-a",
                        description=(
                            "PDF ne sadrzi ugradeni tekst (skeniran dokument). "
                            "Tekst je ekstrahiran pomocu optickog prepoznavanja "
                            "znakova (OCR)."
                        ),
                        risk_score=0.0,
                        confidence=0.60,
                        evidence={"method": "tesseract_ocr", "language": self._ocr_lang},
                    )
                )

            # Confidence is lower when text came from OCR (digit misread risk)
            base_confidence = 0.75 if used_ocr else 0.95

            # --- OIB validation ---
            oib_matches = _OIB_PATTERN.findall(text)
            oib_candidates = [m for m in set(oib_matches) if not _is_trivial_number(m)]

            invalid_oibs: list[str] = []
            valid_oibs: list[str] = []
            for oib in oib_candidates:
                if validate_oib(oib):
                    valid_oibs.append(oib)
                else:
                    invalid_oibs.append(oib)

            # --- IBAN validation ---
            iban_matches = _IBAN_PATTERN.findall(text)
            invalid_ibans: list[str] = []
            valid_ibans: list[str] = []
            for iban in set(iban_matches):
                if validate_iban_hr(iban.upper()):
                    valid_ibans.append(iban.upper())
                else:
                    invalid_ibans.append(iban.upper())

            # --- Emit findings ---
            if invalid_oibs:
                findings.append(
                    AnalyzerFinding(
                        code="CONTENT_INVALID_OIB",
                        title="Nevazeci OIB u dokumentu",
                        description=(
                            f"Pronadeno {len(invalid_oibs)} nevazecih OIB brojeva "
                            f"u dokumentu. Kontrolna znamenka ne odgovara ISO 7064 "
                            f"MOD 11,10 standardu. Ovo je jasan indikator "
                            f"krivotvorenja ili greske u dokumentu."
                        ),
                        risk_score=0.75,
                        confidence=base_confidence,
                        evidence={
                            "invalid_oibs": [_mask_oib(o) for o in invalid_oibs],
                            "count": len(invalid_oibs),
                            "validation": "ISO 7064 MOD 11,10",
                            "ocr_used": used_ocr,
                        },
                    )
                )

            if invalid_ibans:
                findings.append(
                    AnalyzerFinding(
                        code="CONTENT_INVALID_IBAN",
                        title="Nevazeci IBAN u dokumentu",
                        description=(
                            f"Pronadeno {len(invalid_ibans)} nevazecih IBAN brojeva "
                            f"u dokumentu. Kontrolni broj ne odgovara ISO 7064 "
                            f"MOD-97-10 standardu. Ovo je jasan indikator "
                            f"krivotvorenja ili greske u dokumentu."
                        ),
                        risk_score=0.75,
                        confidence=base_confidence,
                        evidence={
                            "invalid_ibans": [_mask_iban(i) for i in invalid_ibans],
                            "count": len(invalid_ibans),
                            "validation": "ISO 7064 MOD-97-10",
                            "ocr_used": used_ocr,
                        },
                    )
                )

            # Trust signal: all identifiers valid
            total_found = (
                len(valid_oibs) + len(valid_ibans)
                + len(invalid_oibs) + len(invalid_ibans)
            )
            if total_found > 0 and not invalid_oibs and not invalid_ibans:
                findings.append(
                    AnalyzerFinding(
                        code="CONTENT_VALID_IDENTIFIERS",
                        title="Svi identifikatori valjani",
                        description=(
                            f"Svi pronadeni identifikatori ({len(valid_oibs)} OIB, "
                            f"{len(valid_ibans)} IBAN) imaju ispravne kontrolne "
                            f"znamenke."
                        ),
                        risk_score=-0.10,
                        confidence=0.90,
                        evidence={
                            "valid_oib_count": len(valid_oibs),
                            "valid_iban_count": len(valid_ibans),
                        },
                    )
                )

            # --- JIR/ZKI fiscalization validation ---
            self._validate_jir_zki(text, findings)

            # --- QR code cross-validation (PDF only) ---
            if fn_lower.endswith(".pdf"):
                self._validate_qr_code(doc_bytes, text, findings)

            # --- Mathematical consistency ---
            self._check_math_consistency(text, findings)

            # --- Temporal consistency (PDF only) ---
            if fn_lower.endswith(".pdf"):
                self._check_temporal_consistency(text, doc_bytes, findings)

        except Exception as e:
            logger.warning("Content validation error: %s", e)
            return self._make_result(
                [], int((time.monotonic() - start) * 1000), error=str(e)
            )

        elapsed = int((time.monotonic() - start) * 1000)
        return self._make_result(findings, elapsed)

    # ------------------------------------------------------------------
    # JIR / ZKI Fiscalization Validation
    # ------------------------------------------------------------------

    def _validate_jir_zki(
        self, text: str, findings: list[AnalyzerFinding]
    ) -> None:
        """Validate Croatian fiscalization codes (JIR and ZKI)."""
        jir_matches = _JIR_PATTERN.findall(text)
        zki_matches = _ZKI_PATTERN.findall(text)

        has_jir = len(jir_matches) > 0
        has_zki = len(zki_matches) > 0
        is_invoice = bool(_INVOICE_KEYWORDS.search(text))

        evidence = {
            "jir_found": len(jir_matches),
            "zki_found": len(zki_matches),
            "is_invoice_document": is_invoice,
        }

        if has_jir and has_zki:
            # Both present — trust signal
            findings.append(
                AnalyzerFinding(
                    code="CONTENT_FISCAL_VALID",
                    title="Fiskalizacijski kodovi prisutni",
                    description=(
                        f"Pronadeni JIR ({len(jir_matches)}) i ZKI ({len(zki_matches)}) "
                        f"kodovi u dokumentu. Prisutnost oba koda u ispravnom formatu "
                        f"konzistentna je s legitimnim fiskaliziranim racunom."
                    ),
                    risk_score=-0.05,
                    confidence=0.80,
                    evidence=evidence,
                )
            )
        elif has_jir != has_zki:
            # Only one present — suspicious on invoices
            present = "JIR" if has_jir else "ZKI"
            missing = "ZKI" if has_jir else "JIR"
            findings.append(
                AnalyzerFinding(
                    code="CONTENT_FISCAL_INCOMPLETE",
                    title="Nepotpuni fiskalizacijski kodovi",
                    description=(
                        f"Pronaden je {present} kod ali nedostaje {missing}. "
                        f"Legalni fiskalizirani racun mora sadrzavati oba koda. "
                        f"Prisutnost jednog bez drugog signalizira polovicno "
                        f"kopiranje s drugog racuna ili nepotpunu manipulaciju."
                    ),
                    risk_score=0.50,
                    confidence=0.75,
                    evidence=evidence,
                )
            )
        elif not has_jir and not has_zki and is_invoice:
            # Neither present on what looks like an invoice
            findings.append(
                AnalyzerFinding(
                    code="CONTENT_FISCAL_MISSING",
                    title="Nedostatak fiskalizacijskih kodova na racunu",
                    description=(
                        "Dokument izgleda kao racun/faktura, ali ne sadrzi JIR "
                        "niti ZKI fiskalizacijske kodove. U Hrvatskoj, svaki "
                        "legalno izdan racun mora sadrzavati ove kodove."
                    ),
                    risk_score=0.35,
                    confidence=0.65,
                    evidence=evidence,
                )
            )

    # ------------------------------------------------------------------
    # QR Code Cross-Validation
    # ------------------------------------------------------------------

    def _validate_qr_code(
        self, doc_bytes: bytes, text: str, findings: list[AnalyzerFinding]
    ) -> None:
        """Extract QR code from PDF and cross-validate with JIR in text."""
        if not _PYZBAR_AVAILABLE or not _FITZ_AVAILABLE or not _PIL_AVAILABLE:
            return

        # Only bother with QR if document has JIR codes
        jir_in_text = _JIR_PATTERN.findall(text)
        if not jir_in_text:
            return

        try:
            doc = fitz.open(stream=doc_bytes, filetype="pdf")
            if len(doc) == 0:
                doc.close()
                return

            # Rasterize first page at 200 DPI for QR detection
            page = doc[0]
            pix = page.get_pixmap(dpi=200)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            doc.close()

            # Decode QR codes
            qr_results = decode_qr(img)
            if not qr_results:
                return

            # Extract JIR from QR data
            for qr in qr_results:
                try:
                    qr_data = qr.data.decode("utf-8", errors="ignore")
                except Exception:
                    continue

                # Look for UUID pattern in QR data
                qr_jirs = _JIR_PATTERN.findall(qr_data)
                if not qr_jirs:
                    continue

                # Cross-validate: does QR JIR match text JIR?
                text_jir_set = {j.lower() for j in jir_in_text}
                qr_jir_set = {j.lower() for j in qr_jirs}

                if not text_jir_set.intersection(qr_jir_set):
                    findings.append(
                        AnalyzerFinding(
                            code="CONTENT_QR_JIR_MISMATCH",
                            title="Nepodudarnost JIR-a u QR kodu i tekstu",
                            description=(
                                "Desifrirani QR kod sadrzi razlicit JIR od onog "
                                "u tekstu racuna. Ovo je jasan dokaz manipulacije "
                                "— originalni QR kod i tekst racuna potjecu iz "
                                "razlicitih izvora."
                            ),
                            risk_score=0.80,
                            confidence=0.85,
                            evidence={
                                "qr_jir": qr_jirs[0][:8] + "...",
                                "text_jir": jir_in_text[0][:8] + "...",
                                "qr_data_length": len(qr_data),
                            },
                        )
                    )
                    return

        except Exception as e:
            logger.debug("QR validation error: %s", e)

    # ------------------------------------------------------------------
    # Mathematical Consistency
    # ------------------------------------------------------------------

    def _check_math_consistency(
        self, text: str, findings: list[AnalyzerFinding]
    ) -> None:
        """Check if line-item amounts sum to the stated total."""
        # Split text into lines for positional analysis
        lines = text.split("\n")

        # Find total line(s) and extract the total amount
        total_amount: float | None = None
        total_line_idx: int = -1

        for i, line in enumerate(lines):
            if _TOTAL_KEYWORDS.search(line):
                # Extract amount from this line
                amounts_in_line = _AMOUNT_PATTERN.findall(line)
                if amounts_in_line:
                    parsed = _parse_amount(amounts_in_line[-1])  # Last amount on total line
                    if parsed and parsed > 1.0:
                        total_amount = parsed
                        total_line_idx = i

        if total_amount is None:
            return  # No total found — can't validate

        # Extract all amounts from lines BEFORE the total
        line_item_amounts: list[float] = []
        for i, line in enumerate(lines):
            if i >= total_line_idx:
                break
            if _TOTAL_KEYWORDS.search(line):
                continue  # Skip subtotal/total lines

            amounts_in_line = _AMOUNT_PATTERN.findall(line)
            for amt_str in amounts_in_line:
                parsed = _parse_amount(amt_str)
                if parsed and 0.01 <= parsed < total_amount:
                    line_item_amounts.append(parsed)

        if len(line_item_amounts) < 3:
            return  # Not enough line items to validate

        # Sum line items and compare with total
        line_items_sum = sum(line_item_amounts)

        if line_items_sum <= 0:
            return

        # Calculate discrepancy
        discrepancy = abs(line_items_sum - total_amount) / total_amount

        evidence = {
            "total_stated": round(total_amount, 2),
            "line_items_sum": round(line_items_sum, 2),
            "line_items_count": len(line_item_amounts),
            "discrepancy_pct": round(discrepancy * 100, 2),
        }

        if discrepancy > 0.05:
            findings.append(
                AnalyzerFinding(
                    code="CONTENT_MATH_INCONSISTENT",
                    title="Matematicka nekonzistentnost iznosa",
                    description=(
                        f"Zbroj pojedinacnih stavki ({round(line_items_sum, 2)}) "
                        f"ne odgovara navedenom ukupnom iznosu ({round(total_amount, 2)}). "
                        f"Razlika od {round(discrepancy * 100, 1)}% je jasan indikator "
                        f"da je konacni iznos na racunu izmijenjen bez prilagodbe "
                        f"pojedinacnih stavki."
                    ),
                    risk_score=0.75,
                    confidence=0.70,
                    evidence=evidence,
                )
            )
        elif discrepancy > 0.01:
            findings.append(
                AnalyzerFinding(
                    code="CONTENT_MATH_INCONSISTENT",
                    title="Manja matematicka nekonzistentnost",
                    description=(
                        f"Razlika od {round(discrepancy * 100, 1)}% izmedu zbroja "
                        f"stavki i ukupnog iznosa. Moguce zaokruzivanje ili "
                        f"djelomicna manipulacija."
                    ),
                    risk_score=0.50,
                    confidence=0.60,
                    evidence=evidence,
                )
            )

        # VAT/PDV consistency check
        vat_matches = _VAT_PATTERN.findall(text)
        if vat_matches and total_amount:
            try:
                vat_rate = int(vat_matches[0]) / 100.0  # e.g., 25 → 0.25
                if 0.05 <= vat_rate <= 0.30:
                    # Find amounts that look like VAT amount near VAT keywords
                    for i, line in enumerate(lines):
                        if _VAT_PATTERN.search(line):
                            amounts = _AMOUNT_PATTERN.findall(line)
                            for amt_str in amounts:
                                vat_stated = _parse_amount(amt_str)
                                if vat_stated and vat_stated < total_amount:
                                    # Calculate expected VAT
                                    base = total_amount / (1 + vat_rate)
                                    expected_vat = base * vat_rate
                                    vat_diff = abs(vat_stated - expected_vat) / max(expected_vat, 0.01)

                                    if vat_diff > 0.05:
                                        findings.append(
                                            AnalyzerFinding(
                                                code="CONTENT_VAT_INCONSISTENT",
                                                title="Nekonzistentan iznos PDV-a",
                                                description=(
                                                    f"Navedeni PDV ({round(vat_stated, 2)}) ne odgovara "
                                                    f"ocekivanom iznosu ({round(expected_vat, 2)}) pri stopi "
                                                    f"od {int(vat_rate * 100)}%. Razlika od "
                                                    f"{round(vat_diff * 100, 1)}%."
                                                ),
                                                risk_score=0.65,
                                                confidence=0.70,
                                                evidence={
                                                    "vat_stated": round(vat_stated, 2),
                                                    "vat_expected": round(expected_vat, 2),
                                                    "vat_rate_pct": int(vat_rate * 100),
                                                    "total_amount": round(total_amount, 2),
                                                },
                                            )
                                        )
                                    return  # One VAT check is enough
            except (ValueError, ZeroDivisionError):
                pass

    # ------------------------------------------------------------------
    # Temporal Consistency
    # ------------------------------------------------------------------

    def _check_temporal_consistency(
        self, text: str, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Compare dates in document text with PDF metadata dates."""
        if not _FITZ_AVAILABLE:
            return

        # Get PDF creation date from metadata
        try:
            doc = fitz.open(stream=doc_bytes, filetype="pdf")
            meta = doc.metadata or {}
            creation_date_str = meta.get("creationDate", "")
            doc.close()
        except Exception:
            return

        creation_date = _parse_pdf_date(creation_date_str)
        if not creation_date:
            return

        # Extract dates from text
        date_matches = _DATE_PATTERN.findall(text)
        if not date_matches:
            return

        text_dates: list[datetime] = []
        for day_str, month_str, year_str in date_matches:
            try:
                day = int(day_str)
                month = int(month_str)
                year = int(year_str)
                if 1 <= day <= 31 and 1 <= month <= 12 and 2000 <= year <= 2030:
                    dt = datetime(year, month, day, tzinfo=timezone.utc)
                    text_dates.append(dt)
            except (ValueError, OverflowError):
                continue

        if not text_dates:
            return

        # Check for dates in text that are AFTER the metadata creation date
        for text_date in text_dates:
            delta_days = (text_date - creation_date).days

            if delta_days > 1:
                # Text claims a date AFTER the PDF was created
                findings.append(
                    AnalyzerFinding(
                        code="CONTENT_TEMPORAL_ANOMALY",
                        title="Vremenska anomalija u dokumentu",
                        description=(
                            f"Datum u tekstu dokumenta ({text_date.strftime('%d.%m.%Y')}) "
                            f"je {delta_days} dana kasniji od datuma stvaranja PDF-a "
                            f"prema metapodacima ({creation_date.strftime('%d.%m.%Y')}). "
                            f"Ovo ukazuje na post-hoc manipulaciju — tekst je izmijenjen "
                            f"nakon izvornog stvaranja dokumenta."
                        ),
                        risk_score=0.60,
                        confidence=0.75,
                        evidence={
                            "text_date": text_date.strftime("%d.%m.%Y"),
                            "creation_date": creation_date.strftime("%d.%m.%Y"),
                            "delta_days": delta_days,
                        },
                    )
                )
                return  # One temporal finding is enough

            if delta_days < -365:
                # Text date is more than 1 year before creation — suspicious but less so
                findings.append(
                    AnalyzerFinding(
                        code="CONTENT_TEMPORAL_ANOMALY",
                        title="Velika vremenska razlika u dokumentu",
                        description=(
                            f"Datum u tekstu ({text_date.strftime('%d.%m.%Y')}) "
                            f"prethodi datumu stvaranja PDF-a za vise od godinu dana. "
                            f"Moguce legitimno (skeniran stariji dokument) ili "
                            f"manipulacija datuma."
                        ),
                        risk_score=0.25,
                        confidence=0.60,
                        evidence={
                            "text_date": text_date.strftime("%d.%m.%Y"),
                            "creation_date": creation_date.strftime("%d.%m.%Y"),
                            "delta_days": delta_days,
                        },
                    )
                )
                return

    # ------------------------------------------------------------------
    # Text extraction
    # ------------------------------------------------------------------

    def _extract_text_from_pdf(self, doc_bytes: bytes) -> tuple[str, bool]:
        """Extract text from PDF. Returns (text, used_ocr).

        Tries embedded text first (PyMuPDF). If too little text found,
        falls back to OCR on rendered page images (max 5 pages).
        """
        if not _FITZ_AVAILABLE:
            return "", False

        text = ""
        used_ocr = False

        try:
            doc = fitz.open(stream=doc_bytes, filetype="pdf")

            # Try embedded text first
            pages_text = []
            for page in doc:
                pages_text.append(page.get_text())
            text = "\n\n".join(pages_text).strip()

            # If very little embedded text, try OCR
            if len(text) < 50 and _TESSERACT_AVAILABLE and _PIL_AVAILABLE:
                ocr_texts = []
                max_pages = min(len(doc), 5)
                for page_idx in range(max_pages):
                    page = doc[page_idx]
                    pix = page.get_pixmap(dpi=200)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    page_text = pytesseract.image_to_string(
                        img, lang=self._ocr_lang
                    )
                    ocr_texts.append(page_text)
                text = "\n\n".join(ocr_texts).strip()
                used_ocr = bool(text)

            doc.close()
        except Exception as e:
            logger.warning("PDF text extraction failed: %s", e)

        return text, used_ocr

    @staticmethod
    def _extract_text_from_docx(doc_bytes: bytes) -> str:
        """Extract text from DOCX via XML parsing."""
        try:
            with zipfile.ZipFile(io.BytesIO(doc_bytes)) as zf:
                if "word/document.xml" not in zf.namelist():
                    return ""
                xml_bytes = zf.read("word/document.xml")
                root = ElementTree.fromstring(xml_bytes)
                ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                texts = [t.text for t in root.iter(f"{{{ns['w']}}}t") if t.text]
                return " ".join(texts)
        except Exception as e:
            logger.warning("DOCX text extraction failed: %s", e)
            return ""

    @staticmethod
    def _extract_text_from_xlsx(doc_bytes: bytes) -> str:
        """Extract text from XLSX shared strings."""
        try:
            with zipfile.ZipFile(io.BytesIO(doc_bytes)) as zf:
                if "xl/sharedStrings.xml" not in zf.namelist():
                    return ""
                xml_bytes = zf.read("xl/sharedStrings.xml")
                root = ElementTree.fromstring(xml_bytes)
                ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
                texts = [t.text for t in root.iter(f"{{{ns}}}t") if t.text]
                return " ".join(texts)
        except Exception as e:
            logger.warning("XLSX text extraction failed: %s", e)
            return ""
