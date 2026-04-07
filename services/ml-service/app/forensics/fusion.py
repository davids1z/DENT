"""
Score fusion — combines forensic module results into a single risk score.

Architecture (v4): Lean core with only WORKING detectors.

Only 5 CORE AI detectors with proven detection on modern generators:
  CLIP (0.45), Organika (0.30), Pixel (0.10), DINOv2 (0.08), Swin (0.07)

Dead modules removed from all sets: RINE (0%), B-Free (1%), SAFE (5%).
Heuristic modules disabled: RA-Det, FatFormer, AIDE (no trained weights).

Changes from v3:
  - Removed dead modules (RINE/SAFE/B-Free) that diluted score by 14%
  - Removed RA-Det/FatFormer/AIDE heuristics from fusion (cause FP)
  - Consensus strong: 2+ high (was 3+), moderate: 1+ high with 1 independent
  - CLIP isolation only counts LIVE modules (was counting dead ones as "low")
  - SAFE JPEG dampening 0.60 → 0.85 (was destroying signal on all JPEG images)
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
# Dead modules removed: RINE (0%), B-Free (1%), SAFE (5%) on modern AI.
# Their 9% weight is redistributed to CLIP (+5%) and Organika (+3%) and pixel (+1%).
# Weights auto-normalize via core_total_w division.
# Only WORKING, CALIBRATED detectors participate in score.
# radet/fatformer/aide DISABLED: heuristic implementations without trained weights.
# bfree/safe/rine removed: 0-5% on modern AI, dilute score.
# B-Free is ENABLED in pipeline (runs, scores logged) but NOT in core weights
# until checkpoint is verified to detect modern generators on production.
# 2026-04-07 — Day 4 of path-to-95 roadmap. REBALANCED based on production
# data analysis. The previous weights were derived from synthetic CV F1
# numbers; production stats showed CLIP discriminates only +11.5pp while
# Organika gives +39.3pp and community_forensics gives +25.8pp. Re-enabled
# community_forensics (was disabled despite being one of the strongest
# discriminators in production data) and gave it real weight in core.
#
# Production gap (auth_mean → AI_mean) from data/production_stats_v1.json:
#   organika_ai_detection            +39.3pp  ★ best
#   community_forensics_detection    +25.8pp  ★ second best (re-enabled)
#   clip_ai_detection                +11.5pp  weaker than CV F1 suggested
#   pixel_forensics                  +10.9pp
#   dinov2_ai_detection               +6.4pp  noise-level (kept at 0.02)
#
# Sum = 1.00 (auto-normalized in fusion).
_CORE_AI_WEIGHTS = {
    "clip_ai_detection":            0.30,  # was 0.50 — gap is smaller than CV F1 suggested
    "organika_ai_detection":        0.35,  # was 0.32 — strongest discriminator
    "community_forensics_detection": 0.15, # NEW — second strongest, re-enabled
    "pixel_forensics":              0.10,  # unchanged — orthogonal physics signal
    "dinov2_ai_detection":          0.02,  # unchanged — capped at 0.50 + dampened
    "ai_generation_detection":      0.08,  # legacy Swin ensemble (small role)
}

# DINOv2 output cap — applied BEFORE the weighted-sum contribution. Even if the
# probe outputs 0.95 on a car damage photo (which it still does post-v11), it
# can never push the weighted score by more than this cap times its weight.
# At weight 0.02 + cap 0.50, max DINOv2 contribution = 0.01 = 1% of overall.
_DINOV2_OUTPUT_CAP = 0.50

# CNN-family: detectors dampened when independents don't confirm.
# Only DINOv2 remains — has severe FP bias on car damage photos.
# CLIP works correctly (74% AI, 13% auth). bfree works when loaded correctly.
_CNN_FAMILY_DETECTORS = frozenset({
    "dinov2_ai_detection",
})

# DAMPENING independent: methods used to check if DINOv2 FPs are real.
# Only modules that actually WORK on modern AI and are independent of DINOv2.
# Added community_forensics 2026-04-07 (Day 4) — production data shows it's
# the second-strongest discriminator at +25.8pp gap.
_DAMPENING_INDEPENDENT = frozenset({
    "clip_ai_detection",              # CLIP MLP probe (different backbone)
    "organika_ai_detection",          # Organika Swin (98.1% acc)
    "pixel_forensics",                # 8 pixel-level signals (numpy)
    "community_forensics_detection",  # ViT-Small trained on 4803 generators
})

# Reliable AI detectors for consensus checking.
# Only modules that CAN detect modern AI (Flux/DALL-E 3) belong here.
_RELIABLE_AI_DETECTORS = frozenset({
    "clip_ai_detection",
    "organika_ai_detection",
    "community_forensics_detection",  # added 2026-04-07 Day 4
    "dinov2_ai_detection",
    "pixel_forensics",
})

# Independent detectors for consensus boost — non-CNN, non-embedding methods.
_INDEPENDENT_DETECTORS = frozenset({
    "organika_ai_detection",          # Organika Swin (98.1% acc, different from CLIP/DINOv2)
    "community_forensics_detection",  # ViT-Small (different training, 4803 gens)
    "pixel_forensics",                # 8 pixel-level signals (numpy, no neural network)
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

    # ── Stacking meta-learner (supervised on production data) ────────
    try:
        from ..config import settings as _settings
        meta_enabled = _settings.forensics_stacking_meta_enabled
        meta_blend_factor = float(getattr(_settings, "forensics_stacking_meta_blend_factor", 0.0))
    except Exception as e:
        logger.debug("Stacking meta config load: %s", e)
        meta_enabled = False
        meta_blend_factor = 0.0

    verdict_probs: dict[str, float] | None = None
    meta_score: float | None = None  # Binary AI probability from supervised meta-learner

    # Meta-learner provides:
    #   1) verdict_probabilities (3-class) for the UI bars
    #   2) a binary "AI risk" score that the rule-based fusion blends with
    # The blend is gated by meta_blend_factor (default 0.0 = pure rules).
    # When set to 0.5 the final overall = 0.5 * rule + 0.5 * meta. This was
    # introduced 2026-04-07 after Day 3 of the path-to-95 roadmap, training
    # the meta-learner supervised on labeled production data.
    if meta_enabled:
        meta_learner = get_meta_learner(_settings.forensics_stacking_meta_weights)
        verdict_probs = meta_learner.predict_proba(modules)
        meta_score = meta_learner.predict(modules)

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
        if m.module_name not in _CORE_AI_WEIGHTS:
            continue
        w = _CORE_AI_WEIGHTS[m.module_name]
        raw = m.risk_score
        score = raw
        steps: list[str] = []

        # Step 1 — DINOv2 hard cap. Even if the probe outputs 0.95 on a car
        # damage photo (which it still does post-v11), the score that enters
        # the weighted sum is bounded by _DINOV2_OUTPUT_CAP. With weight 0.02
        # and cap 0.50, max DINOv2 contribution to overall fusion is 1%.
        if m.module_name == "dinov2_ai_detection" and score > _DINOV2_OUTPUT_CAP:
            score = _DINOV2_OUTPUT_CAP
            steps.append(f"cap{_DINOV2_OUTPUT_CAP:.2f}")

        # Step 2 — CNN-family dampening. When no independent module confirms,
        # CNN-family detectors (currently only DINOv2) are scaled down toward
        # cnn_dampening_floor. This applies AFTER the cap so the cap acts as a
        # ceiling and dampening can only reduce further, never re-inflate.
        if m.module_name in _CNN_FAMILY_DETECTORS and cnn_dampening < 1.0:
            score *= cnn_dampening
            steps.append(f"x{cnn_dampening:.2f}")

        if steps:
            _core_details[m.module_name] = (
                f"{raw:.4f}→{'→'.join(steps)}={score:.4f} w={w}"
            )
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

    # Count independent detectors (organika, pixel) that STRONGLY confirm.
    # CRITICAL: this threshold gates the moderate boost, so it must be high
    # enough to prevent a single FP detector + a barely-elevated independent
    # from triggering an undeserved 65% boost. Use a stricter cutoff than the
    # general independent_confirm threshold.
    strong_independent_confirms = sum(
        1 for name in _INDEPENDENT_DETECTORS
        if reliable_scores.get(name, 0) >= 0.40
    )
    # Legacy weak threshold (0.25) — used by other boost paths only.
    independent_confirms = sum(
        1 for name in _INDEPENDENT_DETECTORS
        if reliable_scores.get(name, 0) >= ft.independent_confirm
    )

    logger.info(
        "FUSION consensus: n_high=%d (cnn=%d→capped=1, non_cnn=%d) n_low=%d "
        "independent_confirms=%d strong_ind=%d (threshold=%.2f) reliable=%s",
        n_high, n_high_cnn, n_high_non_cnn, n_low, independent_confirms,
        strong_independent_confirms, ft.independent_confirm,
        {k: f"{v:.4f}" for k, v in reliable_scores.items()},
    )

    # Apply consensus boost (strongest matching tier wins).
    #
    # 2026-04-07 FIX: the moderate boost was firing on car damage authentic
    # photos because DINOv2 (CNN, FP-prone) alone produced n_high=1 and
    # pixel_forensics at 0.29 alone produced an independent confirmation —
    # giving authentic images a spurious 65%. Two stricter conditions now:
    #   1) require at least one NON-CNN high detector (organika/pixel/CLIP)
    #   2) require at least one STRONG (>=0.40) independent confirmation
    boost_applied = "none"
    if n_high >= ft.boost_strong_min_high and n_low <= 1 and independent_confirms >= 1:
        overall = max(overall, ft.boost_strong_floor)
        boost_applied = f"strong→{ft.boost_strong_floor}"
    elif (
        n_high >= ft.boost_moderate_min_high
        and n_high_non_cnn >= 1                # at least 1 non-CNN must agree
        and strong_independent_confirms >= 1   # at least 1 strong (>=0.40) confirm
    ):
        overall = max(overall, ft.boost_moderate_floor)
        boost_applied = f"moderate→{ft.boost_moderate_floor}"

    # Swin (ai_generation_detection) boost ONLY if independent detectors confirm
    if ai_gen and ai_gen.risk_score >= ft.swin_min and independent_confirms >= 1:
        overall = max(overall, ai_gen.risk_score)
        boost_applied = f"swin→{ai_gen.risk_score:.4f}"

    # High-confidence CLIP boost: when CLIP is very confident (>70%) AND
    # independent detectors confirm, boost aggressively.
    # CLIP 74% + Organika 39% + Pixel 33% = 3 detectors agree = strong AI signal.
    clip_m = _get_module(active, "clip_ai_detection")
    organika_m = _get_module(active, "organika_ai_detection")
    pixel_m = _get_module(active, "pixel_forensics")

    if clip_m and clip_m.risk_score >= 0.70:
        # Count strong confirmations (>= 0.30)
        strong_confirms = 0
        if organika_m and organika_m.risk_score >= 0.30:
            strong_confirms += 1
        if pixel_m and pixel_m.risk_score >= 0.30:
            strong_confirms += 1

        if strong_confirms >= 2:
            # CLIP HIGH + 2 strong confirms → very confident AI (90%)
            clip_floor = max(0.90, clip_m.risk_score)
            if clip_floor > overall:
                overall = clip_floor
                boost_applied = f"clip_high_2confirm→{clip_floor:.4f}"
        elif strong_confirms >= 1:
            # CLIP HIGH + 1 confirm → confident AI (85%)
            clip_floor = max(0.85, clip_m.risk_score)
            if clip_floor > overall:
                overall = clip_floor
                boost_applied = f"clip_high_1confirm→{clip_floor:.4f}"
        elif independent_confirms >= 1:
            # CLIP HIGH + weak confirm → use CLIP score directly
            clip_floor = clip_m.risk_score
            if clip_floor > overall:
                overall = clip_floor
                boost_applied = f"clip_high→{clip_floor:.4f}"

    # CLIP isolation dampening: when CLIP is moderate (50-70%) but ALL other
    # LIVE detectors disagree (n_low >= 3 of 4 remaining), CLIP is likely FP.
    # Car damage photos trigger CLIP FP because the domain is OOD for the
    # generic probe. Cap the score to prevent false "Potreban pregled".
    # With dead modules removed from _RELIABLE_AI_DETECTORS, n_low now only
    # counts modules that CAN detect modern AI (organika, dinov2, pixel, radet).
    # Threshold: n_low >= 3 means 3 of 4 non-CLIP live detectors say "no".
    if clip_m and 0.50 <= clip_m.risk_score < 0.70 and n_low >= 3:
        clip_isolated_cap = 0.20
        if overall > clip_isolated_cap:
            overall = clip_isolated_cap
            boost_applied = f"clip_isolated_cap→{clip_isolated_cap}"

    # ── Step 7: Supervised meta-learner ASYMMETRIC blend ─────────────
    #
    # If a trained meta-learner is loaded and meta_blend_factor > 0, blend
    # the meta score into the rule-based overall. ASYMMETRIC RULES:
    #
    #   1) Confident rule (overall <= 0.15 or >= 0.85):
    #      Trust the rule-based fusion. The meta cannot overturn it because
    #      the rule has produced an unambiguous verdict from multiple
    #      independent signals (e.g. CLIP HIGH boost firing on car4.webp,
    #      or all-zero scores on car5.jpg). The meta-learner's job is to
    #      help the AMBIGUOUS middle, not to second-guess clear cases.
    #
    #   2) Meta wants HIGHER score (meta > rule):
    #      Blend up. This catches the historical FNs where rule-based fusion
    #      under-scored AI images because the OLD pipeline gave them low
    #      module scores. The meta-learner learned the corrected mapping.
    #
    #   3) Meta wants LOWER score AND rule is in [0.15, 0.85]:
    #      Blend down. This catches the historical FPs where rule-based
    #      fusion over-scored authentic images due to OOD CLIP signal.
    #
    # Net effect: confident verdicts stay confident; ambiguous verdicts
    # get supervised correction; the meta cannot regress car4/car5/car6.
    if meta_score is not None and meta_blend_factor > 0.0:
        rule_score = overall
        # Confident rule-based verdict: never overrule with the meta.
        # 0.15 is the bottom of the "Low" risk band; 0.85 is "Critical".
        if rule_score <= 0.15 or rule_score >= 0.85:
            blend_path = "rule_confident_skip"
            blended = rule_score
        elif meta_score > rule_score:
            # Meta wants HIGHER → blend up (rescue historical FNs)
            blend_path = "blend_up"
            blended = (1.0 - meta_blend_factor) * rule_score + meta_blend_factor * meta_score
        else:
            # Meta wants LOWER and rule is in ambiguous middle → blend down
            # (rescue historical FPs)
            blend_path = "blend_down"
            blended = (1.0 - meta_blend_factor) * rule_score + meta_blend_factor * meta_score

        logger.info(
            "FUSION meta blend: rule=%.4f meta=%.4f factor=%.2f path=%s → %.4f",
            rule_score, meta_score, meta_blend_factor, blend_path, blended,
        )
        overall = blended
        boost_applied = f"{boost_applied}+meta_{blend_path}({meta_blend_factor:.2f})"

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
