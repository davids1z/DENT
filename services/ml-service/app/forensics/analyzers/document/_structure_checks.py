"""Structure checks: XREF anomalies, metadata asymmetry, XMP/Info comparison."""

import io
import re
from xml.etree import ElementTree

from ._common import (
    AnalyzerFinding,
    PDF_EDITING_SOFTWARE,
    _PYMUPDF_AVAILABLE,
    _PYPDF_AVAILABLE,
    _parse_pdf_date,
    _parse_xmp_date,
    logger,
)

if _PYPDF_AVAILABLE:
    from pypdf import PdfReader

if _PYMUPDF_AVAILABLE:
    import fitz


def _check_xref_anomalies(
    doc_bytes: bytes, findings: list[AnalyzerFinding]
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
    except Exception as e:
        logger.debug("PDF object count via pypdf failed: %s", e)

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


def _check_metadata_asymmetry(
    doc_bytes: bytes, findings: list[AnalyzerFinding]
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
        except Exception as e:
            logger.debug("Page count check for stripped metadata: %s", e)
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


def _check_xmp_info_asymmetry(
    doc_bytes: bytes, findings: list[AnalyzerFinding]
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
