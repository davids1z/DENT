from .base import ModuleResult, RiskLevel

DEFAULT_WEIGHTS: dict[str, float] = {
    "ai_generation_detection": 0.18,
    "clip_ai_detection": 0.14,
    "vae_reconstruction": 0.10,
    "deep_modification_detection": 0.14,
    "spectral_forensics": 0.10,
    "metadata_analysis": 0.10,
    "modification_detection": 0.08,
    "semantic_forensics": 0.06,
    "optical_forensics": 0.03,
    "document_forensics": 0.07,
    "office_forensics": 0.07,
    "text_ai_detection": 0.13,
}

# Module names that are dedicated AI / synthetic-content detectors
_AI_DETECTOR_MODULES = frozenset({
    "ai_generation_detection",
    "clip_ai_detection",
    "vae_reconstruction",
})


def _risk_level(score: float) -> RiskLevel:
    if score >= 0.75:
        return RiskLevel.CRITICAL
    if score >= 0.50:
        return RiskLevel.HIGH
    if score >= 0.25:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def fuse_scores(modules: list[ModuleResult]) -> tuple[float, RiskLevel]:
    """
    Weighted average score fusion with confidence adjustment.

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
        return 0.0, RiskLevel.LOW

    overall = weighted_score / total_weight

    # ── Max-signal override ──────────────────────────────────────────
    # Prevent strong single-module signals from being diluted by the
    # weighted average.  One CRITICAL module should never produce a LOW
    # overall score.
    active_modules = [m for m in modules if not m.error]
    if active_modules:
        max_module_score = max(m.risk_score for m in active_modules)

        # Single CRITICAL module → boost overall to at least HIGH
        if max_module_score >= 0.75 and overall < 0.50:
            overall = max(overall, 0.50 + (max_module_score - 0.75) * 0.5)

        # Single strong module → floor at 0.50
        elif max_module_score >= 0.55 and overall < 0.50:
            overall = max(overall, 0.50)

        # Single moderate module → floor at 0.40
        elif max_module_score >= 0.45 and overall < 0.40:
            overall = max(overall, 0.40)

        # Multiple high-risk modules agreeing = strong signal
        high_risk_count = sum(1 for m in active_modules if m.risk_score >= 0.50)
        if high_risk_count >= 2 and overall < 0.60:
            overall = max(overall, 0.60)

        # ── AI generation detection override ─────────────────────────
        # Trained classifiers for AI content are authoritative — a single
        # high signal should dominate the overall score.
        aigen = [m for m in active_modules if m.module_name == "ai_generation_detection"]
        if aigen and aigen[0].risk_score >= 0.45:
            overall = max(overall, aigen[0].risk_score * 0.92)

        # ── Multi-signal AI cross-validation ────────────────────────
        # When multiple INDEPENDENT AI detectors (Swin, CLIP, VAE) agree,
        # the combined confidence is much higher than any single detector.
        ai_detectors = [
            m for m in active_modules
            if m.module_name in _AI_DETECTOR_MODULES
        ]
        if ai_detectors:
            high_ai_count = sum(1 for m in ai_detectors if m.risk_score >= 0.45)
            max_ai_score = max(m.risk_score for m in ai_detectors)

            if high_ai_count >= 3:
                # All three AI detectors agree — near-certain AI content
                overall = max(overall, 0.85)
            elif high_ai_count >= 2:
                # Two independent AI detectors agree — strong signal
                overall = max(overall, max_ai_score * 0.95)
            elif high_ai_count == 1 and max_ai_score >= 0.55:
                # Single detector confident — ensure floor
                overall = max(overall, max_ai_score * 0.88)

        # ── Spectral + AI generation cross-validation ─────────────
        # When two INDEPENDENT approaches (trained NN + frequency analysis)
        # both detect AI content, boost confidence significantly.
        spectral = [m for m in active_modules if m.module_name == "spectral_forensics"]
        aigen_score = aigen[0].risk_score if aigen else 0.0
        spectral_score = spectral[0].risk_score if spectral else 0.0

        if aigen_score >= 0.40 and spectral_score >= 0.30:
            # Cross-validated AI detection — two independent methods agree
            cross_score = aigen_score * 0.60 + spectral_score * 0.40
            overall = max(overall, cross_score)
        elif aigen_score >= 0.45 and spectral_score < 0.30:
            # AI detector strong but spectral doesn't confirm — still trust NN
            overall = max(overall, aigen_score * 0.85)
        elif spectral_score >= 0.60 and aigen_score < 0.40:
            # Spectral-only strong signal — novel AI generators may evade NN
            # but leave frequency artifacts.  Don't let it be diluted.
            overall = max(overall, spectral_score * 0.75)

        # ── Text AI detection boost ──────────────────────────────────
        text_ai = [m for m in active_modules if m.module_name == "text_ai_detection"]
        if text_ai and text_ai[0].risk_score >= 0.50:
            overall = max(overall, text_ai[0].risk_score * 0.90)

    overall = max(0.0, min(1.0, overall))
    return overall, _risk_level(overall)
