"""
Score fusion — combines forensic module results into a single risk score.

Architecture (v2): Core-only fusion with context modifiers.

Only 3 CORE AI detectors determine the AI generation score.
Tampering is scored separately from AI generation.
Context signals (metadata, PRNU) modify confidence but never decide alone.
Support modules (spectral, optical, semantic) are informational only.
"""

import logging

from .base import ModuleResult, RiskLevel
from .stacking_meta import get_meta_learner
from .thresholds import get_registry

logger = logging.getLogger(__name__)

# Legacy weights kept for stacking meta-learner feature extraction
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
    "community_forensics_detection": 0.10,
    "npr_ai_detection": 0.08,
    "mesorch_detection": 0.10,
}

# Module names that are dedicated AI / synthetic-content detectors
# (exported for use by analyze.py enforcement logic)
_AI_DETECTOR_MODULES = frozenset({
    "ai_generation_detection",
    "clip_ai_detection",
    "vae_reconstruction",
    "prnu_detection",
    "community_forensics_detection",
    "npr_ai_detection",
})

# Core AI detection modules — only these determine AI generation score
# Weights based on calibration analysis (2007 images):
#   CommFor: best discriminator (auth 0.04 vs AI 0.15), highest weight
#   Swin: decent but 37.8% FP on authentic cars, moderate weight
#   CLIP: constant ~0.15 output (no trained probe yet), minimal weight
#   NPR: JPEG destroys upsampling signal, bimodal random, minimal weight
#   VAE: DIRE hypothesis fails for modern generators, minimal weight
_CORE_AI_WEIGHTS = {
    "community_forensics_detection": 0.45,
    "ai_generation_detection": 0.35,
    "npr_ai_detection": 0.08,
    "clip_ai_detection": 0.07,
    "vae_reconstruction": 0.05,
}


def _risk_level(score: float) -> RiskLevel:
    reg = get_registry()
    if score >= reg.fusion.risk_critical:
        return RiskLevel.CRITICAL
    if score >= reg.fusion.risk_high:
        return RiskLevel.HIGH
    if score >= reg.fusion.risk_medium:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _get_module(active: list[ModuleResult], name: str) -> ModuleResult | None:
    return next((m for m in active if m.module_name == name), None)


def fuse_scores(
    modules: list[ModuleResult],
) -> tuple[float, int, RiskLevel, dict[str, float] | None]:
    """
    Core-only score fusion with context modifiers.

    Returns (overall_float, overall_100, risk_level, verdict_probabilities).
    verdict_probabilities is a dict like {"authentic": 0.65, "ai_generated": 0.25, "tampered": 0.10}
    or None if meta-learner is not available.
    """
    active = [m for m in modules if not m.error]

    if not active:
        return 0.0, 0, RiskLevel.LOW, None

    # ── Stacking meta-learner (replaces everything when trained) ──────
    try:
        from ..config import settings as _settings
        meta_enabled = _settings.forensics_stacking_meta_enabled
    except Exception:
        meta_enabled = False

    verdict_probs: dict[str, float] | None = None

    # Meta-learner provides ONLY verdict_probabilities (3-class breakdown
    # for the UI bars). The overall risk score is ALWAYS computed by the
    # rule-based fusion below — rules are transparent, debuggable, and
    # don't produce false positives like the meta-learner did.
    if meta_enabled:
        meta_learner = get_meta_learner(_settings.forensics_stacking_meta_weights)
        verdict_probs = meta_learner.predict_proba(modules)

    # ── Step 1: Core AI pixel score (PRIMARY signal) ──────────────────
    # CommFor is the most reliable AI detector (4.3% FP vs Swin's 37.8%).
    # When CommFor says "not AI" (< 0.10), dampen Swin to reduce FP.
    commfor = _get_module(active, "community_forensics_detection")
    commfor_low = commfor is not None and commfor.risk_score < 0.10

    core_weighted = 0.0
    core_total_w = 0.0
    for m in active:
        if m.module_name in _CORE_AI_WEIGHTS:
            w = _CORE_AI_WEIGHTS[m.module_name]
            score = m.risk_score
            # Dampen Swin when CommFor disagrees (reduces 37.8% FP on authentic)
            if m.module_name == "ai_generation_detection" and commfor_low and score < 0.80:
                score *= 0.40
            core_weighted += score * w
            core_total_w += w
    core_score = core_weighted / core_total_w if core_total_w > 0 else 0.0

    # ── Step 2: Context modifiers from metadata + PRNU ────────────────
    meta = _get_module(active, "metadata_analysis")
    prnu = _get_module(active, "prnu_detection")

    # PRNU disabled as context signal — 90% of AI images falsely get
    # PRNU_AUTHENTIC_SENSOR due to crude 5x5 denoiser detecting image
    # structure instead of sensor noise. Needs wavelet denoiser rewrite.
    has_authentic_sensor = False
    has_c2pa_valid = meta is not None and any(
        f.code == "META_C2PA_VALID" for f in meta.findings
    )
    has_ai_tool = meta is not None and any(
        f.code in ("META_XMP_AI_TOOL_HISTORY", "META_C2PA_AI_GENERATED")
        for f in meta.findings
    )
    has_ai_filename = meta is not None and any(
        f.code == "META_FILENAME_AI_GENERATOR" for f in meta.findings
    )

    if has_authentic_sensor or has_c2pa_valid:
        core_score *= 0.50  # Strong camera/provenance evidence halves AI risk
    if has_ai_tool or has_ai_filename:
        core_score = max(core_score, 0.90)  # Definitive AI metadata signal

    # ── Step 3: Gemini VLM as SUPPLEMENTARY signal (additive, not dominant)
    # VLMs are great for describing anomalies but unreliable for binary
    # AI classification. Gemini can nudge the score slightly but NEVER
    # override pixel detectors. Max adjustment: ±0.10
    sem = _get_module(active, "semantic_forensics")
    gemini_adjustment = 0.0

    if sem is not None and sem.findings:
        for f in sem.findings:
            if f.code == "SEM_VLM_SYNTHETIC_DETECTED":
                # Gemini agrees it's AI — small boost (max +0.10)
                gemini_adjustment = min(0.10, sem.risk_score * 0.15)
                break
            if f.code == "SEM_VLM_SYNTHETIC_SUSPECTED":
                gemini_adjustment = min(0.05, sem.risk_score * 0.10)
                break
            if f.code == "SEM_VLM_AUTHENTIC":
                # Gemini thinks it's real — small reduction (max -0.05)
                # This CANNOT flip a high pixel score to "safe"
                gemini_adjustment = -0.05
                break

    # ── Step 4: Combine — pixel-first with Gemini adjustment ─────────
    if has_ai_tool or has_ai_filename:
        ai_combined = core_score  # Metadata definitive, skip Gemini
    else:
        ai_combined = core_score + gemini_adjustment

    # ── Step 3: Tampering score (separate from AI generation) ─────────
    # Each tampering detector needs a minimum threshold before contributing.
    # TruFor and ELA/DCT give 0.40-0.65 on authentic JPEG (false positive),
    # so we require higher confidence before calling it tampering.
    deep_mod = _get_module(active, "deep_modification_detection")
    mod_det = _get_module(active, "modification_detection")
    mesorch = _get_module(active, "mesorch_detection")

    deep_mod_score = deep_mod.risk_score if deep_mod and deep_mod.risk_score >= 0.55 else 0.0
    mesorch_score = mesorch.risk_score if mesorch and mesorch.risk_score >= 0.40 else 0.0
    mod_det_score = (mod_det.risk_score * 0.50) if mod_det and mod_det.risk_score >= 0.70 else 0.0

    # Require at least 2 tampering signals to flag as tampered
    tamp_signals = [s for s in [deep_mod_score, mesorch_score, mod_det_score] if s > 0]
    if len(tamp_signals) >= 2:
        tampering = max(tamp_signals)
    elif len(tamp_signals) == 1 and max(tamp_signals) >= 0.65:
        # Single very strong signal still counts
        tampering = max(tamp_signals) * 0.85
    else:
        tampering = 0.0

    # ── Step 4: Document signals ──────────────────────────────────────
    text_ai = _get_module(active, "text_ai_detection")
    text_ai_score = text_ai.risk_score if text_ai and text_ai.risk_score >= 0.50 else 0.0
    content_val = _get_module(active, "content_validation")
    content_score = content_val.risk_score if content_val and content_val.risk_score >= 0.40 else 0.0

    # ── Step 5: Final risk = max of all channels ──────────────────────
    overall = max(ai_combined, tampering, text_ai_score, content_score)

    # ── Step 6: Cross-validation AI boost ─────────────────────────────
    # No single model can boost alone — requires corroboration.
    # Swin ViT has high false positive rate on authentic JPEG photos.
    ai_gen = _get_module(active, "ai_generation_detection")
    commfor = _get_module(active, "community_forensics_detection")

    # Count how many core AI detectors agree at >= 0.50
    high_ai_count = sum(
        1 for m in active
        if m.module_name in _CORE_AI_WEIGHTS and m.risk_score >= 0.50
    )

    # Swin boost ONLY if corroborated by CommFor OR 2+ other detectors
    if ai_gen and ai_gen.risk_score >= 0.60:
        commfor_agrees = commfor is not None and commfor.risk_score >= 0.50
        if commfor_agrees or high_ai_count >= 3:
            overall = max(overall, ai_gen.risk_score)
        elif high_ai_count >= 2:
            # Partial corroboration — moderate boost
            overall = max(overall, ai_gen.risk_score * 0.75)

    # Cross-validation: 2+ core detectors agree → floor at 0.70
    if high_ai_count >= 2:
        overall = max(overall, 0.70)

    overall = max(0.0, min(1.0, overall))

    # ── Reconcile meta-learner verdict bars with rule-based score ────
    # Meta-learner verdict_probabilities can contradict the rule-based
    # overall score. When they diverge too much, override verdict bars
    # to match the rule-based decision.
    if verdict_probs is not None:
        meta_max_class = max(verdict_probs, key=verdict_probs.get)
        meta_max_prob = verdict_probs[meta_max_class]

        # If rule-based says low risk but meta says high AI/tampered
        if overall < 0.30 and meta_max_class != "authentic" and meta_max_prob > 0.50:
            verdict_probs = {
                "authentic": max(0.60, 1.0 - overall),
                "ai_generated": overall * 0.6,
                "tampered": overall * 0.4,
            }
        # If rule-based says high risk but meta says authentic
        elif overall > 0.70 and meta_max_class == "authentic" and meta_max_prob > 0.50:
            verdict_probs = {
                "authentic": max(0.05, 1.0 - overall),
                "ai_generated": ai_combined / max(overall, 0.01) * overall * 0.7,
                "tampered": tampering / max(overall, 0.01) * overall * 0.7,
            }

    return overall, round(overall * 100), _risk_level(overall), verdict_probs
