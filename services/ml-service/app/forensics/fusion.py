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
    overall = max(0.0, min(1.0, overall))
    return overall, _risk_level(overall)
