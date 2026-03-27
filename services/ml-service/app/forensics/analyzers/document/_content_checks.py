"""Content checks: color space, compression, ToUnicode/ActualText, OCG hidden layers."""

import re

from ._common import (
    AnalyzerFinding,
    _PYMUPDF_AVAILABLE,
    logger,
)

if _PYMUPDF_AVAILABLE:
    import fitz


def _check_color_space_inconsistency(
    doc_bytes: bytes, findings: list[AnalyzerFinding]
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
        return  # Uniform color space -- normal

    # Check for suspicious mixes
    has_rgb = "DeviceRGB" in all_colorspaces
    has_cmyk = "DeviceCMYK" in all_colorspaces
    has_icc = "ICCBased" in all_colorspaces

    evidence = {
        "all_colorspaces": sorted(all_colorspaces),
        "per_page": {str(k + 1): sorted(v) for k, v in page_colorspaces.items()},
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
        # ICC profile mixed with Device color -- less suspicious but notable
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


def _check_compression_inconsistency(
    doc_bytes: bytes, findings: list[AnalyzerFinding]
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

    stream_filters: dict[str, int] = {}  # filter_name -> count
    page_filters: dict[int, set[str]] = {}  # page_idx -> set of filters

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
        return  # Uniform compression -- normal

    # Check for uncompressed streams mixed with compressed
    has_none = stream_filters.get("None", 0) > 0
    has_flate = stream_filters.get("/FlateDecode", 0) > 0
    has_other = any(k not in ("None", "/FlateDecode") for k in stream_filters)

    evidence = {
        "stream_filters": stream_filters,
        "distinct_filters": len(stream_filters),
    }

    if has_none and has_flate and stream_filters.get("None", 0) < stream_filters.get("/FlateDecode", 0) * 0.3:
        # A few uncompressed streams among mostly compressed -- suspicious
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


def _check_tounicode_discrepancy(
    doc_bytes: bytes, findings: list[AnalyzerFinding]
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
                                    # Private Use Area -- might indicate CMap trick
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
                                            # Skip strings with backslash escapes -- these
                                            # are encoding sequences (Latin-2, WinAnsiEncoding)
                                            # for special chars like c/s/z, NOT manipulation.
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


def _check_ocg_hidden_layers(
    doc_bytes: bytes, findings: list[AnalyzerFinding]
) -> None:
    """Detect Optional Content Groups (layers) that are hidden by default.

    A sophisticated attack hides content in a layer set to OFF in
    the screen view but ON in the print view -- or vice versa. The
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
