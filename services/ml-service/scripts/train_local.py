#!/usr/bin/env python3
"""Standalone meta-learner training — no app imports, works on Python 3.9+."""
import json
import os
import sys
from pathlib import Path

import numpy as np

# Module order must match stacking_meta.py exactly
MODULE_ORDER = [
    "ai_generation_detection",
    "clip_ai_detection",
    "vae_reconstruction",
    "community_forensics_detection",
    "npr_ai_detection",
    "efficientnet_ai_detection",
    "safe_ai_detection",
    "dinov2_ai_detection",
    "bfree_detection",
    "spai_detection",
    "prnu_detection",
    "deep_modification_detection",
    "mesorch_detection",
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
N_BASE = N_MODULES * 3
N_INTERACTIONS = N_MODULES * (N_MODULES - 1) // 2
N_SQUARED = N_MODULES
N_FEATURES = N_BASE + N_INTERACTIONS + N_SQUARED

CLASSES = ["authentic", "ai_generated", "tampered"]
CLASS_TO_IDX = {c: i for i, c in enumerate(CLASSES)}


def feature_names():
    names = []
    for mod in MODULE_ORDER:
        names.extend([f"risk:{mod}", f"conf:{mod}", f"nfind:{mod}"])
    for i in range(N_MODULES):
        for j in range(i + 1, N_MODULES):
            names.append(f"risk_x:{MODULE_ORDER[i]}:{MODULE_ORDER[j]}")
    for mod in MODULE_ORDER:
        names.append(f"risk_sq:{mod}")
    return names


def extract_features(modules_data):
    risk_scores = np.zeros(N_MODULES, dtype=np.float64)
    base = np.zeros(N_BASE, dtype=np.float64)

    for i, mod_name in enumerate(MODULE_ORDER):
        mod = modules_data.get(mod_name)
        if mod is None:
            continue
        risk = float(mod.get("risk_score", 0.0))
        risk_scores[i] = risk
        findings = mod.get("findings", [])
        if findings:
            avg_conf = sum(f.get("confidence", 0.5) for f in findings) / len(findings)
            nfind_norm = min(len(findings), 10) / 10.0
        else:
            avg_conf = 0.0
            nfind_norm = 0.0
        idx = i * 3
        base[idx] = risk
        base[idx + 1] = avg_conf
        base[idx + 2] = nfind_norm

    interactions = np.zeros(N_INTERACTIONS, dtype=np.float64)
    k = 0
    for i in range(N_MODULES):
        for j in range(i + 1, N_MODULES):
            interactions[k] = risk_scores[i] * risk_scores[j]
            k += 1

    squared = risk_scores ** 2
    return np.concatenate([base, interactions, squared])


def main():
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_predict, StratifiedKFold
    from sklearn.metrics import classification_report, f1_score

    data_path = sys.argv[1] if len(sys.argv) > 1 else "data/labeled_dataset.jsonl"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "models/stacking_meta/meta_weights.npz"

    # Load data
    samples = []
    with open(data_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            sample = json.loads(line)
            gt = sample.get("ground_truth", "").lower()
            if gt == "manipulated":
                gt = "ai_generated"
            if gt in CLASS_TO_IDX:
                samples.append(sample)

    print(f"Loaded {len(samples)} samples from {data_path}")

    # Build feature matrix
    X = np.zeros((len(samples), N_FEATURES), dtype=np.float64)
    y_3class = np.zeros(len(samples), dtype=np.int32)

    for i, sample in enumerate(samples):
        X[i] = extract_features(sample.get("modules", {}))
        y_3class[i] = CLASS_TO_IDX[sample["ground_truth"]]

    y_binary = np.where(y_3class == 0, 0, 1)

    print(f"\nClass distribution:")
    for c in range(len(CLASSES)):
        print(f"  {CLASSES[c]}: {int((y_3class == c).sum())}")
    print(f"  Binary: {int((y_binary == 0).sum())} authentic, {int((y_binary == 1).sum())} manipulated")
    print(f"Feature matrix: {X.shape[0]} x {X.shape[1]}")

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    # JUDGE 1: Binary
    print("\n" + "=" * 60)
    print("JUDGE 1: Binary LogReg (authentic vs manipulated)")
    print("=" * 60)
    lr_binary = LogisticRegression(C=0.1, max_iter=2000, class_weight="balanced", random_state=42)
    y_pred_bin = cross_val_predict(lr_binary, X, y_binary, cv=cv)
    bin_f1 = f1_score(y_binary, y_pred_bin, average="macro")
    print(classification_report(y_binary, y_pred_bin, target_names=["authentic", "manipulated"], digits=3))
    print(f"Binary Macro-F1: {bin_f1:.3f}")

    lr_binary.fit(X, y_binary)
    binary_weights = lr_binary.coef_[0]
    binary_bias = lr_binary.intercept_[0]

    # JUDGE 2: 3-class
    print("\n" + "=" * 60)
    print("JUDGE 2: 3-class LogReg (context breakdown)")
    print("=" * 60)
    lr_multi = LogisticRegression(C=0.1, max_iter=2000, class_weight="balanced", random_state=42)
    y_pred_3 = cross_val_predict(lr_multi, X, y_3class, cv=cv)
    multi_f1 = f1_score(y_3class, y_pred_3, average="macro")
    print(classification_report(y_3class, y_pred_3, target_names=CLASSES, digits=3))
    print(f"3-class Macro-F1: {multi_f1:.3f}")

    lr_multi.fit(X, y_3class)
    W_multi = lr_multi.coef_.T
    B_multi = lr_multi.intercept_

    # Final model on all data
    y_final_pred = lr_multi.predict(X)
    print("\n=== Final Model (all data) ===")
    print(classification_report(y_3class, y_final_pred, target_names=CLASSES, digits=3))

    # Top features per class
    names = feature_names()
    print("=== Top-10 Features per Class ===")
    for c in range(len(CLASSES)):
        importance = sorted(zip(names, W_multi[:, c]), key=lambda x: abs(x[1]), reverse=True)
        print(f"\n  {CLASSES[c]}:")
        for name, weight in importance[:10]:
            print(f"    {weight:+.4f}  {name}")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Binary (gauge/badge):  macro-F1={bin_f1:.3f}")
    print(f"  3-class (context bars): macro-F1={multi_f1:.3f}")

    # Save
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    np.savez(
        output_path,
        weights=binary_weights,
        bias=np.array([binary_bias]),
        module_order=np.array(MODULE_ORDER),
        feature_names=np.array(names),
        weights_multi=W_multi,
        bias_multi=B_multi,
        classes=np.array(CLASSES),
    )
    print(f"\n  Saved to {output_path}")
    print(f"  Binary:  weights ({binary_weights.shape}), bias={binary_bias:.4f}")
    print(f"  3-class: W ({W_multi.shape}), B ({B_multi.shape})")
    print(f"  Modules: {N_MODULES}, Features: {N_FEATURES}")


if __name__ == "__main__":
    main()
