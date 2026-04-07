#!/usr/bin/env python3
"""Generate calibrated meta-learner weights for the slimmed 15-module MODULE_ORDER.

Production reality:
  - Only 4 of the 15 modules produce useful AI signal (CLIP, Organika, Pixel, DINOv2)
  - The other 11 modules either return ~0 (RINE/B-Free/SAFE/Mesorch/PRNU on JPEG)
    or are heuristic with marginal value (modification_detection, metadata_analysis)
  - We have ~14K labeled images but no easy way to run the full pipeline on each
  - The fusion.py rule-based logic OVERRIDES verdict_probs anyway

Strategy: hand-craft logistic-regression weights from prior knowledge of module
F1 scores. This silences the "module_order mismatch" warning in production logs
and gives the meta-learner a sane fallback that mostly agrees with the rule-based
fusion. A proper supervised retrain can come later when we have a JSONL dataset
of labeled images run through the full pipeline.

Output: services/ml-service/models/stacking_meta/meta_weights.npz
        services/ml-service/models/meta/meta_weights.npz
"""
import os
import sys
import numpy as np

# Make app module importable
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from app.forensics.stacking_meta import (  # noqa: E402
    MODULE_ORDER,
    N_MODULES,
    N_FEATURES,
    feature_names,
)

# Per-module risk-score weights for the BINARY (manipulated vs authentic) head.
# Sign convention: positive weight means high score → more likely manipulated.
# Magnitudes loosely match what fusion.py uses for _CORE_AI_WEIGHTS but expressed
# in logistic-regression weight space (logit per unit risk score).
#
# Modules not listed here get weight 0 (no signal). This includes RINE, B-Free,
# SAFE, mesorch, prnu — all known to be unreliable in production.
_RISK_WEIGHTS = {
    # Strong working detectors (matched to fusion.py _CORE_AI_WEIGHTS)
    "clip_ai_detection":         3.5,   # F1 0.85, strongest signal
    "organika_ai_detection":     2.5,   # F1 ~0.97 reported, independent from CLIP
    "pixel_forensics":           1.5,   # 8 numpy signals, weak but orthogonal
    "dinov2_ai_detection":       0.5,   # known FP bias, dampened
    # Tampering / manipulation evidence (also pushes toward "manipulated")
    "modification_detection":    1.0,   # ELA + heuristics
    "mesorch_detection":         0.5,   # post-fix should improve
    # Low-signal heuristics — neutral or near-neutral
    "metadata_analysis":         0.8,
    "prnu_detection":            0.3,   # mostly 0 on JPEG; with EXIF prior may push up
    "safe_ai_detection":         0.0,   # dead on modern AI
    "bfree_detection":           0.0,   # dead on modern AI
    "rine_detection":            0.0,   # dead on modern AI
    # Document modules (only fire on PDFs/Office)
    "text_ai_detection":         3.0,
    "content_validation":        2.0,
    "document_forensics":        1.0,
    "office_forensics":          1.0,
}

# Confidence weights — small positive contribution when a module reports high
# confidence (regardless of risk). Mostly noise; keep small.
_CONFIDENCE_WEIGHT = 0.05

# Number-of-findings weights — modules emit 0+ findings; more findings ≈ more
# evidence of an anomaly. Small positive weight.
_NFIND_WEIGHT = 0.10

# Pairwise interaction weights — only the few that matter (CLIP×Organika,
# CLIP×Pixel) get nonzero. Everything else stays at 0.
_INTERACTION_WEIGHTS = {
    ("clip_ai_detection", "organika_ai_detection"): 1.5,
    ("clip_ai_detection", "pixel_forensics"):       1.0,
    ("organika_ai_detection", "pixel_forensics"):   0.5,
}

# Squared-term weights — captures non-linear "very high" boost on the strong
# detectors. Small positive.
_SQUARED_WEIGHTS = {
    "clip_ai_detection":     2.0,
    "organika_ai_detection": 1.0,
}


def build_binary_weights() -> tuple[np.ndarray, float]:
    """Build the (N_FEATURES,) weight vector for the binary head."""
    weights = np.zeros(N_FEATURES, dtype=np.float64)

    # Layout (matches feature_names() in stacking_meta.py):
    #   indices 0..3*N_MODULES-1   → base features (risk, conf, nfind per module)
    #   indices 3*N            ..  → pairwise interactions (i,j) for i<j
    #   indices ..end                → squared risk per module
    n_base = 3 * N_MODULES

    # Base features
    for i, mod in enumerate(MODULE_ORDER):
        weights[3 * i + 0] = _RISK_WEIGHTS.get(mod, 0.0)        # risk
        weights[3 * i + 1] = _CONFIDENCE_WEIGHT                  # conf
        weights[3 * i + 2] = _NFIND_WEIGHT                       # nfind

    # Pairwise interactions
    idx = n_base
    for i in range(N_MODULES):
        for j in range(i + 1, N_MODULES):
            mi, mj = MODULE_ORDER[i], MODULE_ORDER[j]
            w = _INTERACTION_WEIGHTS.get((mi, mj), 0.0)
            if w == 0.0:
                w = _INTERACTION_WEIGHTS.get((mj, mi), 0.0)
            weights[idx] = w
            idx += 1

    # Squared terms
    for i, mod in enumerate(MODULE_ORDER):
        weights[idx + i] = _SQUARED_WEIGHTS.get(mod, 0.0)

    # Bias: targets ~0.10 sigmoid output for an all-zero feature vector
    # (a clean image with no signal anywhere should score "authentic").
    # logit(0.10) = ln(0.10/0.90) ≈ -2.20
    bias = -2.20

    return weights, bias


def build_multi_weights() -> tuple[np.ndarray, np.ndarray]:
    """Build the (N_FEATURES, 3) multinomial head — one weight column per class.

    Classes: [authentic, ai_generated, tampered]
    """
    bw, _ = build_binary_weights()
    weights_multi = np.zeros((N_FEATURES, 3), dtype=np.float64)

    # authentic ← negative of binary (more "manipulated" signal → less authentic)
    weights_multi[:, 0] = -bw

    # ai_generated ← matches binary heavily for CLIP/Organika/DINOv2/Pixel
    weights_multi[:, 1] = bw.copy()

    # tampered ← matches binary mostly for tampering modules
    tamp_weights = np.zeros(N_FEATURES, dtype=np.float64)
    for i, mod in enumerate(MODULE_ORDER):
        if mod in ("modification_detection", "mesorch_detection", "prnu_detection"):
            tamp_weights[3 * i + 0] = _RISK_WEIGHTS.get(mod, 0.0) * 2.0
    weights_multi[:, 2] = tamp_weights

    # Per-class biases — start with mild "authentic" prior (most images are real)
    bias_multi = np.array([1.5, -0.5, -1.0], dtype=np.float64)

    return weights_multi, bias_multi


def main() -> None:
    weights, bias = build_binary_weights()
    weights_multi, bias_multi = build_multi_weights()

    print(f"MODULE_ORDER ({N_MODULES} modules):")
    for i, m in enumerate(MODULE_ORDER):
        rw = _RISK_WEIGHTS.get(m, 0.0)
        marker = "★" if rw >= 1.0 else (" " if rw > 0 else "·")
        print(f"  {marker} [{i:2d}] {m:30s} risk_w={rw:+.2f}")

    print(f"\nFeature counts: N_MODULES={N_MODULES}, N_FEATURES={N_FEATURES}")
    print(f"Binary weights shape:    {weights.shape}, sum={weights.sum():.2f}")
    print(f"Multi weights shape:     {weights_multi.shape}")
    print(f"Binary bias:             {bias:+.2f}")
    print(f"Multi bias (auth/ai/tamp): {bias_multi}")

    out_dirs = [
        os.path.join(ROOT, "models", "stacking_meta"),
        os.path.join(ROOT, "models", "meta"),
        os.path.join(ROOT, "app", "forensics"),
    ]
    classes = np.array(["authentic", "ai_generated", "tampered"])
    feat_names = np.array(feature_names())

    for d in out_dirs:
        os.makedirs(d, exist_ok=True)
        out_path = os.path.join(d, "meta_weights.npz")
        np.savez(
            out_path,
            weights=weights,
            bias=np.array([bias]),
            weights_multi=weights_multi,
            bias_multi=bias_multi,
            module_order=np.array(MODULE_ORDER),
            feature_names=feat_names,
            classes=classes,
        )
        print(f"  Wrote {out_path} ({os.path.getsize(out_path)} bytes)")

    print("\nDone. Run tests with: pytest tests/test_stacking_meta.py")


if __name__ == "__main__":
    main()
