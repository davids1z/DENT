import logging

from .base import ModuleResult, RiskLevel

logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS: dict[str, float] = {
    "ai_generation_detection": 0.14,
    "clip_ai_detection": 0.11,
    "vae_reconstruction": 0.07,
    "prnu_detection": 0.10,
    "deep_modification_detection": 0.11,
    "spectral_forensics": 0.07,
    "metadata_analysis": 0.07,
    "modification_detection": 0.06,
    "semantic_forensics": 0.05,
    "optical_forensics": 0.03,
    "document_forensics": 0.06,
    "office_forensics": 0.05,
    "text_ai_detection": 0.08,
}  # Sum = 1.00

# Module names that are dedicated AI / synthetic-content detectors
_AI_DETECTOR_MODULES = frozenset({
    "ai_generation_detection",
    "clip_ai_detection",
    "vae_reconstruction",
    "prnu_detection",
})


def _risk_level(score: float) -> RiskLevel:
    if score >= 0.71:
        return RiskLevel.CRITICAL
    if score >= 0.46:
        return RiskLevel.HIGH
    if score >= 0.21:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def fuse_scores(modules: list[ModuleResult]) -> tuple[float, int, RiskLevel]:
    """
    Weighted average score fusion with confidence adjustment.

    Returns (overall_float, overall_100, risk_level).

    Key principles:
    1. Modules with errors are excluded.
    2. Modules with risk=0 and no findings are NEUTRAL — they are excluded
       from the weighted average so they don't dilute genuine signals.
    3. Multiple AI detectors agreeing amplifies the signal (cross-validation).
    4. Individual strong signals are never drowned by many weak modules.
    """
    total_weight = 0.0
    weighted_score = 0.0

    for module in modules:
        if module.error:
            continue

        # ── Neutral-module exclusion ────────────────────────────────
        # A module that found NOTHING (risk=0, no findings) has no opinion.
        # Including it with avg_confidence=0.5 would dilute genuine signals.
        if module.risk_score == 0.0 and not module.findings:
            continue

        weight = DEFAULT_WEIGHTS.get(module.module_name, 0.10)

        # Adjust weight by average confidence of findings
        if module.findings:
            avg_confidence = sum(f.confidence for f in module.findings) / len(
                module.findings
            )
        else:
            avg_confidence = 0.5

        adjusted_weight = weight * avg_confidence
        weighted_score += module.risk_score * adjusted_weight
        total_weight += adjusted_weight

    if total_weight <= 0:
        return 0.0, 0, RiskLevel.LOW

    overall = weighted_score / total_weight

    # ── Max-signal override ──────────────────────────────────────────
    # Only boost for VERY strong single-module signals.
    active_modules = [m for m in modules if not m.error]
    if active_modules:
        max_module_score = max(m.risk_score for m in active_modules)

        # Only a single genuinely CRITICAL module (>0.80) boosts the overall
        if max_module_score >= 0.80 and overall < 0.50:
            overall = max(overall, 0.50)

        # Multiple high-risk modules (3+) agreeing is a strong signal
        high_risk_count = sum(1 for m in active_modules if m.risk_score >= 0.55)
        if high_risk_count >= 3 and overall < 0.55:
            overall = max(overall, 0.55)

        # ── AI generation detection override ─────────────────────────
        # Only the trained Swin classifier is authoritative enough for override
        aigen = [m for m in active_modules if m.module_name == "ai_generation_detection"]
        aigen_score = aigen[0].risk_score if aigen else 0.0
        if aigen and aigen_score >= 0.65:
            overall = max(overall, aigen_score * 0.88)

        # ── Multi-signal AI cross-validation ────────────────────────
        # Require STRONG signals (>= 0.55) from multiple detectors.
        ai_detectors = [
            m for m in active_modules
            if m.module_name in _AI_DETECTOR_MODULES
        ]
        if ai_detectors:
            high_ai_count = sum(1 for m in ai_detectors if m.risk_score >= 0.55)
            max_ai_score = max(m.risk_score for m in ai_detectors)

            if high_ai_count >= 4:
                overall = max(overall, 0.90)
            elif high_ai_count >= 3:
                overall = max(overall, 0.80)
            elif high_ai_count >= 2:
                overall = max(overall, max_ai_score * 0.88)

        # ── PRNU + AI generation cross-validation ─────────────────
        prnu = [m for m in active_modules if m.module_name == "prnu_detection"]
        prnu_score = prnu[0].risk_score if prnu else 0.0

        if prnu_score >= 0.55 and aigen_score >= 0.55:
            overall = max(overall, 0.88)
        elif prnu_score >= 0.65 and aigen_score < 0.40:
            overall = max(overall, prnu_score * 0.70)

        # ── Metadata + AI cross-validation ───────────────────────
        metadata = [m for m in active_modules if m.module_name == "metadata_analysis"]
        if metadata and aigen_score >= 0.50:
            meta_findings = metadata[0].findings
            has_ai_software = any(
                f.code == "META_EDITING_SOFTWARE" and f.risk_score >= 0.30
                for f in meta_findings
            )
            if has_ai_software:
                overall = max(overall, 0.85)

        # ── Spectral + AI generation cross-validation ─────────────
        spectral = [m for m in active_modules if m.module_name == "spectral_forensics"]
        spectral_score = spectral[0].risk_score if spectral else 0.0

        if aigen_score >= 0.55 and spectral_score >= 0.40:
            cross_score = aigen_score * 0.60 + spectral_score * 0.40
            overall = max(overall, cross_score)
        elif spectral_score >= 0.65 and aigen_score < 0.40:
            overall = max(overall, spectral_score * 0.65)

        # ── Text AI detection boost ──────────────────────────────────
        text_ai = [m for m in active_modules if m.module_name == "text_ai_detection"]
        if text_ai and text_ai[0].risk_score >= 0.55:
            overall = max(overall, text_ai[0].risk_score * 0.88)

        # ── VLM authenticity dampening ────────────────────────────────
        # When the semantic/VLM module explicitly finds the image authentic,
        # this is strong negative evidence that should reduce the overall
        # score. VLM analysis considers lighting, shadows, perspective,
        # debris physics — holistic features that simple detectors miss.
        semantic = [m for m in active_modules if m.module_name == "semantic_forensics"]
        if semantic:
            sem_findings = semantic[0].findings
            # Check if VLM found explicit authenticity markers
            authentic_finding = next(
                (f for f in sem_findings
                 if f.code == "SEM_VLM_AUTHENTIC"
                 and f.confidence >= 0.80),
                None,
            )
            if authentic_finding and overall > 0.30:
                # VLM says authentic with high confidence — dampen by 30%
                dampened = overall * 0.70
                overall = max(dampened, 0.25)  # Floor at 0.25
                logger.debug(
                    "VLM authenticity dampening: %.2f → %.2f (finding: %s)",
                    overall / 0.70, overall, authentic_finding.code,
                )

    overall = max(0.0, min(1.0, overall))
    overall_100 = round(overall * 100)
    return overall, overall_100, _risk_level(overall)
