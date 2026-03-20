from .base import ModuleResult, RiskLevel

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
        if aigen and aigen[0].risk_score >= 0.55:
            overall = max(overall, aigen[0].risk_score * 0.92)

        # ── Multi-signal AI cross-validation ────────────────────────
        # When multiple INDEPENDENT AI detectors (Swin, CLIP, VAE, PRNU) agree,
        # the combined confidence is much higher than any single detector.
        ai_detectors = [
            m for m in active_modules
            if m.module_name in _AI_DETECTOR_MODULES
        ]
        if ai_detectors:
            high_ai_count = sum(1 for m in ai_detectors if m.risk_score >= 0.45)
            max_ai_score = max(m.risk_score for m in ai_detectors)

            if high_ai_count >= 4:
                # 4+ AI detectors agree — near-certain AI content
                overall = max(overall, 0.92)
            elif high_ai_count >= 3:
                # Three AI detectors agree — very high confidence
                overall = max(overall, 0.85)
            elif high_ai_count >= 2:
                # Two independent AI detectors agree — strong signal
                overall = max(overall, max_ai_score * 0.95)
            elif high_ai_count == 1 and max_ai_score >= 0.55:
                # Single detector confident — ensure floor
                overall = max(overall, max_ai_score * 0.88)

        # ── PRNU + AI generation cross-validation ─────────────────
        # When PRNU detects no camera sensor pattern AND AI classifiers
        # detect AI content, boost confidence significantly — this is
        # two completely independent methods (physics vs ML) agreeing.
        prnu = [m for m in active_modules if m.module_name == "prnu_detection"]
        prnu_score = prnu[0].risk_score if prnu else 0.0
        aigen_score = aigen[0].risk_score if aigen else 0.0

        if prnu_score >= 0.50 and aigen_score >= 0.50:
            # Both PRNU (no sensor) and AI classifier agree → near-certain
            overall = max(overall, 0.90)
        elif prnu_score >= 0.60 and aigen_score < 0.40:
            # PRNU strong but classifier didn't fire — still suspicious
            overall = max(overall, prnu_score * 0.80)

        # ── Metadata + AI cross-validation ───────────────────────
        # When metadata shows AI generator software AND classifiers agree.
        metadata = [m for m in active_modules if m.module_name == "metadata_analysis"]
        if metadata and aigen_score >= 0.40:
            meta_findings = metadata[0].findings
            has_ai_software = any(
                f.code == "META_EDITING_SOFTWARE" and f.risk_score >= 0.30
                for f in meta_findings
            )
            if has_ai_software:
                overall = max(overall, 0.90)

        # ── Spectral + AI generation cross-validation ─────────────
        # When two INDEPENDENT approaches (trained NN + frequency analysis)
        # both detect AI content, boost confidence significantly.
        spectral = [m for m in active_modules if m.module_name == "spectral_forensics"]
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
    overall_100 = round(overall * 100)
    return overall, overall_100, _risk_level(overall)
