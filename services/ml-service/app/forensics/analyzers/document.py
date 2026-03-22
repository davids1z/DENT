"""Document forensics: PDF structure, metadata, font, and signature analysis.

Enhanced with:
  - XMP vs Info dictionary asymmetry detection
  - Orphaned object detection (hidden previous values)
  - Font glyph analysis via fontTools
  - Zero-width Unicode character detection (Cf category)
  - Mixed-script / Trojan Source detection
  - Shadow attack overlay percentage calculation
  - Kids reference swap detection
  - Post-signature modification analysis
"""

import io
import logging
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

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

                for d in drawings:
                    # Look for filled rectangles (black, white, or any opaque fill)
                    if d.get("fill") is not None and d.get("rect"):
                        rect = fitz.Rect(d["rect"])
                        # Only consider rectangles of reasonable size (not tiny)
                        if rect.width > 5 and rect.height > 3:
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
                                # Check if rectangle covers this text span
                                if rect.contains(span_rect) or rect.intersects(span_rect):
                                    overlap = rect & span_rect  # intersection
                                    if overlap.width > span_rect.width * 0.5:
                                        text = span.get("text", "").strip()
                                        if text:
                                            hidden_chars += len(text)
                                            if len(hidden_texts) < 3:
                                                hidden_texts.append(text[:50])

                    if hidden_chars > 2:
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
