#!/usr/bin/env python3
"""Train a SUPERVISED stacking meta-learner from production data.

Replaces generate_calibrated_meta_weights.py (which produced hand-crafted
weights). This script trains a real LogisticRegression on the labeled
production JSONL and writes weights compatible with stacking_meta.py.

The meta-learner is currently dead code in fusion.py — it predicts
verdict_probabilities which are then immediately overwritten by rule-based
logic. After Day 3.2 (wire meta blend), the trained model's binary score
will be blended with the rule-based score.

Why this works on only ~100 production rows:
  - Feature dim is 165 (15 modules × 3 features + 105 interactions + 15 squared)
  - With L2 regularization (C=0.1) the effective dim is ~10-15
  - Leave-one-out CV is feasible at this size
  - The training data REFLECTS the production distribution (unlike synthetic)
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from app.forensics.stacking_meta import (  # noqa: E402
    MODULE_ORDER,
    N_FEATURES,
    N_MODULES,
    feature_names,
)


def _row_to_features(row: dict) -> np.ndarray:
    """Replicate stacking_meta.extract_features() but operate on a JSONL row.

    extract_features() needs ModuleResult objects; we already have plain dict
    data so we duplicate the math here. Layout (matches feature_names()):
        [0..3*N-1]   base features (risk, conf=0.8, nfind/10) per module
        [3*N..]      pairwise interactions risk_i * risk_j for i<j
        [end..]      squared risk per module
    """
    feats = np.zeros(N_FEATURES, dtype=np.float64)
    risks = np.zeros(N_MODULES, dtype=np.float64)
    mods = row.get("modules") or {}
    n_base = 3 * N_MODULES

    for i, name in enumerate(MODULE_ORDER):
        m = mods.get(name) or {}
        if m.get("error"):
            continue
        risk = float(m.get("risk_score", 0.0))
        risks[i] = risk
        n_find = int(m.get("n_findings", 0))
        feats[3 * i + 0] = risk
        feats[3 * i + 1] = 0.80 if risk > 0 else 0.0  # synthetic confidence
        feats[3 * i + 2] = min(n_find, 10) / 10.0

    # Pairwise interactions
    idx = n_base
    for i in range(N_MODULES):
        for j in range(i + 1, N_MODULES):
            feats[idx] = risks[i] * risks[j]
            idx += 1

    # Squared
    for i in range(N_MODULES):
        feats[idx + i] = risks[i] * risks[i]

    return feats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Labeled training JSONL")
    parser.add_argument("--output", required=True, help="meta_weights.npz path")
    parser.add_argument("--C", type=float, default=0.1, help="LogReg regularization")
    args = parser.parse_args()

    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import LeaveOneOut, cross_val_predict
    from sklearn.metrics import f1_score, classification_report

    rows = []
    with open(args.input) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    print(f"Loaded {len(rows)} training rows")

    # Build feature matrix
    X = np.zeros((len(rows), N_FEATURES), dtype=np.float64)
    y_str = []
    for i, r in enumerate(rows):
        X[i] = _row_to_features(r)
        y_str.append(r.get("ground_truth", "authentic"))

    classes = ["authentic", "ai_generated", "tampered"]
    cls_to_idx = {c: i for i, c in enumerate(classes)}
    y_3 = np.array([cls_to_idx.get(g, 0) for g in y_str], dtype=np.int32)
    y_bin = np.where(y_3 == 0, 0, 1)

    print(f"Class distribution:")
    for c in classes:
        print(f"  {c}: {int((np.array(y_str) == c).sum())}")
    print(f"Binary: {(y_bin == 0).sum()} authentic, {(y_bin == 1).sum()} manipulated")
    print()

    # ── BINARY HEAD ──────────────────────────────────────────────────
    print("=== BINARY HEAD (LogReg, C={}) ===".format(args.C))
    lr_bin = LogisticRegression(
        C=args.C, max_iter=2000, class_weight="balanced", random_state=42
    )

    # Leave-one-out CV
    loo = LeaveOneOut()
    y_pred = cross_val_predict(lr_bin, X, y_bin, cv=loo, n_jobs=1)
    bin_f1 = f1_score(y_bin, y_pred, average="macro")
    print(classification_report(y_bin, y_pred, target_names=["auth", "manip"], digits=3))
    print(f"Binary LOO macro-F1: {bin_f1:.4f}")
    print()

    lr_bin.fit(X, y_bin)
    weights = lr_bin.coef_[0].astype(np.float64)
    bias = float(lr_bin.intercept_[0])

    # ── MULTINOMIAL HEAD ─────────────────────────────────────────────
    print("=== MULTINOMIAL HEAD (LogReg, C={}) ===".format(args.C))
    # Modern sklearn auto-detects multinomial when len(classes) > 2;
    # the multi_class kwarg was removed in sklearn 1.5+.
    lr_multi = LogisticRegression(
        C=args.C, max_iter=2000, class_weight="balanced", random_state=42,
    )
    # If we have at least one "tampered" sample we can train 3-class.
    # Otherwise fall back to binary multi-head with a synthetic tampered slot
    # so the saved weights schema still has shape (N_FEATURES, 3).
    n_classes_present = len(set(y_3))
    if n_classes_present >= 2:
        y_pred_multi = cross_val_predict(lr_multi, X, y_3, cv=loo, n_jobs=1)
        labels_present = sorted(set(y_3))
        names_present = [classes[i] for i in labels_present]
        multi_f1 = f1_score(y_3, y_pred_multi, average="macro")
        print(classification_report(
            y_3, y_pred_multi,
            labels=labels_present, target_names=names_present, digits=3,
        ))
        print(f"Multi LOO macro-F1: {multi_f1:.4f}")
    print()

    lr_multi.fit(X, y_3)
    # Binary case: sklearn returns coef shape (1, N) representing class 1.
    # Multinomial case: shape (n_classes, N) one row per class.
    coef_raw = lr_multi.coef_  # shape (1, N) or (n_cls, N)
    intercept_raw = lr_multi.intercept_

    weights_multi = np.zeros((N_FEATURES, 3), dtype=np.float64)
    bias_multi = np.zeros(3, dtype=np.float64)

    if coef_raw.shape[0] == 1:
        # Binary fit — coef represents the "positive" class (the larger label)
        positive_label = max(set(y_3))
        weights_multi[:, positive_label] = coef_raw[0]
        bias_multi[positive_label] = intercept_raw[0]
        # Negative class (authentic, label 0) gets the inverse to keep the
        # softmax interpretable
        weights_multi[:, 0] = -coef_raw[0]
        bias_multi[0] = -intercept_raw[0]
    else:
        # Multinomial — one row per class, in label order
        labels_present = sorted(set(y_3))
        for col_idx, cls_idx in enumerate(labels_present):
            weights_multi[:, cls_idx] = coef_raw[col_idx]
            bias_multi[cls_idx] = intercept_raw[col_idx]

    # ── SAVE ─────────────────────────────────────────────────────────
    np.savez(
        args.output,
        weights=weights,
        bias=np.array([bias]),
        weights_multi=weights_multi,
        bias_multi=bias_multi,
        module_order=np.array(MODULE_ORDER),
        feature_names=np.array(feature_names()),
        classes=np.array(classes),
    )
    print(f"Saved {args.output}")

    # Top contributing features
    print()
    print("Top 10 features by |weight| (binary head):")
    abs_w = np.abs(weights)
    top_idx = np.argsort(abs_w)[::-1][:10]
    names = feature_names()
    for i in top_idx:
        sign = "+" if weights[i] > 0 else "-"
        print(f"  {sign}{abs_w[i]:.4f}  {names[i]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
