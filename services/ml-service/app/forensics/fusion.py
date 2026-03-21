import logging

from .base import ModuleResult, RiskLevel
from .stacking_meta import get_meta_learner
from .thresholds import get_registry

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
    "semantic_forensics": 0.03,
    "optical_forensics": 0.02,
    "document_forensics": 0.06,
    "office_forensics": 0.05,
    "text_ai_detection": 0.08,
    "content_validation": 0.03,
}  # Sum = 1.00

# Module names that are dedicated AI / synthetic-content detectors
_AI_DETECTOR_MODULES = frozenset({
    "ai_generation_detection",
    "clip_ai_detection",
    "vae_reconstruction",
    "prnu_detection",
})


def _risk_level(score: float) -> RiskLevel:
    reg = get_registry()
    if score >= reg.fusion.risk_critical:
        return RiskLevel.CRITICAL
    if score >= reg.fusion.risk_high:
        return RiskLevel.HIGH
    if score >= reg.fusion.risk_medium:
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

    # ── Stacking meta-learner (replaces override rules when trained) ──
    try:
        from ..config import settings as _settings
        meta_enabled = _settings.forensics_stacking_meta_enabled
    except Exception:
        meta_enabled = False

    if meta_enabled:
        meta = get_meta_learner()
        meta_score = meta.predict(modules)
        if meta_score is not None:
            overall = max(0.0, min(1.0, meta_score))
            overall_100 = round(overall * 100)
            return overall, overall_100, _risk_level(overall)

    # ── Fallback: hand-crafted override rules ─────────────────────────
    active_modules = [m for m in modules if not m.error]
    if active_modules:
        reg = get_registry()
        ft = reg.fusion

        # ── Realness dampening ────────────────────────────────────────
        # When metadata shows a real camera AND PRNU is not flagged,
        # the image is likely genuine — dampen ambiguous AI scores to
        # prevent false positives from noisy detectors on real photos.
        _AI_NAMES = {"ai_generation_detection", "clip_ai_detection", "vae_reconstruction"}
        meta_mod = next((m for m in active_modules if m.module_name == "metadata_analysis"), None)
        prnu_mod = next((m for m in active_modules if m.module_name == "prnu_detection"), None)
        meta_is_clean = meta_mod is not None and meta_mod.risk_score < 0.30
        prnu_is_clean = prnu_mod is not None and prnu_mod.risk_score < 0.30

        # Build effective scores: dampened copies for AI modules if camera signals are clean
        eff_scores: dict[str, float] = {}
        for m in active_modules:
            score = m.risk_score
            if meta_is_clean and prnu_is_clean and m.module_name in _AI_NAMES:
                if 0.40 <= score < 0.70:
                    score = score * 0.5  # halve ambiguous AI scores
            eff_scores[m.module_name] = score

        # Recalculate overall with dampened scores
        damp_weighted = 0.0
        damp_total = 0.0
        for m in active_modules:
            if m.risk_score == 0.0 and not m.findings:
                continue
            w = DEFAULT_WEIGHTS.get(m.module_name, 0.10)
            avg_c = (sum(f.confidence for f in m.findings) / len(m.findings)) if m.findings else 0.5
            aw = w * avg_c
            damp_weighted += eff_scores.get(m.module_name, m.risk_score) * aw
            damp_total += aw
        if damp_total > 0:
            overall = damp_weighted / damp_total

        # ── Max-signal override ──────────────────────────────────────
        # A strong signal from any single module should not be drowned out.
        max_module_score = max(eff_scores.get(m.module_name, m.risk_score) for m in active_modules)

        # A single strong module ensures a minimum floor
        if max_module_score >= ft.single_strong_module and overall < ft.single_strong_floor:
            overall = max(overall, ft.single_strong_floor)

        # Multiple modules (2+) agreeing is a strong signal
        high_risk_count = sum(1 for m in active_modules if eff_scores.get(m.module_name, m.risk_score) >= ft.multi_high_threshold)
        if high_risk_count >= 2 and overall < ft.multi_high_2_floor:
            overall = max(overall, ft.multi_high_2_floor)
        if high_risk_count >= 3 and overall < ft.multi_high_3_floor:
            overall = max(overall, ft.multi_high_3_floor)

        # ── AI generation detection override ─────────────────────────
        aigen = [m for m in active_modules if m.module_name == "ai_generation_detection"]
        aigen_score = eff_scores.get("ai_generation_detection", aigen[0].risk_score if aigen else 0.0)
        if aigen and aigen_score >= ft.aigen_direct:
            overall = max(overall, aigen_score * ft.aigen_factor)

        # ── Multi-signal AI cross-validation ────────────────────────
        # Multiple AI detectors agreeing strongly indicates AI content.
        ai_detectors = [
            m for m in active_modules
            if m.module_name in _AI_DETECTOR_MODULES
        ]
        if ai_detectors:
            high_ai_count = sum(1 for m in ai_detectors if m.risk_score >= ft.ai_cross_threshold)
            max_ai_score = max(m.risk_score for m in ai_detectors)

            if high_ai_count >= 4:
                overall = max(overall, ft.ai_cross_4_floor)
            elif high_ai_count >= 3:
                overall = max(overall, ft.ai_cross_3_floor)
            elif high_ai_count >= 2:
                overall = max(overall, max_ai_score * ft.ai_cross_2_factor)

        # ── PRNU + AI generation cross-validation ─────────────────
        prnu = [m for m in active_modules if m.module_name == "prnu_detection"]
        prnu_score = prnu[0].risk_score if prnu else 0.0

        if prnu_score >= ft.prnu_aigen_threshold and aigen_score >= ft.prnu_aigen_threshold:
            overall = max(overall, ft.prnu_aigen_floor)
        elif prnu_score >= ft.prnu_solo_threshold and aigen_score < 0.40:
            overall = max(overall, prnu_score * ft.prnu_solo_factor)

        # ── Metadata + AI cross-validation ───────────────────────
        metadata = [m for m in active_modules if m.module_name == "metadata_analysis"]
        if metadata and aigen_score >= ft.meta_aigen_threshold:
            meta_findings = metadata[0].findings
            has_ai_software = any(
                f.code == "META_EDITING_SOFTWARE" and f.risk_score >= ft.meta_software_threshold
                for f in meta_findings
            )
            if has_ai_software:
                overall = max(overall, ft.meta_aigen_floor)

        # ── Spectral + AI generation cross-validation ─────────────
        spectral = [m for m in active_modules if m.module_name == "spectral_forensics"]
        spectral_score = spectral[0].risk_score if spectral else 0.0

        if aigen_score >= ft.spectral_aigen_threshold and spectral_score >= ft.spectral_min:
            cross_score = aigen_score * 0.60 + spectral_score * 0.40
            overall = max(overall, cross_score)
        elif spectral_score >= ft.spectral_solo_threshold and aigen_score < 0.40:
            overall = max(overall, spectral_score * ft.spectral_solo_factor)

        # ── Text AI detection boost ──────────────────────────────────
        text_ai = [m for m in active_modules if m.module_name == "text_ai_detection"]
        if text_ai and text_ai[0].risk_score >= ft.text_ai_threshold:
            overall = max(overall, text_ai[0].risk_score * ft.text_ai_factor)

        # ── VLM vs dedicated detectors ───────────────────────────────
        # NOTE: The VLM (Gemini) is a general-purpose model, NOT a trained
        # forensic classifier. Modern AI generators fool VLMs into thinking
        # images are authentic. The VLM's "authentic" verdict should NEVER
        # override or reduce scores from dedicated AI detectors (Swin,
        # CLIP, PRNU, VAE). The VLM is only trusted when it AGREES with
        # other modules, not when it contradicts them.

    overall = max(0.0, min(1.0, overall))
    overall_100 = round(overall * 100)
    return overall, overall_100, _risk_level(overall)
