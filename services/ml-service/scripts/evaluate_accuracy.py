#!/usr/bin/env python3
"""
Evaluate DENT forensic pipeline accuracy on labeled dataset.

Reads labeled_dataset.jsonl (output of build_calibration_dataset.py) OR
runs live evaluation against the API using S3 images + labels.csv.

Computes: F1, Precision, Recall, AUC, Confusion Matrix — both binary
(authentic vs manipulated) and 3-class (authentic/ai_generated/tampered).

Also computes per-module accuracy to identify which modules help vs hurt.

Usage:
  # From existing JSONL (fast, no API calls):
  python -m scripts.evaluate_accuracy --jsonl data/labeled_dataset.jsonl

  # Live evaluation against running API (slow, reprocesses images):
  python -m scripts.evaluate_accuracy \
    --bucket dent-calibration-data \
    --api-url http://localhost:8000 \
    --sample 200

  # Compare two JSONL files (before/after model upgrade):
  python -m scripts.evaluate_accuracy \
    --jsonl data/labeled_dataset_v5.jsonl \
    --compare data/labeled_dataset_v6.jsonl
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
from pathlib import Path

import numpy as np


def load_jsonl(path: str) -> list[dict]:
    """Load labeled dataset from JSONL file."""
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def compute_metrics(
    y_true: list[int],
    y_pred: list[int],
    y_scores: list[float],
    class_names: list[str],
) -> dict:
    """Compute classification metrics without sklearn."""
    n = len(y_true)
    if n == 0:
        return {"error": "no samples"}

    n_classes = len(class_names)

    # Confusion matrix
    cm = [[0] * n_classes for _ in range(n_classes)]
    for t, p in zip(y_true, y_pred):
        cm[t][p] += 1

    # Per-class precision, recall, F1
    per_class = {}
    for i, name in enumerate(class_names):
        tp = cm[i][i]
        fp = sum(cm[j][i] for j in range(n_classes)) - tp
        fn = sum(cm[i][j] for j in range(n_classes)) - tp
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        per_class[name] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": sum(cm[i]),
        }

    # Macro averages
    macro_p = np.mean([v["precision"] for v in per_class.values()])
    macro_r = np.mean([v["recall"] for v in per_class.values()])
    macro_f1 = np.mean([v["f1"] for v in per_class.values()])

    # Accuracy
    correct = sum(cm[i][i] for i in range(n_classes))
    accuracy = correct / n

    # Binary AUC (approximate via trapezoid on sorted scores)
    auc = _compute_auc(y_true, y_scores) if n_classes == 2 else None

    return {
        "accuracy": round(accuracy, 4),
        "macro_precision": round(macro_p, 4),
        "macro_recall": round(macro_r, 4),
        "macro_f1": round(macro_f1, 4),
        "auc": round(auc, 4) if auc is not None else None,
        "per_class": per_class,
        "confusion_matrix": cm,
        "n_samples": n,
    }


def _compute_auc(y_true: list[int], y_scores: list[float]) -> float:
    """Compute AUC-ROC for binary classification."""
    pairs = sorted(zip(y_scores, y_true), reverse=True)
    tp = fp = 0
    prev_score = None
    tpr_points = []
    fpr_points = []
    total_pos = sum(y_true)
    total_neg = len(y_true) - total_pos
    if total_pos == 0 or total_neg == 0:
        return 0.5

    for score, label in pairs:
        if score != prev_score and prev_score is not None:
            tpr_points.append(tp / total_pos)
            fpr_points.append(fp / total_neg)
        if label == 1:
            tp += 1
        else:
            fp += 1
        prev_score = score

    tpr_points.append(tp / total_pos)
    fpr_points.append(fp / total_neg)

    # Trapezoid AUC
    auc = 0.0
    for i in range(1, len(fpr_points)):
        auc += (fpr_points[i] - fpr_points[i - 1]) * (tpr_points[i] + tpr_points[i - 1]) / 2
    return auc


def evaluate_jsonl(records: list[dict], threshold: float = 0.50) -> dict:
    """Evaluate accuracy from JSONL records."""
    # Binary: authentic=0, manipulated(ai_generated|tampered)=1
    binary_true = []
    binary_pred = []
    binary_scores = []

    # 3-class: authentic=0, ai_generated=1, tampered=2
    class3_true = []
    class3_pred = []
    class3_map = {"authentic": 0, "ai_generated": 1, "tampered": 2}

    # Per-module stats
    module_scores: dict[str, list[tuple[float, int]]] = {}  # module -> [(score, is_manipulated)]

    for rec in records:
        gt = rec.get("ground_truth", "")
        if gt not in class3_map:
            continue

        overall = rec.get("overall_risk_score", 0)

        # Binary
        is_manip = 0 if gt == "authentic" else 1
        binary_true.append(is_manip)
        binary_pred.append(1 if overall >= threshold else 0)
        binary_scores.append(overall)

        # 3-class (use verdict_probabilities if available, else overall)
        class3_true.append(class3_map[gt])
        vp = rec.get("verdict_probabilities")
        if vp and all(k in vp for k in ("authentic", "ai_generated", "tampered")):
            pred_class = max(vp, key=vp.get)
            class3_pred.append(class3_map.get(pred_class, 0))
        else:
            # Fallback: binary prediction mapped to most likely class
            if overall >= threshold:
                # Check if AI or tampering signal is stronger
                modules = rec.get("modules", {})
                ai_score = max(
                    modules.get("ai_generation_detection", {}).get("risk_score", 0),
                    modules.get("community_forensics_detection", {}).get("risk_score", 0),
                    modules.get("clip_ai_detection", {}).get("risk_score", 0),
                )
                tamp_score = max(
                    modules.get("deep_modification_detection", {}).get("risk_score", 0),
                    modules.get("mesorch_detection", {}).get("risk_score", 0),
                    modules.get("modification_detection", {}).get("risk_score", 0),
                )
                class3_pred.append(1 if ai_score >= tamp_score else 2)
            else:
                class3_pred.append(0)

        # Per-module accuracy
        modules = rec.get("modules", {})
        for mod_name, mod_data in modules.items():
            if mod_name not in module_scores:
                module_scores[mod_name] = []
            score = mod_data.get("risk_score", 0) if isinstance(mod_data, dict) else 0
            module_scores[mod_name].append((score, is_manip))

    # Compute metrics
    binary_metrics = compute_metrics(
        binary_true, binary_pred, binary_scores,
        ["authentic", "manipulated"],
    )

    class3_metrics = compute_metrics(
        class3_true, class3_pred, binary_scores,
        ["authentic", "ai_generated", "tampered"],
    )

    # Per-module binary accuracy (each module independently)
    module_metrics = {}
    for mod_name, scores_labels in sorted(module_scores.items()):
        mod_true = [lab for _, lab in scores_labels]
        mod_scores = [s for s, _ in scores_labels]
        mod_pred = [1 if s >= threshold else 0 for s in mod_scores]
        n = len(mod_true)
        correct = sum(1 for t, p in zip(mod_true, mod_pred) if t == p)
        acc = correct / n if n > 0 else 0
        avg_score_auth = np.mean([s for s, l in scores_labels if l == 0]) if any(l == 0 for _, l in scores_labels) else 0
        avg_score_manip = np.mean([s for s, l in scores_labels if l == 1]) if any(l == 1 for _, l in scores_labels) else 0
        module_metrics[mod_name] = {
            "accuracy": round(acc, 4),
            "avg_score_authentic": round(float(avg_score_auth), 4),
            "avg_score_manipulated": round(float(avg_score_manip), 4),
            "separation": round(float(avg_score_manip - avg_score_auth), 4),
            "n_samples": n,
        }

    return {
        "binary": binary_metrics,
        "three_class": class3_metrics,
        "per_module": module_metrics,
        "threshold": threshold,
    }


def print_report(results: dict, label: str = "") -> None:
    """Pretty-print evaluation results."""
    if label:
        print(f"\n{'=' * 60}")
        print(f"  {label}")
        print(f"{'=' * 60}")

    binary = results["binary"]
    if "error" in binary:
        print(f"\n  No samples to evaluate: {binary['error']}")
        return
    print(f"\n--- Binary (authentic vs manipulated) ---")
    print(f"  Accuracy:  {binary['accuracy']:.1%}")
    print(f"  Macro F1:  {binary['macro_f1']:.4f}")
    print(f"  Macro P:   {binary['macro_precision']:.4f}")
    print(f"  Macro R:   {binary['macro_recall']:.4f}")
    if binary.get("auc") is not None:
        print(f"  AUC-ROC:   {binary['auc']:.4f}")
    print(f"  Samples:   {binary['n_samples']}")

    cm = binary["confusion_matrix"]
    print(f"\n  Confusion Matrix:")
    print(f"                 Pred Auth  Pred Manip")
    print(f"  True Auth      {cm[0][0]:>6}     {cm[0][1]:>6}")
    print(f"  True Manip     {cm[1][0]:>6}     {cm[1][1]:>6}")

    three = results["three_class"]
    print(f"\n--- 3-Class (authentic / ai_generated / tampered) ---")
    print(f"  Accuracy:  {three['accuracy']:.1%}")
    print(f"  Macro F1:  {three['macro_f1']:.4f}")
    for name, m in three["per_class"].items():
        print(f"    {name:20s}: P={m['precision']:.3f} R={m['recall']:.3f} F1={m['f1']:.3f} (n={m['support']})")

    print(f"\n--- Per-Module Binary Accuracy ---")
    print(f"  {'Module':<40s} {'Acc':>6s} {'AvgAuth':>8s} {'AvgManip':>9s} {'Sep':>6s}")
    for mod_name, m in sorted(results["per_module"].items(), key=lambda x: -x[1]["separation"]):
        print(
            f"  {mod_name:<40s} {m['accuracy']:>5.1%} "
            f"{m['avg_score_authentic']:>8.3f} {m['avg_score_manipulated']:>9.3f} "
            f"{m['separation']:>+6.3f}"
        )

    print(f"\n  Threshold: {results['threshold']}")


def live_evaluate(
    bucket: str,
    api_url: str,
    region: str,
    sample: int | None,
    skip_gemini: bool,
) -> list[dict]:
    """Run live evaluation against API using S3 images."""
    import boto3
    import requests

    s3 = boto3.client("s3", region_name=region)

    # Load labels
    key = "processed/labels.csv"
    resp = s3.get_object(Bucket=bucket, Key=key)
    content = resp["Body"].read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    labels = {}
    for row in reader:
        fn = row.get("filename", "").strip()
        gt = row.get("ground_truth", "").strip().lower()
        if fn and gt in {"authentic", "ai_generated", "tampered"}:
            labels[fn] = gt

    items = list(labels.items())
    if sample and sample < len(items):
        import random
        random.seed(42)
        random.shuffle(items)
        items = items[:sample]

    print(f"Evaluating {len(items)} images against {api_url}...")

    skip_modules = "semantic_forensics" if skip_gemini else None
    records = []

    for i, (fn, gt) in enumerate(items):
        s3_key = f"processed/{fn}"
        try:
            img_resp = s3.get_object(Bucket=bucket, Key=s3_key)
            img_bytes = img_resp["Body"].read()
        except Exception as e:
            print(f"  [{i+1}/{len(items)}] SKIP {fn}: {e}")
            continue

        params = {}
        if skip_modules:
            params["skip_modules"] = skip_modules

        try:
            resp = requests.post(
                f"{api_url}/forensics",
                files={"file": (fn, io.BytesIO(img_bytes))},
                params=params,
                timeout=600,
            )
            if resp.status_code != 200:
                print(f"  [{i+1}/{len(items)}] HTTP {resp.status_code} for {fn}")
                continue
            report = resp.json()
        except Exception as e:
            print(f"  [{i+1}/{len(items)}] ERROR {fn}: {e}")
            continue

        # Build JSONL-compatible record
        modules_data = {}
        for mod in report.get("modules", []):
            mod_name = mod.get("module_name", mod.get("moduleName", ""))
            if mod_name:
                modules_data[mod_name] = {
                    "risk_score": mod.get("risk_score", mod.get("riskScore", 0)),
                    "findings": mod.get("findings", []),
                }

        record = {
            "id": fn,
            "ground_truth": gt,
            "overall_risk_score": report.get("overall_risk_score", report.get("overallRiskScore", 0)),
            "modules": modules_data,
            "verdict_probabilities": report.get("verdict_probabilities", report.get("verdictProbabilities")),
        }
        records.append(record)

        overall = record["overall_risk_score"]
        status = "OK" if (gt == "authentic") == (overall < 0.5) else "WRONG"
        print(f"  [{i+1}/{len(items)}] {status} {fn}: gt={gt} score={overall:.3f}")

    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate DENT accuracy")
    parser.add_argument("--jsonl", help="Path to labeled_dataset.jsonl")
    parser.add_argument("--compare", help="Second JSONL for before/after comparison")
    parser.add_argument("--bucket", help="S3 bucket for live evaluation")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--region", default="eu-central-1")
    parser.add_argument("--sample", type=int, help="Max images for live eval")
    parser.add_argument("--threshold", type=float, default=0.50)
    parser.add_argument("--skip-gemini", action="store_true", default=True)
    parser.add_argument("--output", help="Save evaluation JSONL (live mode)")
    args = parser.parse_args()

    if args.jsonl:
        records = load_jsonl(args.jsonl)
        print(f"Loaded {len(records)} records from {args.jsonl}")
        results = evaluate_jsonl(records, args.threshold)
        print_report(results, label=args.jsonl)

        if args.compare:
            records2 = load_jsonl(args.compare)
            print(f"\nLoaded {len(records2)} records from {args.compare}")
            results2 = evaluate_jsonl(records2, args.threshold)
            print_report(results2, label=args.compare)

            # Delta
            print(f"\n{'=' * 60}")
            print(f"  DELTA: {args.compare} vs {args.jsonl}")
            print(f"{'=' * 60}")
            for metric in ["accuracy", "macro_f1", "macro_precision", "macro_recall", "auc"]:
                v1 = results["binary"].get(metric)
                v2 = results2["binary"].get(metric)
                if v1 is not None and v2 is not None:
                    delta = v2 - v1
                    print(f"  Binary {metric}: {v1:.4f} → {v2:.4f} ({delta:+.4f})")

    elif args.bucket:
        records = live_evaluate(
            args.bucket, args.api_url, args.region,
            args.sample, args.skip_gemini,
        )
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                for rec in records:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"\nSaved {len(records)} records to {args.output}")

        results = evaluate_jsonl(records, args.threshold)
        print_report(results, label=f"Live eval ({args.bucket}, n={len(records)})")

    else:
        parser.error("Specify --jsonl or --bucket")


if __name__ == "__main__":
    main()
