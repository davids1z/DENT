#!/usr/bin/env python3
"""Compute per-module score distribution on production training data,
split by ground-truth class.

Output is consumed by derive_calibrated_thresholds.py to produce
/app/config/calibrated_thresholds.json that overrides hand-tuned defaults.

Usage:
  python -m scripts.compute_production_stats \
      --input data/production_train_v1.jsonl \
      --output data/production_stats_v1.json
"""
import argparse
import json
import statistics
from collections import defaultdict


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))
    return s[k]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    rows = []
    with open(args.input) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    # Per-class, per-module score lists
    by_class_module: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    overall_by_class: dict[str, list[float]] = defaultdict(list)

    for row in rows:
        cls = row.get("ground_truth", "authentic")
        overall_by_class[cls].append(row.get("overall_risk_score", 0.0))
        for mod_name, mod in (row.get("modules") or {}).items():
            by_class_module[cls][mod_name].append(float(mod.get("risk_score", 0.0)))

    def _stats(values: list[float]) -> dict:
        if not values:
            return {"n": 0}
        return {
            "n": len(values),
            "mean": round(statistics.mean(values), 4),
            "stdev": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
            "min": round(min(values), 4),
            "p10": round(_percentile(values, 0.10), 4),
            "p25": round(_percentile(values, 0.25), 4),
            "p50": round(_percentile(values, 0.50), 4),
            "p75": round(_percentile(values, 0.75), 4),
            "p90": round(_percentile(values, 0.90), 4),
            "p95": round(_percentile(values, 0.95), 4),
            "p99": round(_percentile(values, 0.99), 4),
            "max": round(max(values), 4),
        }

    report: dict = {
        "n_rows": len(rows),
        "n_authentic": len(overall_by_class.get("authentic", [])),
        "n_ai": len(overall_by_class.get("ai_generated", [])),
        "n_tampered": len(overall_by_class.get("tampered", [])),
        "overall_score": {
            cls: _stats(values) for cls, values in overall_by_class.items()
        },
        "modules": {},
    }

    all_modules = set()
    for cls_data in by_class_module.values():
        all_modules.update(cls_data.keys())

    for mod in sorted(all_modules):
        report["modules"][mod] = {
            cls: _stats(by_class_module[cls].get(mod, []))
            for cls in by_class_module.keys()
        }

    # Compute the key derived statistics needed for calibration
    auth_clip = by_class_module["authentic"].get("clip_ai_detection", [])
    auth_organika = by_class_module["authentic"].get("organika_ai_detection", [])
    auth_pixel = by_class_module["authentic"].get("pixel_forensics", [])
    auth_dinov2 = by_class_module["authentic"].get("dinov2_ai_detection", [])

    # max_independent on each authentic row
    max_independent = []
    for row in rows:
        if row.get("ground_truth") != "authentic":
            continue
        mods = row.get("modules") or {}
        scores = [
            float(mods.get("clip_ai_detection", {}).get("risk_score", 0)),
            float(mods.get("organika_ai_detection", {}).get("risk_score", 0)),
            float(mods.get("pixel_forensics", {}).get("risk_score", 0)),
        ]
        max_independent.append(max(scores))

    report["derived"] = {
        "auth_max_independent_p95": round(_percentile(max_independent, 0.95), 4),
        "auth_max_independent_p90": round(_percentile(max_independent, 0.90), 4),
        "auth_max_independent_p75": round(_percentile(max_independent, 0.75), 4),
        "auth_pixel_p99": round(_percentile(auth_pixel, 0.99), 4) if auth_pixel else 0.0,
        "auth_pixel_p95": round(_percentile(auth_pixel, 0.95), 4) if auth_pixel else 0.0,
        "auth_clip_p95": round(_percentile(auth_clip, 0.95), 4) if auth_clip else 0.0,
        "auth_clip_p90": round(_percentile(auth_clip, 0.90), 4) if auth_clip else 0.0,
        "auth_dinov2_p95": round(_percentile(auth_dinov2, 0.95), 4) if auth_dinov2 else 0.0,
    }

    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)

    # Print human-readable summary
    print(f"=== PRODUCTION STATS — {args.input} ===")
    print(f"Rows: {report['n_rows']} (auth={report['n_authentic']}, "
          f"AI={report['n_ai']}, tamp={report['n_tampered']})")
    print()
    print(f"Overall score:")
    for cls, s in report["overall_score"].items():
        print(f"  {cls:14}  mean={s.get('mean', 0)*100:5.1f}%  "
              f"p50={s.get('p50', 0)*100:5.1f}%  "
              f"p95={s.get('p95', 0)*100:5.1f}%")
    print()
    print("Per-module mean scores:")
    print(f"  {'module':<28} {'auth':>8} {'AI':>8} {'gap':>8}")
    for mod, by_cls in report["modules"].items():
        a = by_cls.get("authentic", {}).get("mean", 0)
        g = by_cls.get("ai_generated", {}).get("mean", 0)
        gap = g - a
        flag = "  ★" if gap >= 0.15 else ("  ↓" if gap < 0 else "")
        print(f"  {mod:<28} {a*100:7.1f}% {g*100:7.1f}% {gap*100:+7.1f}%{flag}")
    print()
    print("Derived calibration values:")
    for k, v in report["derived"].items():
        print(f"  {k:35} = {v}")
    print()
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
