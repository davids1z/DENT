"""Document forensics orchestrator — thin class that delegates to sub-modules."""

import time

from ._common import (
    AnalyzerFinding,
    BaseAnalyzer,
    ModuleResult,
    _PYPDF_AVAILABLE,
    logger,
)
from ...base import RiskLevel
from ._content_checks import (
    _check_color_space_inconsistency,
    _check_compression_inconsistency,
    _check_ocg_hidden_layers,
    _check_tounicode_discrepancy,
)
from ._font_analysis import (
    _check_char_metrics_anomalies,
    _check_font_anomalies,
    _check_font_glyph_analysis,
    _check_mixed_scripts,
    _check_zero_width_chars,
)
from ._security_checks import (
    _check_dangerous_actions,
    _check_digital_signatures,
    _check_evil_annotations,
    _check_fake_redactions,
    _check_form_overlay_attacks,
    _check_orphaned_objects,
    _check_shadow_attacks,
)
from ._structure_checks import (
    _check_metadata_asymmetry,
    _check_xmp_info_asymmetry,
    _check_xref_anomalies,
)
from ._visual_checks import (
    _check_embedded_image_ela,
    _check_version_pixel_diff,
    _check_visual_vs_ocr,
)


class DocumentForensicsAnalyzer(BaseAnalyzer):
    MODULE_NAME = "document_forensics"
    MODULE_LABEL = "Forenzika dokumenata"

    def __init__(self, signature_verification: bool = True) -> None:
        self._sig_verification = signature_verification

    def _make_result(
        self,
        findings: list[AnalyzerFinding],
        processing_time_ms: int = 0,
        error: str | None = None,
    ) -> ModuleResult:
        """Override base _make_result for document forensics.

        Document forensics runs 18 diverse checks. Using pure MAX (base class)
        means a single false positive at 0.70 dominates regardless of how many
        checks are clean. Instead we use a weighted combination:

          risk = max_score * 0.55 + mean(top_3) * 0.30 + corroboration * 0.15

        The corroboration bonus rewards multiple independent signals agreeing,
        which is the hallmark of real tampering vs. isolated noise.
        """
        if error:
            return ModuleResult(
                module_name=self.MODULE_NAME,
                module_label=self.MODULE_LABEL,
                risk_score=0.0, risk_score100=0,
                risk_level=RiskLevel.LOW,
                findings=[], processing_time_ms=processing_time_ms, error=error,
            )

        if not findings:
            return ModuleResult(
                module_name=self.MODULE_NAME,
                module_label=self.MODULE_LABEL,
                risk_score=0.0, risk_score100=0,
                risk_level=RiskLevel.LOW,
                findings=[], processing_time_ms=processing_time_ms,
            )

        positive = sorted(
            [f.risk_score for f in findings if f.risk_score > 0], reverse=True
        )
        negative = [f.risk_score for f in findings if f.risk_score < 0]

        if not positive:
            risk_score = 0.0
        else:
            max_score = positive[0]
            # Mean of top 3 (or fewer if less available)
            top3 = positive[:3]
            mean_top3 = sum(top3) / len(top3)
            # Corroboration: how many findings exceed 0.30 (meaningful signal)?
            n_corroborating = sum(1 for s in positive if s >= 0.30)
            # Corroboration score: 0 if just 1, scales up with more signals
            corr_score = min((n_corroborating - 1) / 3, 1.0) if n_corroborating > 1 else 0.0

            risk_score = max_score * 0.55 + mean_top3 * 0.30 + corr_score * 0.15

        # Apply trust reductions (e.g. valid digital signature)
        risk_score = risk_score + sum(negative)
        risk_score = max(0.0, min(1.0, risk_score))

        return ModuleResult(
            module_name=self.MODULE_NAME,
            module_label=self.MODULE_LABEL,
            risk_score=risk_score,
            risk_score100=round(risk_score * 100),
            risk_level=self._risk_level(risk_score),
            findings=findings,
            processing_time_ms=processing_time_ms,
        )

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
            _check_xref_anomalies(doc_bytes, findings)

            # B. Metadata asymmetry (Info dict)
            _check_metadata_asymmetry(doc_bytes, findings)

            # B2. XMP vs Info dictionary asymmetry
            _check_xmp_info_asymmetry(doc_bytes, findings)

            # C. Font / typographic forensics (pypdf-based)
            _check_font_anomalies(doc_bytes, findings)

            # C2. Font glyph count analysis (fontTools)
            _check_font_glyph_analysis(doc_bytes, findings)

            # C3. Zero-width character detection
            _check_zero_width_chars(doc_bytes, findings)

            # C4. Mixed script detection (Trojan Source)
            _check_mixed_scripts(doc_bytes, findings)

            # D. Digital signature verification (+ D2 post-sig analysis)
            _check_digital_signatures(doc_bytes, findings, sig_verification=self._sig_verification)

            # E. Fake redaction detection (PyMuPDF)
            _check_fake_redactions(doc_bytes, findings)

            # F. Shadow attack detection -- enhanced (overlay %, Kids swap)
            _check_shadow_attacks(doc_bytes, findings)

            # G. Orphaned object detection
            _check_orphaned_objects(doc_bytes, findings)

            # H. Visual vs OCR comparison
            _check_visual_vs_ocr(doc_bytes, findings)

            # I. Per-character font metrics (baseline/kerning anomalies)
            _check_char_metrics_anomalies(doc_bytes, findings)

            # J. PDF version recovery + pixel diff
            _check_version_pixel_diff(doc_bytes, findings)

            # K. ELA on embedded images
            _check_embedded_image_ela(doc_bytes, findings)

            # L. JavaScript / dangerous action detection
            _check_dangerous_actions(doc_bytes, findings)

            # M. AcroForm / XFA form overlay attack detection
            _check_form_overlay_attacks(doc_bytes, findings)

            # N. Color space inconsistency analysis
            _check_color_space_inconsistency(doc_bytes, findings)

            # O. Compression filter inconsistency detection
            _check_compression_inconsistency(doc_bytes, findings)

            # P. ToUnicode / ActualText discrepancy (highest value check)
            _check_tounicode_discrepancy(doc_bytes, findings)

            # Q. Evil Annotation Attack (EAA) detection
            _check_evil_annotations(doc_bytes, findings)

            # R. OCG default-off hidden layer detection
            _check_ocg_hidden_layers(doc_bytes, findings)

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
