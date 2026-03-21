#!/usr/bin/env python3
"""
Build calibration dataset by running images through the forensic pipeline.

Sends each image to the ML service's /forensics endpoint, collects all
module scores and findings, pairs with ground truth labels, and outputs
JSONL compatible with calibrate_ghost.py and train_stacking_meta.py.

Usage:
  python -m scripts.build_calibration_dataset \
    --images-dir data/calibration_images \
    --labels data/labels.csv \
    --output data/labeled_dataset.jsonl \
    [--api-url http://localhost:8000]

labels.csv format (header required):
  filename,ground_truth
  real_car1.jpg,authentic
  gemini_bmw.png,manipulated
  dalle_crash.png,manipulated

Files not in labels.csv are auto-labeled if filename matches known AI
generator patterns (e.g., "Gemini_Generated_Image_*" → manipulated).
Otherwise they are skipped with a warning.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

import requests

# ── AI filename patterns for auto-labeling ────────────────────────────
_AI_FILENAME_PATTERNS = [
    "gemini_generated",
    "image_fx_",
    "dall-e",
    "dall_e",
    "dalle_",
    "midjourney_",
    "comfyui_",
    "sdxl_",
    "stable_diffusion",
    "novelai_",
]

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".jfif", ".bmp", ".tiff"}


def auto_label_filename(filename: str) -> str | None:
    """Return 'manipulated' if filename matches known AI generator, else None."""
    fn_lower = filename.lower()
    for pattern in _AI_FILENAME_PATTERNS:
        if pattern in fn_lower:
            return "manipulated"
    return None


def load_labels(labels_path: str) -> dict[str, str]:
    """Load ground truth labels from CSV."""
    labels: dict[str, str] = {}
    if not os.path.exists(labels_path):
        return labels

    with open(labels_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fn = row.get("filename", "").strip()
            gt = row.get("ground_truth", "").strip().lower()
            if fn and gt in ("authentic", "manipulated"):
                labels[fn] = gt
            elif fn:
                print(f"  WARNING: Invalid ground_truth '{gt}' for {fn}, skipping")

    return labels


def analyze_image(api_url: str, image_path: Path) -> dict | None:
    """Send image to /forensics endpoint and return parsed ForensicReport."""
    try:
        with open(image_path, "rb") as f:
            resp = requests.post(
                f"{api_url}/forensics",
                files={"file": (image_path.name, f)},
                timeout=300,  # Some modules take 60s+
            )

        if resp.status_code != 200:
            print(f"  ERROR: HTTP {resp.status_code} for {image_path.name}")
            return None

        return resp.json()

    except requests.exceptions.Timeout:
        print(f"  ERROR: Timeout for {image_path.name}")
        return None
    except Exception as e:
        print(f"  ERROR: {e} for {image_path.name}")
        return None


def forensic_report_to_jsonl(
    filename: str,
    ground_truth: str,
    report: dict,
) -> dict:
    """Convert ForensicReport dict to JSONL record for GHOST/stacking."""
    modules_data: dict[str, dict] = {}

    for mod in report.get("modules", []):
        mod_name = mod.get("module_name", mod.get("moduleName", ""))
        if not mod_name:
            continue

        risk_score = mod.get("risk_score", mod.get("riskScore", 0))
        findings = []
        for f in mod.get("findings", []):
            findings.append({
                "code": f.get("code", ""),
                "confidence": f.get("confidence", 0),
                "risk_score": f.get("risk_score", f.get("riskScore", 0)),
            })

        modules_data[mod_name] = {
            "risk_score": risk_score,
            "findings": findings,
        }

    overall = report.get(
        "overall_risk_score",
        report.get("overallRiskScore", 0),
    )

    return {
        "id": filename,
        "ground_truth": ground_truth,
        "overall_risk_score": overall,
        "modules": modules_data,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build calibration dataset from images + labels"
    )
    parser.add_argument(
        "--images-dir", required=True,
        help="Directory containing images to analyze",
    )
    parser.add_argument(
        "--labels", default="",
        help="CSV file with filename,ground_truth columns",
    )
    parser.add_argument(
        "--output", required=True,
        help="Output JSONL file path",
    )
    parser.add_argument(
        "--api-url", default="http://localhost:8000",
        help="ML service base URL (default: http://localhost:8000)",
    )
    args = parser.parse_args()

    images_dir = Path(args.images_dir)
    if not images_dir.is_dir():
        print(f"ERROR: {images_dir} is not a directory")
        sys.exit(1)

    # Load manual labels
    manual_labels = load_labels(args.labels) if args.labels else {}
    print(f"Loaded {len(manual_labels)} manual labels from {args.labels or '(none)'}")

    # Find all images
    image_files = sorted(
        f for f in images_dir.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTENSIONS
    )
    print(f"Found {len(image_files)} images in {images_dir}")

    if not image_files:
        print("ERROR: No images found")
        sys.exit(1)

    # Process each image
    results: list[dict] = []
    skipped = 0
    errors = 0

    for i, img_path in enumerate(image_files, 1):
        filename = img_path.name

        # Determine ground truth
        if filename in manual_labels:
            ground_truth = manual_labels[filename]
        else:
            auto = auto_label_filename(filename)
            if auto:
                ground_truth = auto
                print(f"  AUTO-LABELED: {filename} → {ground_truth}")
            else:
                print(f"  SKIPPED: {filename} (no label in CSV, no auto-label match)")
                skipped += 1
                continue

        print(f"[{i}/{len(image_files)}] {filename} ({ground_truth}) ...", end=" ", flush=True)
        start = time.monotonic()

        report = analyze_image(args.api_url, img_path)
        if report is None:
            errors += 1
            continue

        elapsed = time.monotonic() - start
        record = forensic_report_to_jsonl(filename, ground_truth, report)
        results.append(record)

        n_modules = len(record["modules"])
        risk = record["overall_risk_score"]
        print(f"OK ({elapsed:.1f}s, {n_modules} modules, risk={risk:.2f})")

    # Write output JSONL
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        for record in results:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # Summary
    authentic = sum(1 for r in results if r["ground_truth"] == "authentic")
    manipulated = sum(1 for r in results if r["ground_truth"] == "manipulated")

    print(f"\n{'='*60}")
    print(f"Dataset built: {len(results)} samples")
    print(f"  Authentic:   {authentic}")
    print(f"  Manipulated: {manipulated}")
    print(f"  Skipped:     {skipped}")
    print(f"  Errors:      {errors}")
    print(f"  Output:      {output_path}")
    print(f"{'='*60}")

    if authentic == 0 or manipulated == 0:
        print("WARNING: Dataset is one-sided! Need both classes for calibration.")
    elif min(authentic, manipulated) < 10:
        print(f"WARNING: Only {min(authentic, manipulated)} samples in minority class. "
              "Recommend at least 50 per class for stable calibration.")
    else:
        print("Dataset looks good for calibration.")
        print(f"\nNext steps:")
        print(f"  python -m scripts.calibrate_ghost --data {output_path} --tiers 1,2 --output config/calibrated_thresholds.json")
        print(f"  python -m scripts.train_stacking_meta --data {output_path} --output models/stacking_meta/meta_weights.npz --compare")


if __name__ == "__main__":
    main()
