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
    "efficientnet_ai_detection": 0.10,
    "safe_ai_detection": 0.12,
    "dinov2_ai_detection": 0.12,
}

# Module names that are dedicated AI / synthetic-content detectors
_AI_DETECTOR_MODULES = frozenset({
    "ai_generation_detection",
    "clip_ai_detection",
    "prnu_detection",
    "community_forensics_detection",
    "efficientnet_ai_detection",
    "safe_ai_detection",
    "dinov2_ai_detection",
})

# Core AI detection modules — only these determine AI generation score
# Retrained on diverse dataset (3799 images, 9 generators + RAISE/CarDD auth)
# DINOv2: 0% FP on diverse auth (best discriminator, 0.55 separation)
# SAFE: KDD 2025, JPEG-dampened (×0.70 for compression artifacts)
# CommFor: CVPR 2025, 4803 generators
# CLIP: retrained probe F1=0.746
# Removed: NPR (0.023 separation = noise), VAE (disabled)
_CORE_AI_WEIGHTS = {
    "safe_ai_detection": 0.30,
    "dinov2_ai_detection": 0.25,
    "community_forensics_detection": 0.25,
    "clip_ai_detection": 0.15,
    "ai_generation_detection": 0.05,
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
    #
    # Isolation dampening: DINOv2 and EfficientNet share a CNN/transformer
    # architecture family. When they fire high but SAFE, CommFor, and CLIP
    # (independent architectures) all stay low, it's likely a shared bias
    # false positive. Dampen CNN-family contributions when independents
    # don't confirm.
    # DINOv2 uses our trained probe (potentially biased by training data).
    # EfficientNet uses pre-trained HuggingFace weights (not our probe).
    #
    # For DAMPENING: check if method-diverse detectors confirm (SAFE/CommFor/CLIP).
    # EfficientNet and DINOv2 are both CNN-family for dampening purposes.
    _CNN_FAMILY_DETECTORS = {"dinov2_ai_detection", "efficientnet_ai_detection"}
    _DAMPENING_INDEPENDENT = {
        "safe_ai_detection",              # Pixel correlation (KDD 2025)
        "community_forensics_detection",  # 4803-generator ViT (CVPR 2025)
        "clip_ai_detection",              # Language-vision embedding
    }

    max_independent_score = max(
        (m.risk_score for m in active
         if m.module_name in _DAMPENING_INDEPENDENT and not m.error),
        default=0.0,
    )

    # CNN dampening factor: 1.0 (full) when SAFE/CommFor/CLIP confirm (>= 0.30),
    # scales down linearly to 0.30 when no method-diverse signal at all.
    cnn_dampening = 1.0
    if max_independent_score < 0.30:
        cnn_dampening = 0.30 + 0.70 * (max_independent_score / 0.30)

    # SAFE isolation check: when SAFE fires alone (CommFor+CLIP+DINOv2+Eff all low),
    # it's likely a JPEG artifact FP. Dampen SAFE's contribution.
    safe_mod = _get_module(active, "safe_ai_detection")
    safe_score_raw = safe_mod.risk_score if safe_mod and not safe_mod.error else 0.0
    other_core_max = max(
        (m.risk_score for m in active
         if m.module_name in _CORE_AI_WEIGHTS
         and m.module_name != "safe_ai_detection"
         and not m.error),
        default=0.0,
    )
    safe_dampening = 1.0
    if safe_score_raw > 0.20 and other_core_max < 0.20:
        # SAFE alone, no corroboration → dampen
        safe_dampening = 0.50

    core_weighted = 0.0
    core_total_w = 0.0
    for m in active:
        if m.module_name in _CORE_AI_WEIGHTS:
            w = _CORE_AI_WEIGHTS[m.module_name]
            score = m.risk_score
            if m.module_name in _CNN_FAMILY_DETECTORS:
                score *= cnn_dampening
            if m.module_name == "safe_ai_detection":
                score *= safe_dampening
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
    # ELA/modification at 0.50+ indicates real tampering (lowered from 0.70
    # because with CNN disabled, ELA is the only other tampering signal).
    # Scale by 0.80 to prevent minor ELA anomalies from dominating.
    mod_det_score = (mod_det.risk_score * 0.80) if mod_det and mod_det.risk_score >= 0.50 else 0.0

    # Require at least 2 tampering signals to flag as tampered.
    # With CNN disabled, Mesorch is often the only tampering detector.
    # A single Mesorch/mod_det signal >= 0.50 is reliable enough to flag.
    tamp_signals = [s for s in [deep_mod_score, mesorch_score, mod_det_score] if s > 0]
    if len(tamp_signals) >= 2:
        tampering = max(tamp_signals)
    elif len(tamp_signals) == 1 and max(tamp_signals) >= 0.50:
        # Single strong signal (lowered from 0.65 because CNN is disabled
        # and Mesorch alone at 0.50+ is a reliable tampering indicator)
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

    # ── Step 6: Cross-validation AI boost (consensus with diversity) ────
    #
    # Problem: EfficientNet + DINOv2 share CNN bias — both fire on certain
    # authentic JPEGs (e.g., 25220902d9b0.jpg: Eff=1.00, DINOv2=0.90, but
    # SAFE=0.01, CommFor=0.001, CLIP=0.00). That's DISAGREEMENT, not consensus.
    #
    # Solution: require consensus WITH diversity. When detectors disagree
    # strongly (some HIGH, others near ZERO), that's a red flag for detector
    # bias, not evidence of AI generation.
    #
    # Architecture families:
    #   CNN-family: EfficientNet, DINOv2 (both feed-forward vision transformers/CNNs)
    #   Independent: SAFE (pixel correlations), CommFor (4803 generators), CLIP (language-vision)
    _RELIABLE_AI_DETECTORS = {
        "safe_ai_detection",
        "dinov2_ai_detection",
        "community_forensics_detection",
        "efficientnet_ai_detection",
        "clip_ai_detection",
    }
    # For CONSENSUS: method-diverse detectors that must confirm.
    # EfficientNet is CNN-architecture (like DINOv2) — when both fire high
    # but SAFE/CommFor/CLIP don't, that's CNN-family bias, not real AI.
    # Keep consensus independent = SAFE/CommFor/CLIP only.
    _INDEPENDENT_DETECTORS = {
        "safe_ai_detection",           # Pixel correlation (KDD 2025)
        "community_forensics_detection",  # 4803-generator ViT (CVPR 2025)
        "clip_ai_detection",           # Language-vision embedding
    }

    ai_gen = _get_module(active, "ai_generation_detection")

    # Collect scores from reliable detectors
    reliable_scores = {}
    for m in active:
        if m.module_name in _RELIABLE_AI_DETECTORS and not m.error:
            reliable_scores[m.module_name] = m.risk_score

    # CLIP consistently gives 0.48-0.49 on AI images (just below 0.50).
    # Using 0.45 threshold captures these borderline-but-real AI signals.
    n_high = sum(1 for s in reliable_scores.values() if s >= 0.45)
    n_low = sum(1 for s in reliable_scores.values() if s < 0.15)
    n_total = len(reliable_scores)

    # How many method-diverse INDEPENDENT detectors confirm?
    # Threshold 0.30 catches SAFE/CommFor signals that indicate AI presence
    # (auth images typically have SAFE < 0.25, so 0.30 is safe)
    independent_high = sum(
        1 for name in _INDEPENDENT_DETECTORS
        if reliable_scores.get(name, 0) >= 0.30
    )

    # Consensus boost rules:
    # 1. Strong consensus: 3+ reliable high AND at most 1 low → floor 0.75
    # 2. Moderate consensus: 2+ high AND 1+ independent confirms (>=0.40) → floor 0.65
    #    The independent confirmation is the KEY differentiator:
    #    - Auth FP: Eff+DINOv2 high but SAFE=0.01, CommFor=0.00, CLIP=0.00 → ind=0 → NO boost
    #    - Real AI: Eff+DINOv2 high AND CLIP=0.49 (ind confirms) → ind>=1 → boost
    # 3. Pure CNN agreement without independent: NO boost (possible shared bias)
    if n_high >= 3 and n_low <= 1:
        overall = max(overall, 0.75)
    elif n_high >= 2 and independent_high >= 1:
        overall = max(overall, 0.65)
    # else: no boost — only CNN-family detectors agree, independents don't confirm

    # Swin boost ONLY if independent detector confirms
    if ai_gen and ai_gen.risk_score >= 0.60 and independent_high >= 2:
        overall = max(overall, ai_gen.risk_score)

    overall = max(0.0, min(1.0, overall))

    # ── Reconcile meta-learner verdict bars with rule-based score ────
    # Meta-learner verdict_probabilities can contradict the rule-based
    # overall score. When they diverge too much, override verdict bars
    # to match the rule-based decision.
    if verdict_probs is not None:
        # Low risk (< 0.15) → verdict bars MUST strongly favor authentic.
        # The meta-learner was trained on calibration data with different
        # module behavior; noisy modules inflate its non-authentic scores.
        if overall < 0.15:
            # Low risk → verdict bars MUST strongly favor authentic.
            # Meta-learner trained on different module behavior inflates
            # non-authentic scores for noisy low-signal inputs.
            verdict_probs = {
                "authentic": round(max(0.85, 1.0 - overall * 2), 4),
                "ai_generated": round(overall * 0.4, 4),
                "tampered": round(overall * 0.6 * overall, 4),
            }
        else:
            meta_max_class = max(verdict_probs, key=verdict_probs.get)
            meta_max_prob = verdict_probs[meta_max_class]

            # If rule-based says low-medium risk but meta says high AI/tampered
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
