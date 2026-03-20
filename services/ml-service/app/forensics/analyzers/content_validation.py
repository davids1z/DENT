"""
Content Validation Module: OCR + OIB/IBAN validation for Croatian documents.

Extracts text from documents (embedded or via OCR for scanned PDFs) and validates
Croatian personal/financial identifiers:

- OIB (Personal Identification Number): ISO 7064 MOD 11,10 check
- IBAN (International Bank Account Number): ISO 7064 MOD-97-10 check

Invalid identifiers in a document are a strong indicator of forgery.
"""

import io
import logging
import re
import time
import zipfile
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

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------
_OIB_PATTERN = re.compile(r"\b(\d{11})\b")
_IBAN_PATTERN = re.compile(r"\b(HR\d{19})\b", re.IGNORECASE)


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


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class ContentValidationAnalyzer(BaseAnalyzer):
    """OCR text extraction + OIB/IBAN validation for Croatian documents."""

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

        except Exception as e:
            logger.warning("Content validation error: %s", e)
            return self._make_result(
                [], int((time.monotonic() - start) * 1000), error=str(e)
            )

        elapsed = int((time.monotonic() - start) * 1000)
        return self._make_result(findings, elapsed)

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
