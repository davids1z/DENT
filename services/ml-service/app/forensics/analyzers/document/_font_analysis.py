"""Font analysis: subset anomalies, glyph counting, zero-width chars, mixed scripts, char metrics."""

import io
import re
import unicodedata

import numpy as np

from ._common import (
    AnalyzerFinding,
    _CYRILLIC_HOMOGLYPHS,
    _FONTTOOLS_AVAILABLE,
    _PYMUPDF_AVAILABLE,
    _PYPDF_AVAILABLE,
    _ZERO_WIDTH_CHARS,
    logger,
)

if _PYPDF_AVAILABLE:
    from pypdf import PdfReader

if _PYMUPDF_AVAILABLE:
    import fitz

if _FONTTOOLS_AVAILABLE:
    from fontTools.ttLib import TTFont


def _check_font_anomalies(
    doc_bytes: bytes, findings: list[AnalyzerFinding]
) -> None:
    """Detect font subsetting anomalies indicating character replacement."""
    try:
        reader = PdfReader(io.BytesIO(doc_bytes))
    except Exception as e:
        logger.debug("Could not parse PDF for font analysis: %s", e)
        return

    # Limit to first 20 pages for performance
    max_pages = min(len(reader.pages), 20)
    all_fonts: dict[int, list[dict]] = {}  # page_num -> list of font info dicts
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
                        "page": page_idx + 1,
                        "base_name": name,
                        "variants": [f["base_font"] for f in subsets],
                    })

            # Mix of subset and non-subset of same font family
            if subsets and non_subsets:
                mixed_embedding.append({
                    "page": page_idx + 1,
                    "base_name": name,
                    "subset": [f["base_font"] for f in subsets],
                    "non_subset": [f["base_font"] for f in non_subsets],
                })

        # Check for non-embedded fonts alongside embedded ones
        embedded = [f for f in fonts if f["has_font_file"]]
        non_embedded = [f for f in fonts if not f["has_font_file"] and f["base_font"]]
        if embedded and non_embedded:
            system_fallbacks.append({
                "page": page_idx + 1,
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
                    evidence={**evidence, "page": page_idx + 1, "font_count": len(fonts)},
                )
            )
            break  # One finding is enough


def _check_font_glyph_analysis(
    doc_bytes: bytes, findings: list[AnalyzerFinding]
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

                    if glyph_count < 10:
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

    # Separate into severity levels (threshold lowered: <5 = critical, 5-9 = moderate)
    # PDF generators (Chrome, reportlab, wkhtmltopdf) routinely create subsets
    # with 10-30 glyphs for numeric-only content — only flag truly tiny subsets.
    critical = [f for f in suspicious_fonts if f["glyph_count"] < 5]
    moderate = [f for f in suspicious_fonts if 5 <= f["glyph_count"] < 10]

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
                risk_score=0.50,
                confidence=0.75,
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
                risk_score=0.35,
                confidence=0.65,
                evidence={
                    "suspicious_fonts": moderate[:5],
                    "total_suspicious": len(moderate),
                },
            )
        )


def _check_zero_width_chars(
    doc_bytes: bytes, findings: list[AnalyzerFinding]
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
    zw_counts: dict[str, int] = {}  # char_name -> count

    try:
        max_pages = min(len(doc), 20)
        for page_idx in range(max_pages):
            page = doc[page_idx]
            text = page.get_text()
            total_chars += len(text)

            for ch in text:
                cp = ord(ch)
                # Exclude BOM (U+FEFF) and LRM/RLM (U+200E/U+200F) from
                # the count — these are extremely common in legitimate
                # multilingual documents and Unicode-aware PDF generators.
                if cp in (0xFEFF, 0x200E, 0x200F):
                    continue
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

    if zw_total > 20:
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
    elif zw_total > 10:
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


def _check_mixed_scripts(
    doc_bytes: bytes, findings: list[AnalyzerFinding]
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
                            entry = {
                                "page": page_idx + 1,
                                "text_sample": text[:80],
                                "cyrillic_count": cyrillic_homoglyph_count,
                                "latin_count": latin_count,
                                "homoglyphs": homoglyph_positions,
                            }
                            span_bbox = span.get("bbox")
                            if span_bbox:
                                entry["bbox"] = [round(span_bbox[0], 1), round(span_bbox[1], 1),
                                                 round(span_bbox[2], 1), round(span_bbox[3], 1)]
                            cyrillic_in_latin.append(entry)
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


def _check_char_metrics_anomalies(
    doc_bytes: bytes, findings: list[AnalyzerFinding]
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

                        # Detect width anomalies -- only meaningful for
                        # monospaced or near-monospaced chars (digits, etc.)
                        # Variable-width fonts (Helvetica, Arial, Times) naturally
                        # have large width variance -- skip width check for them.
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
                            entry = {
                                "page": page_idx + 1,
                                "text": text_sample,
                                "font": font_name,
                                "font_size": round(font_size, 1),
                                "baseline_outliers": n_bl_outliers,
                                "width_outliers": n_w_outliers,
                                "kerning_outliers": n_k_outliers,
                                "total_chars": char_count,
                            }
                            span_bbox = span.get("bbox")
                            if span_bbox:
                                entry["bbox"] = [round(span_bbox[0], 1), round(span_bbox[1], 1),
                                                 round(span_bbox[2], 1), round(span_bbox[3], 1)]
                            anomalous_spans.append(entry)

    except Exception as e:
        logger.debug("Char metrics check error: %s", e)
    finally:
        doc.close()

    if not anomalous_spans:
        return

    # Group: many anomalous spans -> likely systematic editing
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
