#!/usr/bin/env python3
"""Standalone meta-learner training — no app imports, works on Python 3.9+.

Supports: --model logreg | gbm | both (default: gbm)

Usage:
    python train_local.py data/labeled_dataset.jsonl [output_dir] [--model gbm]
"""
import argparse
import json
import os
import sys
from collections import defaultdict
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


def analyze_module_coverage(samples):
    """Print which modules have data and their score distributions."""
    module_counts = defaultdict(int)
    module_nonzero = defaultdict(int)
    module_scores = defaultdict(list)

    for sample in samples:
        modules = sample.get("modules", {})
        for mod_name in MODULE_ORDER:
            if mod_name in modules:
                module_counts[mod_name] += 1
                score = modules[mod_name].get("risk_score", 0.0)
                if score > 0:
                    module_nonzero[mod_name] += 1
                module_scores[mod_name].append(score)

    print(f"\n{'Module':<40} {'Present':>8} {'NonZero':>8} {'Mean':>8} {'Std':>8}")
    print("-" * 80)
    for mod in MODULE_ORDER:
        n = module_counts[mod]
        nz = module_nonzero[mod]
        scores = module_scores[mod]
        mean = np.mean(scores) if scores else 0.0
        std = np.std(scores) if scores else 0.0
        flag = " *** MISSING" if n < len(samples) * 0.5 else ""
        print(f"  {mod:<38} {n:>8} {nz:>8} {mean:>8.3f} {std:>8.3f}{flag}")


def main():
    parser = argparse.ArgumentParser(description="Train meta-learner (standalone)")
    parser.add_argument("data", help="Path to labeled JSONL data")
    parser.add_argument("output_dir", nargs="?", default="models/stacking_meta",
                        help="Output directory (default: models/stacking_meta)")
    parser.add_argument("--model", default="gbm", choices=["logreg", "gbm", "both"],
                        help="Model type (default: gbm)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.model_selection import cross_val_predict, StratifiedKFold
    from sklearn.metrics import classification_report, f1_score

    # Load data
    samples = []
    with open(args.data) as f:
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

    print(f"Loaded {len(samples)} samples from {args.data}")

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

    analyze_module_coverage(samples)

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=args.seed)
    names = feature_names()
    results = {}

    # ── LogReg ────────────────────────────────────────────────────────
    if args.model in ("logreg", "both"):
        print("\n" + "=" * 60)
        print("LOGREG: Binary (authentic vs manipulated)")
        print("=" * 60)
        lr_binary = LogisticRegression(C=0.1, max_iter=2000, class_weight="balanced", random_state=args.seed)
        y_pred = cross_val_predict(lr_binary, X, y_binary, cv=cv)
        lr_bin_f1 = f1_score(y_binary, y_pred, average="macro")
        print(classification_report(y_binary, y_pred, target_names=["authentic", "manipulated"], digits=3))
        print(f"Binary Macro-F1: {lr_bin_f1:.3f}")
        lr_binary.fit(X, y_binary)

        print("\n" + "=" * 60)
        print("LOGREG: 3-class (context breakdown)")
        print("=" * 60)
        lr_multi = LogisticRegression(C=0.1, max_iter=2000, class_weight="balanced", random_state=args.seed)
        y_pred = cross_val_predict(lr_multi, X, y_3class, cv=cv)
        lr_multi_f1 = f1_score(y_3class, y_pred, average="macro")
        print(classification_report(y_3class, y_pred, target_names=CLASSES, digits=3))
        print(f"3-class Macro-F1: {lr_multi_f1:.3f}")
        lr_multi.fit(X, y_3class)

        results["logreg"] = {"binary_f1": lr_bin_f1, "multi_f1": lr_multi_f1}

    # ── GBM ───────────────────────────────────────────────────────────
    if args.model in ("gbm", "both"):
        print("\n" + "=" * 60)
        print("GBM: Binary (authentic vs manipulated)")
        print("=" * 60)
        gbm_binary = GradientBoostingClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.1,
            subsample=0.8, random_state=args.seed,
        )
        y_pred = cross_val_predict(gbm_binary, X, y_binary, cv=cv)
        gbm_bin_f1 = f1_score(y_binary, y_pred, average="macro")
        print(classification_report(y_binary, y_pred, target_names=["authentic", "manipulated"], digits=3))
        print(f"Binary Macro-F1: {gbm_bin_f1:.3f}")
        gbm_binary.fit(X, y_binary)

        print("\n" + "=" * 60)
        print("GBM: 3-class (context breakdown)")
        print("=" * 60)
        gbm_multi = GradientBoostingClassifier(
            n_estimators=200, max_depth=4, learning_rate=0.1,
            subsample=0.8, random_state=args.seed,
        )
        y_pred = cross_val_predict(gbm_multi, X, y_3class, cv=cv)
        gbm_multi_f1 = f1_score(y_3class, y_pred, average="macro")
        print(classification_report(y_3class, y_pred, target_names=CLASSES, digits=3))
        print(f"3-class Macro-F1: {gbm_multi_f1:.3f}")
        gbm_multi.fit(X, y_3class)

        # Feature importance
        print("\n=== Top-20 Features (GBM Binary) ===")
        importance = sorted(zip(names, gbm_binary.feature_importances_), key=lambda x: x[1], reverse=True)
        for name, imp in importance[:20]:
            print(f"  {imp:.4f}  {name}")

        print("\n=== Top-20 Features (GBM 3-class) ===")
        importance = sorted(zip(names, gbm_multi.feature_importances_), key=lambda x: x[1], reverse=True)
        for name, imp in importance[:20]:
            print(f"  {imp:.4f}  {name}")

        results["gbm"] = {"binary_f1": gbm_bin_f1, "multi_f1": gbm_multi_f1}

    # ── Summary ───────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for model_name, metrics in results.items():
        print(f"  {model_name.upper()}: binary F1={metrics['binary_f1']:.3f}, 3-class F1={metrics['multi_f1']:.3f}")

    if "logreg" in results and "gbm" in results:
        lr_avg = (results["logreg"]["binary_f1"] + results["logreg"]["multi_f1"]) / 2
        gbm_avg = (results["gbm"]["binary_f1"] + results["gbm"]["multi_f1"]) / 2
        print(f"\n  Better: {'GBM' if gbm_avg > lr_avg else 'LogReg'} (avg: LR={lr_avg:.3f}, GBM={gbm_avg:.3f})")

    # ── Save ──────────────────────────────────────────────────────────
    if args.dry_run:
        print("\nDry run — not saving")
        return

    os.makedirs(args.output_dir, exist_ok=True)
    print(f"\nSaving to {args.output_dir}/")

    if args.model in ("logreg", "both"):
        npz_path = os.path.join(args.output_dir, "meta_weights.npz")
        np.savez(
            npz_path,
            weights=lr_binary.coef_[0],
            bias=np.array([lr_binary.intercept_[0]]),
            module_order=np.array(MODULE_ORDER),
            feature_names=np.array(names),
            weights_multi=lr_multi.coef_.T,
            bias_multi=lr_multi.intercept_,
            classes=np.array(CLASSES),
        )
        print(f"  LogReg: {npz_path}")

    if args.model in ("gbm", "both"):
        import joblib
        bin_path = os.path.join(args.output_dir, "gbm_binary.joblib")
        multi_path = os.path.join(args.output_dir, "gbm_multi.joblib")
        meta_path = os.path.join(args.output_dir, "gbm_meta.json")

        joblib.dump(gbm_binary, bin_path)
        joblib.dump(gbm_multi, multi_path)

        # Metadata sidecar for module order validation at load time
        meta = {
            "module_order": MODULE_ORDER,
            "n_modules": len(MODULE_ORDER),
            "n_features": N_FEATURES,
            "classes": CLASSES,
            "feature_names": names,
            "gbm_params": {
                "n_estimators": gbm_binary.n_estimators,
                "max_depth": gbm_binary.max_depth,
                "learning_rate": gbm_binary.learning_rate,
            },
        }
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

        print(f"  GBM binary:  {bin_path}")
        print(f"  GBM 3-class: {multi_path}")
        print(f"  GBM meta:    {meta_path}")

    print(f"\n  Modules: {N_MODULES}, Features: {N_FEATURES}")


if __name__ == "__main__":
    main()
