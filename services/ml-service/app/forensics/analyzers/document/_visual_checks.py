"""Visual checks: OCR comparison, version pixel diff, embedded image ELA."""

import base64
import difflib
import io
import re

import numpy as np
from PIL import Image

from ._common import (
    AnalyzerFinding,
    _PYMUPDF_AVAILABLE,
    _TESSERACT_AVAILABLE,
    logger,
)

if _PYMUPDF_AVAILABLE:
    import fitz

if _TESSERACT_AVAILABLE:
    import pytesseract


def _check_visual_vs_ocr(
    doc_bytes: bytes, findings: list[AnalyzerFinding]
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
                # (Latin-2/WinAnsi c/s/z -> garbled in extraction)
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
        # Major discrepancy -- likely hidden text or content manipulation
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
                    "page": worst["page"],
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
                    "page": worst["page"],
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
                    "page": worst["page"],
                    "page_diffs": page_diffs[:5],
                    "average_similarity": round(avg_sim, 3),
                },
            )
        )


def _check_version_pixel_diff(
    doc_bytes: bytes, findings: list[AnalyzerFinding]
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
                    continue  # Less than 0.1% changed -- ignore

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
            logger.debug("Version diff error (v%d->v%d): %s", i + 1, i + 2, e)
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
        # More than 5% of pixels changed -- significant modification
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
                    f"u specifi\u010dnim podrucjima dokumenta."
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


def _check_embedded_image_ela(
    doc_bytes: bytes, findings: list[AnalyzerFinding]
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
                    anomaly_ratio, heatmap_b64 = _perform_ela(img_bytes)

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
