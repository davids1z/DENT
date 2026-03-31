#!/usr/bin/env python3
"""Train dual stacking meta-learner for DENT forensic score fusion.

Supports two model types:
  --model logreg  → LogisticRegression (numpy .npz, fast, portable)
  --model gbm     → GradientBoosting (joblib, better F1, larger)
  --model both    → Train both, save side by side

Dual-judge architecture:
  1. Binary (authentic vs manipulated) → overall risk_score
  2. 3-class (authentic/ai_generated/tampered) → verdict breakdown

22 modules → 319 features (66 base + 231 pairwise + 22 squared).

Usage:
    python -m scripts.train_stacking_meta \
        --data labeled_samples.jsonl \
        [--model gbm] \
        [--output-dir /app/models/stacking_meta] \
        [--dry-run]
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.forensics.stacking_meta import (  # noqa: E402
    MODULE_ORDER,
    N_FEATURES,
    extract_features,
    feature_names,
)
from app.forensics.base import AnalyzerFinding, ModuleResult, RiskLevel  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# 3-class labels
CLASSES = ["authentic", "ai_generated", "tampered"]
CLASS_TO_IDX = {c: i for i, c in enumerate(CLASSES)}


# ── Data loading ─────────────────────────────────────────────────────


def load_labeled_data(path: str) -> list[dict]:
    """Load JSONL labeled samples. Supports 3 classes + legacy 'manipulated'."""
    samples = []
    with open(path) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                sample = json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning("Skipping line %d: %s", line_num, e)
                continue

            gt = sample.get("ground_truth", "").lower()

            # Backward compat: "manipulated" → "ai_generated"
            if gt == "manipulated":
                gt = "ai_generated"
                sample["ground_truth"] = gt

            if gt not in CLASS_TO_IDX:
                logger.warning("Skipping line %d: invalid ground_truth %r", line_num, gt)
                continue

            samples.append(sample)

    logger.info("Loaded %d labeled samples from %s", len(samples), path)
    return samples


def sample_to_module_results(sample: dict) -> list[ModuleResult]:
    """Convert a JSONL sample dict into a list of ModuleResult objects."""
    modules_data = sample.get("modules", {})
    results = []

    for mod_name in MODULE_ORDER:
        mod = modules_data.get(mod_name)
        if mod is None:
            continue

        risk_score = float(mod.get("risk_score", 0.0))

        findings = []
        raw_findings = mod.get("findings", [])
        if raw_findings:
            for rf in raw_findings:
                findings.append(AnalyzerFinding(
                    code="TRAIN_DATA",
                    title="Training sample finding",
                    description="",
                    risk_score=risk_score,
                    confidence=float(rf.get("confidence", 0.5)),
                    evidence=None,
                ))
        elif risk_score > 0:
            findings.append(AnalyzerFinding(
                code="TRAIN_DATA",
                title="Training sample finding",
                description="",
                risk_score=risk_score,
                confidence=0.5,
                evidence=None,
            ))

        results.append(ModuleResult(
            module_name=mod_name,
            module_label=mod_name,
            risk_score=risk_score,
            risk_score100=round(risk_score * 100),
            risk_level=RiskLevel.LOW,
            findings=findings,
            processing_time_ms=0,
        ))

    return results


def build_feature_matrix(samples: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Build feature matrix X and integer label vector y."""
    X = np.zeros((len(samples), N_FEATURES), dtype=np.float64)
    y = np.zeros(len(samples), dtype=np.int32)

    for i, sample in enumerate(samples):
        module_results = sample_to_module_results(sample)
        X[i] = extract_features(module_results)
        y[i] = CLASS_TO_IDX[sample["ground_truth"]]

    return X, y


def analyze_module_coverage(samples: list[dict]) -> None:
    """Print which modules have data and their score distributions."""
    from collections import defaultdict
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

    print("\n=== Module Coverage ===")
    print(f"{'Module':<40} {'Present':>8} {'NonZero':>8} {'Mean':>8} {'Std':>8}")
    print("-" * 80)
    for mod in MODULE_ORDER:
        n = module_counts[mod]
        nz = module_nonzero[mod]
        scores = module_scores[mod]
        if scores:
            mean = np.mean(scores)
            std = np.std(scores)
        else:
            mean = std = 0.0
        flag = " *** MISSING" if n < len(samples) * 0.5 else ""
        print(f"  {mod:<38} {n:>8} {nz:>8} {mean:>8.3f} {std:>8.3f}{flag}")


# ── Training ─────────────────────────────────────────────────────────


def train_logreg(X, y_binary, y_3class, cv, seed):
    """Train LogisticRegression models (binary + 3-class)."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_predict
    from sklearn.metrics import classification_report, f1_score

    print("\n" + "=" * 60)
    print("LOGREG: Binary (authentic vs manipulated)")
    print("=" * 60)

    lr_binary = LogisticRegression(C=0.1, max_iter=2000, class_weight="balanced", random_state=seed)
    y_pred_bin = cross_val_predict(lr_binary, X, y_binary, cv=cv)
    bin_f1 = f1_score(y_binary, y_pred_bin, average="macro")
    print(classification_report(y_binary, y_pred_bin, target_names=["authentic", "manipulated"], digits=3))
    print(f"Binary Macro-F1: {bin_f1:.3f}")

    lr_binary.fit(X, y_binary)

    print("\n" + "=" * 60)
    print("LOGREG: 3-class (context breakdown)")
    print("=" * 60)

    lr_multi = LogisticRegression(C=0.1, max_iter=2000, class_weight="balanced", random_state=seed)
    y_pred_3 = cross_val_predict(lr_multi, X, y_3class, cv=cv)
    multi_f1 = f1_score(y_3class, y_pred_3, average="macro")
    print(classification_report(y_3class, y_pred_3, target_names=CLASSES, digits=3))
    print(f"3-class Macro-F1: {multi_f1:.3f}")

    lr_multi.fit(X, y_3class)

    return lr_binary, lr_multi, bin_f1, multi_f1


def train_gbm(X, y_binary, y_3class, cv, seed):
    """Train GradientBoosting models (binary + 3-class)."""
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.model_selection import cross_val_predict
    from sklearn.metrics import classification_report, f1_score

    print("\n" + "=" * 60)
    print("GBM: Binary (authentic vs manipulated)")
    print("=" * 60)

    gbm_binary = GradientBoostingClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.1,
        subsample=0.8,
        random_state=seed,
    )
    y_pred_bin = cross_val_predict(gbm_binary, X, y_binary, cv=cv)
    bin_f1 = f1_score(y_binary, y_pred_bin, average="macro")
    print(classification_report(y_binary, y_pred_bin, target_names=["authentic", "manipulated"], digits=3))
    print(f"Binary Macro-F1: {bin_f1:.3f}")

    gbm_binary.fit(X, y_binary)

    print("\n" + "=" * 60)
    print("GBM: 3-class (context breakdown)")
    print("=" * 60)

    gbm_multi = GradientBoostingClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.1,
        subsample=0.8,
        random_state=seed,
    )
    y_pred_3 = cross_val_predict(gbm_multi, X, y_3class, cv=cv)
    multi_f1 = f1_score(y_3class, y_pred_3, average="macro")
    print(classification_report(y_3class, y_pred_3, target_names=CLASSES, digits=3))
    print(f"3-class Macro-F1: {multi_f1:.3f}")

    gbm_multi.fit(X, y_3class)

    # Feature importance (GBM has built-in)
    names = feature_names()
    print("\n=== Top-20 Features (GBM Binary) ===")
    importance = sorted(
        zip(names, gbm_binary.feature_importances_),
        key=lambda x: x[1], reverse=True,
    )
    for name, imp in importance[:20]:
        print(f"  {imp:.4f}  {name}")

    print("\n=== Top-20 Features (GBM 3-class) ===")
    importance = sorted(
        zip(names, gbm_multi.feature_importances_),
        key=lambda x: x[1], reverse=True,
    )
    for name, imp in importance[:20]:
        print(f"  {imp:.4f}  {name}")

    return gbm_binary, gbm_multi, bin_f1, multi_f1


# ── Save ─────────────────────────────────────────────────────────────


def save_logreg(lr_binary, lr_multi, output_dir: str):
    """Save LogReg weights as .npz."""
    names = feature_names()
    output_path = os.path.join(output_dir, "meta_weights.npz")

    binary_weights = lr_binary.coef_[0]
    binary_bias = lr_binary.intercept_[0]
    W_multi = lr_multi.coef_.T
    B_multi = lr_multi.intercept_

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
    logger.info("Saved LogReg meta weights to %s", output_path)
    print(f"  LogReg: {output_path}")
    print(f"    Binary:  weights ({binary_weights.shape}), bias={binary_bias:.4f}")
    print(f"    3-class: W ({W_multi.shape}), B ({B_multi.shape})")


def save_gbm(gbm_binary, gbm_multi, output_dir: str):
    """Save GBM models as joblib + metadata sidecar JSON."""
    import joblib

    bin_path = os.path.join(output_dir, "gbm_binary.joblib")
    multi_path = os.path.join(output_dir, "gbm_multi.joblib")
    meta_path = os.path.join(output_dir, "gbm_meta.json")

    joblib.dump(gbm_binary, bin_path)
    joblib.dump(gbm_multi, multi_path)

    # Save metadata sidecar for module order validation at load time
    meta = {
        "module_order": MODULE_ORDER,
        "n_modules": len(MODULE_ORDER),
        "n_features": N_FEATURES,
        "classes": CLASSES,
        "feature_names": feature_names(),
        "gbm_params": {
            "n_estimators": gbm_binary.n_estimators,
            "max_depth": gbm_binary.max_depth,
            "learning_rate": gbm_binary.learning_rate,
        },
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    logger.info("Saved GBM meta-learner to %s", output_dir)
    print(f"  GBM binary:  {bin_path}")
    print(f"  GBM 3-class: {multi_path}")
    print(f"  GBM meta:    {meta_path}")


# ── Main ─────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Train dual stacking meta-learner (binary + 3-class)"
    )
    parser.add_argument("--data", required=True, help="Path to labeled JSONL data")
    parser.add_argument(
        "--model", default="gbm", choices=["logreg", "gbm", "both"],
        help="Model type: logreg, gbm, or both (default: gbm)",
    )
    parser.add_argument("--output-dir", default="", help="Output directory for models")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--dry-run", action="store_true", help="Show metrics without saving")
    # Legacy compat
    parser.add_argument("--output", default="", help="(deprecated) Use --output-dir instead")

    args = parser.parse_args()

    if args.output_dir:
        output_dir = args.output_dir
    elif args.output:
        output_dir = os.path.dirname(args.output) or "."
    else:
        cache_dir = os.environ.get("DENT_FORENSICS_MODEL_CACHE_DIR", "/app/models")
        output_dir = os.path.join(cache_dir, "stacking_meta")

    os.makedirs(output_dir, exist_ok=True)

    from sklearn.model_selection import StratifiedKFold

    # Load data
    samples = load_labeled_data(args.data)
    if len(samples) < 10:
        logger.error("Need at least 10 samples, got %d", len(samples))
        sys.exit(1)

    X, y_3class = build_feature_matrix(samples)
    y_binary = np.where(y_3class == 0, 0, 1)  # 0=authentic, 1=manipulated

    print(f"\nClass distribution:")
    for c in range(len(CLASSES)):
        count = int((y_3class == c).sum())
        print(f"  {CLASSES[c]}: {count}")
    print(f"  Total: {len(y_3class)}")
    print(f"  Binary: {int((y_binary == 0).sum())} authentic, {int((y_binary == 1).sum())} manipulated")
    print(f"Feature matrix: {X.shape[0]} x {X.shape[1]}")

    # Module coverage analysis (helps diagnose missing modules)
    analyze_module_coverage(samples)

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=args.seed)

    results = {}

    if args.model in ("logreg", "both"):
        lr_binary, lr_multi, lr_bin_f1, lr_multi_f1 = train_logreg(
            X, y_binary, y_3class, cv, args.seed
        )
        results["logreg"] = {"binary_f1": lr_bin_f1, "multi_f1": lr_multi_f1}

    if args.model in ("gbm", "both"):
        gbm_binary, gbm_multi, gbm_bin_f1, gbm_multi_f1 = train_gbm(
            X, y_binary, y_3class, cv, args.seed
        )
        results["gbm"] = {"binary_f1": gbm_bin_f1, "multi_f1": gbm_multi_f1}

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for model_name, metrics in results.items():
        print(f"  {model_name.upper()}:")
        print(f"    Binary (gauge/badge):   macro-F1={metrics['binary_f1']:.3f}")
        print(f"    3-class (context bars):  macro-F1={metrics['multi_f1']:.3f}")

    if "logreg" in results and "gbm" in results:
        lr_avg = (results["logreg"]["binary_f1"] + results["logreg"]["multi_f1"]) / 2
        gbm_avg = (results["gbm"]["binary_f1"] + results["gbm"]["multi_f1"]) / 2
        better = "GBM" if gbm_avg > lr_avg else "LogReg"
        print(f"\n  Better model: {better} (avg F1: LogReg={lr_avg:.3f}, GBM={gbm_avg:.3f})")

    # Save
    if args.dry_run:
        logger.info("Dry run — not saving")
    else:
        print(f"\nSaving to {output_dir}/")
        if args.model in ("logreg", "both"):
            save_logreg(lr_binary, lr_multi, output_dir)
        if args.model in ("gbm", "both"):
            save_gbm(gbm_binary, gbm_multi, output_dir)

        print(f"\n  To enable: set DENT_FORENSICS_STACKING_META_ENABLED=true")


if __name__ == "__main__":
    main()
