from .base import ModuleResult, RiskLevel

DEFAULT_WEIGHTS: dict[str, float] = {
    "metadata_analysis": 0.20,
    "modification_detection": 0.20,
    "deep_modification_detection": 0.25,
    "optical_forensics": 0.10,
    "semantic_forensics": 0.15,
    "document_forensics": 0.10,
}


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
    Modules that errored or have no findings are excluded from weighting.
    """
    total_weight = 0.0
    weighted_score = 0.0

    for module in modules:
        if module.error:
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

        # Single strong module → boost to at least moderate
        elif max_module_score >= 0.60 and overall < 0.40:
            overall = max(overall, 0.40)

        # Multiple high-risk modules agreeing = strong signal
        high_risk_count = sum(1 for m in active_modules if m.risk_score >= 0.50)
        if high_risk_count >= 2 and overall < 0.60:
            overall = max(overall, 0.60)

    overall = max(0.0, min(1.0, overall))
    return overall, _risk_level(overall)
