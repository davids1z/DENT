#!/usr/bin/env python3
"""Train a stacking meta-learner for DENT forensic score fusion.

Replaces hand-crafted override rules in fusion.py with a learned
logistic regression model using polynomial interaction features.

Usage:
    python -m scripts.train_stacking_meta \
        --data labeled_samples.jsonl \
        [--output /app/models/stacking_meta/meta_weights.npz] \
        [--reg 0.1] [--k-folds 5] [--dry-run]

Input format (JSONL):
    {"id": "s001", "ground_truth": "authentic", "modules": {"ai_generation_detection": {"risk_score": 0.12, "findings": [{"confidence": 0.8}]}, ...}}
    {"id": "s002", "ground_truth": "manipulated", "modules": {"clip_ai_detection": {"risk_score": 0.78, "findings": [{"confidence": 0.9}]}, ...}}
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# Allow running from ml-service root
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


# ── Data loading ─────────────────────────────────────────────────────


def load_labeled_data(path: str) -> list[dict]:
    """Load JSONL labeled samples."""
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
            if gt not in ("authentic", "manipulated"):
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

        # Build findings from the sample data
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
            # No findings data: synthetic finding with default confidence
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
    """Convert samples to feature matrix X and label vector y."""
    X = np.zeros((len(samples), N_FEATURES), dtype=np.float64)
    y = np.zeros(len(samples), dtype=np.float64)

    for i, sample in enumerate(samples):
        module_results = sample_to_module_results(sample)
        X[i] = extract_features(module_results)
        y[i] = 1.0 if sample["ground_truth"] == "manipulated" else 0.0

    return X, y


# ── Training ─────────────────────────────────────────────────────────


def train_ridge_logistic(
    X: np.ndarray,
    y: np.ndarray,
    lr: float = 0.05,
    epochs: int = 2000,
    reg: float = 0.1,
    verbose: bool = True,
) -> tuple[np.ndarray, float]:
    """Train binary logistic regression via gradient descent with L2 regularization.

    Follows the same pattern as train_clip_probe.py.
    """
    n, d = X.shape
    w = np.zeros(d)
    b = 0.0

    for epoch in range(epochs):
        logits = X @ w + b
        probs = 1.0 / (1.0 + np.exp(-np.clip(logits, -500, 500)))

        diff = probs - y
        grad_w = (X.T @ diff) / n + reg * w
        grad_b = diff.mean()

        w -= lr * grad_w
        b -= lr * grad_b

        if verbose and (epoch + 1) % 500 == 0:
            loss = -np.mean(y * np.log(probs + 1e-8) + (1 - y) * np.log(1 - probs + 1e-8))
            acc = ((probs > 0.5) == y).mean()
            print(f"  Epoch {epoch + 1}/{epochs} — loss: {loss:.4f}, acc: {acc:.1%}")

    return w, b


# ── Evaluation ───────────────────────────────────────────────────────


def cohens_kappa(preds: np.ndarray, labels: np.ndarray) -> float:
    """Cohen's Kappa for binary classification."""
    n = len(preds)
    if n == 0:
        return 0.0

    tp = int(np.sum((preds == 1) & (labels == 1)))
    tn = int(np.sum((preds == 0) & (labels == 0)))
    fp = int(np.sum((preds == 1) & (labels == 0)))
    fn = int(np.sum((preds == 0) & (labels == 1)))

    p_o = (tp + tn) / n
    p_yes = ((tp + fp) / n) * ((tp + fn) / n)
    p_no = ((tn + fn) / n) * ((tn + fp) / n)
    p_e = p_yes + p_no

    if p_e >= 1.0:
        return 1.0 if p_o >= 1.0 else 0.0
    return (p_o - p_e) / (1.0 - p_e)


def f1_score(preds: np.ndarray, labels: np.ndarray) -> float:
    """F1 score for binary classification."""
    tp = int(np.sum((preds == 1) & (labels == 1)))
    fp = int(np.sum((preds == 1) & (labels == 0)))
    fn = int(np.sum((preds == 0) & (labels == 1)))
    if tp == 0:
        return 0.0
    precision = tp / (tp + fp)
    recall = tp / (tp + fn)
    return 2 * precision * recall / (precision + recall)


def evaluate(X: np.ndarray, y: np.ndarray, w: np.ndarray, b: float) -> dict:
    """Compute evaluation metrics."""
    logits = X @ w + b
    probs = 1.0 / (1.0 + np.exp(-np.clip(logits, -500, 500)))
    preds = (probs > 0.5).astype(np.float64)

    return {
        "accuracy": float((preds == y).mean()),
        "f1": f1_score(preds, y),
        "kappa": cohens_kappa(preds, y),
        "n_samples": len(y),
    }


def stratified_kfold(y: np.ndarray, k: int, rng: np.random.Generator):
    """Generate k stratified fold indices."""
    pos_idx = np.where(y == 1)[0]
    neg_idx = np.where(y == 0)[0]

    rng.shuffle(pos_idx)
    rng.shuffle(neg_idx)

    pos_folds = np.array_split(pos_idx, k)
    neg_folds = np.array_split(neg_idx, k)

    for i in range(k):
        test_idx = np.concatenate([pos_folds[i], neg_folds[i]])
        train_idx = np.concatenate(
            [np.concatenate([pos_folds[j] for j in range(k) if j != i]),
             np.concatenate([neg_folds[j] for j in range(k) if j != i])]
        )
        yield train_idx, test_idx


# ── Main ─────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Train stacking meta-learner for DENT forensic fusion"
    )
    parser.add_argument("--data", required=True, help="Path to labeled JSONL data")
    parser.add_argument(
        "--output",
        default="",
        help="Output path for meta_weights.npz (default: auto-detect model cache)",
    )
    parser.add_argument("--lr", type=float, default=0.05, help="Learning rate (default: 0.05)")
    parser.add_argument("--epochs", type=int, default=2000, help="Training epochs (default: 2000)")
    parser.add_argument("--reg", type=float, default=0.0, help="Ridge lambda (0 = grid search)")
    parser.add_argument("--k-folds", type=int, default=5, help="CV folds (default: 5)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("--dry-run", action="store_true", help="Show metrics without saving")

    args = parser.parse_args()

    # Resolve output path
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
        logger.error("Need at least 10 labeled samples, got %d", len(samples))
        sys.exit(1)

    X, y = build_feature_matrix(samples)
    n_pos = int(y.sum())
    n_neg = len(y) - n_pos
    logger.info("Class distribution: %d manipulated, %d authentic", n_pos, n_neg)
    logger.info("Feature matrix: %d samples x %d features", X.shape[0], X.shape[1])

    rng = np.random.default_rng(args.seed)

    # ── Lambda grid search (if reg=0) ────────────────────────────────
    if args.reg <= 0:
        lambdas = [0.001, 0.01, 0.1, 1.0]
        print("\n=== Lambda Grid Search (k-fold CV) ===")
        best_lambda = lambdas[0]
        best_kappa = -1.0

        for lam in lambdas:
            kappas = []
            for train_idx, test_idx in stratified_kfold(y, args.k_folds, rng):
                w, b = train_ridge_logistic(
                    X[train_idx], y[train_idx],
                    lr=args.lr, epochs=args.epochs, reg=lam, verbose=False,
                )
                metrics = evaluate(X[test_idx], y[test_idx], w, b)
                kappas.append(metrics["kappa"])

            avg_kappa = np.mean(kappas)
            print(f"  lambda={lam:.3f}: avg Kappa={avg_kappa:.3f} (folds: {[f'{k:.3f}' for k in kappas]})")

            if avg_kappa > best_kappa:
                best_kappa = avg_kappa
                best_lambda = lam

        print(f"\n  Best lambda: {best_lambda} (avg Kappa={best_kappa:.3f})")
        reg = best_lambda
    else:
        reg = args.reg

    # ── Cross-validation ─────────────────────────────────────────────
    print(f"\n=== {args.k_folds}-Fold Cross-Validation (lambda={reg}) ===")
    cv_metrics = {"accuracy": [], "f1": [], "kappa": []}

    for fold, (train_idx, test_idx) in enumerate(stratified_kfold(y, args.k_folds, rng)):
        w, b = train_ridge_logistic(
            X[train_idx], y[train_idx],
            lr=args.lr, epochs=args.epochs, reg=reg, verbose=False,
        )
        metrics = evaluate(X[test_idx], y[test_idx], w, b)
        for k, v in metrics.items():
            if k in cv_metrics:
                cv_metrics[k].append(v)
        print(f"  Fold {fold + 1}: acc={metrics['accuracy']:.1%}, F1={metrics['f1']:.3f}, κ={metrics['kappa']:.3f}")

    print(f"\n  Average: acc={np.mean(cv_metrics['accuracy']):.1%}, "
          f"F1={np.mean(cv_metrics['f1']):.3f}, κ={np.mean(cv_metrics['kappa']):.3f}")

    # ── Final training on all data ───────────────────────────────────
    print(f"\n=== Final Training (all {len(y)} samples, lambda={reg}) ===")
    w_final, b_final = train_ridge_logistic(
        X, y, lr=args.lr, epochs=args.epochs, reg=reg, verbose=True,
    )
    final_metrics = evaluate(X, y, w_final, b_final)
    print(f"\n  Final (in-sample): acc={final_metrics['accuracy']:.1%}, "
          f"F1={final_metrics['f1']:.3f}, κ={final_metrics['kappa']:.3f}")

    # ── Feature importance ───────────────────────────────────────────
    names = feature_names()
    importance = sorted(
        zip(names, w_final), key=lambda x: abs(x[1]), reverse=True
    )
    print("\n=== Top-20 Features by Weight Magnitude ===")
    for name, weight in importance[:20]:
        print(f"  {weight:+.4f}  {name}")

    # ── Save ─────────────────────────────────────────────────────────
    if args.dry_run:
        logger.info("Dry run — not writing output file")
    else:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        np.savez(
            output_path,
            weights=w_final,
            bias=np.array([b_final]),
            module_order=np.array(MODULE_ORDER),
            feature_names=np.array(names),
        )
        logger.info("Saved stacking meta weights to %s", output_path)
        print(f"\n  Weights shape: {w_final.shape}, bias: {b_final:.4f}")
        print(f"  To enable: set DENT_FORENSICS_STACKING_META_ENABLED=true")


if __name__ == "__main__":
    main()
