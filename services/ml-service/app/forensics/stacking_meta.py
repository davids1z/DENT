"""Stacking meta-learner for forensic module score fusion.

Replaces hand-crafted override rules in fusion.py with a learned
logistic regression model that captures pairwise module interactions
(e.g., PRNU x AI, spectral x AI) automatically from labeled data.

Architecture:
  - Input: 22 modules → (risk_score, avg_confidence, num_findings_norm) each
  - Feature engineering: 66 base + 231 pairwise interactions + 22 squared = 319 features
  - Model: Ridge-regularized logistic regression (numpy only)
  - Output: sigmoid probability in [0, 1]

Graceful degradation: If no trained weights exist, predict() returns
None, signaling the caller to use the fallback (weighted average +
override rules).
"""

import logging
import os

import numpy as np

from .base import ModuleResult

logger = logging.getLogger(__name__)

# Canonical module ordering — must include ALL pipeline modules (enabled or disabled).
# The training script saves this list into .npz for validation.
# Missing/disabled modules contribute zeros (= no signal) during feature extraction.
#
# IMPORTANT: Adding modules here changes N_MODULES/N_FEATURES, which invalidates
# existing GBM/LogReg weights. After changing, retrain with:
#   python -m scripts.train_meta_learner --model gbm
# 2026-04-07: SLIMMED from 30 → 15 modules. Removed all permanently disabled
# modules (radet/fatformer/aide/spai/npr/siglip/ai_source/efficientnet/community
# forensics — heuristic stubs or no checkpoints; vae_reconstruction/
# deep_modification — need GPU; semantic/optical/spectral_forensics — heuristic
# FP generators; ai_generation_detection — old Swin ensemble).
#
# Production reality: 11 image modules + 4 document modules = 15 modules.
# Feature space dropped from 522 → 165 features (~3x smaller), making the
# meta-learner trainable on the available calibration data.
MODULE_ORDER: list[str] = [
    # AI detection (active, ML-backed)
    "clip_ai_detection",            # CLIP ViT-L/14 + MLP probe v9 (F1=0.85)
    "dinov2_ai_detection",          # DINOv2-large + MLP probe v9 (F1=0.71, FP-biased)
    "organika_ai_detection",        # Organika Swin-T (98% reported accuracy)
    "pixel_forensics",              # 8 numpy pixel-level signals
    "safe_ai_detection",            # SAFE (KDD 2025), heavily JPEG-dampened
    "bfree_detection",              # B-Free (CVPR 2025), old checkpoint
    "rine_detection",               # RINE (ECCV 2024) CLIP intermediate
    # Tampering / sensor
    "modification_detection",       # ELA + heuristics
    "mesorch_detection",            # Mesorch (AAAI 2025)
    "prnu_detection",               # PRNU sensor fingerprint (+ EXIF baseline)
    # Always-on heuristic
    "metadata_analysis",            # EXIF/metadata anomalies
    # Document modules (only fire on PDFs/Office docs)
    "document_forensics",
    "office_forensics",
    "text_ai_detection",
    "content_validation",
]

N_MODULES = len(MODULE_ORDER)  # 15 (down from 30 — pruned dead/disabled modules)
N_BASE = N_MODULES * 3  # risk, confidence, num_findings per module
N_INTERACTIONS = N_MODULES * (N_MODULES - 1) // 2  # pairwise interactions
N_SQUARED = N_MODULES
N_FEATURES = N_BASE + N_INTERACTIONS + N_SQUARED


def feature_names() -> list[str]:
    """Return the feature names (useful for interpretability)."""
    names: list[str] = []
    # Base features
    for mod in MODULE_ORDER:
        names.append(f"risk:{mod}")
        names.append(f"conf:{mod}")
        names.append(f"nfind:{mod}")
    # Pairwise interactions
    for i in range(N_MODULES):
        for j in range(i + 1, N_MODULES):
            names.append(f"risk_x:{MODULE_ORDER[i]}:{MODULE_ORDER[j]}")
    # Squared terms
    for mod in MODULE_ORDER:
        names.append(f"risk_sq:{mod}")
    return names


def extract_features(modules: list[ModuleResult]) -> np.ndarray:
    """Extract the feature vector from module results.

    Missing or errored modules contribute zeros (= no signal).
    """
    # Build lookup
    mod_lookup: dict[str, ModuleResult] = {}
    for m in modules:
        if not m.error:
            mod_lookup[m.module_name] = m

    # Base features: (risk_score, avg_confidence, num_findings_norm) x N_MODULES
    risk_scores = np.zeros(N_MODULES, dtype=np.float64)
    base = np.zeros(N_BASE, dtype=np.float64)

    for i, mod_name in enumerate(MODULE_ORDER):
        m = mod_lookup.get(mod_name)
        if m is None:
            continue

        risk = float(m.risk_score)
        risk_scores[i] = risk

        if m.findings:
            avg_conf = sum(f.confidence for f in m.findings) / len(m.findings)
            nfind_norm = min(len(m.findings), 10) / 10.0
        else:
            # Module ran but found nothing
            avg_conf = 0.0
            nfind_norm = 0.0

        idx = i * 3
        base[idx] = risk
        base[idx + 1] = avg_conf
        base[idx + 2] = nfind_norm

    # Pairwise interactions: risk_i * risk_j for all i < j
    interactions = np.zeros(N_INTERACTIONS, dtype=np.float64)
    k = 0
    for i in range(N_MODULES):
        for j in range(i + 1, N_MODULES):
            interactions[k] = risk_scores[i] * risk_scores[j]
            k += 1

    # Squared terms: risk_i^2
    squared = risk_scores ** 2

    return np.concatenate([base, interactions, squared])


class StackingMetaLearner:
    """Stacking meta-learner with lazy weight loading.

    Supports two model types:
      1. GradientBoosting (joblib pickle) — preferred, better F1
      2. LogisticRegression (numpy .npz) — fallback, numpy-only
    """

    def __init__(self, weights_path: str = ""):
        self._weights_path = weights_path
        # LogReg weights (fallback)
        self._weights: np.ndarray | None = None
        self._bias: float = 0.0
        self._weights_multi: np.ndarray | None = None
        self._bias_multi: np.ndarray | None = None
        # GBM models (preferred)
        self._gbm_binary = None
        self._gbm_multi = None
        self._loaded = False
        self._load_attempted = False

    def predict(self, modules: list[ModuleResult]) -> float | None:
        """Predict fused risk score from module results.

        Returns None if no trained weights are available (signals fallback).
        """
        if not self._loaded and not self._load_attempted:
            self._try_load()

        if not self._loaded:
            return None

        features = extract_features(modules)

        # GBM: predict_proba gives [p_authentic, p_manipulated]
        if self._gbm_binary is not None:
            proba = self._gbm_binary.predict_proba(features.reshape(1, -1))[0]
            return float(proba[1])  # p(manipulated)

        # LogReg fallback
        logit = float(features @ self._weights + self._bias)
        score = 1.0 / (1.0 + np.exp(-np.clip(logit, -500, 500)))
        return score

    def predict_proba(self, modules: list[ModuleResult]) -> dict[str, float] | None:
        """Predict 3-class probabilities (authentic, ai_generated, tampered).

        Returns dict like {"authentic": 0.65, "ai_generated": 0.25, "tampered": 0.10}
        or None if no weights loaded.
        """
        if not self._loaded and not self._load_attempted:
            self._try_load()

        if not self._loaded:
            return None

        features = extract_features(modules)

        # GBM: predict_proba gives [p_auth, p_ai, p_tamp]
        if self._gbm_multi is not None:
            proba = self._gbm_multi.predict_proba(features.reshape(1, -1))[0]
            return {
                "authentic": round(float(proba[0]), 4),
                "ai_generated": round(float(proba[1]), 4),
                "tampered": round(float(proba[2]), 4),
            }

        # LogReg: multinomial weights
        if self._weights_multi is not None and self._bias_multi is not None:
            logits = features @ self._weights_multi + self._bias_multi
            logits_shifted = logits - logits.max()
            exp_logits = np.exp(logits_shifted)
            probs = exp_logits / exp_logits.sum()
            return {
                "authentic": round(float(probs[0]), 4),
                "ai_generated": round(float(probs[1]), 4),
                "tampered": round(float(probs[2]), 4),
            }

        # Fallback: derive from binary score
        binary_score = float(features @ self._weights + self._bias)
        p_manip = 1.0 / (1.0 + np.exp(-np.clip(binary_score, -500, 500)))
        p_auth = 1.0 - p_manip
        return {
            "authentic": round(p_auth, 4),
            "ai_generated": round(p_manip * 0.6, 4),
            "tampered": round(p_manip * 0.4, 4),
        }

    def _try_load(self) -> None:
        """Attempt to load models. Tries GBM first, then LogReg .npz."""
        self._load_attempted = True

        base_dir = self._resolve_dir()

        # Try GBM (joblib pickle) first
        gbm_bin_path = os.path.join(base_dir, "gbm_binary.joblib")
        gbm_multi_path = os.path.join(base_dir, "gbm_multi.joblib")
        gbm_meta_path = os.path.join(base_dir, "gbm_meta.json")
        if os.path.isfile(gbm_bin_path) and os.path.isfile(gbm_multi_path):
            try:
                # Validate module order if metadata sidecar exists
                if os.path.isfile(gbm_meta_path):
                    import json
                    with open(gbm_meta_path) as f:
                        gbm_meta = json.load(f)
                    saved_order = gbm_meta.get("module_order", [])
                    if saved_order and saved_order != MODULE_ORDER:
                        logger.warning(
                            "GBM module_order MISMATCH: trained on %d modules, "
                            "current code has %d. Features are misaligned — "
                            "predictions will be wrong. Falling back to .npz.",
                            len(saved_order), len(MODULE_ORDER),
                        )
                        # Fall through to LogReg .npz which has its own validation
                    else:
                        import joblib
                        self._gbm_binary = joblib.load(gbm_bin_path)
                        self._gbm_multi = joblib.load(gbm_multi_path)
                        self._loaded = True
                        logger.info(
                            "Loaded GBM meta-learner from %s "
                            "(binary + 3-class, %d features, module_order OK)",
                            base_dir, gbm_meta.get("n_features", N_FEATURES),
                        )
                        return
                else:
                    # No metadata — load but warn
                    import joblib
                    self._gbm_binary = joblib.load(gbm_bin_path)
                    self._gbm_multi = joblib.load(gbm_multi_path)
                    self._loaded = True
                    logger.warning(
                        "Loaded GBM from %s WITHOUT module_order validation "
                        "(no gbm_meta.json). Re-train with updated script to "
                        "generate metadata sidecar.",
                        base_dir,
                    )
                    return
            except Exception as exc:
                logger.warning("Failed to load GBM models: %s, trying .npz", exc)

        # Fall back to LogReg .npz
        npz_path = self._resolve_path()
        if not npz_path or not os.path.isfile(npz_path):
            logger.debug("No stacking meta weights at %s", npz_path)
            return

        try:
            data = np.load(npz_path, allow_pickle=True)
        except Exception as exc:
            logger.warning("Failed to load stacking meta weights: %s", exc)
            return

        # Validate module order
        if "module_order" in data:
            saved_order = list(data["module_order"])
            if saved_order != MODULE_ORDER:
                logger.warning(
                    "Stacking meta weights incompatible: module_order mismatch "
                    "(saved %d modules vs current %d). Using fallback.",
                    len(saved_order),
                    len(MODULE_ORDER),
                )
                return

        weights = data.get("weights")
        bias = data.get("bias")

        if weights is None or bias is None:
            logger.warning("Stacking meta .npz missing 'weights' or 'bias'")
            return

        if len(weights) != N_FEATURES:
            logger.warning(
                "Stacking meta weights dimension mismatch: %d vs expected %d",
                len(weights),
                N_FEATURES,
            )
            return

        self._weights = weights.astype(np.float64)
        self._bias = float(bias.flat[0])

        # Load multinomial weights if available (3-class)
        if "weights_multi" in data and "bias_multi" in data:
            w_multi = data["weights_multi"]
            b_multi = data["bias_multi"]
            if w_multi.shape == (N_FEATURES, 3):
                self._weights_multi = w_multi.astype(np.float64)
                self._bias_multi = b_multi.astype(np.float64)
                logger.info("Loaded 3-class multinomial weights (%s)", w_multi.shape)

        self._loaded = True
        logger.info(
            "Loaded LogReg stacking meta from %s (%d features)",
            npz_path,
            len(self._weights),
        )

    def _resolve_dir(self) -> str:
        """Resolve the model directory."""
        cache_dir = os.environ.get(
            "DENT_FORENSICS_MODEL_CACHE_DIR", "/app/models"
        )
        return os.path.join(cache_dir, "stacking_meta")

    def _resolve_path(self) -> str:
        """Resolve the .npz weights file path."""
        if self._weights_path:
            return self._weights_path

        env_path = os.environ.get("DENT_FORENSICS_STACKING_META_WEIGHTS", "")
        if env_path:
            return env_path

        return os.path.join(self._resolve_dir(), "meta_weights.npz")


# ── Singleton ────────────────────────────────────────────────────────

_meta_learner: StackingMetaLearner | None = None


def get_meta_learner(weights_path: str = "") -> StackingMetaLearner:
    """Return the singleton StackingMetaLearner."""
    global _meta_learner
    if _meta_learner is None:
        _meta_learner = StackingMetaLearner(weights_path)
    elif weights_path and not _meta_learner._loaded and weights_path != _meta_learner._weights_path:
        # Path provided but singleton was created without it — retry
        _meta_learner._weights_path = weights_path
        _meta_learner._load_attempted = False
        _meta_learner._try_load()
    return _meta_learner


def reset_meta_learner() -> None:
    """Reset the singleton (for testing)."""
    global _meta_learner
    _meta_learner = None
