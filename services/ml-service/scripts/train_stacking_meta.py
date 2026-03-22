#!/usr/bin/env python3
"""Train a stacking meta-learner for DENT forensic score fusion.

Supports 3 classes: authentic, ai_generated, tampered.
Uses one-vs-rest multinomial logistic regression with L2 regularization.
Outputs per-class weights that predict class probabilities.

Usage:
    python -m scripts.train_stacking_meta \
        --data labeled_samples.jsonl \
        [--output /app/models/stacking_meta/meta_weights.npz] \
        [--reg 0.1] [--k-folds 5] [--dry-run]

Input format (JSONL):
    {"id": "s001", "ground_truth": "authentic", "modules": {...}}
    {"id": "s002", "ground_truth": "ai_generated", "modules": {...}}
    {"id": "s003", "ground_truth": "tampered", "modules": {...}}
    {"id": "s004", "ground_truth": "manipulated", "modules": {...}}

    "manipulated" is treated as "ai_generated" for backward compatibility.
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
    """Build feature matrix X and integer label vector y (0=authentic, 1=ai_gen, 2=tampered)."""
    X = np.zeros((len(samples), N_FEATURES), dtype=np.float64)
    y = np.zeros(len(samples), dtype=np.int32)

    for i, sample in enumerate(samples):
        module_results = sample_to_module_results(sample)
        X[i] = extract_features(module_results)
        y[i] = CLASS_TO_IDX[sample["ground_truth"]]

    return X, y


# ── Multinomial Logistic Regression (One-vs-Rest) ────────────────────


def softmax(Z: np.ndarray) -> np.ndarray:
    """Numerically stable softmax across last axis."""
    Z_shift = Z - Z.max(axis=1, keepdims=True)
    exp_Z = np.exp(Z_shift)
    return exp_Z / exp_Z.sum(axis=1, keepdims=True)


def train_multinomial_logistic(
    X: np.ndarray,
    y: np.ndarray,
    n_classes: int = 3,
    lr: float = 0.05,
    epochs: int = 2000,
    reg: float = 0.1,
    verbose: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    """Train multinomial logistic regression via gradient descent.

    Returns (W, B) where W is (n_features, n_classes) and B is (n_classes,).
    """
    n, d = X.shape
    W = np.zeros((d, n_classes), dtype=np.float64)
    B = np.zeros(n_classes, dtype=np.float64)

    # One-hot encode labels
    Y_onehot = np.eye(n_classes)[y]  # (n, n_classes)

    for epoch in range(epochs):
        logits = X @ W + B  # (n, n_classes)
        probs = softmax(logits)  # (n, n_classes)

        diff = probs - Y_onehot  # (n, n_classes)
        grad_W = (X.T @ diff) / n + reg * W  # (d, n_classes)
        grad_B = diff.mean(axis=0)  # (n_classes,)

        W -= lr * grad_W
        B -= lr * grad_B

        if verbose and (epoch + 1) % 500 == 0:
            loss = -np.mean(np.sum(Y_onehot * np.log(probs + 1e-8), axis=1))
            preds = probs.argmax(axis=1)
            acc = (preds == y).mean()
            print(f"  Epoch {epoch + 1}/{epochs} — loss: {loss:.4f}, acc: {acc:.1%}")

    return W, B


# ── Evaluation ───────────────────────────────────────────────────────


def evaluate_multiclass(
    X: np.ndarray, y: np.ndarray, W: np.ndarray, B: np.ndarray
) -> dict:
    """Compute per-class and overall metrics."""
    logits = X @ W + B
    probs = softmax(logits)
    preds = probs.argmax(axis=1)

    n_classes = W.shape[1]
    accuracy = (preds == y).mean()

    # Per-class precision, recall, F1
    per_class = {}
    for c in range(n_classes):
        tp = int(((preds == c) & (y == c)).sum())
        fp = int(((preds == c) & (y != c)).sum())
        fn = int(((preds != c) & (y == c)).sum())

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        per_class[CLASSES[c]] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": int((y == c).sum()),
        }

    # Confusion matrix
    confusion = np.zeros((n_classes, n_classes), dtype=int)
    for true, pred in zip(y, preds):
        confusion[true][pred] += 1

    # Macro F1
    macro_f1 = np.mean([pc["f1"] for pc in per_class.values()])

    return {
        "accuracy": float(accuracy),
        "macro_f1": float(macro_f1),
        "per_class": per_class,
        "confusion_matrix": confusion.tolist(),
        "n_samples": len(y),
    }


def stratified_kfold_multi(y: np.ndarray, k: int, n_classes: int, rng: np.random.Generator):
    """Generate k stratified fold indices for multi-class labels."""
    class_indices = [np.where(y == c)[0] for c in range(n_classes)]
    for ci in class_indices:
        rng.shuffle(ci)

    class_folds = [np.array_split(ci, k) for ci in class_indices]

    for i in range(k):
        test_idx = np.concatenate([cf[i] for cf in class_folds])
        train_parts = []
        for cf in class_folds:
            train_parts.extend([cf[j] for j in range(k) if j != i])
        train_idx = np.concatenate(train_parts)
        yield train_idx, test_idx


# ── Main ─────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Train 3-class stacking meta-learner for DENT forensic fusion"
    )
    parser.add_argument("--data", required=True, help="Path to labeled JSONL data")
    parser.add_argument("--output", default="", help="Output path for meta_weights.npz")
    parser.add_argument("--lr", type=float, default=0.05, help="Learning rate")
    parser.add_argument("--epochs", type=int, default=2000, help="Training epochs")
    parser.add_argument("--reg", type=float, default=0.0, help="Ridge lambda (0 = grid search)")
    parser.add_argument("--k-folds", type=int, default=5, help="CV folds")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--dry-run", action="store_true", help="Show metrics without saving")
    parser.add_argument("--compare", action="store_true", help="Compare with current fusion")

    args = parser.parse_args()

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

    X, y = build_feature_matrix(samples)
    n_classes = len(CLASSES)

    print(f"\nClass distribution:")
    for c in range(n_classes):
        count = int((y == c).sum())
        print(f"  {CLASSES[c]}: {count}")
    print(f"  Total: {len(y)}")
    print(f"Feature matrix: {X.shape[0]} x {X.shape[1]}")

    rng = np.random.default_rng(args.seed)

    # Lambda grid search
    if args.reg <= 0:
        lambdas = [0.001, 0.01, 0.1, 1.0]
        print("\n=== Lambda Grid Search ===")
        best_lambda = lambdas[0]
        best_f1 = -1.0

        for lam in lambdas:
            f1s = []
            for train_idx, test_idx in stratified_kfold_multi(y, args.k_folds, n_classes, rng):
                W, B = train_multinomial_logistic(
                    X[train_idx], y[train_idx], n_classes,
                    lr=args.lr, epochs=args.epochs, reg=lam, verbose=False,
                )
                metrics = evaluate_multiclass(X[test_idx], y[test_idx], W, B)
                f1s.append(metrics["macro_f1"])

            avg_f1 = np.mean(f1s)
            print(f"  lambda={lam:.3f}: avg macro-F1={avg_f1:.3f}")

            if avg_f1 > best_f1:
                best_f1 = avg_f1
                best_lambda = lam

        print(f"  Best: lambda={best_lambda} (macro-F1={best_f1:.3f})")
        reg = best_lambda
    else:
        reg = args.reg

    # Cross-validation
    print(f"\n=== {args.k_folds}-Fold CV (lambda={reg}) ===")
    cv_f1s = []
    cv_accs = []

    for fold, (train_idx, test_idx) in enumerate(
        stratified_kfold_multi(y, args.k_folds, n_classes, rng)
    ):
        W, B = train_multinomial_logistic(
            X[train_idx], y[train_idx], n_classes,
            lr=args.lr, epochs=args.epochs, reg=reg, verbose=False,
        )
        metrics = evaluate_multiclass(X[test_idx], y[test_idx], W, B)
        cv_f1s.append(metrics["macro_f1"])
        cv_accs.append(metrics["accuracy"])
        print(f"  Fold {fold + 1}: acc={metrics['accuracy']:.1%}, macro-F1={metrics['macro_f1']:.3f}")

    print(f"  Average: acc={np.mean(cv_accs):.1%}, macro-F1={np.mean(cv_f1s):.3f}")

    # Final training
    print(f"\n=== Final Training (all {len(y)} samples) ===")
    W_final, B_final = train_multinomial_logistic(
        X, y, n_classes, lr=args.lr, epochs=args.epochs, reg=reg, verbose=True,
    )
    final = evaluate_multiclass(X, y, W_final, B_final)
    print(f"\n  Accuracy: {final['accuracy']:.1%}, Macro-F1: {final['macro_f1']:.3f}")

    # Per-class metrics
    print("\n=== Per-Class Metrics ===")
    for cls_name, m in final["per_class"].items():
        print(f"  {cls_name:15s}: P={m['precision']:.3f}  R={m['recall']:.3f}  F1={m['f1']:.3f}  (n={m['support']})")

    # Confusion matrix
    print("\n=== Confusion Matrix ===")
    print(f"{'':15s}", end="")
    for c in CLASSES:
        print(f"{c[:8]:>10s}", end="")
    print()
    for i, row in enumerate(final["confusion_matrix"]):
        print(f"{CLASSES[i]:15s}", end="")
        for v in row:
            print(f"{v:10d}", end="")
        print()

    # Feature importance (per class)
    names = feature_names()
    print("\n=== Top-10 Features per Class ===")
    for c in range(n_classes):
        importance = sorted(
            zip(names, W_final[:, c]), key=lambda x: abs(x[1]), reverse=True
        )
        print(f"\n  {CLASSES[c]}:")
        for name, weight in importance[:10]:
            print(f"    {weight:+.4f}  {name}")

    # Save — for multinomial, save W (n_features, n_classes) and B (n_classes,)
    # For backward compat with binary meta-learner in fusion.py,
    # also save binary weights (ai_generated class = "manipulated" probability)
    if args.dry_run:
        logger.info("Dry run — not saving")
    else:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        # Binary compat: use ai_generated class weights as "manipulated" score
        # fusion.py expects (147,) weights and scalar bias
        ai_gen_idx = CLASS_TO_IDX["ai_generated"]
        binary_weights = W_final[:, ai_gen_idx]
        binary_bias = B_final[ai_gen_idx]

        np.savez(
            output_path,
            # Binary compat (used by current fusion.py)
            weights=binary_weights,
            bias=np.array([binary_bias]),
            module_order=np.array(MODULE_ORDER),
            feature_names=np.array(names),
            # Full multinomial (for future use)
            weights_multi=W_final,
            bias_multi=B_final,
            classes=np.array(CLASSES),
        )
        logger.info("Saved stacking meta weights to %s", output_path)
        print(f"\n  Binary compat: weights ({binary_weights.shape}), bias={binary_bias:.4f}")
        print(f"  Multinomial: W ({W_final.shape}), B ({B_final.shape})")
        print(f"  Classes: {CLASSES}")
        print(f"  To enable: set DENT_FORENSICS_STACKING_META_ENABLED=true")


if __name__ == "__main__":
    main()
