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
_CORE_AI_WEIGHTS = {
    "safe_ai_detection": 0.25,
    "dinov2_ai_detection": 0.20,
    "community_forensics_detection": 0.20,
    "spai_detection": 0.15,              # FFT+ViT, independent architecture
    "clip_ai_detection": 0.10,
    "bfree_detection": 0.05,             # DINOv2-family (bias-free)
    "ai_generation_detection": 0.05,
}

# CNN-family: detectors dampened when independents don't confirm.
# CLIP removed from CNN-family — insurance-domain probe trained on car
# damage images, no longer shares OOD false positive bias.
_CNN_FAMILY_DETECTORS = frozenset({
    "dinov2_ai_detection",
    "efficientnet_ai_detection",
    "bfree_detection",
})

# DAMPENING independent: methods used to check if CNN detectors are correct.
_DAMPENING_INDEPENDENT = frozenset({
    "safe_ai_detection",              # Pixel correlation (KDD 2025)
    "community_forensics_detection",  # 4803-generator ViT (CVPR 2025)
    "spai_detection",                 # FFT spectral (CVPR 2025)
    "clip_ai_detection",              # Insurance-domain MLP probe
})

# Reliable AI detectors for consensus checking
_RELIABLE_AI_DETECTORS = frozenset({
    "safe_ai_detection",
    "dinov2_ai_detection",
    "community_forensics_detection",
    "efficientnet_ai_detection",
    "clip_ai_detection",
    "spai_detection",
    "bfree_detection",
})

# Independent detectors for consensus boost.
_INDEPENDENT_DETECTORS = frozenset({
    "safe_ai_detection",              # Pixel correlation (KDD 2025)
    "community_forensics_detection",  # 4803-generator ViT (CVPR 2025)
    "spai_detection",                 # FFT spectral (CVPR 2025)
    "clip_ai_detection",              # Insurance-domain MLP probe
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

    # ── Step 1: Core AI pixel score (PRIMARY signal) ──────────────────
    #
    # CNN dampening: DINOv2, EfficientNet, bfree, and CLIP share an
    # embedding-based architecture. When they fire high but SAFE, CommFor,
    # and SPAI (fundamentally different methods) stay low, it's likely a
    # shared bias false positive. Dampen CNN-family contributions.
    #
    # v3: Raised floor from 0.30 to 0.50 — CNN detectors always contribute
    # at least 50% of their signal. Old floor was too aggressive and caused
    # false negatives on real AI images where independent detectors were
    # borderline (e.g., SAFE=0.20, CommFor=0.15).

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

    # v3: Removed SAFE isolation dampening. SAFE uses pixel correlation
    # analysis (KDD 2025) — a fundamentally different method from CNN/ViT
    # detectors. When SAFE fires alone at 0.80, that's a legitimate signal
    # from an independent method, not a false positive.
    # Old behavior dampened SAFE to 0.50 when other core modules < 0.20,
    # causing false negatives on AI images that only SAFE could detect.

    core_weighted = 0.0
    core_total_w = 0.0
    for m in active:
        if m.module_name in _CORE_AI_WEIGHTS:
            w = _CORE_AI_WEIGHTS[m.module_name]
            score = m.risk_score
            if m.module_name in _CNN_FAMILY_DETECTORS:
                score *= cnn_dampening
            core_weighted += score * w
            core_total_w += w
    core_score = core_weighted / core_total_w if core_total_w > 0 else 0.0

    # CNN dampening already applied above via cnn_dampening factor.
    # No additional cap — let the weighted average and consensus logic decide.

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
    if has_ai_tool or has_ai_filename:
        core_score = max(core_score, ft.ai_metadata_floor)  # Definitive AI signal

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

    n_high = sum(1 for s in reliable_scores.values() if s >= ft.detector_high)
    n_low = sum(1 for s in reliable_scores.values() if s < ft.detector_low)

    # Count independent detectors (SAFE/CommFor/SPAI) that confirm AI signal
    independent_confirms = sum(
        1 for name in _INDEPENDENT_DETECTORS
        if reliable_scores.get(name, 0) >= ft.independent_confirm
    )

    # Apply consensus boost (strongest matching tier wins)
    if n_high >= ft.boost_strong_min_high and n_low <= 1 and independent_confirms >= 1:
        overall = max(overall, ft.boost_strong_floor)
    elif n_high >= ft.boost_moderate_min_high and independent_confirms >= 1:
        overall = max(overall, ft.boost_moderate_floor)

    # Swin (ai_generation_detection) boost ONLY if independent detectors confirm
    if ai_gen and ai_gen.risk_score >= ft.swin_min and independent_confirms >= 2:
        overall = max(overall, ai_gen.risk_score)

    overall = max(0.0, min(1.0, overall))

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
