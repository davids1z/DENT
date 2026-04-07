#!/usr/bin/env python3
"""Split a labeled production JSONL into train + holdout sets.

Strategy:
  - Sort by created_at
  - Take the OLDEST 80% as train (these were processed by older pipeline
    versions and capture historical FP/FN modes the meta-learner needs)
  - Take the NEWEST 20% as holdout (these are the most recent production
    state and most representative of what we're deploying against)
  - Stratify by ground_truth so both classes are represented in both splits
"""
import argparse
import json
import os
from collections import defaultdict


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--train-out", required=True)
    parser.add_argument("--holdout-out", required=True)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    args = parser.parse_args()

    rows = []
    with open(args.input) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    # Group by class
    by_class = defaultdict(list)
    for r in rows:
        by_class[r.get("ground_truth", "authentic")].append(r)

    # Sort each class by created_at (oldest first)
    for cls in by_class:
        by_class[cls].sort(key=lambda r: r.get("created_at", ""))

    train, holdout = [], []
    for cls, items in by_class.items():
        n = len(items)
        n_holdout = max(1, int(round(n * args.holdout_fraction)))
        n_train = n - n_holdout
        train.extend(items[:n_train])
        holdout.extend(items[n_train:])

    # Restore time order in each split
    train.sort(key=lambda r: r.get("created_at", ""))
    holdout.sort(key=lambda r: r.get("created_at", ""))

    os.makedirs(os.path.dirname(args.train_out) or ".", exist_ok=True)
    with open(args.train_out, "w") as f:
        for r in train:
            f.write(json.dumps(r) + "\n")
    with open(args.holdout_out, "w") as f:
        for r in holdout:
            f.write(json.dumps(r) + "\n")

    from collections import Counter
    print(f"Train:   {len(train)} rows → {args.train_out}")
    print(f"  classes: {dict(Counter(r['ground_truth'] for r in train))}")
    print(f"Holdout: {len(holdout)} rows → {args.holdout_out}")
    print(f"  classes: {dict(Counter(r['ground_truth'] for r in holdout))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
