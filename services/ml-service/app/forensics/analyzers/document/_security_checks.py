"""Security checks: signatures, redactions, shadow attacks, orphans, dangerous actions, forms, annotations."""

import io
import re
from datetime import datetime, timezone

from ._common import (
    AnalyzerFinding,
    _PYHANKO_AVAILABLE,
    _PYMUPDF_AVAILABLE,
    logger,
)

if _PYHANKO_AVAILABLE:
    from pyhanko.pdf_utils.reader import PdfFileReader as HankoPdfReader
    from pyhanko.sign.validation import validate_pdf_signature

if _PYMUPDF_AVAILABLE:
    import fitz


def _check_digital_signatures(
    doc_bytes: bytes, findings: list[AnalyzerFinding], sig_verification: bool = True
) -> None:
    """Verify embedded digital signatures using PyHanko."""
    if not sig_verification or not _PYHANKO_AVAILABLE:
        return

    try:
        reader = HankoPdfReader(io.BytesIO(doc_bytes))
        sig_fields = reader.embedded_signatures
    except Exception as e:
        logger.debug("Could not read PDF signatures: %s", e)
        return

    if not sig_fields:
        return  # No signatures -- neutral (most PDFs are unsigned)

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
                _analyze_post_signature_changes(
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


def _analyze_post_signature_changes(
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


def _check_fake_redactions(
    doc_bytes: bytes, findings: list[AnalyzerFinding]
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
                                    # on a dark rect IS visible -- it's design.
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


def _check_shadow_attacks(
    doc_bytes: bytes, findings: list[AnalyzerFinding]
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
        # 1. Check Optional Content Groups (OCG) -- layer visibility manipulation
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

        # 3. Check for Form XObjects -- excessive count
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
        _check_kids_reference_swap(doc, doc_bytes, findings)

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


def _check_kids_reference_swap(
    doc: "fitz.Document", doc_bytes: bytes, findings: list[AnalyzerFinding]
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


def _check_orphaned_objects(
    doc_bytes: bytes, findings: list[AnalyzerFinding]
) -> None:
    """Detect orphaned objects -- remnants of previous document versions."""
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


def _check_dangerous_actions(
    doc_bytes: bytes, findings: list[AnalyzerFinding]
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


def _check_form_overlay_attacks(
    doc_bytes: bytes, findings: list[AnalyzerFinding]
) -> None:
    """Detect form fields with custom appearance streams overlaying content.

    A common tampering technique: place a form field with a custom
    appearance stream over original text. The visible content changes
    but the underlying PDF text layer remains -- or vice versa.
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
        # Check for XFA (XML Forms Architecture) -- highly unusual in normal docs
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


def _check_evil_annotations(
    doc_bytes: bytes, findings: list[AnalyzerFinding]
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
