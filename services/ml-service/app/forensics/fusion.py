"""
Score fusion — combines forensic module results into a single risk score.

Architecture (v3): Core-only fusion with configurable thresholds.

Only 7 CORE AI detectors determine the AI generation score.
Tampering is scored separately from AI generation.
Context signals (metadata, PRNU) modify confidence but never decide alone.
Support modules (spectral, optical, semantic) are informational only.

Changes from v2:
  - Removed SAFE isolation dampening (SAFE is pixel-correlation, independent)
  - Softened CNN dampening floor (0.30 → 0.50)
  - Removed CLIP from independent detectors (shares CNN embedding bias)
  - Two consensus boost tiers: strong (3+, 0.75) and moderate (2+, 0.65)
  - All thresholds loaded from FusionThresholds registry (configurable)
"""

import logging

from .base import ModuleResult, RiskLevel
from .stacking_meta import get_meta_learner
from .thresholds import get_registry

logger = logging.getLogger(__name__)

# Legacy weights — not used for fusion (see _CORE_AI_WEIGHTS below).
# Kept only for backward compatibility with old training scripts.
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
    # Added 2026-04-05 — were missing from MODULE_ORDER, invisible to GBM
    "organika_ai_detection": 0.25,
    "rine_detection": 0.03,
    "pixel_forensics": 0.10,
    "siglip_ai_detection": 0.05,
    "ai_source_detection": 0.05,
    "bfree_detection": 0.05,
    "spai_detection": 0.05,
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

# Core AI detection modules — only these determine AI generation score.
# Disabled modules (SAFE, SPAI, RINE, CommFor, EfficientNet) removed.
# Weights auto-normalize via core_total_w division.
# Weights reflect ACTUAL detection performance, not theoretical accuracy.
# Modules that don't detect modern AI (Flux/DALL-E) get low weight to avoid
# diluting the working detectors.
# RA-Det enabled with conservative thresholds (L2 8-14).
# From testing: real photos L2=4-5 → score~0%, AI faces L2=16-17 → score~100%.
# fatformer/aide still disabled until calibrated.
_CORE_AI_WEIGHTS = {
    "clip_ai_detection": 0.38,            # BEST: 74% on AI, 13% on authentic
    "organika_ai_detection": 0.23,        # GOOD: 39% on AI, 0% on authentic
    "radet_detection": 0.10,              # NEW: perturbation robustness, conservative thresholds
    "pixel_forensics": 0.08,              # WEAK: 33% AI, 22% auth — small edge
    "dinov2_ai_detection": 0.07,          # FP BIAS: dampened on car damage
    "ai_generation_detection": 0.05,      # Legacy Swin
    "bfree_detection": 0.04,              # POOR on modern AI: 1% on Flux/DALL-E
    "safe_ai_detection": 0.03,            # POOR on modern AI: 5% on Flux/DALL-E
    "rine_detection": 0.02,               # DEAD: 0% (trained on ProGAN/StyleGAN only)
}

# CNN-family: detectors dampened when independents don't confirm.
# Only DINOv2 remains — has severe FP bias on car damage photos.
# CLIP works correctly (74% AI, 13% auth). bfree works when loaded correctly.
_CNN_FAMILY_DETECTORS = frozenset({
    "dinov2_ai_detection",
})

# DAMPENING independent: methods used to check if DINOv2 FPs are real.
# Only modules that actually WORK and are independent of DINOv2 embeddings.
# RA-Det included (conservative thresholds prevent FP).
# fatformer/aide still excluded until calibrated.
_DAMPENING_INDEPENDENT = frozenset({
    "safe_ai_detection",              # DWT wavelet pixel correlation (KDD 2025)
    "clip_ai_detection",              # CLIP MLP probe (different backbone)
    "organika_ai_detection",          # Organika Swin (98.1% acc)
    "ai_source_detection",            # ViT-Base multi-class (91.6% acc)
    "rine_detection",                 # RINE intermediate CLIP (ECCV 2024)
    "bfree_detection",                # B-Free DINOv2 ViT-Base (5-crop)
    "pixel_forensics",                # 8 pixel-level signals (numpy)
    "radet_detection",                # RA-Det perturbation robustness
})

# Reliable AI detectors for consensus checking
_RELIABLE_AI_DETECTORS = frozenset({
    "clip_ai_detection",
    "bfree_detection",
    "organika_ai_detection",
    "ai_source_detection",
    "safe_ai_detection",
    "rine_detection",
    "dinov2_ai_detection",
    "pixel_forensics",
    "radet_detection",
})

# Independent detectors for consensus boost — non-CNN methods
_INDEPENDENT_DETECTORS = frozenset({
    "safe_ai_detection",              # DWT wavelet (KDD 2025)
    "organika_ai_detection",          # Organika Swin (98.1% acc)
    "ai_source_detection",            # ViT-Base multi-class (91.6% acc)
    "rine_detection",                 # RINE intermediate CLIP (ECCV 2024)
    "pixel_forensics",                # 8 pixel-level signals (numpy)
    "radet_detection",                # RA-Det perturbation robustness
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

    reg = get_registry()
    ft = reg.fusion

    # ── Stacking meta-learner (replaces everything when trained) ──────
    try:
        from ..config import settings as _settings
        meta_enabled = _settings.forensics_stacking_meta_enabled
    except Exception as e:
        logger.debug("Stacking meta config load: %s", e)
        meta_enabled = False

    verdict_probs: dict[str, float] | None = None

    # Meta-learner provides ONLY verdict_probabilities (3-class breakdown
    # for the UI bars). The overall risk score is ALWAYS computed by the
    # rule-based fusion below — rules are transparent and debuggable.
    if meta_enabled:
        meta_learner = get_meta_learner(_settings.forensics_stacking_meta_weights)
        verdict_probs = meta_learner.predict_proba(modules)

    # ── Debug: log all module scores ──────────────────────────────────
    _scores_debug = {m.module_name: round(m.risk_score, 4) for m in active}
    logger.info("FUSION module scores: %s", _scores_debug)

    # ── Step 1: Core AI pixel score (PRIMARY signal) ──────────────────
    #
    # CNN dampening: DINOv2, EfficientNet, bfree, and CLIP share an
    # embedding-based architecture. When they fire high but SAFE, CommFor,
    # and SPAI (fundamentally different methods) stay low, it's likely a
    # shared bias false positive. Dampen CNN-family contributions.

    max_independent_score = max(
        (m.risk_score for m in active
         if m.module_name in _DAMPENING_INDEPENDENT and not m.error),
        default=0.0,
    )

    # CNN dampening factor: 1.0 when independents confirm (>= threshold),
    # scales linearly down to floor when no independent signal.
    cnn_dampening = 1.0
    if max_independent_score < ft.cnn_dampening_threshold:
        cnn_dampening = ft.cnn_dampening_floor + (1.0 - ft.cnn_dampening_floor) * (
            max_independent_score / ft.cnn_dampening_threshold
        )

    logger.info(
        "FUSION CNN dampening: max_independent=%.4f threshold=%.2f factor=%.4f",
        max_independent_score, ft.cnn_dampening_threshold, cnn_dampening,
    )

    core_weighted = 0.0
    core_total_w = 0.0
    _core_details = {}
    for m in active:
        if m.module_name in _CORE_AI_WEIGHTS:
            w = _CORE_AI_WEIGHTS[m.module_name]
            score = m.risk_score
            if m.module_name in _CNN_FAMILY_DETECTORS:
                score *= cnn_dampening
                _core_details[m.module_name] = f"{m.risk_score:.4f}*{cnn_dampening:.2f}={score:.4f} w={w}"
            else:
                _core_details[m.module_name] = f"{score:.4f} w={w}"
            core_weighted += score * w
            core_total_w += w
    core_score = core_weighted / core_total_w if core_total_w > 0 else 0.0

    logger.info("FUSION core breakdown: %s → core_score=%.4f", _core_details, core_score)

    # ── Step 2: Context modifiers from metadata + PRNU ────────────────
    meta = _get_module(active, "metadata_analysis")

    # PRNU disabled as context signal — WebP/JPEG compression destroys
    # PRNU signal (Cohen's d = 0.011, no separation).
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

    if has_c2pa_valid:
        core_score *= ft.c2pa_factor  # Strong camera/provenance evidence
    if has_ai_tool:
        core_score = max(core_score, ft.ai_metadata_floor)  # XMP/C2PA = definitive AI signal
    # Filename is spoofable but still a useful signal. Use as strong boost
    # when at least 1 AI detector also shows elevated score (>= 0.25).
    # If no detector confirms, filename alone caps at 0.50 (not definitive).
    if has_ai_filename and not has_ai_tool:
        any_detector_elevated = any(
            m.risk_score >= 0.25 for m in active
            if m.module_name in _CORE_AI_WEIGHTS and m.module_name != "pixel_forensics"
        )
        if any_detector_elevated:
            core_score = max(core_score, 0.75)  # Filename + detector confirm = strong
        else:
            core_score = max(core_score, min(core_score + 0.15, 0.50))  # Filename alone = moderate

    ai_combined = core_score

    # ── Step 3: Tampering score (separate from AI generation) ─────────
    deep_mod = _get_module(active, "deep_modification_detection")
    mod_det = _get_module(active, "modification_detection")
    mesorch = _get_module(active, "mesorch_detection")

    deep_mod_score = deep_mod.risk_score if deep_mod and deep_mod.risk_score >= ft.deep_mod_min else 0.0
    mesorch_score = mesorch.risk_score if mesorch and mesorch.risk_score >= ft.mesorch_min else 0.0
    mod_det_score = (mod_det.risk_score * ft.ela_scale) if mod_det and mod_det.risk_score >= ft.ela_min else 0.0

    tamp_signals = [s for s in [deep_mod_score, mesorch_score, mod_det_score] if s > 0]
    if len(tamp_signals) >= 2:
        tampering = max(tamp_signals)
    elif len(tamp_signals) == 1 and max(tamp_signals) >= ft.single_tamp_min:
        tampering = max(tamp_signals) * ft.single_tamp_scale
    else:
        tampering = 0.0

    # ── Step 4: Document signals ──────────────────────────────────────
    text_ai = _get_module(active, "text_ai_detection")
    text_ai_score = text_ai.risk_score if text_ai and text_ai.risk_score >= ft.text_ai_min else 0.0
    content_val = _get_module(active, "content_validation")
    content_score = content_val.risk_score if content_val and content_val.risk_score >= ft.content_val_min else 0.0

    # ── Step 5: Final risk = max of all channels ──────────────────────
    overall = max(ai_combined, tampering, text_ai_score, content_score)

    # ── Step 6: Cross-validation AI boost (consensus with diversity) ──
    #
    # Problem: EfficientNet + DINOv2 + CLIP share embedding-based architecture.
    # When they fire high on OOD images (car damage, medical) but SAFE, CommFor,
    # SPAI (fundamentally different methods) stay low, it's CNN-family bias.
    #
    # Solution: require consensus WITH diversity — at least 1 independent
    # detector (SAFE/CommFor/SPAI) must confirm before boosting.
    #   Strong:   3+ reliable high AND 1+ independent confirms → 0.75
    #   Moderate: 2+ high AND 1+ independent confirms → 0.65

    ai_gen = _get_module(active, "ai_generation_detection")

    reliable_scores = {}
    for m in active:
        if m.module_name in _RELIABLE_AI_DETECTORS and not m.error:
            reliable_scores[m.module_name] = m.risk_score

    # Count high detectors separately for CNN-family vs non-CNN.
    # CNN-family detectors (DINOv2/EfficientNet/bfree/CLIP) share embedding
    # bias — 3 CNN detectors firing high is 1 signal, not 3.
    n_high_cnn = sum(
        1 for name, s in reliable_scores.items()
        if s >= ft.detector_high and name in _CNN_FAMILY_DETECTORS
    )
    n_high_non_cnn = sum(
        1 for name, s in reliable_scores.items()
        if s >= ft.detector_high and name not in _CNN_FAMILY_DETECTORS
    )
    # Cap CNN-family contribution to 1 vote for consensus
    n_high = min(n_high_cnn, 1) + n_high_non_cnn
    n_low = sum(1 for s in reliable_scores.values() if s < ft.detector_low)

    # Count independent detectors (SAFE/CommFor/SPAI/etc) that confirm AI signal
    independent_confirms = sum(
        1 for name in _INDEPENDENT_DETECTORS
        if reliable_scores.get(name, 0) >= ft.independent_confirm
    )

    logger.info(
        "FUSION consensus: n_high=%d (cnn=%d→capped=1, non_cnn=%d) n_low=%d "
        "independent_confirms=%d (threshold=%.2f) reliable=%s",
        n_high, n_high_cnn, n_high_non_cnn, n_low, independent_confirms,
        ft.independent_confirm,
        {k: f"{v:.4f}" for k, v in reliable_scores.items()},
    )

    # Apply consensus boost (strongest matching tier wins)
    boost_applied = "none"
    if n_high >= ft.boost_strong_min_high and n_low <= 1 and independent_confirms >= 1:
        overall = max(overall, ft.boost_strong_floor)
        boost_applied = f"strong→{ft.boost_strong_floor}"
    elif n_high >= ft.boost_moderate_min_high and independent_confirms >= 2:
        overall = max(overall, ft.boost_moderate_floor)
        boost_applied = f"moderate→{ft.boost_moderate_floor}"

    # Swin (ai_generation_detection) boost ONLY if independent detectors confirm
    if ai_gen and ai_gen.risk_score >= ft.swin_min and independent_confirms >= 2:
        overall = max(overall, ai_gen.risk_score)
        boost_applied = f"swin→{ai_gen.risk_score:.4f}"

    # High-confidence CLIP boost: when CLIP is very confident (>70%) AND
    # at least 1 independent confirms, use CLIP score directly as floor.
    # CLIP at 74% with Organika+pixel confirming = strong AI signal.
    clip_m = _get_module(active, "clip_ai_detection")
    if clip_m and clip_m.risk_score >= 0.70 and independent_confirms >= 1:
        clip_floor = clip_m.risk_score * 0.95  # 74% → 70% floor
        if clip_floor > overall:
            overall = clip_floor
            boost_applied = f"clip_high→{clip_floor:.4f}"

    # CLIP isolation dampening: when CLIP is moderate (50-70%) but ALL other
    # detectors disagree (n_low >= 4), CLIP is likely a false positive.
    # Car damage photos trigger CLIP FP because the domain is OOD for the
    # generic probe. Cap the score to prevent false "Potreban pregled".
    if clip_m and 0.50 <= clip_m.risk_score < 0.70 and n_low >= 4:
        clip_isolated_cap = 0.20
        if overall > clip_isolated_cap:
            overall = clip_isolated_cap
            boost_applied = f"clip_isolated_cap→{clip_isolated_cap}"

    overall = max(0.0, min(1.0, overall))

    logger.info(
        "FUSION result: core=%.4f tamp=%.4f boost=%s → overall=%.4f (%s)",
        core_score, tampering, boost_applied, overall, _risk_level(overall).value,
    )

    # ── Verdict bars — always derive from rule-based scores ─────────
    # GBM verdict_probs may be stale (trained on different probe version).
    # Override with rule-based derivation that's always consistent.
    ai_signal = max(ai_combined, core_score)
    tamp_signal = tampering

    if overall < ft.verdict_low_threshold:
        # Low risk → strongly authentic
        verdict_probs = {
            "authentic": round(max(0.85, 1.0 - overall * 2), 4),
            "ai_generated": round(overall * 0.4, 4),
            "tampered": round(overall * 0.6 * overall, 4),
        }
    elif overall >= ft.verdict_high_threshold:
        # High risk → determine AI vs tampered from signal sources
        p_auth = round(max(0.02, 1.0 - overall), 4)
        remaining = 1.0 - p_auth
        if ai_signal > 0 or tamp_signal > 0:
            total_signal = ai_signal + tamp_signal
            p_ai = round(remaining * (ai_signal / total_signal), 4)
            p_tamp = round(remaining * (tamp_signal / total_signal), 4)
        else:
            p_ai = round(remaining * 0.7, 4)
            p_tamp = round(remaining * 0.3, 4)
        verdict_probs = {"authentic": p_auth, "ai_generated": p_ai, "tampered": p_tamp}
    else:
        # Medium risk
        verdict_probs = {
            "authentic": round(max(0.40, 1.0 - overall), 4),
            "ai_generated": round(overall * 0.6, 4),
            "tampered": round(overall * 0.4, 4),
        }

    return overall, round(overall * 100), _risk_level(overall), verdict_probs
