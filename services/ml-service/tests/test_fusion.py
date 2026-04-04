"""Tests for score fusion logic.

Verifies that the rule-based fusion correctly combines module scores
into an overall risk assessment.
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


def test_core_ai_weights_include_dinov2():
    assert "dinov2_ai_detection" in _CORE_AI_WEIGHTS


def test_core_ai_weights_include_safe():
    assert "safe_ai_detection" in _CORE_AI_WEIGHTS


# ---------------------------------------------------------------------------
# Zero signals → Low risk
# ---------------------------------------------------------------------------

def test_all_zero_scores():
    modules = [
        _make_module("safe_ai_detection", 0.0),
        _make_module("community_forensics_detection", 0.0),
        _make_module("clip_ai_detection", 0.0),
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
# Strong AI signal from multiple detectors → High risk
# ---------------------------------------------------------------------------

def test_strong_consensus_three_high():
    """3 detectors high with 2 independent confirms → floor 0.65+."""
    modules = [
        _make_module("safe_ai_detection", 0.80),       # Independent + high
        _make_module("community_forensics_detection", 0.60),  # Independent + high
        _make_module("dinov2_ai_detection", 0.70),     # high
        _make_module("clip_ai_detection", 0.0),
        _make_module("efficientnet_ai_detection", 0.0),
    ]
    overall, _, level, _ = fuse_scores(modules)
    # 3 high but 2 low → falls to rule 2 (2+high + independent confirms → 0.65)
    assert overall >= 0.65, f"Expected >= 0.65, got {overall}"
    assert level in (RiskLevel.HIGH, RiskLevel.CRITICAL)


def test_single_safe_moderate():
    """Only SAFE=0.60, others zero → moderate score (not high)."""
    modules = [
        _make_module("safe_ai_detection", 0.60),
        _make_module("community_forensics_detection", 0.0),
        _make_module("clip_ai_detection", 0.0),
        _make_module("dinov2_ai_detection", 0.0),
    ]
    overall, _, _, _ = fuse_scores(modules)
    # With only SAFE at 0.60 and weight 0.25, weighted = 0.15
    # No cross-validation boost (only 1 detector above 0.50)
    assert overall < 0.70, f"Single detector shouldn't reach 0.70, got {overall}"


# ---------------------------------------------------------------------------
# Metadata AI tool → definitive signal
# ---------------------------------------------------------------------------

def test_metadata_ai_tool_overrides():
    """AI tool in metadata (XMP/C2PA) should push overall to >= 0.90."""
    modules = [
        _make_module("safe_ai_detection", 0.0),
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
    # Single signal >= 0.65 → contributes at 0.85 factor
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
# Errored modules should not contribute
# ---------------------------------------------------------------------------

def test_safe_plus_swin_no_floor():
    """SAFE FP + Swin FP should NOT trigger cross-validation floor.
    Swin/NPR are unreliable and excluded from reliable detectors."""
    modules = [
        _make_module("safe_ai_detection", 0.55),
        _make_module("ai_generation_detection", 0.65),  # Swin — unreliable
        _make_module("npr_ai_detection", 0.55),          # NPR — unreliable
        _make_module("dinov2_ai_detection", 0.02),        # DINOv2 disagrees → not AI
        _make_module("clip_ai_detection", 0.0),
        _make_module("community_forensics_detection", 0.0),
    ]
    overall, _, _, _ = fuse_scores(modules)
    assert overall < 0.70, f"SAFE+Swin+NPR without DINOv2 should NOT reach 0.70, got {overall}"


def test_moderate_consensus_with_independent():
    """2 high + strict independent (CommFor) confirms → floor 0.65."""
    modules = [
        _make_module("efficientnet_ai_detection", 0.95),
        _make_module("dinov2_ai_detection", 0.90),
        _make_module("clip_ai_detection", 0.49),
        _make_module("safe_ai_detection", 0.04),
        _make_module("community_forensics_detection", 0.35),  # Strict independent confirms
    ]
    overall, _, _, _ = fuse_scores(modules)
    assert overall >= 0.65, f"2 high + CommFor independent confirm should reach 0.65, got {overall}"


def test_cnn_only_no_boost():
    """CNN-family (Eff+DINOv2) high but no independent confirms → dampened.
    CLIP is now independent (insurance-domain probe), so this test uses
    low CLIP to simulate pure CNN false positive without CLIP confirmation."""
    modules = [
        _make_module("efficientnet_ai_detection", 0.98),
        _make_module("dinov2_ai_detection", 0.79),
        _make_module("clip_ai_detection", 0.10),        # Insurance probe says NOT AI
        _make_module("safe_ai_detection", 0.04),         # Low — no pixel artifacts
        _make_module("community_forensics_detection", 0.01),  # Low
        _make_module("spai_detection", 0.05),            # Low
    ]
    overall, _, _, _ = fuse_scores(modules)
    assert overall < 0.50, f"CNN-only FP (no independent) should be < 0.50, got {overall}"


def test_single_detector_no_floor():
    """Single detector alone should NOT trigger floor — needs 2+."""
    modules = [
        _make_module("safe_ai_detection", 0.30),
        _make_module("dinov2_ai_detection", 0.90),
        _make_module("community_forensics_detection", 0.0),
        _make_module("clip_ai_detection", 0.0),
    ]
    overall, _, _, _ = fuse_scores(modules)
    assert overall < 0.70, f"Single detector should NOT reach 0.70, got {overall}"


def test_disagreement_no_boost():
    """CNN-family high but SAFE/CommFor/CLIP near-zero → disagreement, no boost."""
    modules = [
        _make_module("efficientnet_ai_detection", 1.00),
        _make_module("dinov2_ai_detection", 0.90),
        _make_module("safe_ai_detection", 0.01),
        _make_module("community_forensics_detection", 0.001),
        _make_module("clip_ai_detection", 0.00),
    ]
    overall, _, level, _ = fuse_scores(modules)
    # CNN scores dampened + no consensus boost (SAFE/CommFor/CLIP all < 0.30)
    assert overall < 0.15, f"CNN-only disagreement should be LOW risk, got {overall}"


# ---------------------------------------------------------------------------
# Errored modules should not contribute
# ---------------------------------------------------------------------------

def test_errored_modules_ignored():
    errored = ModuleResult(
        module_name="safe_ai_detection",
        module_label="SAFE",
        risk_score=0.99,
        risk_level=RiskLevel.CRITICAL,
        error="Model load failed",
    )
    modules = [errored, _make_module("clip_ai_detection", 0.0)]
    overall, _, _, _ = fuse_scores(modules)
    assert overall < 0.10, "Errored module should be excluded from fusion"
