"""Document forensics: PDF structure, metadata, font, and signature analysis.

18 check categories (A-R), ~50+ finding codes:
  A.  XREF / Incremental update detection
  B.  Metadata asymmetry (Info dict + XMP)
  C.  Font forensics (subset, glyph, zero-width, homoglyph, per-char metrics)
  D.  Digital signature verification + post-sig analysis
  E.  Fake redaction detection
  F.  Shadow attack detection (overlay %, Kids swap)
  G.  Orphaned object detection
  H.  Visual vs OCR comparison (render + pytesseract vs text layer)
  I.  Per-character font metrics (rawdict baseline/kerning anomalies)
  J.  PDF version recovery + pixel diff between revisions
  K.  ELA on embedded images within PDF documents
  L.  JavaScript / dangerous action detection
  M.  AcroForm / XFA form overlay attack detection
  N.  Color space inconsistency analysis
  O.  Compression filter inconsistency detection
  P.  ToUnicode CMap / ActualText discrepancy
  Q.  Evil Annotation Attack (EAA) detection
  R.  OCG default-off hidden layer detection
"""

import base64
import difflib
import io
import logging
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

import numpy as np
from PIL import Image

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

_PYMUPDF_AVAILABLE = False
try:
    import fitz  # PyMuPDF

    _PYMUPDF_AVAILABLE = True
except ImportError:
    logger.info("PyMuPDF not installed, advanced PDF forensics (fake redaction/shadow) disabled")

_FONTTOOLS_AVAILABLE = False
try:
    from fontTools.ttLib import TTFont

    _FONTTOOLS_AVAILABLE = True
except ImportError:
    logger.info("fontTools not installed, font glyph analysis disabled")

_TESSERACT_AVAILABLE = False
try:
    import pytesseract

    _TESSERACT_AVAILABLE = True
except ImportError:
    logger.info("pytesseract not installed, Visual vs OCR comparison disabled")

# Known PDF editing software (keyword_lower, risk_score, display_name)
# Ordered from highest risk (online tools) to lowest risk (standard office).
PDF_EDITING_SOFTWARE: list[tuple[str, float, str]] = [
    # Online editing tools — highest risk (anonymous web-based manipulation)
    ("ilovepdf", 0.55, "iLovePDF"),
    ("smallpdf", 0.55, "Smallpdf"),
    ("pdf24", 0.55, "PDF24"),
    ("sejda", 0.55, "Sejda"),
    ("docfly", 0.55, "DocFly"),
    ("sodapdf", 0.50, "Soda PDF"),
    ("pdfcandy", 0.50, "PDF Candy"),
    ("pdf-xchange", 0.45, "PDF-XChange"),
    # Local editing tools
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

# Unicode codepoints considered zero-width or invisible formatting
_ZERO_WIDTH_CHARS = frozenset({
    0x200B,  # ZWSP - Zero Width Space
    0x200C,  # ZWNJ - Zero Width Non-Joiner
    0x200D,  # ZWJ  - Zero Width Joiner
    0x200E,  # LRM  - Left-to-Right Mark
    0x200F,  # RLM  - Right-to-Left Mark
    0xFEFF,  # BOM  - Byte Order Mark (when used as ZWNBSP)
    # BiDi embedding/override controls
    0x202A,  # LRE  - Left-to-Right Embedding
    0x202B,  # RLE  - Right-to-Left Embedding
    0x202C,  # PDF  - Pop Directional Formatting
    0x202D,  # LRO  - Left-to-Right Override
    0x202E,  # RLO  - Right-to-Left Override
    # BiDi isolate controls (Unicode 6.3+)
    0x2066,  # LRI  - Left-to-Right Isolate
    0x2067,  # RLI  - Right-to-Left Isolate
    0x2068,  # FSI  - First Strong Isolate
    0x2069,  # PDI  - Pop Directional Isolate
})

# Cyrillic letters visually identical to Latin (homoglyphs)
_CYRILLIC_HOMOGLYPHS: dict[int, str] = {
    0x0410: "A",  # А
    0x0412: "B",  # В
    0x0421: "C",  # С
    0x0415: "E",  # Е
    0x041D: "H",  # Н
    0x041A: "K",  # К
    0x041C: "M",  # М
    0x041E: "O",  # О
    0x0420: "P",  # Р
    0x0422: "T",  # Т
    0x0425: "X",  # Х
    0x0430: "a",  # а
    0x0435: "e",  # е
    0x043E: "o",  # о
    0x0440: "p",  # р
    0x0441: "c",  # с
    0x0443: "y",  # у (looks like y)
    0x0445: "x",  # х
}


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


def _parse_xmp_date(date_str: str | None) -> datetime | None:
    """Parse an XMP/ISO 8601 date string into datetime."""
    if not date_str:
        return None
    s = date_str.strip()
    # XMP dates: 2024-01-15T10:30:00+02:00 or 2024-01-15T10:30:00Z
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d",
    ):
        try:
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

        # Check producer AND creator against known editing tools
        for field_name, field_value in [("producer", producer), ("creator", creator)]:
            if not field_value:
                continue
            field_lower = field_value.lower()
            for keyword, risk, display_name in PDF_EDITING_SOFTWARE:
                if keyword in field_lower:
                    findings.append(
                        AnalyzerFinding(
                            code="DOC_META_EDITING_SOFTWARE",
                            title="Otkriven softver za uredivanje PDF-a",
                            description=f"Dokument je izraden ili modificiran pomocu softvera: {display_name} (detektirano u {field_name} polju).",
                            risk_score=risk,
                            confidence=0.80,
                            evidence={**evidence, "matched_software": display_name, "matched_field": field_name},
                        )
                    )
                    return  # One software match is enough

    # ------------------------------------------------------------------
    # B2. XMP vs Info Dictionary Asymmetry
    # ------------------------------------------------------------------

    def _check_xmp_info_asymmetry(
        self, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Compare XMP metadata stream with Info dictionary for inconsistencies."""
        if not _PYMUPDF_AVAILABLE:
            return

        try:
            doc = fitz.open(stream=doc_bytes, filetype="pdf")
        except Exception as e:
            logger.debug("Could not open PDF for XMP analysis: %s", e)
            return

        try:
            # Info dict metadata (PyMuPDF normalizes it)
            info_meta = doc.metadata or {}
            info_mod_date = _parse_pdf_date(info_meta.get("modDate", ""))
            info_create_date = _parse_pdf_date(info_meta.get("creationDate", ""))
            info_creator = info_meta.get("creator", "")
            info_producer = info_meta.get("producer", "")

            # XMP metadata stream (raw XML)
            xmp_xml = doc.xref_xml_metadata
            if not xmp_xml:
                return

            xmp_mod_date = None
            xmp_create_date = None
            xmp_creator_tool = ""

            try:
                root = ElementTree.fromstring(xmp_xml)
                # Search for common XMP date namespaces
                ns_map = {
                    "xmp": "http://ns.adobe.com/xap/1.0/",
                    "pdf": "http://ns.adobe.com/pdf/1.3/",
                    "dc": "http://purl.org/dc/elements/1.1/",
                    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
                }

                for elem in root.iter():
                    tag_local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                    text = (elem.text or "").strip()
                    if not text:
                        continue

                    if tag_local == "ModifyDate":
                        xmp_mod_date = _parse_xmp_date(text)
                    elif tag_local == "CreateDate":
                        xmp_create_date = _parse_xmp_date(text)
                    elif tag_local == "CreatorTool":
                        xmp_creator_tool = text
                    elif tag_local == "Producer" and not xmp_creator_tool:
                        xmp_creator_tool = text
            except ElementTree.ParseError:
                logger.debug("Could not parse XMP XML")
                return

            evidence = {
                "info_mod_date": str(info_mod_date) if info_mod_date else None,
                "xmp_mod_date": str(xmp_mod_date) if xmp_mod_date else None,
                "info_create_date": str(info_create_date) if info_create_date else None,
                "xmp_create_date": str(xmp_create_date) if xmp_create_date else None,
                "info_creator": info_creator,
                "info_producer": info_producer,
                "xmp_creator_tool": xmp_creator_tool,
            }

            # Compare ModDate: difference > 2 minutes = suspicious
            if info_mod_date and xmp_mod_date:
                delta = abs((info_mod_date - xmp_mod_date).total_seconds())
                evidence["mod_date_delta_seconds"] = round(delta, 1)

                if delta > 120:  # > 2 minutes
                    findings.append(
                        AnalyzerFinding(
                            code="DOC_META_XMP_MISMATCH",
                            title="Nepodudarnost XMP i Info metapodataka",
                            description=(
                                f"Datum izmjene u Info rjecniku i XMP streamu razlikuju se za "
                                f"{int(delta)} sekundi. Manipulativni alati cesto azuriraju "
                                f"samo jedan izvor metapodataka."
                            ),
                            risk_score=0.60,
                            confidence=0.85,
                            evidence=evidence,
                        )
                    )

            # Compare Creator/Producer tools
            if xmp_creator_tool and info_creator:
                # Normalize for comparison
                xmp_norm = xmp_creator_tool.lower().strip()
                info_norm = info_creator.lower().strip()
                if xmp_norm and info_norm and xmp_norm != info_norm:
                    # Check if they're substantially different (not just version differences)
                    xmp_base = xmp_norm.split()[0] if xmp_norm else ""
                    info_base = info_norm.split()[0] if info_norm else ""
                    if xmp_base != info_base:
                        findings.append(
                            AnalyzerFinding(
                                code="DOC_META_SOURCE_MISMATCH",
                                title="Nepodudarnost izvora u metapodacima",
                                description=(
                                    f"XMP CreatorTool ('{xmp_creator_tool}') razlikuje se od "
                                    f"Info Creator ('{info_creator}') — dokument je moguce "
                                    f"obradivan razlicitim alatima."
                                ),
                                risk_score=0.45,
                                confidence=0.80,
                                evidence=evidence,
                            )
                        )

        except Exception as e:
            logger.debug("XMP asymmetry check error: %s", e)
        finally:
            doc.close()

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
    # C2. Font Glyph Count Analysis (fontTools)
    # ------------------------------------------------------------------

    def _check_font_glyph_analysis(
        self, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Detect suspiciously small font subsets via glyph counting."""
        if not _FONTTOOLS_AVAILABLE or not _PYMUPDF_AVAILABLE:
            return

        try:
            doc = fitz.open(stream=doc_bytes, filetype="pdf")
        except Exception as e:
            logger.debug("Could not open PDF for glyph analysis: %s", e)
            return

        suspicious_fonts: list[dict] = []
        analyzed_xrefs: set[int] = set()

        try:
            max_pages = min(len(doc), 20)
            for page_idx in range(max_pages):
                page = doc[page_idx]
                # get_fonts returns: (xref, ext, type, basefont, name, encoding, ...)
                font_list = page.get_fonts(full=True)

                for font_info in font_list:
                    xref = font_info[0]
                    if xref in analyzed_xrefs or xref <= 0:
                        continue
                    analyzed_xrefs.add(xref)

                    base_font_name = font_info[3] if len(font_info) > 3 else ""

                    try:
                        # Extract font binary data
                        font_data = doc.extract_font(xref)
                        if not font_data or len(font_data) < 4:
                            continue
                        # font_data = (basename, ext, subtype, content)
                        font_binary = font_data[3]
                        if not font_binary or len(font_binary) < 100:
                            continue

                        # Parse with fontTools
                        tt = TTFont(io.BytesIO(font_binary))
                        cmap = tt.getBestCmap()
                        if cmap is None:
                            continue
                        glyph_count = len(cmap)
                        tt.close()

                        if glyph_count < 30:
                            suspicious_fonts.append({
                                "page": page_idx + 1,
                                "xref": xref,
                                "font_name": base_font_name,
                                "glyph_count": glyph_count,
                            })
                    except Exception:
                        # fontTools parsing can fail on malformed/non-TrueType fonts
                        continue
        except Exception as e:
            logger.debug("Font glyph analysis error: %s", e)
        finally:
            doc.close()

        if not suspicious_fonts:
            return

        # Separate into severity levels
        critical = [f for f in suspicious_fonts if f["glyph_count"] < 15]
        moderate = [f for f in suspicious_fonts if 15 <= f["glyph_count"] < 30]

        if critical:
            findings.append(
                AnalyzerFinding(
                    code="DOC_FONT_SUSPICIOUS_SUBSET",
                    title="Kriticno mali podskup fonta",
                    description=(
                        f"Font '{critical[0]['font_name']}' sadrzi samo "
                        f"{critical[0]['glyph_count']} glifova — sumnjivo mali podskup "
                        f"koji pokriva samo umetnute znakove (cifre ili pojedina slova). "
                        f"Ovo je tipican trag alata za uredivanje koji ugraduje minimalni "
                        f"font za zamijenjene znakove."
                    ),
                    risk_score=0.75,
                    confidence=0.80,
                    evidence={
                        "suspicious_fonts": critical[:5],
                        "total_suspicious": len(critical),
                    },
                )
            )
        elif moderate:
            findings.append(
                AnalyzerFinding(
                    code="DOC_FONT_SUSPICIOUS_SUBSET",
                    title="Sumnjivo mali podskup fonta",
                    description=(
                        f"Font '{moderate[0]['font_name']}' sadrzi samo "
                        f"{moderate[0]['glyph_count']} glifova — neobicno mali "
                        f"podskup za standardni poslovni dokument."
                    ),
                    risk_score=0.60,
                    confidence=0.80,
                    evidence={
                        "suspicious_fonts": moderate[:5],
                        "total_suspicious": len(moderate),
                    },
                )
            )

    # ------------------------------------------------------------------
    # C3. Zero-Width Character Detection
    # ------------------------------------------------------------------

    def _check_zero_width_chars(
        self, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Detect invisible Unicode formatting characters (Cf category)."""
        if not _PYMUPDF_AVAILABLE:
            return

        try:
            doc = fitz.open(stream=doc_bytes, filetype="pdf")
        except Exception as e:
            logger.debug("Could not open PDF for zero-width check: %s", e)
            return

        total_chars = 0
        zw_counts: dict[str, int] = {}  # char_name → count

        try:
            max_pages = min(len(doc), 20)
            for page_idx in range(max_pages):
                page = doc[page_idx]
                text = page.get_text()
                total_chars += len(text)

                for ch in text:
                    cp = ord(ch)
                    if cp in _ZERO_WIDTH_CHARS or unicodedata.category(ch) == "Cf":
                        try:
                            name = unicodedata.name(ch, f"U+{cp:04X}")
                        except ValueError:
                            name = f"U+{cp:04X}"
                        zw_counts[name] = zw_counts.get(name, 0) + 1
        except Exception as e:
            logger.debug("Zero-width char check error: %s", e)
        finally:
            doc.close()

        zw_total = sum(zw_counts.values())
        if zw_total <= 0:
            return

        zw_ratio = zw_total / max(total_chars, 1)
        evidence = {
            "zero_width_total": zw_total,
            "total_chars": total_chars,
            "zw_ratio": round(zw_ratio, 6),
            "char_types": dict(sorted(zw_counts.items(), key=lambda x: -x[1])[:10]),
        }

        if zw_total > 10:
            findings.append(
                AnalyzerFinding(
                    code="DOC_ZERO_WIDTH_CHARS",
                    title="Otkriveni nevidljivi Unicode znakovi",
                    description=(
                        f"Pronadeno {zw_total} znakova nulte sirine ili nevidljivih "
                        f"formatirajucih kontrola (Unicode Cf kategorija). "
                        f"Ovi se znakovi koriste za obfuskaciju kljucnih rijeci — "
                        f"sto ljudsko oko vidi razlikuje se od onoga sto OCR/NLP sustav cita."
                    ),
                    risk_score=0.70,
                    confidence=0.80,
                    evidence=evidence,
                )
            )
        elif zw_total > 3:
            findings.append(
                AnalyzerFinding(
                    code="DOC_ZERO_WIDTH_CHARS",
                    title="Prisutnost nevidljivih Unicode znakova",
                    description=(
                        f"Pronadeno {zw_total} nevidljivih formatirajucih znakova. "
                        f"Moguca obfuskacija teksta za zaobilazenje automatske obrade."
                    ),
                    risk_score=0.55,
                    confidence=0.80,
                    evidence=evidence,
                )
            )

    # ------------------------------------------------------------------
    # C4. Mixed Script Detection (Trojan Source)
    # ------------------------------------------------------------------

    def _check_mixed_scripts(
        self, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Detect Cyrillic homoglyphs mixed into Latin text (Trojan Source attack)."""
        if not _PYMUPDF_AVAILABLE:
            return

        try:
            doc = fitz.open(stream=doc_bytes, filetype="pdf")
        except Exception as e:
            logger.debug("Could not open PDF for mixed script check: %s", e)
            return

        cyrillic_in_latin: list[dict] = []

        try:
            max_pages = min(len(doc), 20)
            for page_idx in range(max_pages):
                page = doc[page_idx]
                text_dict = page.get_text("dict", flags=0)
                blocks = text_dict.get("blocks", [])

                for block in blocks:
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            text = span.get("text", "")
                            if len(text) < 3:
                                continue

                            # Count Latin and Cyrillic chars
                            latin_count = 0
                            cyrillic_homoglyph_count = 0
                            homoglyph_positions: list[dict] = []

                            for i, ch in enumerate(text):
                                cp = ord(ch)
                                if cp in _CYRILLIC_HOMOGLYPHS:
                                    cyrillic_homoglyph_count += 1
                                    if len(homoglyph_positions) < 5:
                                        homoglyph_positions.append({
                                            "pos": i,
                                            "char": ch,
                                            "looks_like": _CYRILLIC_HOMOGLYPHS[cp],
                                            "codepoint": f"U+{cp:04X}",
                                        })
                                elif 0x0041 <= cp <= 0x007A:  # Basic Latin A-z
                                    latin_count += 1

                            # Flag: Cyrillic homoglyphs in predominantly Latin text
                            if cyrillic_homoglyph_count >= 3 and latin_count > cyrillic_homoglyph_count * 2:
                                cyrillic_in_latin.append({
                                    "page": page_idx + 1,
                                    "text_sample": text[:80],
                                    "cyrillic_count": cyrillic_homoglyph_count,
                                    "latin_count": latin_count,
                                    "homoglyphs": homoglyph_positions,
                                })
        except Exception as e:
            logger.debug("Mixed script check error: %s", e)
        finally:
            doc.close()

        if cyrillic_in_latin:
            findings.append(
                AnalyzerFinding(
                    code="DOC_MIXED_SCRIPTS",
                    title="Otkriveni cirilicki homoglifi u latinicnom tekstu",
                    description=(
                        f"Pronadeno {len(cyrillic_in_latin)} tekstualnih blokova s "
                        f"cirilichim znakovima umetnutim u pretezno latinicni tekst. "
                        f"Ova 'Trojan Source' tehnika koristi vizualno identicna slova "
                        f"iz razlicitih Unicode skripti za obfuskaciju sadrzaja."
                    ),
                    risk_score=0.60,
                    confidence=0.75,
                    evidence={"instances": cyrillic_in_latin[:5]},
                )
            )

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

                    # D2. Analyze what was modified after signature
                    self._analyze_post_signature_changes(
                        doc_bytes, byte_range, findings, evidence
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
    # D2. Post-Signature Modification Analysis
    # ------------------------------------------------------------------

    def _analyze_post_signature_changes(
        self,
        doc_bytes: bytes,
        byte_range: list | None,
        findings: list[AnalyzerFinding],
        sig_evidence: dict,
    ) -> None:
        """Analyze content added after digital signature ByteRange."""
        if not byte_range or not _PYMUPDF_AVAILABLE:
            return

        try:
            br = list(byte_range)
            if len(br) != 4:
                return

            # Bytes after the signed range
            signed_end = int(br[2]) + int(br[3])
            if signed_end >= len(doc_bytes) - 10:
                return  # No significant content after signature

            post_sig_bytes = doc_bytes[signed_end:]
            post_sig_size = len(post_sig_bytes)

            # Check what's in the post-signature content
            has_stream_content = b"/Contents" in post_sig_bytes or b"stream\n" in post_sig_bytes
            has_font_changes = b"/Font" in post_sig_bytes or b"/BaseFont" in post_sig_bytes
            has_page_changes = b"/Pages" in post_sig_bytes or b"/Kids" in post_sig_bytes
            has_form_only = b"/AcroForm" in post_sig_bytes or b"/Annot" in post_sig_bytes

            evidence = {
                **sig_evidence,
                "post_sig_bytes": post_sig_size,
                "has_stream_content": has_stream_content,
                "has_font_changes": has_font_changes,
                "has_page_changes": has_page_changes,
                "has_form_only": has_form_only,
            }

            if has_stream_content or has_font_changes or has_page_changes:
                findings.append(
                    AnalyzerFinding(
                        code="DOC_SIG_CONTENT_MODIFIED",
                        title="Sadrzaj dokumenta izmijenjen nakon potpisa",
                        description=(
                            "Analiza bajtova dodanih nakon digitalnog potpisa otkriva promjene "
                            "u tekstu, fontovima ili strukturi stranica. Ovo ponistava integritet "
                            "potpisanog dokumenta — sadrzaj koji je potpisan razlikuje se od "
                            "trenutno vidljivog."
                        ),
                        risk_score=0.85,
                        confidence=0.90,
                        evidence=evidence,
                    )
                )
            elif has_form_only and post_sig_size > 500:
                findings.append(
                    AnalyzerFinding(
                        code="DOC_SIG_FORM_MODIFIED",
                        title="Polja obrasca izmijenjena nakon potpisa",
                        description=(
                            "Nakon potpisa dodane su izmjene u interaktivnim poljima "
                            "obrasca (AcroForm/Annots). Ovo moze biti legitimno "
                            "(npr. drugi potpisnik), ali zahtijeva dodatnu provjeru."
                        ),
                        risk_score=0.30,
                        confidence=0.70,
                        evidence=evidence,
                    )
                )

        except Exception as e:
            logger.debug("Post-signature analysis error: %s", e)

    # ------------------------------------------------------------------
    # E. Fake Redaction Detection (PyMuPDF)
    # ------------------------------------------------------------------

    def _check_fake_redactions(
        self, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Detect fake redactions: rectangles covering extractable text."""
        if not _PYMUPDF_AVAILABLE:
            return

        try:
            doc = fitz.open(stream=doc_bytes, filetype="pdf")
        except Exception as e:
            logger.debug("PyMuPDF could not open PDF: %s", e)
            return

        fake_redactions: list[dict] = []
        max_pages = min(len(doc), 20)

        try:
            for page_idx in range(max_pages):
                page = doc[page_idx]

                # Get all drawings (rectangles) on the page
                drawings = page.get_drawings()
                # Also get annotations of type Redact or FreeText
                annots = list(page.annots()) if page.annots() else []

                # Collect all dark/opaque rectangles
                cover_rects: list[fitz.Rect] = []

                page_width = page.rect.width

                for d in drawings:
                    if d.get("fill") is None or not d.get("rect"):
                        continue
                    fill = d["fill"]
                    rect = fitz.Rect(d["rect"])

                    # Skip tiny rectangles
                    if rect.width < 10 or rect.height < 5:
                        continue

                    # --- Filter out common non-redaction patterns ---

                    # 1. Skip white/near-white fills (table backgrounds)
                    if isinstance(fill, (tuple, list)) and len(fill) >= 3:
                        r, g, b = fill[0], fill[1], fill[2]
                        brightness = 0.299 * r + 0.587 * g + 0.114 * b
                        # Skip light fills (> 0.35 brightness = not dark enough to hide text)
                        if brightness > 0.35:
                            continue

                    # 2. Skip full-width rectangles (headers, footers, section bars)
                    if rect.width > page_width * 0.85:
                        continue

                    # 3. Skip very tall rectangles (full table columns / page backgrounds)
                    if rect.height > 200:
                        continue

                    # Only truly dark/opaque rectangles pass through
                    cover_rects.append(rect)

                for annot in annots:
                    # Redact annotations and FreeText with fill color
                    if annot.type[0] in (12, 2):  # Redact=12, FreeText=2
                        cover_rects.append(annot.rect)

                if not cover_rects:
                    continue

                # Get full text dict (with positions) for this page
                text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
                text_blocks = text_dict.get("blocks", [])

                for rect in cover_rects:
                    # Check if any text spans fall under this rectangle
                    hidden_chars = 0
                    hidden_texts: list[str] = []

                    for block in text_blocks:
                        if block.get("type") != 0:  # 0 = text block
                            continue
                        for line in block.get("lines", []):
                            for span in line.get("spans", []):
                                span_rect = fitz.Rect(span["bbox"])
                                if rect.contains(span_rect) or rect.intersects(span_rect):
                                    overlap = rect & span_rect
                                    if overlap.width > span_rect.width * 0.5:
                                        text = span.get("text", "").strip()
                                        if not text:
                                            continue

                                        # Only count as "hidden" if text is truly
                                        # invisible: same darkness as the covering
                                        # rectangle (black text under black rect).
                                        # Any non-black text (gray, white, colored)
                                        # on a dark rect IS visible — it's design.
                                        text_color = span.get("color", 0)
                                        if isinstance(text_color, int):
                                            tr = (text_color >> 16) & 0xFF
                                            tg = (text_color >> 8) & 0xFF
                                            tb = text_color & 0xFF
                                            text_bright = (0.299*tr + 0.587*tg + 0.114*tb) / 255.0
                                            # Non-black text = visible on dark bg, skip
                                            if text_bright > 0.10:
                                                continue

                                        hidden_chars += len(text)
                                        if len(hidden_texts) < 3:
                                            hidden_texts.append(text[:50])

                    if hidden_chars > 5:
                        fake_redactions.append({
                            "page": page_idx + 1,
                            "rect": [round(rect.x0, 1), round(rect.y0, 1),
                                     round(rect.x1, 1), round(rect.y1, 1)],
                            "hidden_chars": hidden_chars,
                            "sample_text": hidden_texts[:2],
                        })
        except Exception as e:
            logger.debug("Error during fake redaction check: %s", e)
        finally:
            doc.close()

        if fake_redactions:
            # Many rects with text underneath (>8) = likely table/form layout,
            # not targeted redaction. Real fake redactions are surgical: 1-5 rects.
            if len(fake_redactions) > 8:
                return  # Table layout, not redaction

            total_hidden = sum(r["hidden_chars"] for r in fake_redactions)
            findings.append(
                AnalyzerFinding(
                    code="DOC_FAKE_REDACTION",
                    title="Otkrivena lazna redakcija",
                    description=(
                        f"Pronadeno {len(fake_redactions)} pravokutnika koji prekrivaju citljiv tekst "
                        f"({total_hidden} skrivenih znakova). Tekst ispod 'redakcija' je jos uvijek "
                        f"ekstrahibilan — ovo je LAZNA redakcija koja skriva ali ne uklanja sadrzaj."
                    ),
                    risk_score=0.85,
                    confidence=0.90,
                    evidence={
                        "fake_redactions": fake_redactions[:10],
                        "total_hidden_chars": total_hidden,
                        "pages_analyzed": max_pages,
                    },
                )
            )

    # ------------------------------------------------------------------
    # F. Shadow Attack Detection (PyMuPDF) — Enhanced
    # ------------------------------------------------------------------

    def _check_shadow_attacks(
        self, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Detect shadow attacks: hidden layers, overlay percentage, Kids swap."""
        if not _PYMUPDF_AVAILABLE:
            return

        try:
            doc = fitz.open(stream=doc_bytes, filetype="pdf")
        except Exception as e:
            logger.debug("PyMuPDF could not open PDF for shadow check: %s", e)
            return

        shadow_indicators: list[dict] = []

        try:
            # 1. Check Optional Content Groups (OCG) — layer visibility manipulation
            ocgs = doc.get_ocgs()
            if ocgs:
                hidden_layers = []
                for xref, info in ocgs.items():
                    # OCGs with "OFF" initial state hide content by default
                    if info.get("on") is False or info.get("intent") == "Design":
                        hidden_layers.append({
                            "name": info.get("name", "unnamed"),
                            "xref": xref,
                            "on": info.get("on"),
                        })

                if hidden_layers:
                    shadow_indicators.append({
                        "type": "hidden_ocg_layers",
                        "count": len(hidden_layers),
                        "layers": hidden_layers[:5],
                    })

            max_pages = min(len(doc), 20)

            # 2. Overlay Percentage: images/annotations covering text
            overlay_findings: list[dict] = []
            suspicious_annots: list[dict] = []

            for page_idx in range(max_pages):
                page = doc[page_idx]
                page_rect = page.rect
                page_area = page_rect.width * page_rect.height

                # Get text bounding boxes
                text_dict = page.get_text("dict", flags=0)
                text_rects: list[fitz.Rect] = []
                for block in text_dict.get("blocks", []):
                    if block.get("type") == 0:  # text block
                        text_rects.append(fitz.Rect(block["bbox"]))

                if not text_rects:
                    continue

                total_text_area = sum(r.width * r.height for r in text_rects)
                if total_text_area <= 0:
                    continue

                # Get image bounding boxes
                image_rects: list[fitz.Rect] = []
                img_list = page.get_images(full=True)
                for img_info in img_list:
                    try:
                        img_rects_on_page = page.get_image_rects(img_info[0])
                        for ir in img_rects_on_page:
                            if isinstance(ir, fitz.Rect) and ir.width > 20 and ir.height > 20:
                                image_rects.append(ir)
                    except Exception:
                        continue

                # Check annotations
                annots = list(page.annots()) if page.annots() else []
                annot_rects: list[fitz.Rect] = []
                for annot in annots:
                    annot_area = annot.rect.width * annot.rect.height
                    if page_area > 0 and annot_area / page_area > 0.20:
                        suspicious_annots.append({
                            "page": page_idx + 1,
                            "type": annot.type[1],
                            "coverage_pct": round(annot_area / page_area * 100, 1),
                        })
                    if annot.rect.width > 20 and annot.rect.height > 20:
                        annot_rects.append(annot.rect)

                # Calculate overlay percentage for images and annotations over text
                all_overlay_rects = image_rects + annot_rects
                for overlay_rect in all_overlay_rects:
                    overlap_area = 0.0
                    for text_rect in text_rects:
                        intersection = overlay_rect & text_rect
                        if not intersection.is_empty:
                            overlap_area += intersection.width * intersection.height

                    if overlap_area > 0:
                        overlay_pct = overlap_area / total_text_area
                        if overlay_pct > 0.30:
                            overlay_findings.append({
                                "page": page_idx + 1,
                                "overlay_percentage": round(overlay_pct, 3),
                                "overlay_rect": [
                                    round(overlay_rect.x0, 1), round(overlay_rect.y0, 1),
                                    round(overlay_rect.x1, 1), round(overlay_rect.y1, 1),
                                ],
                            })

            if overlay_findings:
                max_overlay = max(f["overlay_percentage"] for f in overlay_findings)
                findings.append(
                    AnalyzerFinding(
                        code="DOC_SHADOW_HIDE_ATTACK",
                        title="Otkriveno prekrivanje teksta (Hide Shadow napad)",
                        description=(
                            f"Slika ili anotacija prekriva {round(max_overlay * 100, 1)}% "
                            f"tekstualnog sadrzaja na stranici. Ovo je tipican 'Hide' Shadow "
                            f"napad u kojem se originalni tekst maskira vizualnim prekrivanjem."
                        ),
                        risk_score=0.75,
                        confidence=0.85,
                        evidence={
                            "overlays": overlay_findings[:5],
                            "max_overlay_percentage": round(max_overlay, 3),
                        },
                    )
                )

            if suspicious_annots:
                shadow_indicators.append({
                    "type": "large_overlay_annotations",
                    "count": len(suspicious_annots),
                    "annotations": suspicious_annots[:5],
                })

            # 3. Check for Form XObjects — excessive count
            orphan_xobjects: list[dict] = []
            for page_idx in range(max_pages):
                page = doc[page_idx]
                xobjects = page.get_xobjects()
                if len(xobjects) > 5:
                    orphan_xobjects.append({
                        "page": page_idx + 1,
                        "xobject_count": len(xobjects),
                    })

            if orphan_xobjects:
                shadow_indicators.append({
                    "type": "excessive_xobjects",
                    "pages": orphan_xobjects[:5],
                })

            # 4. Kids Reference Swap Detection
            self._check_kids_reference_swap(doc, doc_bytes, findings)

        except Exception as e:
            logger.debug("Error during shadow attack check: %s", e)
        finally:
            doc.close()

        if shadow_indicators:
            indicator_types = [s["type"] for s in shadow_indicators]
            findings.append(
                AnalyzerFinding(
                    code="DOC_SHADOW_ATTACK",
                    title="Indikatori shadow napada",
                    description=(
                        f"Detektirano {len(shadow_indicators)} indikatora moguceg shadow napada: "
                        f"{', '.join(indicator_types)}. Shadow napadi koriste skrivene slojeve ili "
                        f"overlay sadrzaj za maskiranje pravog teksta dokumenta."
                    ),
                    risk_score=0.70,
                    confidence=0.75,
                    evidence={"indicators": shadow_indicators},
                )
            )

    # ------------------------------------------------------------------
    # F2. Kids Reference Swap Detection
    # ------------------------------------------------------------------

    def _check_kids_reference_swap(
        self, doc: "fitz.Document", doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Detect Hide-and-Replace shadow attack via Kids array manipulation."""
        # Only relevant if document has multiple revisions
        eof_count = len(re.findall(rb"%%EOF", doc_bytes))
        if eof_count < 2:
            return

        try:
            # Extract Kids references from the raw PDF
            # Look for /Kids arrays in the document
            kids_pattern = re.compile(rb"/Kids\s*\[([^\]]+)\]")
            kids_matches = kids_pattern.findall(doc_bytes)

            if len(kids_matches) < 2:
                return

            # Parse object references from Kids arrays
            ref_pattern = re.compile(rb"(\d+)\s+\d+\s+R")
            kids_sets: list[set[int]] = []

            for kids_raw in kids_matches:
                refs = {int(m.group(1)) for m in ref_pattern.finditer(kids_raw)}
                if refs:
                    kids_sets.append(refs)

            # Check if Kids arrays differ between revisions
            if len(kids_sets) >= 2:
                first_kids = kids_sets[0]
                for i, later_kids in enumerate(kids_sets[1:], 1):
                    if first_kids != later_kids:
                        added = later_kids - first_kids
                        removed = first_kids - later_kids

                        if removed:  # Pages were swapped out
                            findings.append(
                                AnalyzerFinding(
                                    code="DOC_SHADOW_KIDS_SWAP",
                                    title="Otkrivena zamjena stabla stranica (Hide-and-Replace)",
                                    description=(
                                        "Kids niz unutar Pages objekta promijenjen je izmedu "
                                        "revizija dokumenta — stranice su zamijenjene alternativnim "
                                        "stablom objekata. Ovo je tipican 'Hide-and-Replace' Shadow "
                                        "napad koji preusmjerava PDF citac na lazni sadrzaj."
                                    ),
                                    risk_score=0.80,
                                    confidence=0.85,
                                    evidence={
                                        "revision_count": eof_count,
                                        "kids_sets_found": len(kids_sets),
                                        "removed_refs": sorted(removed)[:10],
                                        "added_refs": sorted(added)[:10],
                                    },
                                )
                            )
                            return  # One finding is enough

        except Exception as e:
            logger.debug("Kids reference swap check error: %s", e)

    # ------------------------------------------------------------------
    # G. Orphaned Object Detection
    # ------------------------------------------------------------------

    def _check_orphaned_objects(
        self, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Detect orphaned objects — remnants of previous document versions."""
        if not _PYMUPDF_AVAILABLE:
            return

        try:
            doc = fitz.open(stream=doc_bytes, filetype="pdf")
        except Exception as e:
            logger.debug("Could not open PDF for orphan check: %s", e)
            return

        try:
            total_xrefs = doc.xref_length()
            if total_xrefs < 5:
                return

            # Collect all xrefs referenced from the active page tree
            referenced_xrefs: set[int] = set()

            # Pages and their content
            for page_idx in range(len(doc)):
                page = doc[page_idx]
                referenced_xrefs.add(page.xref)
                # Page fonts
                for font_info in page.get_fonts():
                    if font_info[0] > 0:
                        referenced_xrefs.add(font_info[0])
                # Page images
                for img_info in page.get_images():
                    if img_info[0] > 0:
                        referenced_xrefs.add(img_info[0])

            # Check for orphaned stream objects
            orphan_count = 0
            orphan_text_fragments: list[str] = []

            for xref in range(1, total_xrefs):
                if xref in referenced_xrefs:
                    continue

                try:
                    if doc.xref_is_stream(xref):
                        orphan_count += 1

                        # Try to extract text from orphaned streams
                        if len(orphan_text_fragments) < 5:
                            try:
                                stream_data = doc.xref_stream(xref)
                                if stream_data:
                                    # Try to decode as text
                                    try:
                                        text = stream_data.decode("utf-8", errors="ignore")
                                    except Exception:
                                        text = stream_data.decode("latin-1", errors="ignore")

                                    # Look for readable text fragments
                                    # PDF text operators: Tj, TJ, ' , "
                                    text_ops = re.findall(r"\(([^)]{3,50})\)", text)
                                    for op in text_ops[:3]:
                                        clean = op.strip()
                                        if clean and any(c.isalnum() for c in clean):
                                            orphan_text_fragments.append(clean[:50])
                            except Exception:
                                pass
                except Exception:
                    continue

            orphan_ratio = orphan_count / max(total_xrefs, 1)

            if orphan_count > 0:
                evidence = {
                    "total_xrefs": total_xrefs,
                    "orphan_stream_count": orphan_count,
                    "orphan_ratio": round(orphan_ratio, 4),
                    "referenced_xrefs": len(referenced_xrefs),
                }

                if orphan_text_fragments:
                    evidence["orphan_text_samples"] = orphan_text_fragments[:5]

                    findings.append(
                        AnalyzerFinding(
                            code="DOC_ORPHANED_TEXT_CONTENT",
                            title="Tekst u napustenim objektima dokumenta",
                            description=(
                                f"Pronadeno {orphan_count} napustenih stream objekata "
                                f"od kojih neki sadrze citljiv tekst. Ovo su ostaci "
                                f"prethodnih verzija dokumenta — moguc dokaz da je "
                                f"originalni sadrzaj (npr. iznos na fakturi) izbrisan i "
                                f"zamijenjen novim."
                            ),
                            risk_score=0.70,
                            confidence=0.85,
                            evidence=evidence,
                        )
                    )
                elif orphan_ratio > 0.05:
                    findings.append(
                        AnalyzerFinding(
                            code="DOC_ORPHANED_OBJECTS",
                            title="Napusteni objekti u strukturi dokumenta",
                            description=(
                                f"Pronadeno {orphan_count} stream objekata ({round(orphan_ratio * 100, 1)}% "
                                f"ukupnih) koji nisu referencirani iz aktivnog stabla dokumenta. "
                                f"Visok omjer napustenih objekata ukazuje na visestruko uredivanje "
                                f"i moguce brisanje originalnog sadrzaja."
                            ),
                            risk_score=0.45,
                            confidence=0.75,
                            evidence=evidence,
                        )
                    )
        except Exception as e:
            logger.debug("Orphaned object check error: %s", e)
        finally:
            doc.close()

    # ------------------------------------------------------------------
    # H. Visual vs OCR Comparison
    # ------------------------------------------------------------------

    def _check_visual_vs_ocr(
        self, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Render PDF to image, OCR it, compare with embedded text layer.

        Catches:
        - Black rectangles hiding text (OCR misses it, text layer has it)
        - Invisible text differing from visible content
        - Text replacement where visual != text layer
        """
        if not _PYMUPDF_AVAILABLE or not _TESSERACT_AVAILABLE:
            return

        try:
            doc = fitz.open(stream=doc_bytes, filetype="pdf")
        except Exception as e:
            logger.debug("Could not open PDF for visual-vs-OCR: %s", e)
            return

        page_diffs: list[dict] = []

        try:
            max_pages = min(len(doc), 5)  # Limit for performance (OCR is slow)

            for page_idx in range(max_pages):
                page = doc[page_idx]

                # 1. Extract text from PDF text layer (what copy-paste gives)
                text_layer = page.get_text("text").strip()
                if not text_layer:
                    continue  # Skip pages with no text layer

                # 2. Render page to image and OCR it (what human eyes see)
                # Use 150 DPI for speed/quality balance
                pix = page.get_pixmap(dpi=150)
                img_bytes = pix.tobytes("png")
                pil_img = Image.open(io.BytesIO(img_bytes))

                try:
                    ocr_text = pytesseract.image_to_string(
                        pil_img, lang="hrv+eng", timeout=15
                    ).strip()
                except Exception as e:
                    logger.debug("OCR failed on page %d: %s", page_idx, e)
                    continue

                if not ocr_text:
                    continue

                # 3. Normalize both texts for comparison
                def _normalize(t: str) -> str:
                    # Strip replacement chars and encoding artifacts
                    t = t.replace("\ufffd", "")  # U+FFFD replacement char
                    # Remove all non-ASCII non-letter chars that differ
                    # between text extraction and OCR due to encoding
                    # (Latin-2/WinAnsi č/š/ž → garbled in extraction)
                    t = re.sub(r"[^\x20-\x7E]", "", t)  # Keep only ASCII printable
                    # Remove punctuation that OCR often garbles
                    t = re.sub(r"[^\w\s]", " ", t)
                    # Collapse whitespace, lowercase
                    t = re.sub(r"\s+", " ", t).strip().lower()
                    return t

                text_norm = _normalize(text_layer)
                ocr_norm = _normalize(ocr_text)

                if not text_norm or not ocr_norm:
                    continue

                # 4. Compare using SequenceMatcher
                matcher = difflib.SequenceMatcher(None, text_norm, ocr_norm)
                similarity = matcher.ratio()

                if similarity > 0.80:
                    continue  # Texts match well enough

                # 5. Find specific differences
                # Text in layer but NOT in OCR = hidden/invisible text
                # Text in OCR but NOT in layer = visible but not in text layer (image-based)
                text_words = set(text_norm.split())
                ocr_words = set(ocr_norm.split())

                only_in_layer = text_words - ocr_words
                only_in_ocr = ocr_words - text_words

                # Filter out short words and OCR noise (garbled characters)
                only_in_layer = {w for w in only_in_layer if len(w) > 3}
                only_in_ocr = {w for w in only_in_ocr
                               if len(w) > 3 and w.isalpha()}  # OCR junk is non-alpha

                if len(only_in_layer) > 5 or len(only_in_ocr) > 5 or similarity < 0.50:
                    page_diffs.append({
                        "page": page_idx + 1,
                        "similarity": round(similarity, 3),
                        "text_layer_len": len(text_norm),
                        "ocr_text_len": len(ocr_norm),
                        "only_in_text_layer": sorted(only_in_layer)[:10],
                        "only_in_ocr": sorted(only_in_ocr)[:10],
                    })

        except Exception as e:
            logger.debug("Visual-vs-OCR check error: %s", e)
        finally:
            doc.close()

        if not page_diffs:
            return

        worst = min(page_diffs, key=lambda d: d["similarity"])
        avg_sim = sum(d["similarity"] for d in page_diffs) / len(page_diffs)

        if worst["similarity"] < 0.30:
            # Major discrepancy — likely hidden text or content manipulation
            findings.append(
                AnalyzerFinding(
                    code="DOC_VISUAL_OCR_MAJOR_MISMATCH",
                    title="Velika nepodudarnost vizualnog i tekstualnog sloja",
                    description=(
                        f"Vizualni sadrzaj stranice {worst['page']} znacajno se razlikuje "
                        f"od ugradenog tekstualnog sloja (podudarnost: {worst['similarity']:.0%}). "
                        f"Ovo ukazuje na skriveni tekst, crne pravokutnike koji maskiraju "
                        f"sadrzaj, ili manipulaciju tekstualnog sloja."
                    ),
                    risk_score=0.75,
                    confidence=0.75,
                    evidence={
                        "page_diffs": page_diffs[:5],
                        "average_similarity": round(avg_sim, 3),
                        "worst_page": worst["page"],
                    },
                )
            )
        elif worst["similarity"] < 0.50:
            findings.append(
                AnalyzerFinding(
                    code="DOC_VISUAL_OCR_MISMATCH",
                    title="Nepodudarnost vizualnog i tekstualnog sloja",
                    description=(
                        f"Na {len(page_diffs)} stranica otkrivena je razlika izmedu "
                        f"onoga sto se vidi (OCR) i ugradenog teksta "
                        f"(prosjecna podudarnost: {avg_sim:.0%}). "
                        f"Moguca manipulacija sadrzaja ili skriveni tekst."
                    ),
                    risk_score=0.55,
                    confidence=0.70,
                    evidence={
                        "page_diffs": page_diffs[:5],
                        "average_similarity": round(avg_sim, 3),
                    },
                )
            )
        else:
            findings.append(
                AnalyzerFinding(
                    code="DOC_VISUAL_OCR_MINOR_DIFF",
                    title="Blage razlike vizualnog i tekstualnog sloja",
                    description=(
                        f"Na {len(page_diffs)} stranica postoje manje razlike "
                        f"izmedu vizualnog prikaza i tekstualnog sloja "
                        f"(prosjecna podudarnost: {avg_sim:.0%})."
                    ),
                    risk_score=0.35,
                    confidence=0.65,
                    evidence={
                        "page_diffs": page_diffs[:5],
                        "average_similarity": round(avg_sim, 3),
                    },
                )
            )

    # ------------------------------------------------------------------
    # I. Per-Character Font Metrics (rawdict baseline/kerning)
    # ------------------------------------------------------------------

    def _check_char_metrics_anomalies(
        self, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Detect per-character baseline/kerning anomalies via PyMuPDF rawdict.

        When someone edits a single digit or character in a PDF, the replacement
        character often has subtly different metrics (baseline offset, width,
        kerning gap) compared to its neighbors from the original font rendering.
        """
        if not _PYMUPDF_AVAILABLE:
            return

        try:
            doc = fitz.open(stream=doc_bytes, filetype="pdf")
        except Exception as e:
            logger.debug("Could not open PDF for char metrics: %s", e)
            return

        anomalous_spans: list[dict] = []

        try:
            max_pages = min(len(doc), 10)

            for page_idx in range(max_pages):
                page = doc[page_idx]
                # rawdict gives per-character bounding boxes
                raw = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

                for block in raw.get("blocks", []):
                    if block.get("type") != 0:
                        continue

                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            chars = span.get("chars", [])
                            if len(chars) < 4:
                                continue

                            font_name = span.get("font", "")
                            font_size = span.get("size", 0)

                            # Collect baselines (y1 = bottom of char bbox)
                            baselines = []
                            widths = []
                            kernings = []

                            for i, ch in enumerate(chars):
                                c = ch.get("c", "")
                                if not c.strip():
                                    continue  # Skip whitespace

                                bbox = ch.get("bbox")
                                if not bbox or len(bbox) < 4:
                                    continue

                                x0, y0, x1, y1 = bbox
                                baselines.append(y1)
                                widths.append(x1 - x0)

                                # Kerning: gap between this char and previous
                                if i > 0 and chars[i - 1].get("bbox"):
                                    prev_x1 = chars[i - 1]["bbox"][2]
                                    kernings.append(x0 - prev_x1)

                            if len(baselines) < 4:
                                continue

                            # Detect baseline anomalies
                            bl_arr = np.array(baselines)
                            bl_median = np.median(bl_arr)
                            bl_deviations = np.abs(bl_arr - bl_median)
                            # A normal span should have very consistent baselines
                            # (within ~0.5pt for same-font text)
                            threshold = max(0.5, font_size * 0.03)
                            outlier_mask = bl_deviations > threshold
                            n_bl_outliers = int(np.sum(outlier_mask))

                            # Detect width anomalies — only meaningful for
                            # monospaced or near-monospaced chars (digits, etc.)
                            # Variable-width fonts (Helvetica, Arial, Times) naturally
                            # have large width variance — skip width check for them.
                            w_arr = np.array(widths)
                            w_median = np.median(w_arr)
                            w_cv = float(np.std(w_arr) / max(w_median, 0.1))
                            # Coefficient of variation > 0.25 = variable-width font, skip
                            if w_cv > 0.25:
                                n_w_outliers = 0
                            else:
                                w_threshold = max(0.5, w_median * 0.20)
                                w_deviations = np.abs(w_arr - w_median)
                                n_w_outliers = int(np.sum(w_deviations > w_threshold))

                            # Detect kerning anomalies
                            n_k_outliers = 0
                            if len(kernings) >= 3:
                                k_arr = np.array(kernings)
                                k_median = np.median(k_arr)
                                k_threshold = max(0.3, abs(k_median) * 0.30 + 0.5)
                                k_deviations = np.abs(k_arr - k_median)
                                n_k_outliers = int(np.sum(k_deviations > k_threshold))

                            # Flag if multiple anomaly types detected in same span
                            total_anomalies = n_bl_outliers + n_w_outliers + n_k_outliers
                            char_count = len(baselines)

                            # Require baseline OR kerning anomalies (not just width)
                            # and multiple anomaly types to reduce false positives
                            has_structural = n_bl_outliers >= 1 or n_k_outliers >= 1
                            if has_structural and total_anomalies >= 3 and total_anomalies <= char_count * 0.35:
                                text_sample = span.get("text", "")[:60]
                                anomalous_spans.append({
                                    "page": page_idx + 1,
                                    "text": text_sample,
                                    "font": font_name,
                                    "font_size": round(font_size, 1),
                                    "baseline_outliers": n_bl_outliers,
                                    "width_outliers": n_w_outliers,
                                    "kerning_outliers": n_k_outliers,
                                    "total_chars": char_count,
                                })

        except Exception as e:
            logger.debug("Char metrics check error: %s", e)
        finally:
            doc.close()

        if not anomalous_spans:
            return

        # Group: many anomalous spans → likely systematic editing
        if len(anomalous_spans) >= 8:
            findings.append(
                AnalyzerFinding(
                    code="DOC_CHAR_METRICS_SYSTEMATIC",
                    title="Sustavne anomalije metrika znakova",
                    description=(
                        f"Otkriveno {len(anomalous_spans)} tekstualnih segmenata s "
                        f"nekonzistentnim baseline, sirinom ili kerning razmacima. "
                        f"Kad netko editira pojedine znakove (npr. cifre na fakturi), "
                        f"zamijenjeni znakovi imaju subtilno razlicite tipografske metrike."
                    ),
                    risk_score=0.70,
                    confidence=0.75,
                    evidence={"anomalous_spans": anomalous_spans[:10]},
                )
            )
        elif len(anomalous_spans) >= 2:
            findings.append(
                AnalyzerFinding(
                    code="DOC_CHAR_METRICS_ANOMALY",
                    title="Anomalije metrika znakova",
                    description=(
                        f"Otkriveno {len(anomalous_spans)} segmenata gdje pojedini "
                        f"znakovi imaju razlicitu baseline poziciju, sirinu ili kerning "
                        f"u odnosu na susjedne znakove istog fonta. Moguci trag "
                        f"rucnog uredivanja teksta u PDF editoru."
                    ),
                    risk_score=0.55,
                    confidence=0.70,
                    evidence={"anomalous_spans": anomalous_spans[:10]},
                )
            )
        else:
            findings.append(
                AnalyzerFinding(
                    code="DOC_CHAR_METRICS_MINOR",
                    title="Blaga anomalija metrika znakova",
                    description=(
                        f"Jedan tekstualni segment pokazuje nekonzistentne tipografske "
                        f"metrike — moguce uredivanje pojedinog znaka."
                    ),
                    risk_score=0.35,
                    confidence=0.60,
                    evidence={"anomalous_spans": anomalous_spans[:5]},
                )
            )

    # ------------------------------------------------------------------
    # J. PDF Version Recovery + Pixel Diff
    # ------------------------------------------------------------------

    def _check_version_pixel_diff(
        self, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Extract all PDF revisions and compute pixel diffs between them.

        For documents with incremental saves (multiple %%EOF markers),
        we can recover each version by truncating at each %%EOF boundary
        and rendering the pages. Pixel diffs show EXACTLY what changed.
        """
        if not _PYMUPDF_AVAILABLE:
            return

        # Find %%EOF positions
        eof_positions = [m.end() for m in re.finditer(rb"%%EOF", doc_bytes)]
        if len(eof_positions) < 2:
            return  # Only one version, nothing to diff

        # Extract version snapshots (truncate at each %%EOF)
        versions: list[bytes] = []
        for eof_end in eof_positions:
            # Include any trailing whitespace/newline after %%EOF
            end_pos = min(eof_end + 2, len(doc_bytes))
            version_bytes = doc_bytes[:end_pos]
            # Verify it's a valid PDF by trying to open it
            try:
                test_doc = fitz.open(stream=version_bytes, filetype="pdf")
                if len(test_doc) > 0:
                    versions.append(version_bytes)
                test_doc.close()
            except Exception:
                continue

        if len(versions) < 2:
            return  # Need at least 2 valid versions to diff

        # Limit to first and last version for performance (and one middle if many)
        if len(versions) > 3:
            versions = [versions[0], versions[len(versions) // 2], versions[-1]]

        version_diffs: list[dict] = []
        diff_heatmaps: list[str] = []

        for i in range(len(versions) - 1):
            try:
                doc_old = fitz.open(stream=versions[i], filetype="pdf")
                doc_new = fitz.open(stream=versions[i + 1], filetype="pdf")

                # Compare first page of each version (most document modifications happen on page 1)
                max_cmp_pages = min(len(doc_old), len(doc_new), 3)

                for page_idx in range(max_cmp_pages):
                    page_old = doc_old[page_idx]
                    page_new = doc_new[page_idx]

                    # Render at 150 DPI
                    pix_old = page_old.get_pixmap(dpi=150)
                    pix_new = page_new.get_pixmap(dpi=150)

                    # Convert to numpy arrays
                    arr_old = np.frombuffer(pix_old.samples, dtype=np.uint8).reshape(
                        pix_old.height, pix_old.width, pix_old.n
                    )
                    arr_new = np.frombuffer(pix_new.samples, dtype=np.uint8).reshape(
                        pix_new.height, pix_new.width, pix_new.n
                    )

                    # Ensure same dimensions (crop to minimum)
                    min_h = min(arr_old.shape[0], arr_new.shape[0])
                    min_w = min(arr_old.shape[1], arr_new.shape[1])
                    min_c = min(arr_old.shape[2], arr_new.shape[2])
                    arr_old = arr_old[:min_h, :min_w, :min_c]
                    arr_new = arr_new[:min_h, :min_w, :min_c]

                    # Compute absolute difference
                    diff = np.abs(arr_old.astype(np.int16) - arr_new.astype(np.int16)).astype(np.uint8)
                    diff_gray = np.max(diff, axis=2)  # Max across channels

                    # Count significantly different pixels (threshold > 10)
                    changed_mask = diff_gray > 10
                    n_changed = int(np.sum(changed_mask))
                    total_pixels = diff_gray.size
                    change_ratio = n_changed / max(total_pixels, 1)

                    if change_ratio < 0.001:
                        continue  # Less than 0.1% changed — ignore

                    # Find bounding box of changes
                    rows = np.any(changed_mask, axis=1)
                    cols = np.any(changed_mask, axis=0)
                    if not np.any(rows):
                        continue

                    rmin, rmax = int(np.where(rows)[0][0]), int(np.where(rows)[0][-1])
                    cmin, cmax = int(np.where(cols)[0][0]), int(np.where(cols)[0][-1])

                    # Create a diff heatmap image (amplify differences)
                    heatmap = np.clip(diff_gray * 10, 0, 255).astype(np.uint8)
                    heatmap_img = Image.fromarray(heatmap, mode="L")
                    # Apply a red tint: changed pixels in red, unchanged in gray
                    heatmap_rgb = Image.merge("RGB", (
                        heatmap_img,
                        Image.fromarray(np.zeros_like(heatmap), mode="L"),
                        Image.fromarray(np.zeros_like(heatmap), mode="L"),
                    ))
                    # Composite over the new version for context
                    new_img = Image.fromarray(arr_new[:, :, :3] if arr_new.shape[2] >= 3 else arr_new)
                    if new_img.mode != "RGB":
                        new_img = new_img.convert("RGB")
                    composite = Image.blend(new_img, heatmap_rgb, alpha=0.5)

                    # Encode to base64
                    buf = io.BytesIO()
                    composite.save(buf, format="JPEG", quality=60)
                    diff_b64 = base64.b64encode(buf.getvalue()).decode()
                    if len(diff_heatmaps) < 3:
                        diff_heatmaps.append(diff_b64)

                    version_diffs.append({
                        "from_version": i + 1,
                        "to_version": i + 2,
                        "page": page_idx + 1,
                        "change_ratio": round(change_ratio, 4),
                        "changed_pixels": n_changed,
                        "total_pixels": total_pixels,
                        "change_bbox": {
                            "top": rmin, "left": cmin,
                            "bottom": rmax, "right": cmax,
                        },
                    })

                doc_old.close()
                doc_new.close()

            except Exception as e:
                logger.debug("Version diff error (v%d→v%d): %s", i + 1, i + 2, e)
                continue

        if not version_diffs:
            return

        max_change = max(d["change_ratio"] for d in version_diffs)
        evidence = {
            "total_versions": len(eof_positions),
            "diffs": version_diffs[:5],
        }
        if diff_heatmaps:
            evidence["diff_heatmap_b64"] = diff_heatmaps[0]

        if max_change > 0.05:
            # More than 5% of pixels changed — significant modification
            findings.append(
                AnalyzerFinding(
                    code="DOC_VERSION_MAJOR_CHANGE",
                    title="Znacajne vizualne promjene izmedu verzija dokumenta",
                    description=(
                        f"Usporedba {len(eof_positions)} verzija dokumenta otkriva "
                        f"promjenu {max_change:.1%} piksela. Pixel diff jasno pokazuje "
                        f"TOCNO koja podrucja su izmijenjena izmedu revizija."
                    ),
                    risk_score=0.75,
                    confidence=0.85,
                    evidence=evidence,
                )
            )
        elif max_change > 0.005:
            findings.append(
                AnalyzerFinding(
                    code="DOC_VERSION_CHANGE",
                    title="Vizualne promjene izmedu verzija dokumenta",
                    description=(
                        f"Pixel diff izmedu {len(eof_positions)} verzija otkriva "
                        f"izmjene na {max_change:.2%} piksela — lokalizirane promjene "
                        f"u specifičnim podrucjima dokumenta."
                    ),
                    risk_score=0.55,
                    confidence=0.80,
                    evidence=evidence,
                )
            )
        else:
            findings.append(
                AnalyzerFinding(
                    code="DOC_VERSION_MINOR_CHANGE",
                    title="Manje vizualne razlike izmedu verzija",
                    description=(
                        f"Pixel diff otkriva minimalne promjene ({max_change:.3%}) "
                        f"izmedu verzija — moguce samo formatiranje ili metadata update."
                    ),
                    risk_score=0.25,
                    confidence=0.70,
                    evidence=evidence,
                )
            )

    # ------------------------------------------------------------------
    # K. ELA on Embedded Images
    # ------------------------------------------------------------------

    def _check_embedded_image_ela(
        self, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Run Error Level Analysis on images embedded within the PDF.

        Photos inside PDF documents (e.g., ID photos, scanned receipts) can be
        manipulated. ELA detects compression-level inconsistencies that indicate
        pixel-level editing within those embedded images.
        """
        if not _PYMUPDF_AVAILABLE:
            return

        try:
            doc = fitz.open(stream=doc_bytes, filetype="pdf")
        except Exception as e:
            logger.debug("Could not open PDF for embedded ELA: %s", e)
            return

        ela_results: list[dict] = []

        try:
            seen_xrefs: set[int] = set()

            for page_idx in range(min(len(doc), 20)):
                page = doc[page_idx]
                img_list = page.get_images(full=True)

                for img_info in img_list:
                    xref = img_info[0]
                    if xref in seen_xrefs or xref <= 0:
                        continue
                    seen_xrefs.add(xref)

                    try:
                        base_image = doc.extract_image(xref)
                        if not base_image:
                            continue

                        img_bytes = base_image.get("image")
                        width = base_image.get("width", 0)
                        height = base_image.get("height", 0)

                        # Skip tiny images
                        if width < 100 or height < 100:
                            continue
                        if not img_bytes or len(img_bytes) < 1000:
                            continue

                        # Run ELA
                        anomaly_ratio, heatmap_b64 = self._perform_ela(img_bytes)

                        if anomaly_ratio > 0.02:  # More than 2% anomalous pixels
                            ela_results.append({
                                "page": page_idx + 1,
                                "xref": xref,
                                "image_size": f"{width}x{height}",
                                "anomaly_ratio": round(anomaly_ratio, 4),
                                "ela_heatmap_b64": heatmap_b64,
                            })

                    except Exception:
                        continue

        except Exception as e:
            logger.debug("Embedded image ELA error: %s", e)
        finally:
            doc.close()

        if not ela_results:
            return

        worst = max(ela_results, key=lambda r: r["anomaly_ratio"])
        evidence = {
            "images_analyzed": len(ela_results),
            "ela_results": [{k: v for k, v in r.items() if k != "ela_heatmap_b64"}
                            for r in ela_results[:5]],
        }
        if worst.get("ela_heatmap_b64"):
            evidence["ela_heatmap_b64"] = worst["ela_heatmap_b64"]

        if worst["anomaly_ratio"] > 0.10:
            findings.append(
                AnalyzerFinding(
                    code="DOC_EMBEDDED_IMG_ELA_HIGH",
                    title="Visoka ELA anomalija u ugradenoj slici",
                    description=(
                        f"Error Level Analysis otkriva znacajne anomalije kompresije "
                        f"({worst['anomaly_ratio']:.1%} anomalnih piksela) u slici na "
                        f"stranici {worst['page']}. Ovo ukazuje na manipulaciju piksela "
                        f"unutar fotografije ugradene u dokument."
                    ),
                    risk_score=0.70,
                    confidence=0.80,
                    evidence=evidence,
                )
            )
        elif worst["anomaly_ratio"] > 0.04:
            findings.append(
                AnalyzerFinding(
                    code="DOC_EMBEDDED_IMG_ELA_MODERATE",
                    title="Umjerena ELA anomalija u ugradenoj slici",
                    description=(
                        f"Umjerene anomalije kompresije ({worst['anomaly_ratio']:.1%}) "
                        f"u ugradenoj slici na stranici {worst['page']}."
                    ),
                    risk_score=0.50,
                    confidence=0.70,
                    evidence=evidence,
                )
            )
        else:
            findings.append(
                AnalyzerFinding(
                    code="DOC_EMBEDDED_IMG_ELA_LOW",
                    title="Blage ELA anomalije u ugradenoj slici",
                    description=(
                        f"Blage anomalije kompresije ({worst['anomaly_ratio']:.2%}) "
                        f"u ugradenoj slici — moguca blaga manipulacija ili "
                        f"visestruka rekompresija."
                    ),
                    risk_score=0.30,
                    confidence=0.60,
                    evidence=evidence,
                )
            )

    @staticmethod
    def _perform_ela(img_bytes: bytes, quality: int = 95, scale: int = 20) -> tuple[float, str]:
        """Run ELA on a single image. Returns (anomaly_ratio, heatmap_b64)."""
        img = Image.open(io.BytesIO(img_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")

        # Re-save at fixed JPEG quality
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        buf.seek(0)
        resaved = Image.open(buf)

        # Compute absolute difference
        arr_orig = np.array(img, dtype=np.int16)
        arr_resaved = np.array(resaved, dtype=np.int16)
        diff = np.abs(arr_orig - arr_resaved).astype(np.uint8)

        # Amplify
        ela = np.clip(diff * scale, 0, 255).astype(np.uint8)

        # Grayscale for analysis
        ela_gray = np.max(ela, axis=2)

        # Anomaly ratio: pixels significantly above mean
        mean_val = float(np.mean(ela_gray))
        std_val = float(np.std(ela_gray))
        threshold = mean_val + 2.0 * std_val
        anomaly_mask = ela_gray > threshold
        anomaly_ratio = float(np.sum(anomaly_mask)) / max(ela_gray.size, 1)

        # Generate heatmap
        heatmap_img = Image.fromarray(ela)
        hm_buf = io.BytesIO()
        heatmap_img.save(hm_buf, format="JPEG", quality=50)
        heatmap_b64 = base64.b64encode(hm_buf.getvalue()).decode()

        return anomaly_ratio, heatmap_b64

    # ------------------------------------------------------------------
    # L. JavaScript / Dangerous Action Detection
    # ------------------------------------------------------------------

    def _check_dangerous_actions(
        self, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Detect embedded JavaScript and dangerous PDF actions.

        Invoices and financial documents should NEVER contain JavaScript,
        Launch actions, or auto-submission forms. Their presence is a
        strong indicator of either malware or sophisticated fraud.
        """
        raw = doc_bytes

        # Keywords to scan for, with risk levels and descriptions
        dangerous_keywords: list[tuple[bytes, str, float, str]] = [
            (b"/JavaScript", "DOC_DANGEROUS_JAVASCRIPT", 0.80,
             "Ugraden JavaScript kod — fakture i izvodi nikad ne sadrze JavaScript"),
            (b"/JS", "DOC_DANGEROUS_JS", 0.75,
             "Skracena JavaScript referenca u PDF objektu"),
            (b"/OpenAction", "DOC_DANGEROUS_OPENACTION", 0.60,
             "Automatska akcija pri otvaranju dokumenta"),
            (b"/AA", "DOC_DANGEROUS_AA", 0.50,
             "Dodatne automatske akcije (Additional Actions)"),
            (b"/Launch", "DOC_DANGEROUS_LAUNCH", 0.85,
             "Launch akcija — pokusaj pokretanja eksterne aplikacije"),
            (b"/SubmitForm", "DOC_DANGEROUS_SUBMITFORM", 0.80,
             "Automatsko slanje podataka na vanjski URL"),
            (b"/GoToR", "DOC_DANGEROUS_GOTOR", 0.45,
             "Referenca na vanjsku PDF datoteku (GoToR)"),
            (b"/GoToE", "DOC_DANGEROUS_GOTOE", 0.45,
             "Referenca na ugradenu datoteku (GoToE)"),
            (b"/EmbeddedFile", "DOC_DANGEROUS_EMBEDDED_FILE", 0.55,
             "Ugradena datoteka unutar PDF-a"),
            (b"/RichMedia", "DOC_DANGEROUS_RICHMEDIA", 0.60,
             "Ugraden multimedijalni sadrzaj (Flash, video)"),
        ]

        found_actions: list[dict] = []

        for keyword, code, risk, desc in dangerous_keywords:
            count = raw.count(keyword)
            if count > 0:
                found_actions.append({
                    "keyword": keyword.decode(),
                    "code": code,
                    "count": count,
                    "risk": risk,
                    "description": desc,
                })

        if not found_actions:
            return

        # Sort by risk descending
        found_actions.sort(key=lambda x: -x["risk"])
        worst = found_actions[0]

        # High-risk actions (JavaScript, Launch, SubmitForm)
        high_risk = [a for a in found_actions if a["risk"] >= 0.70]
        medium_risk = [a for a in found_actions if 0.40 <= a["risk"] < 0.70]

        evidence = {
            "dangerous_actions": [{k: v for k, v in a.items() if k != "description"}
                                  for a in found_actions],
        }

        if high_risk:
            action_names = ", ".join(a["keyword"] for a in high_risk)
            findings.append(
                AnalyzerFinding(
                    code="DOC_DANGEROUS_ACTIONS_HIGH",
                    title="Opasne akcije u dokumentu",
                    description=(
                        f"Dokument sadrzi {len(high_risk)} visokorizicnih akcija "
                        f"({action_names}). Legitimne fakture, izvodi i potvrde "
                        f"NIKAD ne sadrze JavaScript ili Launch akcije — ovo je "
                        f"snazni indikator zlonamjernog ili laznog dokumenta."
                    ),
                    risk_score=worst["risk"],
                    confidence=0.90,
                    evidence=evidence,
                )
            )
        elif medium_risk:
            action_names = ", ".join(a["keyword"] for a in medium_risk)
            findings.append(
                AnalyzerFinding(
                    code="DOC_DANGEROUS_ACTIONS_MEDIUM",
                    title="Sumnjive akcije u dokumentu",
                    description=(
                        f"Dokument sadrzi {len(medium_risk)} sumnjivih elemenata "
                        f"({action_names}). Neobicno za standardne poslovne dokumente."
                    ),
                    risk_score=worst["risk"],
                    confidence=0.75,
                    evidence=evidence,
                )
            )

    # ------------------------------------------------------------------
    # M. AcroForm / XFA Form Overlay Attack Detection
    # ------------------------------------------------------------------

    def _check_form_overlay_attacks(
        self, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Detect form fields with custom appearance streams overlaying content.

        A common tampering technique: place a form field with a custom
        appearance stream over original text. The visible content changes
        but the underlying PDF text layer remains — or vice versa.
        """
        if not _PYMUPDF_AVAILABLE:
            return

        try:
            doc = fitz.open(stream=doc_bytes, filetype="pdf")
        except Exception as e:
            logger.debug("Could not open PDF for form check: %s", e)
            return

        suspicious_fields: list[dict] = []
        has_xfa = False

        try:
            # Check for XFA (XML Forms Architecture) — highly unusual in normal docs
            raw = doc_bytes
            if b"/XFA" in raw:
                has_xfa = True

            max_pages = min(len(doc), 20)
            for page_idx in range(max_pages):
                page = doc[page_idx]

                # Get all widgets (form fields) on this page
                widgets = list(page.widgets()) if hasattr(page, "widgets") else []

                for widget in widgets:
                    try:
                        field_name = widget.field_name or ""
                        field_type = widget.field_type_string or ""
                        field_value = widget.field_value or ""
                        rect = widget.rect

                        # Check if this widget has a custom appearance stream
                        # Widgets with custom /AP that cover significant area
                        field_area = rect.width * rect.height
                        page_area = page.rect.width * page.rect.height

                        if field_area <= 0 or page_area <= 0:
                            continue

                        coverage = field_area / page_area

                        # Check if text exists under this widget
                        text_under = page.get_text("text", clip=rect).strip()

                        if coverage > 0.02 and text_under:
                            # Widget covers area with text underneath
                            suspicious_fields.append({
                                "page": page_idx + 1,
                                "field_name": field_name[:50],
                                "field_type": field_type,
                                "field_value": str(field_value)[:50],
                                "coverage_pct": round(coverage * 100, 2),
                                "text_underneath": text_under[:80],
                                "rect": [round(rect.x0), round(rect.y0),
                                         round(rect.x1), round(rect.y1)],
                            })

                    except Exception:
                        continue

        except Exception as e:
            logger.debug("Form overlay check error: %s", e)
        finally:
            doc.close()

        # XFA finding
        if has_xfa:
            findings.append(
                AnalyzerFinding(
                    code="DOC_XFA_FORM",
                    title="XFA formulari u dokumentu",
                    description=(
                        "Dokument sadrzi XML Forms Architecture (XFA) — napredni "
                        "formular sustav koji se rijetko koristi u standardnim "
                        "poslovnim dokumentima i moze sadrzavati skripta."
                    ),
                    risk_score=0.45,
                    confidence=0.70,
                    evidence={"has_xfa": True},
                )
            )

        if not suspicious_fields:
            return

        # Fields covering text = likely overlay attack
        total_covering = len(suspicious_fields)
        max_coverage = max(f["coverage_pct"] for f in suspicious_fields)

        if total_covering >= 3 or max_coverage > 10:
            findings.append(
                AnalyzerFinding(
                    code="DOC_FORM_OVERLAY_ATTACK",
                    title="Formular polja prekrivaju postojeci tekst",
                    description=(
                        f"Otkriveno {total_covering} interaktivnih polja formulara "
                        f"koja prekrivaju tekstualni sadrzaj ispod sebe (max pokrivanje: "
                        f"{max_coverage:.1f}%). Ovo je tipican napad gdje se form field "
                        f"s prilagodenim izgledom postavi preko originalnog teksta "
                        f"da bi se promijenio vidljivi sadrzaj."
                    ),
                    risk_score=0.75,
                    confidence=0.80,
                    evidence={"suspicious_fields": suspicious_fields[:10]},
                )
            )
        elif total_covering >= 1:
            findings.append(
                AnalyzerFinding(
                    code="DOC_FORM_OVERLAY_SUSPICIOUS",
                    title="Sumnjivo pozicionirano polje formulara",
                    description=(
                        f"Polje formulara '{suspicious_fields[0]['field_name']}' "
                        f"prekriva tekst na stranici {suspicious_fields[0]['page']}."
                    ),
                    risk_score=0.50,
                    confidence=0.70,
                    evidence={"suspicious_fields": suspicious_fields[:5]},
                )
            )

    # ------------------------------------------------------------------
    # N. Color Space Inconsistency Analysis
    # ------------------------------------------------------------------

    def _check_color_space_inconsistency(
        self, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Detect mixed color spaces within a document.

        When a document is created by one tool and edited by another,
        the original content typically uses one color space (e.g. DeviceCMYK)
        while edits use another (e.g. DeviceRGB or ICCBased). This
        inconsistency is a strong indicator of multi-tool editing.
        """
        if not _PYMUPDF_AVAILABLE:
            return

        try:
            doc = fitz.open(stream=doc_bytes, filetype="pdf")
        except Exception as e:
            logger.debug("Could not open PDF for color space check: %s", e)
            return

        page_colorspaces: dict[int, set[str]] = {}
        all_colorspaces: set[str] = set()

        try:
            max_pages = min(len(doc), 20)

            for page_idx in range(max_pages):
                page = doc[page_idx]
                cs_set: set[str] = set()

                # Extract color spaces from page resources
                try:
                    xref = page.xref
                    # Get the page's resource dictionary
                    res_str = doc.xref_object(xref)

                    # Look for color space references in the content
                    # Common patterns: /DeviceRGB, /DeviceCMYK, /DeviceGray,
                    # /ICCBased, /CalRGB, /CalGray, /Lab
                    cs_patterns = [
                        "DeviceRGB", "DeviceCMYK", "DeviceGray",
                        "ICCBased", "CalRGB", "CalGray", "Lab",
                        "Indexed", "Separation", "DeviceN",
                    ]

                    for cs in cs_patterns:
                        if cs in res_str:
                            cs_set.add(cs)

                    # Also check the content stream for inline color operators
                    try:
                        # Get raw content stream text
                        page_text_raw = page.get_text("rawdict", flags=0)
                        blocks = page_text_raw.get("blocks", [])
                        for block in blocks:
                            if block.get("type") == 0:
                                for line in block.get("lines", []):
                                    for span in line.get("spans", []):
                                        color = span.get("color", 0)
                                        # PyMuPDF returns color as int (RGB packed)
                                        if color != 0:
                                            cs_set.add("DeviceRGB")  # Text with color
                    except Exception:
                        pass

                except Exception:
                    continue

                if cs_set:
                    page_colorspaces[page_idx] = cs_set
                    all_colorspaces.update(cs_set)

        except Exception as e:
            logger.debug("Color space check error: %s", e)
        finally:
            doc.close()

        if len(all_colorspaces) < 2:
            return  # Uniform color space — normal

        # Check for suspicious mixes
        has_rgb = "DeviceRGB" in all_colorspaces
        has_cmyk = "DeviceCMYK" in all_colorspaces
        has_icc = "ICCBased" in all_colorspaces

        evidence = {
            "all_colorspaces": sorted(all_colorspaces),
            "per_page": {str(k): sorted(v) for k, v in page_colorspaces.items()},
        }

        # RGB + CMYK mix is the strongest signal of multi-tool editing
        if has_rgb and has_cmyk:
            findings.append(
                AnalyzerFinding(
                    code="DOC_COLORSPACE_MIXED_RGB_CMYK",
                    title="Mijesani RGB i CMYK prostori boja",
                    description=(
                        "Dokument kombinira DeviceRGB i DeviceCMYK prostore boja. "
                        "Kad se dokument generira jednim alatom, koristi se jedan "
                        "prostor boja. Mijesanje ukazuje na uredivanje razlicitim "
                        "alatom koji koristi drugaciji sustav boja."
                    ),
                    risk_score=0.55,
                    confidence=0.75,
                    evidence=evidence,
                )
            )
        elif has_icc and (has_rgb or has_cmyk):
            # ICC profile mixed with Device color — less suspicious but notable
            findings.append(
                AnalyzerFinding(
                    code="DOC_COLORSPACE_MIXED",
                    title="Nekonzistentni prostori boja",
                    description=(
                        f"Dokument koristi {len(all_colorspaces)} razlicitih prostora "
                        f"boja ({', '.join(sorted(all_colorspaces))}). "
                        f"Moguca indikacija uredivanja razlicitim alatima."
                    ),
                    risk_score=0.35,
                    confidence=0.65,
                    evidence=evidence,
                )
            )

    # ------------------------------------------------------------------
    # O. Compression Filter Inconsistency Detection
    # ------------------------------------------------------------------

    def _check_compression_inconsistency(
        self, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Detect inconsistent compression filters across content streams.

        A document produced by a single tool uses the same compression
        for all content streams. If some streams use FlateDecode while
        others use no compression (or different filters), it suggests
        content was added or replaced by a different tool.
        """
        if not _PYMUPDF_AVAILABLE:
            return

        try:
            doc = fitz.open(stream=doc_bytes, filetype="pdf")
        except Exception as e:
            logger.debug("Could not open PDF for compression check: %s", e)
            return

        stream_filters: dict[str, int] = {}  # filter_name → count
        page_filters: dict[int, set[str]] = {}  # page_idx → set of filters

        try:
            total_xrefs = doc.xref_length()

            for xref in range(1, min(total_xrefs, 500)):
                try:
                    if not doc.xref_is_stream(xref):
                        continue

                    # Get the object's dictionary to find Filter
                    obj_str = doc.xref_object(xref)

                    # Extract filter
                    filter_match = re.search(r"/Filter\s*(/\w+|\[([^\]]+)\])", obj_str)
                    if filter_match:
                        filter_name = filter_match.group(1).strip()
                    else:
                        filter_name = "None"

                    stream_filters[filter_name] = stream_filters.get(filter_name, 0) + 1

                except Exception:
                    continue

            # Also check per-page content streams
            max_pages = min(len(doc), 20)
            for page_idx in range(max_pages):
                page = doc[page_idx]
                xref = page.xref
                try:
                    obj_str = doc.xref_object(xref)
                    # Check Contents reference
                    filter_match = re.search(r"/Filter\s*(/\w+)", obj_str)
                    if filter_match:
                        page_filters.setdefault(page_idx, set()).add(filter_match.group(1))
                except Exception:
                    continue

        except Exception as e:
            logger.debug("Compression check error: %s", e)
        finally:
            doc.close()

        if len(stream_filters) < 2:
            return  # Uniform compression — normal

        # Check for uncompressed streams mixed with compressed
        has_none = stream_filters.get("None", 0) > 0
        has_flate = stream_filters.get("/FlateDecode", 0) > 0
        has_other = any(k not in ("None", "/FlateDecode") for k in stream_filters)

        evidence = {
            "stream_filters": stream_filters,
            "distinct_filters": len(stream_filters),
        }

        if has_none and has_flate and stream_filters.get("None", 0) < stream_filters.get("/FlateDecode", 0) * 0.3:
            # A few uncompressed streams among mostly compressed — suspicious
            findings.append(
                AnalyzerFinding(
                    code="DOC_COMPRESSION_INCONSISTENT",
                    title="Nekonzistentna kompresija content streamova",
                    description=(
                        f"Dokument sadrzi {stream_filters.get('None', 0)} nekomprimiranih "
                        f"streamova medu {stream_filters.get('/FlateDecode', 0)} komprimiranih. "
                        f"Kad jedan alat generira PDF, svi streamovi koriste isti filter. "
                        f"Nekonzistentnost ukazuje na naknadno dodavanje sadrzaja."
                    ),
                    risk_score=0.45,
                    confidence=0.70,
                    evidence=evidence,
                )
            )
        elif has_other:
            findings.append(
                AnalyzerFinding(
                    code="DOC_COMPRESSION_MIXED_FILTERS",
                    title="Razliciti kompresijski filteri u dokumentu",
                    description=(
                        f"Dokument koristi {len(stream_filters)} razlicitih "
                        f"kompresijskih filtera ({', '.join(stream_filters.keys())}). "
                        f"Neobicno za dokument generiran jednim alatom."
                    ),
                    risk_score=0.35,
                    confidence=0.65,
                    evidence=evidence,
                )
            )

    # ------------------------------------------------------------------
    # P. ToUnicode CMap / ActualText Discrepancy Detection
    # ------------------------------------------------------------------

    def _check_tounicode_discrepancy(
        self, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Detect discrepancies between visual glyphs and text extraction.

        A PDF can display one thing visually via glyphs but report
        different text via the ToUnicode CMap or ActualText attribute.
        For example: visually shows "$50,000" but text extraction yields
        "$500,000". This is nearly invisible to humans but affects all
        automated processing systems.

        We compare PyMuPDF's text extraction (which uses ToUnicode/CMap)
        against the raw content stream operators to detect mismatches.
        """
        if not _PYMUPDF_AVAILABLE:
            return

        try:
            doc = fitz.open(stream=doc_bytes, filetype="pdf")
        except Exception as e:
            logger.debug("Could not open PDF for ToUnicode check: %s", e)
            return

        discrepancies: list[dict] = []

        try:
            max_pages = min(len(doc), 10)

            for page_idx in range(max_pages):
                page = doc[page_idx]

                # Method 1: Compare get_text("text") with get_text("rawdict")
                # text mode uses ToUnicode CMap for mapping
                # rawdict gives per-char info including the original char code

                text_extracted = page.get_text("text").strip()
                if not text_extracted:
                    continue

                # Check for /ActualText in the page's structure
                try:
                    xref = page.xref
                    page_obj = doc.xref_object(xref)

                    # Look for ActualText entries in marked content
                    if "/ActualText" in page_obj:
                        # Extract ActualText values
                        at_matches = re.findall(
                            r"/ActualText\s*\(([^)]*)\)", page_obj
                        )
                        at_hex_matches = re.findall(
                            r"/ActualText\s*<([^>]*)>", page_obj
                        )

                        if at_matches or at_hex_matches:
                            actual_texts = at_matches + [
                                bytes.fromhex(h).decode("utf-16-be", errors="ignore")
                                for h in at_hex_matches if h
                            ]

                            for at in actual_texts:
                                at_clean = at.strip()
                                if at_clean and at_clean not in text_extracted:
                                    discrepancies.append({
                                        "page": page_idx + 1,
                                        "type": "ActualText",
                                        "actual_text": at_clean[:80],
                                        "not_in_visual": True,
                                    })
                except Exception:
                    pass

                # Method 2: Check for ToUnicode CMap irregularities
                # via raw content streams
                try:
                    raw = page.get_text("rawdict", flags=0)
                    blocks = raw.get("blocks", [])

                    for block in blocks:
                        if block.get("type") != 0:
                            continue

                        for line in block.get("lines", []):
                            for span in line.get("spans", []):
                                chars = span.get("chars", [])
                                if not chars:
                                    continue

                                for ch in chars:
                                    c = ch.get("c", "")
                                    # Check for replacement characters or unusual
                                    # mappings (private use area)
                                    if c and ord(c) >= 0xE000 and ord(c) <= 0xF8FF:
                                        # Private Use Area — might indicate CMap trick
                                        discrepancies.append({
                                            "page": page_idx + 1,
                                            "type": "PrivateUseArea",
                                            "char": c,
                                            "codepoint": f"U+{ord(c):04X}",
                                            "context": span.get("text", "")[:40],
                                        })
                except Exception:
                    pass

                # Method 3: Check if any content stream contains raw text
                # operators with strings that differ from extracted text
                try:
                    # Get content stream bytes
                    xref = page.xref
                    # Read all content streams for this page
                    page_contents = doc.xref_stream(xref) if doc.xref_is_stream(xref) else None

                    if not page_contents:
                        # Page might reference content via /Contents array
                        obj_str = doc.xref_object(xref)
                        contents_match = re.findall(r"(\d+)\s+0\s+R", obj_str)
                        for ref_xref in contents_match[:5]:
                            try:
                                ref_int = int(ref_xref)
                                if doc.xref_is_stream(ref_int):
                                    stream_data = doc.xref_stream(ref_int)
                                    if stream_data:
                                        # Look for text showing operators: Tj, TJ, ', "
                                        text_ops = re.findall(
                                            rb"\(([^)]{2,50})\)\s*Tj",
                                            stream_data,
                                        )
                                        for op in text_ops:
                                            try:
                                                raw_text = op.decode("latin-1", errors="ignore")
                                                # Skip strings with backslash escapes — these
                                                # are encoding sequences (Latin-2, WinAnsiEncoding)
                                                # for special chars like č/š/ž, NOT manipulation.
                                                if "\\" in raw_text:
                                                    continue
                                                # Check if this raw text appears in extracted text
                                                if (len(raw_text) >= 5
                                                        and raw_text.isprintable()
                                                        and raw_text not in text_extracted):
                                                    discrepancies.append({
                                                        "page": page_idx + 1,
                                                        "type": "ContentStreamMismatch",
                                                        "raw_text": raw_text[:50],
                                                        "not_in_extracted": True,
                                                    })
                                            except Exception:
                                                continue
                            except Exception:
                                continue
                except Exception:
                    pass

        except Exception as e:
            logger.debug("ToUnicode check error: %s", e)
        finally:
            doc.close()

        if not discrepancies:
            return

        # Filter: Private Use Area characters are only suspicious in quantity
        pua_count = sum(1 for d in discrepancies if d["type"] == "PrivateUseArea")
        actual_text_issues = [d for d in discrepancies if d["type"] == "ActualText"]
        content_mismatches = [d for d in discrepancies if d["type"] == "ContentStreamMismatch"]

        evidence = {"discrepancies": discrepancies[:15]}

        if actual_text_issues:
            findings.append(
                AnalyzerFinding(
                    code="DOC_ACTUALTEXT_DISCREPANCY",
                    title="ActualText razlikuje se od vidljivog sadrzaja",
                    description=(
                        f"Otkriveno {len(actual_text_issues)} /ActualText unosa koji se "
                        f"ne podudaraju s vizualnim prikazom. Ovo znaci da PDF prikazuje "
                        f"jedan tekst ljudskom oku, ali automatskim sustavima (OCR, copy-paste) "
                        f"isporucuje DRUGACIJI tekst — izuzetno opasan oblik manipulacije."
                    ),
                    risk_score=0.85,
                    confidence=0.85,
                    evidence=evidence,
                )
            )

        if content_mismatches and len(content_mismatches) >= 3:
            findings.append(
                AnalyzerFinding(
                    code="DOC_TOUNICODE_MISMATCH",
                    title="Nepodudarnost content streama i ekstrahiranog teksta",
                    description=(
                        f"Otkriveno {len(content_mismatches)} tekstualnih segmenata u "
                        f"content streamu koji se ne pojavljuju u ekstrahiranom tekstu. "
                        f"Moguca ToUnicode CMap manipulacija — tekst se vizualno prikazuje "
                        f"drugacije od onoga sto sustav za obradu cita."
                    ),
                    risk_score=0.55,
                    confidence=0.65,
                    evidence=evidence,
                )
            )

        if pua_count > 5:
            findings.append(
                AnalyzerFinding(
                    code="DOC_PRIVATE_USE_CHARS",
                    title="Znakovi iz privatnog Unicode podrucja",
                    description=(
                        f"Pronadeno {pua_count} znakova iz Unicode Private Use Area "
                        f"(U+E000-U+F8FF). Ovo moze ukazivati na prilagodenu CMap "
                        f"tablicu koja mapira glifove na nestandardne kodne tocke."
                    ),
                    risk_score=0.40,
                    confidence=0.60,
                    evidence=evidence,
                )
            )

    # ------------------------------------------------------------------
    # Q. Evil Annotation Attack (EAA) Detection
    # ------------------------------------------------------------------

    def _check_evil_annotations(
        self, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Detect Evil Annotation Attack patterns.

        Unlike fake redactions (section E) which use obviously dark rectangles,
        EAA uses annotations with custom appearance streams (/AP) that LOOK
        like normal content but actually overlay and replace the original.
        These are much harder to detect visually.
        """
        if not _PYMUPDF_AVAILABLE:
            return

        try:
            doc = fitz.open(stream=doc_bytes, filetype="pdf")
        except Exception as e:
            logger.debug("Could not open PDF for EAA check: %s", e)
            return

        evil_annots: list[dict] = []

        try:
            max_pages = min(len(doc), 20)

            for page_idx in range(max_pages):
                page = doc[page_idx]
                annots = list(page.annots()) if page.annots() else []

                if not annots:
                    continue

                # Get all text positions on this page
                text_dict = page.get_text("dict", flags=0)
                text_rects: list[fitz.Rect] = []
                for block in text_dict.get("blocks", []):
                    if block.get("type") == 0:
                        text_rects.append(fitz.Rect(block["bbox"]))

                for annot in annots:
                    try:
                        annot_type = annot.type[0]  # numeric type
                        annot_type_name = annot.type[1]  # string name

                        # Skip redact annotations (handled in section E)
                        if annot_type == 12:
                            continue

                        # Focus on annotations that can carry appearance streams:
                        # FreeText (2), Stamp (13), Widget (20), various others
                        rect = annot.rect

                        # Check if annotation has a custom appearance stream
                        has_ap = False
                        try:
                            ap_xref = annot.xref
                            ap_obj = doc.xref_object(ap_xref)
                            has_ap = "/AP" in ap_obj
                        except Exception:
                            pass

                        if not has_ap:
                            continue

                        # Check if this annotation covers existing text
                        text_overlap = 0
                        for tr in text_rects:
                            intersection = rect & tr
                            if not intersection.is_empty:
                                text_overlap += intersection.width * intersection.height

                        if text_overlap <= 0:
                            continue

                        annot_area = rect.width * rect.height
                        if annot_area <= 0:
                            continue

                        # FreeText annotations with AP streams covering text = EAA
                        if annot_type == 2:  # FreeText
                            evil_annots.append({
                                "page": page_idx + 1,
                                "type": annot_type_name,
                                "rect": [round(rect.x0, 1), round(rect.y0, 1),
                                         round(rect.x1, 1), round(rect.y1, 1)],
                                "text_overlap_area": round(text_overlap, 1),
                                "has_custom_ap": True,
                                "severity": "high",
                            })
                        elif annot_type == 13:  # Stamp
                            evil_annots.append({
                                "page": page_idx + 1,
                                "type": annot_type_name,
                                "rect": [round(rect.x0, 1), round(rect.y0, 1),
                                         round(rect.x1, 1), round(rect.y1, 1)],
                                "text_overlap_area": round(text_overlap, 1),
                                "has_custom_ap": True,
                                "severity": "medium",
                            })
                        elif annot_type == 20 and text_overlap > 100:  # Widget
                            evil_annots.append({
                                "page": page_idx + 1,
                                "type": "Widget",
                                "rect": [round(rect.x0, 1), round(rect.y0, 1),
                                         round(rect.x1, 1), round(rect.y1, 1)],
                                "text_overlap_area": round(text_overlap, 1),
                                "has_custom_ap": True,
                                "severity": "medium",
                            })

                    except Exception:
                        continue

        except Exception as e:
            logger.debug("EAA check error: %s", e)
        finally:
            doc.close()

        if not evil_annots:
            return

        high_severity = [a for a in evil_annots if a["severity"] == "high"]
        evidence = {"evil_annotations": evil_annots[:10]}

        if high_severity:
            findings.append(
                AnalyzerFinding(
                    code="DOC_EVIL_ANNOTATION_ATTACK",
                    title="Evil Annotation napad — anotacija prekriva tekst",
                    description=(
                        f"Otkriveno {len(high_severity)} FreeText anotacija s prilagodenim "
                        f"appearance streamovima koje prekrivaju postojeci tekst. "
                        f"Za razliku od lazne redakcije, ove anotacije IZGLEDAJU kao "
                        f"normalan tekst ali zapravo prekrivaju i zamjenjuju original."
                    ),
                    risk_score=0.75,
                    confidence=0.80,
                    evidence=evidence,
                )
            )
        else:
            findings.append(
                AnalyzerFinding(
                    code="DOC_SUSPICIOUS_ANNOTATION_OVERLAY",
                    title="Sumnjive anotacije s prekrivanjem teksta",
                    description=(
                        f"Otkriveno {len(evil_annots)} anotacija s prilagodenim "
                        f"appearance streamovima koje prekrivaju tekst na stranici."
                    ),
                    risk_score=0.55,
                    confidence=0.70,
                    evidence=evidence,
                )
            )

    # ------------------------------------------------------------------
    # R. OCG Default-Off Hidden Layer Detection
    # ------------------------------------------------------------------

    def _check_ocg_hidden_layers(
        self, doc_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Detect Optional Content Groups (layers) that are hidden by default.

        A sophisticated attack hides content in a layer set to OFF in
        the screen view but ON in the print view — or vice versa. The
        document looks normal on screen but prints differently, or
        content is hidden from automated processing but visible when printed.
        """
        if not _PYMUPDF_AVAILABLE:
            return

        try:
            doc = fitz.open(stream=doc_bytes, filetype="pdf")
        except Exception as e:
            logger.debug("Could not open PDF for OCG check: %s", e)
            return

        hidden_layers: list[dict] = []
        view_print_mismatch: list[dict] = []

        try:
            ocgs = doc.get_ocgs()
            if not ocgs:
                return

            total_layers = len(ocgs)

            for xref, info in ocgs.items():
                layer_name = info.get("name", f"Layer_{xref}")
                is_on = info.get("on", True)
                intent = info.get("intent", "View")
                usage = info.get("usage", "")

                if not is_on:
                    hidden_layers.append({
                        "xref": xref,
                        "name": layer_name,
                        "on": False,
                        "intent": intent,
                    })

                # Check for View vs Print intent mismatch
                if isinstance(intent, str) and intent.lower() == "design":
                    view_print_mismatch.append({
                        "xref": xref,
                        "name": layer_name,
                        "intent": intent,
                    })

            # Also check the OCProperties for Default configuration
            # Look for print-only or screen-only layers in raw PDF
            raw = doc_bytes
            # /Usage with /Print and /View states
            if b"/Usage" in raw:
                usage_sections = re.findall(
                    rb"/Usage\s*<<([^>]*(?:>>|>)[^>]*)>>",
                    raw, re.DOTALL,
                )
                for usage_raw in usage_sections:
                    usage_str = usage_raw.decode("latin-1", errors="ignore")
                    # Check for Print ON but View OFF (or vice versa)
                    has_print = "/Print" in usage_str
                    has_view = "/View" in usage_str
                    if has_print and has_view:
                        view_print_mismatch.append({
                            "type": "usage_directive",
                            "raw_hint": usage_str[:100],
                        })

        except Exception as e:
            logger.debug("OCG check error: %s", e)
        finally:
            doc.close()

        evidence = {
            "total_layers": len(ocgs) if ocgs else 0,
        }

        if hidden_layers:
            evidence["hidden_layers"] = hidden_layers[:10]
            findings.append(
                AnalyzerFinding(
                    code="DOC_OCG_HIDDEN_LAYERS",
                    title="Skriveni slojevi sadrzaja (OCG OFF)",
                    description=(
                        f"Dokument sadrzi {len(hidden_layers)} od {total_layers} "
                        f"slojeva (Optional Content Groups) koji su zadano ISKLJUCENI. "
                        f"Skriveni slojevi mogu sadrzavati alternativni tekst ili "
                        f"slike koje su nevidljive na ekranu ali se otkrivaju u "
                        f"odredenim kontekstima (ispis, eksport, specificni citaci)."
                    ),
                    risk_score=0.65,
                    confidence=0.80,
                    evidence=evidence,
                )
            )

        if view_print_mismatch:
            evidence["view_print_mismatch"] = view_print_mismatch[:5]
            findings.append(
                AnalyzerFinding(
                    code="DOC_OCG_VIEW_PRINT_MISMATCH",
                    title="Razlicit sadrzaj za prikaz i ispis",
                    description=(
                        "Dokument sadrzi slojeve s razlicitim postavkama za "
                        "prikaz na ekranu i ispis. Ovo znaci da se dokument "
                        "prikazuje drugacije ovisno o kontekstu — moguc napad "
                        "gdje se na ekranu vidi jedan sadrzaj a tiska drugi."
                    ),
                    risk_score=0.75,
                    confidence=0.80,
                    evidence=evidence,
                )
            )

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

            # B. Metadata asymmetry (Info dict)
            self._check_metadata_asymmetry(doc_bytes, findings)

            # B2. XMP vs Info dictionary asymmetry
            self._check_xmp_info_asymmetry(doc_bytes, findings)

            # C. Font / typographic forensics (pypdf-based)
            self._check_font_anomalies(doc_bytes, findings)

            # C2. Font glyph count analysis (fontTools)
            self._check_font_glyph_analysis(doc_bytes, findings)

            # C3. Zero-width character detection
            self._check_zero_width_chars(doc_bytes, findings)

            # C4. Mixed script detection (Trojan Source)
            self._check_mixed_scripts(doc_bytes, findings)

            # D. Digital signature verification (+ D2 post-sig analysis)
            self._check_digital_signatures(doc_bytes, findings)

            # E. Fake redaction detection (PyMuPDF)
            self._check_fake_redactions(doc_bytes, findings)

            # F. Shadow attack detection — enhanced (overlay %, Kids swap)
            self._check_shadow_attacks(doc_bytes, findings)

            # G. Orphaned object detection
            self._check_orphaned_objects(doc_bytes, findings)

            # H. Visual vs OCR comparison
            self._check_visual_vs_ocr(doc_bytes, findings)

            # I. Per-character font metrics (baseline/kerning anomalies)
            self._check_char_metrics_anomalies(doc_bytes, findings)

            # J. PDF version recovery + pixel diff
            self._check_version_pixel_diff(doc_bytes, findings)

            # K. ELA on embedded images
            self._check_embedded_image_ela(doc_bytes, findings)

            # L. JavaScript / dangerous action detection
            self._check_dangerous_actions(doc_bytes, findings)

            # M. AcroForm / XFA form overlay attack detection
            self._check_form_overlay_attacks(doc_bytes, findings)

            # N. Color space inconsistency analysis
            self._check_color_space_inconsistency(doc_bytes, findings)

            # O. Compression filter inconsistency detection
            self._check_compression_inconsistency(doc_bytes, findings)

            # P. ToUnicode / ActualText discrepancy (highest value check)
            self._check_tounicode_discrepancy(doc_bytes, findings)

            # Q. Evil Annotation Attack (EAA) detection
            self._check_evil_annotations(doc_bytes, findings)

            # R. OCG default-off hidden layer detection
            self._check_ocg_hidden_layers(doc_bytes, findings)

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
