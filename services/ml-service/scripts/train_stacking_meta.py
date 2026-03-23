#!/usr/bin/env python3
"""Train dual stacking meta-learner for DENT forensic score fusion.

Dual-judge architecture using sklearn L-BFGS (superior convergence):
  1. Binary LogReg (authentic vs manipulated) → overall risk_score
  2. 3-class LogReg (authentic/ai_generated/tampered) → verdict breakdown

Both models saved in same .npz. stacking_meta.py loads both:
  - predict() uses binary weights → sigmoid → risk score for gauge
  - predict_proba() uses multinomial weights → softmax → 3 bars

Usage:
    python -m scripts.train_stacking_meta \
        --data labeled_samples.jsonl \
        [--output /app/models/stacking_meta/meta_weights.npz] \
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


# ── Main ─────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Train dual stacking meta-learner (binary + 3-class)"
    )
    parser.add_argument("--data", required=True, help="Path to labeled JSONL data")
    parser.add_argument("--output", default="", help="Output path for meta_weights.npz")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--dry-run", action="store_true", help="Show metrics without saving")

    args = parser.parse_args()

    # sklearn imports (not at top-level so script can show --help without sklearn)
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_predict, StratifiedKFold
    from sklearn.metrics import classification_report, f1_score

    if args.output:
        output_path = args.output
    else:
        cache_dir = os.environ.get("DENT_FORENSICS_MODEL_CACHE_DIR", "/app/models")
        output_dir = os.path.join(cache_dir, "stacking_meta")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "meta_weights.npz")

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

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=args.seed)

    # ══════════════════════════════════════════════════════════════════
    # JUDGE 1: Binary LogReg (authentic vs manipulated) → risk_score
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("JUDGE 1: Binary LogReg (authentic vs manipulated)")
    print("=" * 60)

    lr_binary = LogisticRegression(C=1000, max_iter=2000, class_weight="balanced", random_state=args.seed)
    y_pred_bin = cross_val_predict(lr_binary, X, y_binary, cv=cv)
    bin_f1 = f1_score(y_binary, y_pred_bin, average="macro")
    print(classification_report(
        y_binary, y_pred_bin,
        target_names=["authentic", "manipulated"],
        digits=3,
    ))
    print(f"Binary Macro-F1: {bin_f1:.3f}")

    # Train final binary model on all data
    lr_binary.fit(X, y_binary)
    # Extract weights: sklearn stores coef_ as (1, n_features) for binary
    binary_weights = lr_binary.coef_[0]  # (147,)
    binary_bias = lr_binary.intercept_[0]  # scalar

    # ══════════════════════════════════════════════════════════════════
    # JUDGE 2: 3-class LogReg → verdict_probabilities (context bars)
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("JUDGE 2: 3-class LogReg (context breakdown)")
    print("=" * 60)

    lr_multi = LogisticRegression(C=1000, max_iter=2000, class_weight="balanced", random_state=args.seed)
    y_pred_3 = cross_val_predict(lr_multi, X, y_3class, cv=cv)
    multi_f1 = f1_score(y_3class, y_pred_3, average="macro")
    print(classification_report(
        y_3class, y_pred_3,
        target_names=CLASSES,
        digits=3,
    ))
    print(f"3-class Macro-F1: {multi_f1:.3f}")

    # Train final 3-class model on all data
    lr_multi.fit(X, y_3class)
    # Extract weights: sklearn stores coef_ as (n_classes, n_features)
    W_multi = lr_multi.coef_.T  # (147, 3)
    B_multi = lr_multi.intercept_  # (3,)

    # Verify class order matches our CLASSES
    sklearn_classes = [CLASSES[i] for i in lr_multi.classes_]
    print(f"\n  sklearn class order: {sklearn_classes}")
    print(f"  Our class order:    {CLASSES}")

    # Per-class metrics on final model
    y_final_pred = lr_multi.predict(X)
    print("\n=== Final Model (all data) ===")
    print(classification_report(
        y_3class, y_final_pred,
        target_names=CLASSES,
        digits=3,
    ))

    # Feature importance (per class)
    names = feature_names()
    print("=== Top-10 Features per Class ===")
    for c in range(len(CLASSES)):
        importance = sorted(
            zip(names, W_multi[:, c]), key=lambda x: abs(x[1]), reverse=True
        )
        print(f"\n  {CLASSES[c]}:")
        for name, weight in importance[:10]:
            print(f"    {weight:+.4f}  {name}")

    # ══════════════════════════════════════════════════════════════════
    # Summary
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Binary (gauge/badge):  macro-F1={bin_f1:.3f}")
    print(f"  3-class (context bars): macro-F1={multi_f1:.3f}")

    # Save
    if args.dry_run:
        logger.info("Dry run — not saving")
    else:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        np.savez(
            output_path,
            # Binary judge (used by predict() → risk_score)
            weights=binary_weights,
            bias=np.array([binary_bias]),
            module_order=np.array(MODULE_ORDER),
            feature_names=np.array(names),
            # 3-class judge (used by predict_proba() → verdict bars)
            weights_multi=W_multi,
            bias_multi=B_multi,
            classes=np.array(CLASSES),
        )
        logger.info("Saved dual meta weights to %s", output_path)
        print(f"\n  Binary:  weights ({binary_weights.shape}), bias={binary_bias:.4f}")
        print(f"  3-class: W ({W_multi.shape}), B ({B_multi.shape})")
        print(f"  Classes: {CLASSES}")
        print(f"  To enable: set DENT_FORENSICS_STACKING_META_ENABLED=true")


if __name__ == "__main__":
    main()
