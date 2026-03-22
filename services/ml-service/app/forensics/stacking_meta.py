"""Stacking meta-learner for forensic module score fusion.

Replaces hand-crafted override rules in fusion.py with a learned
logistic regression model that captures pairwise module interactions
(e.g., PRNU x AI, spectral x AI) automatically from labeled data.

Architecture:
  - Input: 14 modules → (risk_score, avg_confidence, num_findings_norm) each
  - Feature engineering: 42 base + 91 pairwise interactions + 14 squared = 147 features
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

# Canonical module ordering — must match DEFAULT_WEIGHTS order in fusion.py.
# The training script saves this list into .npz for validation.
MODULE_ORDER: list[str] = [
    "ai_generation_detection",
    "clip_ai_detection",
    "vae_reconstruction",
    "prnu_detection",
    "deep_modification_detection",
    "spectral_forensics",
    "metadata_analysis",
    "modification_detection",
    "semantic_forensics",
    "optical_forensics",
    "document_forensics",
    "office_forensics",
    "text_ai_detection",
    "content_validation",
]

N_MODULES = len(MODULE_ORDER)
N_BASE = N_MODULES * 3  # risk, confidence, num_findings per module
N_INTERACTIONS = N_MODULES * (N_MODULES - 1) // 2  # C(14,2) = 91
N_SQUARED = N_MODULES
N_FEATURES = N_BASE + N_INTERACTIONS + N_SQUARED  # 42 + 91 + 14 = 147


def feature_names() -> list[str]:
    """Return the 147 feature names (useful for interpretability)."""
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
    """Extract the 147-dim feature vector from module results.

    Missing or errored modules contribute zeros (= no signal).
    """
    # Build lookup
    mod_lookup: dict[str, ModuleResult] = {}
    for m in modules:
        if not m.error:
            mod_lookup[m.module_name] = m

    # Base features: (risk_score, avg_confidence, num_findings_norm) x 14
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
    """Stacking meta-learner with lazy weight loading."""

    def __init__(self, weights_path: str = ""):
        self._weights_path = weights_path
        self._weights: np.ndarray | None = None
        self._bias: float = 0.0
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
        logit = float(features @ self._weights + self._bias)
        # Numerically stable sigmoid
        score = 1.0 / (1.0 + np.exp(-np.clip(logit, -500, 500)))
        return score

    def _try_load(self) -> None:
        """Attempt to load weights from .npz file."""
        self._load_attempted = True

        path = self._resolve_path()
        if not path or not os.path.isfile(path):
            logger.debug("No stacking meta weights at %s", path)
            return

        try:
            data = np.load(path, allow_pickle=True)
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
        self._loaded = True
        logger.info(
            "Loaded stacking meta weights from %s (%d features)",
            path,
            len(self._weights),
        )

    def _resolve_path(self) -> str:
        """Resolve the weights file path."""
        if self._weights_path:
            return self._weights_path

        # Check env var
        env_path = os.environ.get("DENT_FORENSICS_STACKING_META_WEIGHTS", "")
        if env_path:
            return env_path

        # Default: model_cache_dir/stacking_meta/meta_weights.npz
        cache_dir = os.environ.get(
            "DENT_FORENSICS_MODEL_CACHE_DIR", "/app/models"
        )
        return os.path.join(cache_dir, "stacking_meta", "meta_weights.npz")


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
