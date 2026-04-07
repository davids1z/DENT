"""Tests for score fusion logic.

Verifies that the rule-based fusion correctly combines module scores
into an overall risk assessment.

Updated for v4 config: only CLIP, bfree, Organika, DINOv2, pixel_forensics
are active in core weights. SAFE, SPAI, RINE, CommFor, EfficientNet disabled.
"""
import pytest

from app.forensics.base import AnalyzerFinding, ModuleResult, RiskLevel
from app.forensics.fusion import _CORE_AI_WEIGHTS, fuse_scores


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_module(name: str, risk: float, findings: list | None = None) -> ModuleResult:
    """Create a ModuleResult with given risk score."""
    f = findings or []
    if risk > 0 and not f:
        f = [AnalyzerFinding(
            code=f"{name.upper()}_TEST",
            title="Test finding",
            description="Test",
            risk_score=risk,
            confidence=0.80,
        )]
    return ModuleResult(
        module_name=name,
        module_label=name,
        risk_score=risk,
        risk_score100=round(risk * 100),
        risk_level=RiskLevel.LOW if risk < 0.25 else RiskLevel.MEDIUM,
        findings=f,
    )


# ---------------------------------------------------------------------------
# Core AI weights sanity
# ---------------------------------------------------------------------------

def test_core_ai_weights_sum_to_one():
    total = sum(_CORE_AI_WEIGHTS.values())
    assert abs(total - 1.0) < 0.01, f"Core AI weights sum to {total}, expected ~1.0"


def test_core_ai_weights_include_clip():
    assert "clip_ai_detection" in _CORE_AI_WEIGHTS


def test_core_ai_weights_include_pixel_forensics():
    assert "pixel_forensics" in _CORE_AI_WEIGHTS


def test_core_ai_weights_include_organika():
    assert "organika_ai_detection" in _CORE_AI_WEIGHTS


# ---------------------------------------------------------------------------
# Zero signals → Low risk
# ---------------------------------------------------------------------------

def test_all_zero_scores():
    modules = [
        _make_module("clip_ai_detection", 0.0),
        _make_module("bfree_detection", 0.0),
        _make_module("organika_ai_detection", 0.0),
        _make_module("dinov2_ai_detection", 0.0),
        _make_module("pixel_forensics", 0.0),
        _make_module("metadata_analysis", 0.0),
    ]
    overall, score100, level, _ = fuse_scores(modules)
    assert overall < 0.10
    assert level == RiskLevel.LOW


def test_empty_modules():
    overall, score100, level, _ = fuse_scores([])
    assert overall == 0.0
    assert level == RiskLevel.LOW


# ---------------------------------------------------------------------------
# Strong AI signal — CLIP + bfree + Organika high → High risk
# ---------------------------------------------------------------------------

def test_strong_ai_signal():
    """CLIP=74%, bfree=98%, Organika=39%, pixel=33% → should be high."""
    modules = [
        _make_module("clip_ai_detection", 0.74),
        _make_module("bfree_detection", 0.98),
        _make_module("organika_ai_detection", 0.39),
        _make_module("dinov2_ai_detection", 0.27),
        _make_module("pixel_forensics", 0.33),
    ]
    overall, _, level, _ = fuse_scores(modules)
    assert overall >= 0.50, f"Strong AI signal should be >= 0.50, got {overall}"
    assert level in (RiskLevel.HIGH, RiskLevel.CRITICAL)


def test_consensus_boost_clip_bfree_high():
    """CLIP + bfree both high + independent confirms → boost to 0.65."""
    modules = [
        _make_module("clip_ai_detection", 0.80),
        _make_module("bfree_detection", 0.90),
        _make_module("organika_ai_detection", 0.40),  # independent confirm
        _make_module("pixel_forensics", 0.30),          # independent confirm
        _make_module("dinov2_ai_detection", 0.30),
    ]
    overall, _, _, _ = fuse_scores(modules)
    assert overall >= 0.65, f"CLIP+bfree high + independent should reach 0.65, got {overall}"


# ---------------------------------------------------------------------------
# Authentic image: DINOv2 false positive dampened
# ---------------------------------------------------------------------------

def test_dinov2_fp_dampened():
    """DINOv2=58% on authentic but no independent confirms → dampened."""
    modules = [
        _make_module("clip_ai_detection", 0.13),
        _make_module("bfree_detection", 0.003),
        _make_module("organika_ai_detection", 0.0),
        _make_module("dinov2_ai_detection", 0.58),
        _make_module("pixel_forensics", 0.22),
    ]
    overall, _, level, _ = fuse_scores(modules)
    assert overall < 0.20, f"DINOv2 FP should be dampened to < 0.20, got {overall}"
    assert level == RiskLevel.LOW


def test_cnn_only_no_boost():
    """Only DINOv2 high (CNN-family), no independent confirm → no boost."""
    modules = [
        _make_module("clip_ai_detection", 0.10),
        _make_module("bfree_detection", 0.01),
        _make_module("organika_ai_detection", 0.05),
        _make_module("dinov2_ai_detection", 0.90),
        _make_module("pixel_forensics", 0.10),
    ]
    overall, _, _, _ = fuse_scores(modules)
    assert overall < 0.30, f"DINOv2-only high should be dampened, got {overall}"


def test_dinov2_extreme_fp_dampened_without_independent_confirm():
    """DINOv2 raw 0.95 with NO independent confirmations must be dampened.

    Sprint 1 (2026-04-07) removed the hard 0.50 cap because the v11 probe
    no longer false-positives on the car damage class that motivated it
    (car5/car6 now score 0.0005). The defense layer is now CNN-family
    dampening alone: when no independent module crosses the threshold,
    DINOv2 is scaled down toward `cnn_dampening_floor`.

    Bound was tightened from 0.10 → 0.25 to reflect the new math:
        DINOv2 0.95 × dampening (~0.50) × weight 0.20 = ~0.095 contribution
        plus pixel 0.10 × 0.10 = 0.010 and clip 0.05 × 0.20 = 0.010
        normalized over total weight ~0.75 → ~0.15 overall
    Still well below the 0.40 "Povišen" threshold and the 0.65 "high" band,
    so no boost paths fire and no high-risk verdict can result.
    """
    modules = [
        _make_module("clip_ai_detection", 0.05),
        _make_module("organika_ai_detection", 0.00),
        _make_module("pixel_forensics", 0.10),
        _make_module("dinov2_ai_detection", 0.95),  # extreme FP, dampening kicks in
    ]
    overall, _, level, _ = fuse_scores(modules)
    assert overall < 0.25, (
        f"DINOv2 extreme FP should be dampened to < 0.25; got {overall}"
    )
    # Critical safety property: no high-risk verdict from DINOv2 alone
    assert level == RiskLevel.LOW, (
        f"DINOv2 alone must not produce high-risk verdict; got {level.name}"
    )


def test_car5_authentic_dinov2_fp_with_pixel_borderline():
    """REGRESSION (2026-04-07): car5.jpg authentic produced 65% because:
        DINOv2 = 0.67 (FP, only "high" detector, CNN-family)
        Pixel  = 0.29 (just above independent_confirm threshold of 0.25)
        → moderate boost fired and pushed overall to 0.65.

    Fix: moderate boost now requires (a) at least one NON-CNN high detector
    and (b) at least one strong (>=0.40) independent confirmation. Neither
    holds here, so the boost must NOT fire.
    """
    modules = [
        _make_module("clip_ai_detection", 0.08),
        _make_module("organika_ai_detection", 0.00),
        _make_module("pixel_forensics", 0.29),
        _make_module("dinov2_ai_detection", 0.67),
        _make_module("modification_detection", 0.15),
        _make_module("metadata_analysis", 0.10),
        _make_module("safe_ai_detection", 0.03),
        _make_module("bfree_detection", 0.00),
    ]
    overall, score100, level, _ = fuse_scores(modules)
    assert overall < 0.30, (
        f"car5.jpg authentic should NOT trigger moderate boost; got {overall} (was 0.65)"
    )
    assert level in (RiskLevel.LOW, RiskLevel.MEDIUM)


def test_moderate_boost_still_fires_when_legitimate():
    """Moderate boost MUST still fire when there is genuine consensus:
    e.g. CLIP high + Organika strong + Pixel strong = real AI signal.
    """
    modules = [
        _make_module("clip_ai_detection", 0.55),       # non-CNN high
        _make_module("organika_ai_detection", 0.50),   # strong independent
        _make_module("pixel_forensics", 0.45),         # strong independent
        _make_module("dinov2_ai_detection", 0.30),
    ]
    overall, _, _, _ = fuse_scores(modules)
    assert overall >= 0.60, (
        f"Genuine multi-detector AI signal should trigger boost; got {overall}"
    )


# ---------------------------------------------------------------------------
# Metadata AI tool → definitive signal
# ---------------------------------------------------------------------------

def test_metadata_ai_tool_overrides():
    """AI tool in metadata (XMP/C2PA) should push overall to >= 0.90."""
    modules = [
        _make_module("clip_ai_detection", 0.0),
        _make_module("metadata_analysis", 0.0, findings=[
            AnalyzerFinding(
                code="META_XMP_AI_TOOL_HISTORY",
                title="AI tool found",
                description="XMP CreatorTool indicates AI generation",
                risk_score=0.0,
                confidence=0.95,
                evidence={"tool": "Midjourney"},
            ),
        ]),
    ]
    overall, _, _, _ = fuse_scores(modules)
    assert overall >= 0.90, f"AI metadata should force >= 0.90, got {overall}"


# ---------------------------------------------------------------------------
# Tampering: single strong signal vs 2+ signals
# ---------------------------------------------------------------------------

def test_single_mesorch_strong():
    """Single Mesorch=0.70 is 'very strong' so it should contribute."""
    modules = [
        _make_module("mesorch_detection", 0.70),
        _make_module("modification_detection", 0.0),
        _make_module("deep_modification_detection", 0.0),
    ]
    overall, _, _, _ = fuse_scores(modules)
    assert overall > 0.0, "Strong single tampering signal should contribute"


def test_two_tampering_signals():
    """Two tampering signals should give higher confidence."""
    modules = [
        _make_module("mesorch_detection", 0.65),
        _make_module("deep_modification_detection", 0.60),
        _make_module("modification_detection", 0.0),
    ]
    overall, _, _, _ = fuse_scores(modules)
    assert overall >= 0.60, f"Two tampering signals should give >= 0.60, got {overall}"


# ---------------------------------------------------------------------------
# Edge cases and isolation
# ---------------------------------------------------------------------------

def test_single_detector_moderate():
    """Single CLIP=0.60 alone → moderate, not high."""
    modules = [
        _make_module("clip_ai_detection", 0.60),
        _make_module("bfree_detection", 0.0),
        _make_module("organika_ai_detection", 0.0),
        _make_module("dinov2_ai_detection", 0.0),
        _make_module("pixel_forensics", 0.0),
    ]
    overall, _, _, _ = fuse_scores(modules)
    assert overall < 0.40, f"Single detector shouldn't reach 0.40, got {overall}"


def test_organika_only_moderate():
    """Only Organika=0.90 → moderate boost fires (Organika is both high AND independent)."""
    modules = [
        _make_module("clip_ai_detection", 0.0),
        _make_module("organika_ai_detection", 0.90),
        _make_module("dinov2_ai_detection", 0.0),
        _make_module("pixel_forensics", 0.0),
    ]
    overall, _, _, _ = fuse_scores(modules)
    # With fusion v4: Organika 0.90 counts as both n_high=1 and independent_confirm=1
    # → moderate boost fires → floor 0.65
    assert 0.50 < overall < 0.80, f"Organika high expected moderate boost 0.50-0.80, got {overall}"


# ---------------------------------------------------------------------------
# Errored modules should not contribute
# ---------------------------------------------------------------------------

def test_errored_modules_ignored():
    errored = ModuleResult(
        module_name="clip_ai_detection",
        module_label="CLIP",
        risk_score=0.99,
        risk_level=RiskLevel.CRITICAL,
        error="Model load failed",
    )
    modules = [errored, _make_module("bfree_detection", 0.0)]
    overall, _, _, _ = fuse_scores(modules)
    assert overall < 0.10, "Errored module should be excluded from fusion"


# ---------------------------------------------------------------------------
# Disabled modules (EfficientNet, SAFE, etc.) don't affect core fusion
# ---------------------------------------------------------------------------

def test_disabled_modules_dont_affect_core():
    """EfficientNet=98%, SAFE=20% on authentic → should NOT affect overall
    because they're not in _CORE_AI_WEIGHTS."""
    modules = [
        _make_module("clip_ai_detection", 0.13),
        _make_module("bfree_detection", 0.003),
        _make_module("organika_ai_detection", 0.0),
        _make_module("dinov2_ai_detection", 0.58),
        _make_module("pixel_forensics", 0.22),
        # Disabled modules with high scores
        _make_module("efficientnet_ai_detection", 0.98),
        _make_module("safe_ai_detection", 0.20),
        _make_module("spai_detection", 0.0),
    ]
    overall, _, _, _ = fuse_scores(modules)
    assert overall < 0.20, f"Disabled modules shouldn't push score up, got {overall}"
