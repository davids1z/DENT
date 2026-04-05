"""Centralized threshold registry for DENT forensic analysis.

All hardcoded thresholds are gathered here so they can be overridden
by GHOST calibration (or manual tuning) without touching analyzer code.

Without a calibration file, every threshold matches the original
hardcoded value — zero behavioral change.
"""

import json
import logging
import os
from dataclasses import dataclass, field, fields

logger = logging.getLogger(__name__)


# ── Tier 1: Verdict & enforcement thresholds ─────────────────────────


@dataclass
class VerdictThresholds:
    """Thresholds used by _compute_deterministic_verdict() in analyze.py."""

    forged_risk: float = 0.85
    forged_min_findings: int = 5
    suspicious_risk: float = 0.40
    suspicious_min_findings: int = 3
    urgency_critical: float = 0.85
    urgency_high: float = 0.40
    urgency_medium: float = 0.15


@dataclass
class EnforcementThresholds:
    """Thresholds used by _enforce_forensic_severity() in analyze.py."""

    # Normal mode
    critical: float = 0.65
    high: float = 0.40
    medium: float = 0.20
    # Upload mode (stricter)
    upload_critical: float = 0.50
    upload_high: float = 0.30
    upload_medium: float = 0.12
    # AI detector override
    ai_detector_override: float = 0.45


# ── Tier 2: Module damage thresholds ─────────────────────────────────


@dataclass
class ModuleDamageThreshold:
    """Per-module threshold for emitting a mandatory finding."""

    threshold: float
    upload_offset: float = 0.10


# ── Fusion thresholds ────────────────────────────────────────────────


@dataclass
class FusionThresholds:
    """Thresholds used in fuse_scores() for override rules."""

    # ── CNN dampening ──────────────────────────────────────────────
    # When independent methods (SAFE/CommFor/SPAI) don't confirm CNN-family
    # detectors (DINOv2/EfficientNet/bfree/CLIP), dampen CNN contributions.
    # Floor: minimum dampening factor (0.30 = CNN contributes at least 30%).
    # Threshold: independent score above which dampening is disabled.
    # SAFE=0.20 on authentic photos should NOT disable dampening.
    cnn_dampening_floor: float = 0.30
    cnn_dampening_threshold: float = 0.35

    # ── Tampering thresholds ───────────────────────────────────────
    deep_mod_min: float = 0.55
    mesorch_min: float = 0.40
    ela_min: float = 0.50
    ela_scale: float = 0.80
    single_tamp_min: float = 0.50
    single_tamp_scale: float = 0.85

    # ── Document signals ───────────────────────────────────────────
    text_ai_min: float = 0.50
    content_val_min: float = 0.40

    # ── Consensus boost ────────────────────────────────────────────
    # detector_high: score threshold for a detector to count as "high"
    # detector_low: score below which a detector counts as "low" (disagreeing)
    # independent_confirm: score for an independent detector to confirm
    detector_high: float = 0.45
    detector_low: float = 0.15
    independent_confirm: float = 0.25
    # Strong boost: 3+ reliable high AND 1+ independent (SAFE/CommFor/SPAI)
    boost_strong_min_high: int = 3
    boost_strong_floor: float = 0.75
    # Moderate boost: 1+ high AND 2+ independent confirms
    boost_moderate_min_high: int = 1
    boost_moderate_floor: float = 0.75
    # Swin (ai_gen) boost: requires 2+ independent confirmation
    swin_min: float = 0.60

    # ── Context modifiers ──────────────────────────────────────────
    c2pa_factor: float = 0.50
    ai_metadata_floor: float = 0.90

    # ── Verdict bar reconciliation ─────────────────────────────────
    verdict_low_threshold: float = 0.15
    verdict_mid_threshold: float = 0.30
    verdict_high_threshold: float = 0.65

    # ── Risk level boundaries (fusion.py _risk_level) ──────────────
    # Medium raised from 0.15 to 0.20 so CNN-dampened scores (16-19%)
    # on authentic car photos stay Low instead of triggering "Potreban pregled"
    risk_critical: float = 0.85
    risk_high: float = 0.40
    risk_medium: float = 0.20


# ── Risk level boundaries (base.py _risk_level — per-module) ────────


@dataclass
class BaseRiskThresholds:
    """Per-module risk level boundaries in BaseAnalyzer._risk_level()."""

    critical: float = 0.75
    high: float = 0.50
    medium: float = 0.25


# ── Registry ─────────────────────────────────────────────────────────


# Default module damage thresholds (matching _MODULE_DAMAGE_MAP in analyze.py)
_DEFAULT_MODULE_DAMAGE: dict[str, float] = {
    "ai_generation_detection": 0.50,
    "clip_ai_detection": 0.45,
    "prnu_detection": 0.45,
    "vae_reconstruction": 0.45,
    "spectral_forensics": 0.45,
    "deep_modification_detection": 0.50,
    "modification_detection": 0.45,
    "metadata_analysis": 0.45,
    "semantic_forensics": 0.50,
    "optical_forensics": 0.50,
    "text_ai_detection": 0.45,
    "content_validation": 0.40,
}


@dataclass
class ThresholdRegistry:
    """Central registry for all calibratable thresholds."""

    verdict: VerdictThresholds = field(default_factory=VerdictThresholds)
    enforcement: EnforcementThresholds = field(default_factory=EnforcementThresholds)
    fusion: FusionThresholds = field(default_factory=FusionThresholds)
    base_risk: BaseRiskThresholds = field(default_factory=BaseRiskThresholds)
    module_damage: dict[str, ModuleDamageThreshold] = field(default_factory=dict)
    calibration_source: str = "defaults"

    def __post_init__(self):
        if not self.module_damage:
            self.module_damage = {
                name: ModuleDamageThreshold(threshold=val)
                for name, val in _DEFAULT_MODULE_DAMAGE.items()
            }


# ── Singleton ────────────────────────────────────────────────────────

_registry: ThresholdRegistry | None = None


def get_registry(calibration_file: str = "") -> ThresholdRegistry:
    """Return the singleton ThresholdRegistry.

    On first call, tries to load calibrated thresholds from:
      1. ``calibration_file`` argument (if non-empty)
      2. ``DENT_CALIBRATION_FILE`` env var
      3. ``/app/config/calibrated_thresholds.json`` (default Docker path)

    Missing or invalid files are silently ignored — defaults are used.
    """
    global _registry
    if _registry is not None:
        return _registry

    _registry = ThresholdRegistry()
    _try_load_calibration(_registry, calibration_file)
    return _registry


def reset_registry() -> None:
    """Reset the singleton (for testing)."""
    global _registry
    _registry = None


def _try_load_calibration(reg: ThresholdRegistry, explicit_path: str) -> None:
    """Attempt to load calibrated thresholds from a JSON file.

    Only keys present in the JSON are overwritten; everything else
    keeps its default value.
    """
    path = (
        explicit_path
        or os.environ.get("DENT_CALIBRATION_FILE", "")
        or "/app/config/calibrated_thresholds.json"
    )

    if not os.path.isfile(path):
        logger.debug("No calibration file at %s — using defaults", path)
        return

    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read calibration file %s: %s", path, exc)
        return

    reg.calibration_source = f"calibrated:{path}"
    logger.info("Loading calibrated thresholds from %s", path)

    # Verdict
    if "verdict" in data:
        _apply_overrides(reg.verdict, data["verdict"])

    # Enforcement
    if "enforcement" in data:
        _apply_overrides(reg.enforcement, data["enforcement"])

    # Fusion
    if "fusion" in data:
        _apply_overrides(reg.fusion, data["fusion"])

    # Base risk
    if "base_risk" in data:
        _apply_overrides(reg.base_risk, data["base_risk"])

    # Module damage (flat dict: module_name → threshold float)
    if "module_damage" in data:
        for mod_name, val in data["module_damage"].items():
            if mod_name in reg.module_damage:
                reg.module_damage[mod_name].threshold = float(val)
            else:
                reg.module_damage[mod_name] = ModuleDamageThreshold(
                    threshold=float(val)
                )


def _apply_overrides(target, overrides: dict) -> None:
    """Apply only known fields from *overrides* onto *target* dataclass."""
    known = {f.name for f in fields(target)}
    for key, val in overrides.items():
        if key in known:
            setattr(target, key, type(getattr(target, key))(val))
        else:
            logger.warning("Unknown calibration key %r — skipping", key)
