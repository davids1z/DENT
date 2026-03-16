"""Document forensics: PDF structure, metadata, font, and signature analysis."""

import io
import logging
import re
import time
from datetime import datetime, timezone

from ..base import AnalyzerFinding, BaseAnalyzer, ModuleResult

logger = logging.getLogger(__name__)

# Graceful degradation for optional libraries
_PYPDF_AVAILABLE = False
try:
    from pypdf import PdfReader

    _PYPDF_AVAILABLE = True
except ImportError:
    logger.info("pypdf not installed, PDF document forensics disabled")

_PYHANKO_AVAILABLE = False
try:
    from pyhanko.pdf_utils.reader import PdfFileReader as HankoPdfReader
    from pyhanko.sign.validation import validate_pdf_signature

    _PYHANKO_AVAILABLE = True
except ImportError:
    logger.info("pyhanko not installed, PDF signature verification disabled")

# Known PDF editing software (keyword_lower, risk_score, display_name)
PDF_EDITING_SOFTWARE: list[tuple[str, float, str]] = [
    ("pdftk", 0.45, "PDFtk"),
    ("itext", 0.40, "iText"),
    ("itextsharp", 0.40, "iTextSharp"),
    ("nitro", 0.40, "Nitro PDF"),
    ("qoppa", 0.40, "Qoppa PDF"),
    ("fpdf", 0.35, "FPDF"),
    ("tcpdf", 0.35, "TCPDF"),
    ("pdfsharp", 0.35, "PDFsharp"),
    ("foxit phantompdf", 0.35, "Foxit PhantomPDF"),
    ("reportlab", 0.30, "ReportLab"),
    ("adobe acrobat", 0.15, "Adobe Acrobat"),
    ("libreoffice", 0.10, "LibreOffice"),
    ("microsoft", 0.05, "Microsoft Office"),
]


def _parse_pdf_date(date_str: str | None) -> datetime | None:
    """Parse a PDF date string (D:YYYYMMDDHHmmSSOHH'mm') into datetime."""
    if not date_str:
        return None
    # Strip D: prefix
    s = date_str.strip()
    if s.startswith("D:"):
        s = s[2:]

    # Try common formats
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y%m%d"):
        try:
            # Take only the date portion (ignore timezone offset after +/- or Z)
            clean = re.split(r"[+\-Z]", s)[0]
            return datetime.strptime(clean, fmt).replace(tzinfo=timezone.utc)
        except (ValueError, IndexError):
            continue
    return None


class DocumentForensicsAnalyzer(BaseAnalyzer):
    MODULE_NAME = "document_forensics"
    MODULE_LABEL = "Forenzika dokumenata"

    def __init__(self, signature_verification: bool = True) -> None:
        self._sig_verification = signature_verification

    # ------------------------------------------------------------------
    # A. XREF / Incremental Update Detection
    # ------------------------------------------------------------------

    def _check_xref_anomalies(
        self, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> dict:
        """Scan raw PDF bytes for multiple XREF/EOF markers."""
        raw = doc_bytes

        # Count %%EOF markers
        eof_positions = [m.start() for m in re.finditer(rb"%%EOF", raw)]
        eof_count = len(eof_positions)

        # Count startxref tokens
        startxref_positions = [m.start() for m in re.finditer(rb"startxref", raw)]
        startxref_count = len(startxref_positions)

        evidence = {
            "eof_count": eof_count,
            "startxref_count": startxref_count,
            "eof_positions": eof_positions[:10],  # Cap for evidence
            "file_size_bytes": len(raw),
        }

        # Estimate revision sizes
        if eof_count > 1:
            revision_sizes = []
            prev = 0
            for pos in eof_positions:
                revision_sizes.append(pos - prev)
                prev = pos
            evidence["revision_sizes"] = revision_sizes

        # Try to detect orphan objects via pypdf
        try:
            reader = PdfReader(io.BytesIO(doc_bytes))
            # Count objects in the document
            evidence["total_objects"] = len(reader.pdf_header) if hasattr(reader, "pdf_header") else 0
        except Exception:
            pass

        if eof_count >= 3:
            findings.append(
                AnalyzerFinding(
                    code="DOC_MULTIPLE_UPDATES",
                    title="Visestruke inkrementalne izmjene PDF-a",
                    description=f"Dokument sadrzi {eof_count} revizija (%%EOF markera), sto ukazuje na visestruke naknadne izmjene nakon izvornog stvaranja.",
                    risk_score=0.50,
                    confidence=0.85,
                    evidence=evidence,
                )
            )
        elif eof_count == 2:
            findings.append(
                AnalyzerFinding(
                    code="DOC_INCREMENTAL_UPDATE",
                    title="Otkrivena inkrementalna izmjena PDF-a",
                    description="Dokument je modificiran nakon izvornog stvaranja — pronaden je jedan inkrementalni update s novom XREF tablicom.",
                    risk_score=0.25,
                    confidence=0.70,
                    evidence=evidence,
                )
            )

        return evidence

    # ------------------------------------------------------------------
    # B. Metadata Asymmetry Detection
    # ------------------------------------------------------------------

    def _check_metadata_asymmetry(
        self, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Check PDF metadata for modification indicators."""
        try:
            reader = PdfReader(io.BytesIO(doc_bytes))
            info = reader.metadata
        except Exception as e:
            logger.debug("Could not read PDF metadata: %s", e)
            return

        if info is None:
            # Check if document has pages (content exists but metadata stripped)
            try:
                if len(reader.pages) > 0:
                    findings.append(
                        AnalyzerFinding(
                            code="DOC_META_STRIPPED",
                            title="Uklonjeni metapodaci dokumenta",
                            description="PDF dokument sadrzi stranice ali nema metapodataka (/Info rjecnik) — moguce namjerno uklanjanje tragova.",
                            risk_score=0.15,
                            confidence=0.50,
                            evidence={},
                        )
                    )
            except Exception:
                pass
            return

        # Extract dates
        creation_str = str(info.get("/CreationDate", "")) if info.get("/CreationDate") else None
        mod_str = str(info.get("/ModDate", "")) if info.get("/ModDate") else None
        creation_date = _parse_pdf_date(creation_str)
        mod_date = _parse_pdf_date(mod_str)

        producer = str(info.get("/Producer", "")) if info.get("/Producer") else ""
        creator = str(info.get("/Creator", "")) if info.get("/Creator") else ""
        author = str(info.get("/Author", "")) if info.get("/Author") else ""

        evidence = {
            "creation_date": creation_str,
            "mod_date": mod_str,
            "producer": producer,
            "creator": creator,
            "author": author,
        }

        # Date gap check
        if creation_date and mod_date and mod_date > creation_date:
            gap = mod_date - creation_date
            gap_hours = gap.total_seconds() / 3600
            evidence["time_gap_hours"] = round(gap_hours, 2)

            if gap_hours > 168:  # > 7 days
                findings.append(
                    AnalyzerFinding(
                        code="DOC_META_DATE_GAP_LARGE",
                        title="Velika vremenska razlika u metapodacima dokumenta",
                        description=f"Datum izmjene nadmasuje datum stvaranja za {int(gap_hours / 24)} dana — dokument je modificiran znatno nakon izvornog izdavanja.",
                        risk_score=0.50,
                        confidence=0.85,
                        evidence=evidence,
                    )
                )
            elif gap_hours > 1:
                findings.append(
                    AnalyzerFinding(
                        code="DOC_META_DATE_GAP",
                        title="Razlika datuma stvaranja i izmjene dokumenta",
                        description=f"Datum izmjene nadmasuje datum stvaranja za {round(gap_hours, 1)} sati.",
                        risk_score=0.30,
                        confidence=0.80,
                        evidence=evidence,
                    )
                )

        # Check producer against known editing tools
        if producer:
            producer_lower = producer.lower()
            for keyword, risk, display_name in PDF_EDITING_SOFTWARE:
                if keyword in producer_lower:
                    findings.append(
                        AnalyzerFinding(
                            code="DOC_META_EDITING_SOFTWARE",
                            title="Otkriven softver za uredivanje PDF-a",
                            description=f"Dokument je izraden ili modificiran pomocu softvera: {display_name}.",
                            risk_score=risk,
                            confidence=0.80,
                            evidence={**evidence, "matched_software": display_name},
                        )
                    )
                    break

    # ------------------------------------------------------------------
    # C. Font / Typographic Forensics
    # ------------------------------------------------------------------

    def _check_font_anomalies(
        self, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Detect font subsetting anomalies indicating character replacement."""
        try:
            reader = PdfReader(io.BytesIO(doc_bytes))
        except Exception as e:
            logger.debug("Could not parse PDF for font analysis: %s", e)
            return

        # Limit to first 20 pages for performance
        max_pages = min(len(reader.pages), 20)
        all_fonts: dict[int, list[dict]] = {}  # page_num → list of font info dicts
        subset_pattern = re.compile(r"^[A-Z]{6}\+(.+)$")

        for page_idx in range(max_pages):
            try:
                page = reader.pages[page_idx]
                resources = page.get("/Resources")
                if not resources:
                    continue
                fonts_dict = resources.get("/Font")
                if not fonts_dict:
                    continue

                page_fonts: list[dict] = []
                font_obj = fonts_dict.get_object() if hasattr(fonts_dict, "get_object") else fonts_dict

                for font_key in font_obj:
                    try:
                        font_ref = font_obj[font_key]
                        font = font_ref.get_object() if hasattr(font_ref, "get_object") else font_ref

                        base_font = str(font.get("/BaseFont", "")) if font.get("/BaseFont") else ""
                        subtype = str(font.get("/Subtype", "")) if font.get("/Subtype") else ""

                        # Check for font file embedding
                        descriptor = font.get("/FontDescriptor")
                        has_font_file = False
                        if descriptor:
                            desc_obj = descriptor.get_object() if hasattr(descriptor, "get_object") else descriptor
                            has_font_file = any(
                                desc_obj.get(k) is not None
                                for k in ("/FontFile", "/FontFile2", "/FontFile3")
                            )

                        # Parse subset prefix
                        is_subset = False
                        base_name = base_font.lstrip("/")
                        match = subset_pattern.match(base_name)
                        if match:
                            is_subset = True
                            base_name_clean = match.group(1)
                        else:
                            base_name_clean = base_name

                        page_fonts.append({
                            "key": str(font_key),
                            "base_font": base_font,
                            "base_name_clean": base_name_clean,
                            "subtype": subtype,
                            "is_subset": is_subset,
                            "has_font_file": has_font_file,
                        })
                    except Exception:
                        continue

                if page_fonts:
                    all_fonts[page_idx] = page_fonts
            except Exception:
                continue

        if not all_fonts:
            return

        # Analysis: detect anomalies
        total_unique_fonts = set()
        subset_mismatches: list[dict] = []
        mixed_embedding: list[dict] = []
        system_fallbacks: list[dict] = []

        for page_idx, fonts in all_fonts.items():
            for f in fonts:
                total_unique_fonts.add(f["base_font"])

            # Group fonts by clean base name on this page
            name_groups: dict[str, list[dict]] = {}
            for f in fonts:
                name = f["base_name_clean"]
                if name:
                    name_groups.setdefault(name, []).append(f)

            for name, group in name_groups.items():
                if len(group) < 2:
                    continue

                subsets = [f for f in group if f["is_subset"]]
                non_subsets = [f for f in group if not f["is_subset"]]

                # Same base font with different subset prefixes on same page
                if len(subsets) >= 2:
                    prefixes = set(f["base_font"] for f in subsets)
                    if len(prefixes) >= 2:
                        subset_mismatches.append({
                            "page": page_idx,
                            "base_name": name,
                            "variants": [f["base_font"] for f in subsets],
                        })

                # Mix of subset and non-subset of same font family
                if subsets and non_subsets:
                    mixed_embedding.append({
                        "page": page_idx,
                        "base_name": name,
                        "subset": [f["base_font"] for f in subsets],
                        "non_subset": [f["base_font"] for f in non_subsets],
                    })

            # Check for non-embedded fonts alongside embedded ones
            embedded = [f for f in fonts if f["has_font_file"]]
            non_embedded = [f for f in fonts if not f["has_font_file"] and f["base_font"]]
            if embedded and non_embedded:
                system_fallbacks.append({
                    "page": page_idx,
                    "embedded": [f["base_font"] for f in embedded],
                    "non_embedded": [f["base_font"] for f in non_embedded],
                })

        evidence = {
            "total_unique_fonts": len(total_unique_fonts),
            "pages_analyzed": max_pages,
            "fonts_per_page": {str(k): len(v) for k, v in all_fonts.items()},
        }

        # Generate findings
        if subset_mismatches:
            findings.append(
                AnalyzerFinding(
                    code="DOC_FONT_SUBSET_MISMATCH",
                    title="Nepodudarnost podskupova fontova",
                    description=f"Isti bazni font pojavljuje se s razlicitim podskupovima na istoj stranici na {len(subset_mismatches)} mjesta — jasan indikator da su pojedini znakovi zamijenjeni koristeci drugi izvor fonta.",
                    risk_score=0.65,
                    confidence=0.85,
                    evidence={**evidence, "mismatches": subset_mismatches[:5]},
                )
            )

        if mixed_embedding:
            findings.append(
                AnalyzerFinding(
                    code="DOC_FONT_MIXED_EMBEDDING",
                    title="Mijesano ugradivanje fontova",
                    description=f"Otkrivena je kombinacija ugradenih podskupova i neugradenih verzija istog fonta na {len(mixed_embedding)} stranica.",
                    risk_score=0.55,
                    confidence=0.80,
                    evidence={**evidence, "mixed": mixed_embedding[:5]},
                )
            )

        if system_fallbacks:
            findings.append(
                AnalyzerFinding(
                    code="DOC_FONT_SYSTEM_FALLBACK",
                    title="Otkrivena zamjena sistemskim fontom",
                    description=f"Na {len(system_fallbacks)} stranica koriste se neugradeni (sistemski) fontovi uz ugradene — moguca zamjena znakova alatom koji koristi lokalne fontove.",
                    risk_score=0.45,
                    confidence=0.75,
                    evidence={**evidence, "fallbacks": system_fallbacks[:5]},
                )
            )

        # Excessive font count
        for page_idx, fonts in all_fonts.items():
            if len(fonts) > 10:
                findings.append(
                    AnalyzerFinding(
                        code="DOC_FONT_EXCESS_COUNT",
                        title="Neobicno velik broj fontova",
                        description=f"Stranica {page_idx + 1} koristi {len(fonts)} razlicitih fontova — neobicno za standardni dokument poput racuna ili izvoda.",
                        risk_score=0.30,
                        confidence=0.65,
                        evidence={**evidence, "page": page_idx, "font_count": len(fonts)},
                    )
                )
                break  # One finding is enough

    # ------------------------------------------------------------------
    # D. Digital Signature Verification
    # ------------------------------------------------------------------

    def _check_digital_signatures(
        self, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Verify embedded digital signatures using PyHanko."""
        if not self._sig_verification or not _PYHANKO_AVAILABLE:
            return

        try:
            reader = HankoPdfReader(io.BytesIO(doc_bytes))
            sig_fields = reader.embedded_signatures
        except Exception as e:
            logger.debug("Could not read PDF signatures: %s", e)
            return

        if not sig_fields:
            return  # No signatures — neutral (most PDFs are unsigned)

        for sig in sig_fields:
            try:
                # Check byte range coverage
                sig_obj = sig.sig_object
                byte_range = sig_obj.get("/ByteRange")
                covers_whole_file = False
                if byte_range:
                    # ByteRange = [offset1, length1, offset2, length2]
                    # If offset2 + length2 == file size, signature covers entire file
                    try:
                        br = list(byte_range)
                        if len(br) == 4:
                            covered_end = int(br[2]) + int(br[3])
                            covers_whole_file = covered_end >= len(doc_bytes) - 1
                    except (ValueError, TypeError):
                        pass

                # Extract signer info
                signer_name = ""
                signing_time = ""
                cert_issuer = ""
                is_self_signed = False
                cert_expired = False

                try:
                    signer_cert = sig.signer_cert
                    if signer_cert:
                        signer_name = signer_cert.subject.human_friendly
                        cert_issuer = signer_cert.issuer.human_friendly
                        is_self_signed = signer_cert.self_signed in ("maybe", True)

                        # Check expiry
                        now = datetime.now(timezone.utc)
                        if signer_cert.not_valid_after.replace(tzinfo=timezone.utc) < now:
                            cert_expired = True
                except Exception:
                    pass

                try:
                    if sig_obj.get("/M"):
                        signing_time = str(sig_obj["/M"])
                except Exception:
                    pass

                evidence = {
                    "signer_name": signer_name,
                    "signing_time": signing_time,
                    "cert_issuer": cert_issuer,
                    "is_self_signed": is_self_signed,
                    "covers_whole_file": covers_whole_file,
                    "byte_range": list(byte_range) if byte_range else None,
                }

                # Try validation (may fail without network for OCSP/CRL)
                sig_valid = False
                validation_error = ""
                try:
                    status = validate_pdf_signature(reader, sig)
                    sig_valid = status.bottom_line
                except Exception as e:
                    validation_error = str(e)
                    # Even if full validation fails, check byte range
                    logger.debug("Signature validation error (may be expected): %s", e)

                evidence["validation_error"] = validation_error

                # Generate findings based on analysis
                if not covers_whole_file:
                    findings.append(
                        AnalyzerFinding(
                            code="DOC_SIG_MODIFIED_AFTER",
                            title="Dokument modificiran nakon potpisivanja",
                            description="Raspon bajtova digitalnog potpisa ne pokriva cijeli dokument — podaci su dodani nakon potpisivanja.",
                            risk_score=0.80,
                            confidence=0.90,
                            evidence=evidence,
                        )
                    )
                elif sig_valid:
                    findings.append(
                        AnalyzerFinding(
                            code="DOC_SIG_VALID",
                            title="Valjan digitalni potpis",
                            description=f"Dokument ima valjan digitalni potpis ({signer_name or 'nepoznat potpisnik'}) koji pokriva cijeli sadrzaj.",
                            risk_score=-0.15,
                            confidence=0.95,
                            evidence=evidence,
                        )
                    )
                elif not sig_valid and validation_error:
                    findings.append(
                        AnalyzerFinding(
                            code="DOC_SIG_INVALID",
                            title="Nevaljan digitalni potpis",
                            description="Verifikacija digitalnog potpisa nije uspjela — potpis je neispravan ili je dokument izmijenjen.",
                            risk_score=0.70,
                            confidence=0.95,
                            evidence=evidence,
                        )
                    )

                # Additional cert findings
                if is_self_signed:
                    findings.append(
                        AnalyzerFinding(
                            code="DOC_SIG_SELF_SIGNED",
                            title="Samopotpisan certifikat",
                            description="Digitalni potpis koristi samopotpisan certifikat bez lanca povjerenja (CA).",
                            risk_score=0.25,
                            confidence=0.70,
                            evidence=evidence,
                        )
                    )

                if cert_expired:
                    findings.append(
                        AnalyzerFinding(
                            code="DOC_SIG_EXPIRED_CERT",
                            title="Istekli certifikat potpisa",
                            description="Certifikat koristeni za potpisivanje dokumenta je istekao.",
                            risk_score=0.30,
                            confidence=0.80,
                            evidence=evidence,
                        )
                    )

            except Exception as e:
                logger.debug("Error processing signature: %s", e)
                continue

    # ------------------------------------------------------------------
    # Main analysis
    # ------------------------------------------------------------------

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([])  # No-op for images

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        t0 = time.perf_counter()
        findings: list[AnalyzerFinding] = []

        if not _PYPDF_AVAILABLE:
            elapsed = int((time.perf_counter() - t0) * 1000)
            return self._make_result(
                [], processing_time_ms=elapsed, error="pypdf not installed, PDF analysis unavailable"
            )

        try:
            # A. XREF / Incremental update detection
            self._check_xref_anomalies(doc_bytes, findings)

            # B. Metadata asymmetry
            self._check_metadata_asymmetry(doc_bytes, findings)

            # C. Font / typographic forensics
            self._check_font_anomalies(doc_bytes, findings)

            # D. Digital signature verification
            self._check_digital_signatures(doc_bytes, findings)

        except Exception as e:
            logger.error("Document forensics failed: %s", e, exc_info=True)
            elapsed = int((time.perf_counter() - t0) * 1000)
            return self._make_result([], processing_time_ms=elapsed, error=str(e))

        elapsed = int((time.perf_counter() - t0) * 1000)

        logger.info(
            "Document forensics complete: %s findings=%d time=%dms",
            filename,
            len(findings),
            elapsed,
        )

        return self._make_result(findings, processing_time_ms=elapsed)
