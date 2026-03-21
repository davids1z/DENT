#!/usr/bin/env python3
"""
Build calibration dataset by running images through the forensic pipeline.

Downloads images from S3 processed/, sends each to /forensics endpoint,
collects all module scores, pairs with ground truth labels, and outputs
JSONL compatible with calibrate_ghost.py and train_stacking_meta.py.

Supports 3 classes: authentic, ai_generated, tampered.
NO auto-labeling from filenames (prevents data leakage).
ALL labels come from labels.csv on S3.

Usage:
  python -m scripts.build_calibration_dataset \
    --bucket dent-calibration-data \
    --output data/labeled_dataset.jsonl \
    [--api-url http://localhost:8000] \
    [--resume]

Requirements:
  pip install boto3 requests tqdm
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

import boto3
import requests

try:
    from tqdm import tqdm
except ImportError:
    # Fallback if tqdm not installed
    def tqdm(iterable, **kwargs):
        total = kwargs.get("total", "?")
        desc = kwargs.get("desc", "")
        for i, item in enumerate(iterable, 1):
            print(f"\r  {desc} [{i}/{total}]", end="", flush=True)
            yield item
        print()

S3_PREFIX_PROCESSED = "processed"
VALID_CLASSES = {"authentic", "ai_generated", "tampered"}


def load_labels_from_s3(s3_client, bucket: str) -> dict[str, str]:
    """Load labels.csv from S3 processed/ prefix."""
    key = f"{S3_PREFIX_PROCESSED}/labels.csv"
    try:
        resp = s3_client.get_object(Bucket=bucket, Key=key)
        content = resp["Body"].read().decode("utf-8")
        reader = csv.DictReader(io.StringIO(content))
        labels = {}
        for row in reader:
            fn = row.get("filename", "").strip()
            gt = row.get("ground_truth", "").strip().lower()
            if fn and gt in VALID_CLASSES:
                labels[fn] = gt
        return labels
    except Exception as e:
        print(f"ERROR: Cannot load labels from s3://{bucket}/{key}: {e}")
        sys.exit(1)


def download_image_from_s3(s3_client, bucket: str, key: str) -> bytes | None:
    """Download image bytes from S3."""
    try:
        resp = s3_client.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read()
    except Exception as e:
        print(f"  ERROR downloading {key}: {e}")
        return None


def analyze_image(api_url: str, image_bytes: bytes, filename: str) -> dict | None:
    """Send image to /forensics endpoint with retry logic."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                f"{api_url}/forensics",
                files={"file": (filename, io.BytesIO(image_bytes))},
                timeout=300,
            )
            if resp.status_code == 200:
                return resp.json()
            else:
                print(f"  HTTP {resp.status_code} for {filename} (attempt {attempt + 1})")
        except requests.exceptions.Timeout:
            print(f"  Timeout for {filename} (attempt {attempt + 1})")
        except Exception as e:
            print(f"  Error for {filename}: {e} (attempt {attempt + 1})")

        if attempt < max_retries - 1:
            time.sleep(5 * (attempt + 1))  # Backoff: 5s, 10s

    return None


def forensic_report_to_jsonl(filename: str, ground_truth: str, report: dict) -> dict:
    """Convert ForensicReport to JSONL record."""
    modules_data = {}
    for mod in report.get("modules", []):
        mod_name = mod.get("module_name", mod.get("moduleName", ""))
        if not mod_name:
            continue
        risk = mod.get("risk_score", mod.get("riskScore", 0))
        findings = []
        for f in mod.get("findings", []):
            findings.append({
                "code": f.get("code", ""),
                "confidence": f.get("confidence", 0),
                "risk_score": f.get("risk_score", f.get("riskScore", 0)),
            })
        modules_data[mod_name] = {"risk_score": risk, "findings": findings}

    overall = report.get("overall_risk_score", report.get("overallRiskScore", 0))
    return {
        "id": filename,
        "ground_truth": ground_truth,
        "overall_risk_score": overall,
        "modules": modules_data,
    }


def load_existing_results(output_path: str) -> set[str]:
    """Load already-processed image IDs for resume support."""
    done = set()
    if os.path.exists(output_path):
        with open(output_path, encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                    done.add(record.get("id", ""))
                except json.JSONDecodeError:
                    continue
    return done


def main() -> None:
    parser = argparse.ArgumentParser(description="Build calibration dataset from S3 images")
    parser.add_argument("--bucket", required=True, help="S3 bucket with processed images")
    parser.add_argument("--output", required=True, help="Output JSONL file path")
    parser.add_argument("--api-url", default="http://localhost:8000", help="ML service URL")
    parser.add_argument("--region", default="eu-central-1", help="AWS region")
    parser.add_argument("--resume", action="store_true", help="Skip already-processed images")
    args = parser.parse_args()

    s3 = boto3.client("s3", region_name=args.region)

    # Load labels
    labels = load_labels_from_s3(s3, args.bucket)
    print(f"Loaded {len(labels)} labels from S3")
    for cls in VALID_CLASSES:
        count = sum(1 for gt in labels.values() if gt == cls)
        print(f"  {cls}: {count}")

    # Resume support
    already_done = set()
    if args.resume:
        already_done = load_existing_results(args.output)
        print(f"Resume: {len(already_done)} already processed, skipping")

    # Filter to images not yet processed
    to_process = [(fn, gt) for fn, gt in labels.items() if fn not in already_done]
    print(f"\nImages to process: {len(to_process)}")

    if not to_process:
        print("Nothing to do!")
        return

    # Process images
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    mode = "a" if args.resume else "w"
    processed = 0
    errors = 0

    with open(output_path, mode, encoding="utf-8") as out_f:
        for filename, ground_truth in tqdm(to_process, desc="Analyzing", total=len(to_process)):
            s3_key = f"{S3_PREFIX_PROCESSED}/{filename}"

            # Download from S3
            image_bytes = download_image_from_s3(s3, args.bucket, s3_key)
            if image_bytes is None:
                errors += 1
                continue

            # Analyze through forensic pipeline
            report = analyze_image(args.api_url, image_bytes, filename)
            if report is None:
                errors += 1
                continue

            # Write JSONL record
            record = forensic_report_to_jsonl(filename, ground_truth, report)
            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_f.flush()  # Flush each record for resume safety
            processed += 1

    # Summary
    print(f"\n{'='*60}")
    print(f"Dataset built: {processed} samples ({errors} errors)")

    # Count classes in output
    counts = {}
    with open(output_path, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
                gt = r.get("ground_truth", "unknown")
                counts[gt] = counts.get(gt, 0) + 1
            except json.JSONDecodeError:
                continue

    for cls in VALID_CLASSES:
        print(f"  {cls}: {counts.get(cls, 0)}")
    print(f"  Total: {sum(counts.values())}")
    print(f"  Output: {output_path}")

    min_count = min(counts.get(c, 0) for c in VALID_CLASSES)
    if min_count < 50:
        print(f"\nWARNING: Minority class has only {min_count} samples.")
        print("Recommend at least 100 per class for stable calibration.")
    else:
        print("\nDataset ready for calibration!")
        print(f"  python -m scripts.calibrate_ghost --data {output_path} --tiers 1,2")
        print(f"  python -m scripts.train_stacking_meta --data {output_path} --compare")


if __name__ == "__main__":
    main()
