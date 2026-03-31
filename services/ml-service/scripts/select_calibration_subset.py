#!/usr/bin/env python3
"""Select optimal calibration subset using active learning + stratified sampling.

Reads vast.ai JSONL (64K images with partial modules) and picks ~5K images
that are most useful for meta-learner training:

1. HIGH DISAGREEMENT — images where modules disagree (most informative)
2. BOUNDARY CASES — images near decision threshold (0.25-0.75 overall)
3. STRATIFIED — balanced across classes (auth/AI/tampered)
4. EASY ANCHORS — some clearly authentic + clearly AI for baseline

These 5K images will be re-run through production server (all modules)
to get SPAI/bfree/metadata scores that vast.ai couldn't provide.

Usage:
    python3 scripts/select_calibration_subset.py \
        --input data/labeled_dataset_v8_fixed.jsonl \
        --output data/calibration_subset_5k.txt \
        --n 5000
"""

import argparse
import json
import random
import sys
from collections import defaultdict


def compute_disagreement(modules: dict) -> float:
    """Compute disagreement score: high when detectors conflict."""
    ai_detectors = [
        "clip_ai_detection", "dinov2_ai_detection", "community_forensics_detection",
        "safe_ai_detection", "spai_detection", "bfree_detection",
    ]
    scores = []
    for det in ai_detectors:
        if det in modules:
            scores.append(modules[det].get("risk_score", 0.0))

    if len(scores) < 2:
        return 0.0

    # Disagreement = variance of scores (high when some say AI, others don't)
    mean = sum(scores) / len(scores)
    variance = sum((s - mean) ** 2 for s in scores) / len(scores)
    return variance


def compute_uncertainty(modules: dict) -> float:
    """Compute uncertainty: highest when overall score is near 0.5."""
    scores = [m.get("risk_score", 0.0) for m in modules.values() if m.get("risk_score", 0.0) > 0]
    if not scores:
        return 0.0
    avg = sum(scores) / len(scores)
    # Uncertainty peaks at 0.5
    return 1.0 - abs(avg - 0.5) * 2


def main():
    parser = argparse.ArgumentParser(description="Select optimal calibration subset")
    parser.add_argument("--input", required=True, help="Vast.ai JSONL with partial modules")
    parser.add_argument("--output", required=True, help="Output: list of image filenames (one per line)")
    parser.add_argument("--n", type=int, default=5000, help="Number of images to select")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)

    # Load all records
    records = []
    with open(args.input) as f:
        for line in f:
            r = json.loads(line.strip())
            r["_disagreement"] = compute_disagreement(r.get("modules", {}))
            r["_uncertainty"] = compute_uncertainty(r.get("modules", {}))
            records.append(r)

    print(f"Loaded {len(records)} records")

    # Group by class
    by_class = defaultdict(list)
    for r in records:
        by_class[r["ground_truth"]].append(r)

    print(f"Classes: {', '.join(f'{k}={len(v)}' for k, v in sorted(by_class.items()))}")

    # Target per class (balanced)
    n_per_class = args.n // 3
    remainder = args.n - n_per_class * 3

    selected = []

    for cls in ["authentic", "ai_generated", "tampered"]:
        pool = by_class[cls]
        target = n_per_class + (1 if remainder > 0 else 0)
        remainder -= 1

        # Sort by disagreement + uncertainty (most informative first)
        pool.sort(key=lambda r: r["_disagreement"] + r["_uncertainty"], reverse=True)

        # Take 60% high-disagreement, 20% boundary, 20% easy anchors
        n_disagree = int(target * 0.6)
        n_boundary = int(target * 0.2)
        n_easy = target - n_disagree - n_boundary

        # High disagreement (top by disagreement score)
        disagree_picks = pool[:n_disagree]

        # Boundary cases (overall score 0.25-0.75)
        boundary_pool = [r for r in pool[n_disagree:] if 0.25 <= r.get("overall_risk_score", 0) <= 0.75]
        boundary_picks = boundary_pool[:n_boundary]
        if len(boundary_picks) < n_boundary:
            # Fill from remaining high-disagreement
            boundary_picks += pool[n_disagree:n_disagree + n_boundary - len(boundary_picks)]

        # Easy anchors (very high or very low scores — clear cases)
        remaining = [r for r in pool if r not in set(map(id, disagree_picks + boundary_picks))]
        if cls == "authentic":
            # Easy authentic = very low overall risk
            remaining.sort(key=lambda r: r.get("overall_risk_score", 0))
        else:
            # Easy AI/tampered = very high overall risk
            remaining.sort(key=lambda r: -r.get("overall_risk_score", 0))
        easy_picks = remaining[:n_easy]

        cls_selected = disagree_picks + boundary_picks + easy_picks
        selected.extend(cls_selected)
        print(f"  {cls}: {len(cls_selected)} selected "
              f"(disagree={len(disagree_picks)}, boundary={len(boundary_picks)}, easy={len(easy_picks)})")

    # Deduplicate by ID
    seen = set()
    unique = []
    for r in selected:
        rid = r["id"]
        if rid not in seen:
            seen.add(rid)
            unique.append(r)

    # If dedup reduced count, fill from remaining high-disagreement
    if len(unique) < args.n:
        all_remaining = [r for r in records if r["id"] not in seen]
        all_remaining.sort(key=lambda r: r["_disagreement"] + r["_uncertainty"], reverse=True)
        for r in all_remaining:
            if len(unique) >= args.n:
                break
            unique.append(r)
            seen.add(r["id"])

    selected = unique[:args.n]

    # Stats
    print(f"\nFinal selection: {len(selected)} images")
    class_counts = defaultdict(int)
    for r in selected:
        class_counts[r["ground_truth"]] += 1
    for cls, cnt in sorted(class_counts.items()):
        print(f"  {cls}: {cnt}")

    avg_disagree = sum(r["_disagreement"] for r in selected) / len(selected)
    avg_uncertainty = sum(r["_uncertainty"] for r in selected) / len(selected)
    print(f"  Avg disagreement: {avg_disagree:.4f}")
    print(f"  Avg uncertainty: {avg_uncertainty:.4f}")

    # Write filenames
    with open(args.output, "w") as f:
        for r in selected:
            f.write(r["id"] + "\n")

    print(f"\nWrote {len(selected)} filenames to {args.output}")


if __name__ == "__main__":
    main()
