#!/usr/bin/env python3
"""Derive calibrated_thresholds.json from production stats.

Reads data/production_stats_v1.json and writes a JSON file that overrides
the hand-tuned defaults in app/forensics/thresholds.py. The threshold
registry already supports loading this file via DENT_FORENSICS_CALIBRATION_FILE
or /app/config/calibrated_thresholds.json.

Strategy
--------
For each threshold, derive its value from a percentile of the corresponding
production statistic. This guarantees the thresholds reflect the actual
production score distribution, not synthetic ProGAN-era expectations.

  cnn_dampening_threshold  ← p75 of auth_max_independent
                              (75% of authentic photos have max < this)
  independent_confirm      ← p95 of auth_pixel_forensics
                              (only 5% of authentic pixel scores reach this)
  risk_medium / risk_high  ← derived from sweep on training data
  boost_moderate_floor     ← keep default 0.65 unless data says otherwise
"""
import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))


def _sweep_threshold(rows: list[dict], score_key: str = "overall_risk_score") -> tuple[float, float, dict]:
    """Find the threshold that maximizes balanced accuracy on the input rows.

    Returns (best_threshold, balanced_acc, metrics_at_best).
    """
    best_t, best_ba = 0.40, 0.0
    best_metrics: dict = {}
    for t10 in range(15, 65):  # 0.15 to 0.65 in 0.01 steps
        t = t10 / 100.0
        tp = fp = tn = fn = 0
        for r in rows:
            score = float(r.get(score_key, 0.0))
            truth = r.get("ground_truth", "authentic")
            pred_ai = score >= t
            if truth == "ai_generated":
                if pred_ai:
                    tp += 1
                else:
                    fn += 1
            else:
                if pred_ai:
                    fp += 1
                else:
                    tn += 1
        sens = tp / max(tp + fn, 1)
        spec = tn / max(tn + fp, 1)
        ba = (sens + spec) / 2
        if ba > best_ba:
            best_ba = ba
            best_t = t
            best_metrics = {
                "threshold": t,
                "balanced_acc": ba,
                "sensitivity": sens,
                "specificity": spec,
                "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            }
    return best_t, best_ba, best_metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stats", required=True, help="data/production_stats_v1.json")
    parser.add_argument("--train-jsonl", required=True, help="data/production_train_v1.jsonl (for threshold sweep)")
    parser.add_argument("--output", required=True, help="services/ml-service/config/calibrated_thresholds.json")
    args = parser.parse_args()

    with open(args.stats) as f:
        stats = json.load(f)
    with open(args.train_jsonl) as f:
        train_rows = [json.loads(line) for line in f if line.strip()]

    derived = stats["derived"]

    # Sweep risk_high threshold for the baseline rule-based fusion
    best_t, best_ba, sweep_metrics = _sweep_threshold(train_rows)

    # Build calibrated thresholds dict matching FusionThresholds dataclass schema
    fusion_overrides = {
        # CNN dampening: kick in below p75 of authentic max-independent.
        # Production p75 = 0.22, much lower than the hand-tuned 0.35.
        # This means most authentic photos will trigger DINOv2 dampening,
        # exactly what we want.
        "cnn_dampening_threshold": round(max(0.20, derived["auth_max_independent_p75"]), 2),
        # Floor: keep at 0.30 (how aggressively to dampen).
        "cnn_dampening_floor": 0.30,

        # Independent confirm: pixel/organika must beat 95% of authentic
        # pixel scores to count as confirmation.
        "independent_confirm": round(max(0.20, derived["auth_pixel_p95"]), 2),

        # Detector "high": cap at 0.50. The raw production p90 is 0.85
        # because of historical bimodal data (some authentic photos got
        # bogus 90% scores from the old broken pipeline). Trusting that
        # number would push the high-detector bar above any realistic
        # signal. Keep within [0.40, 0.50].
        "detector_high": round(min(0.50, max(0.40, derived["auth_max_independent_p90"])), 2),
        "detector_low": 0.15,

        # Risk band boundary: derived from the sweep on training data
        "risk_medium": round(max(0.15, best_t - 0.20), 2),
        "risk_high":   round(max(0.30, best_t), 2),
        "risk_critical": 0.85,

        # Keep boost floors but document the choice
        "boost_strong_floor": 0.75,
        "boost_strong_min_high": 2,
        "boost_moderate_floor": 0.55,   # lowered from 0.65 - production shows
                                         # the moderate band needs more headroom
        "boost_moderate_min_high": 1,
    }

    # Wrap in the schema FusionThresholds expects (top-level "fusion" key)
    config = {
        "fusion": fusion_overrides,
        "_metadata": {
            "source": "scripts/derive_calibrated_thresholds.py",
            "stats_file": args.stats,
            "train_jsonl": args.train_jsonl,
            "n_train_rows": len(train_rows),
            "best_threshold_sweep": sweep_metrics,
            "production_p75_max_indep": derived["auth_max_independent_p75"],
            "production_p95_pixel": derived["auth_pixel_p95"],
            "note": (
                "These thresholds are derived from production statistics in "
                "production_stats_v1.json. Re-derive whenever the production "
                "data distribution shifts (e.g., new generators in production)."
            ),
        },
    }

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(config, f, indent=2)

    print(f"=== CALIBRATED THRESHOLDS ===")
    print(f"Train rows used for sweep: {len(train_rows)}")
    print()
    print(f"Threshold sweep best:")
    for k, v in sweep_metrics.items():
        if isinstance(v, float):
            print(f"  {k:20} = {v:.4f}")
        else:
            print(f"  {k:20} = {v}")
    print()
    print(f"Fusion overrides:")
    for k, v in fusion_overrides.items():
        print(f"  {k:30} = {v}")
    print()
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
