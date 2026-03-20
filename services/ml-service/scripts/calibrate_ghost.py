#!/usr/bin/env python3
"""GHOST calibration script — optimize thresholds from labeled data.

Usage:
    python -m scripts.calibrate_ghost \
        --data labeled_samples.jsonl \
        --output calibrated_thresholds.json \
        [--tiers 1,2] [--dry-run]

Input format (JSONL):
    {"id": "s001", "ground_truth": "authentic", "modules": {"ai_generation_detection": {"risk_score": 0.12}, ...}, "overall_risk_score": 0.15}
    {"id": "s002", "ground_truth": "manipulated", "modules": {"ai_generation_detection": {"risk_score": 0.78}, ...}, "overall_risk_score": 0.65}

ground_truth: "authentic" or "manipulated"
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# Allow running from ml-service root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.forensics.ghost import GHOSTCalibrator  # noqa: E402
from app.forensics.thresholds import (  # noqa: E402
    ThresholdRegistry,
    _DEFAULT_MODULE_DAMAGE,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


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
                logger.warning(
                    "Skipping line %d: ground_truth must be 'authentic' or 'manipulated', got %r",
                    line_num, gt,
                )
                continue

            samples.append(sample)

    logger.info("Loaded %d labeled samples from %s", len(samples), path)
    return samples


def calibrate_tier1(
    samples: list[dict], calibrator: GHOSTCalibrator
) -> dict:
    """Calibrate Tier 1: verdict and enforcement thresholds."""
    results = {}
    reg = ThresholdRegistry()

    # Extract overall scores and labels
    scores = np.array([s.get("overall_risk_score", 0.0) for s in samples])
    labels = np.array(
        [1 if s["ground_truth"] == "manipulated" else 0 for s in samples]
    )

    # Verdict thresholds
    for name, default in [
        ("forged_risk", reg.verdict.forged_risk),
        ("suspicious_risk", reg.verdict.suspicious_risk),
    ]:
        result = calibrator.calibrate(scores, labels, f"verdict.{name}", default)
        results.setdefault("verdict", {})[name] = round(result.optimal_threshold, 2)

    # Enforcement thresholds
    for name, default in [
        ("critical", reg.enforcement.critical),
        ("high", reg.enforcement.high),
        ("medium", reg.enforcement.medium),
        ("upload_critical", reg.enforcement.upload_critical),
        ("upload_high", reg.enforcement.upload_high),
        ("upload_medium", reg.enforcement.upload_medium),
    ]:
        result = calibrator.calibrate(scores, labels, f"enforcement.{name}", default)
        results.setdefault("enforcement", {})[name] = round(result.optimal_threshold, 2)

    return results


def calibrate_tier2(
    samples: list[dict], calibrator: GHOSTCalibrator
) -> dict:
    """Calibrate Tier 2: per-module damage thresholds."""
    results = {}
    labels = np.array(
        [1 if s["ground_truth"] == "manipulated" else 0 for s in samples]
    )

    for mod_name, default_threshold in _DEFAULT_MODULE_DAMAGE.items():
        # Extract per-module scores
        mod_scores = []
        for s in samples:
            modules = s.get("modules", {})
            if isinstance(modules, dict) and mod_name in modules:
                mod_scores.append(
                    float(modules[mod_name].get("risk_score", 0.0))
                )
            else:
                mod_scores.append(0.0)

        scores = np.array(mod_scores)

        # Skip if no variance
        if scores.max() == scores.min():
            logger.info("Skipping %s: no score variance", mod_name)
            continue

        result = calibrator.calibrate(
            scores, labels, f"module_damage.{mod_name}", default_threshold
        )
        results[mod_name] = round(result.optimal_threshold, 2)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="GHOST threshold calibration for DENT forensics"
    )
    parser.add_argument(
        "--data", required=True, help="Path to labeled JSONL data file"
    )
    parser.add_argument(
        "--output",
        default="calibrated_thresholds.json",
        help="Output JSON path (default: calibrated_thresholds.json)",
    )
    parser.add_argument(
        "--tiers",
        default="1,2",
        help="Comma-separated tiers to calibrate: 1=verdict/enforcement, 2=module_damage",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show comparison without writing output file",
    )
    parser.add_argument(
        "--n-subsamples",
        type=int,
        default=100,
        help="Number of stratified subsamples (default: 100)",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed (default: 42)"
    )

    args = parser.parse_args()

    tiers = {int(t.strip()) for t in args.tiers.split(",")}
    samples = load_labeled_data(args.data)

    if len(samples) < 10:
        logger.error("Need at least 10 labeled samples, got %d", len(samples))
        sys.exit(1)

    n_pos = sum(1 for s in samples if s["ground_truth"] == "manipulated")
    n_neg = len(samples) - n_pos
    logger.info("Class distribution: %d manipulated, %d authentic", n_pos, n_neg)

    calibrator = GHOSTCalibrator(
        n_subsamples=args.n_subsamples, random_seed=args.seed
    )

    output = {
        "calibrated_at": datetime.now(timezone.utc).isoformat(),
        "data_source": args.data,
        "n_samples": len(samples),
        "n_manipulated": n_pos,
        "n_authentic": n_neg,
    }

    if 1 in tiers:
        logger.info("=== Calibrating Tier 1: verdict & enforcement ===")
        tier1 = calibrate_tier1(samples, calibrator)
        output.update(tier1)

    if 2 in tiers:
        logger.info("=== Calibrating Tier 2: module damage thresholds ===")
        tier2 = calibrate_tier2(samples, calibrator)
        if tier2:
            output["module_damage"] = tier2

    # Print comparison
    reg = ThresholdRegistry()
    print("\n" + "=" * 60)
    print("GHOST Calibration Results")
    print("=" * 60)

    if "verdict" in output:
        print("\nVerdict thresholds:")
        for key, val in output["verdict"].items():
            default = getattr(reg.verdict, key)
            delta = val - default
            print(f"  {key}: {default:.2f} → {val:.2f} ({delta:+.2f})")

    if "enforcement" in output:
        print("\nEnforcement thresholds:")
        for key, val in output["enforcement"].items():
            default = getattr(reg.enforcement, key)
            delta = val - default
            print(f"  {key}: {default:.2f} → {val:.2f} ({delta:+.2f})")

    if "module_damage" in output:
        print("\nModule damage thresholds:")
        for mod, val in output["module_damage"].items():
            default = _DEFAULT_MODULE_DAMAGE.get(mod, 0.0)
            delta = val - default
            print(f"  {mod}: {default:.2f} → {val:.2f} ({delta:+.2f})")

    print()

    if args.dry_run:
        logger.info("Dry run — not writing output file")
    else:
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
        logger.info("Wrote calibrated thresholds to %s", args.output)


if __name__ == "__main__":
    main()
