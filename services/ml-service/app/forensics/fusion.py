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
}

# Core AI detection modules — only these determine AI generation score
_CORE_AI_WEIGHTS = {
    "ai_generation_detection": 0.50,
    "clip_ai_detection": 0.25,
    "vae_reconstruction": 0.25,
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


def fuse_scores(modules: list[ModuleResult]) -> tuple[float, int, RiskLevel]:
    """
    Core-only score fusion with context modifiers.

    Returns (overall_float, overall_100, risk_level).

    Architecture:
    1. Core AI score from 3 dedicated detectors (Swin, CLIP, VAE)
    2. Context modifiers from metadata/PRNU findings (amplify or dampen)
    3. Tampering score from modification detectors (separate from AI)
    4. Final risk = max(core_score, tampering_score)
    5. Cross-validation: 2+ AI core detectors >= 0.60 → floor 0.85
    """
    active = [m for m in modules if not m.error]

    if not active:
        return 0.0, 0, RiskLevel.LOW

    # ── Stacking meta-learner (replaces everything when trained) ──────
    try:
        from ..config import settings as _settings
        meta_enabled = _settings.forensics_stacking_meta_enabled
    except Exception:
        meta_enabled = False

    if meta_enabled:
        meta_learner = get_meta_learner()
        meta_score = meta_learner.predict(modules)
        if meta_score is not None:
            overall = max(0.0, min(1.0, meta_score))
            return overall, round(overall * 100), _risk_level(overall)

    # ── Step 1: Core AI score (only dedicated AI detectors) ───────────
    core_weighted = 0.0
    core_total_w = 0.0
    for m in active:
        if m.module_name in _CORE_AI_WEIGHTS:
            w = _CORE_AI_WEIGHTS[m.module_name]
            core_weighted += m.risk_score * w
            core_total_w += w
    core_score = core_weighted / core_total_w if core_total_w > 0 else 0.0

    # ── Step 2: Context modifiers from metadata + PRNU findings ───────
    meta = _get_module(active, "metadata_analysis")
    prnu = _get_module(active, "prnu_detection")

    # Positive authenticity signals → reduce AI risk
    has_authentic_sensor = prnu is not None and any(
        f.code == "PRNU_AUTHENTIC_SENSOR" for f in prnu.findings
    )
    has_c2pa_valid = meta is not None and any(
        f.code == "META_C2PA_VALID" for f in meta.findings
    )

    # Negative signals → increase AI risk
    has_ai_tool = meta is not None and any(
        f.code in ("META_XMP_AI_TOOL_HISTORY", "META_C2PA_AI_GENERATED")
        for f in meta.findings
    )

    if has_authentic_sensor or has_c2pa_valid:
        core_score *= 0.50  # Strong camera/provenance evidence halves AI risk

    if has_ai_tool:
        core_score = max(core_score, 0.80)  # AI tool in metadata = strong signal

    # ── Step 3: Tampering score (separate from AI generation) ─────────
    deep_mod = _get_module(active, "deep_modification_detection")
    mod_det = _get_module(active, "modification_detection")
    tampering = max(
        deep_mod.risk_score if deep_mod else 0.0,
        (mod_det.risk_score * 0.70) if mod_det else 0.0,
    )

    # ── Step 4: Text AI detection (for documents) ─────────────────────
    text_ai = _get_module(active, "text_ai_detection")
    text_ai_score = text_ai.risk_score if text_ai and text_ai.risk_score >= 0.50 else 0.0

    # Content validation (OIB/IBAN forgery)
    content_val = _get_module(active, "content_validation")
    content_score = content_val.risk_score if content_val and content_val.risk_score >= 0.40 else 0.0

    # ── Step 5: Final risk = max of all signal channels ───────────────
    overall = max(core_score, tampering, text_ai_score, content_score)

    # ── Step 6: Cross-validation floor ────────────────────────────────
    # When 2+ core AI detectors independently agree at >= 0.60,
    # this is very strong evidence — enforce a minimum floor.
    high_ai_count = sum(
        1 for m in active
        if m.module_name in _CORE_AI_WEIGHTS and m.risk_score >= 0.60
    )
    if high_ai_count >= 2:
        overall = max(overall, 0.85)

    overall = max(0.0, min(1.0, overall))
    return overall, round(overall * 100), _risk_level(overall)
