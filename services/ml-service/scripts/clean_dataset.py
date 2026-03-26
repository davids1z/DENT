"""
Clean calibration dataset by identifying mislabeled images.

Scans all images through the /forensics API and identifies:
1. "authentic" images with high AI/tampered scores → likely mislabeled
2. "ai_generated" images with very low scores → likely mislabeled
3. "tampered" images with no tampering signals → likely mislabeled

Outputs:
- clean_labels.csv: corrected labels
- flagged_images.csv: images needing manual review
- stats: per-class distribution before/after

Usage:
  # Full scan (slow, ~2.5h for 3000 images)
  python -m scripts.clean_dataset --api-url https://dent.xyler.ai/ml --bucket dent-calibration-data

  # Quick scan using existing JSONL
  python -m scripts.clean_dataset --jsonl data/labeled_dataset.jsonl

  # Dry run (just report, don't upload)
  python -m scripts.clean_dataset --api-url https://dent.xyler.ai/ml --bucket dent-calibration-data --dry-run
"""

import argparse
import csv
import io
import json
import os
import sys
import time

import boto3
import requests


def load_labels(s3_client, bucket: str) -> list[dict]:
    resp = s3_client.get_object(Bucket=bucket, Key="processed/labels.csv")
    content = resp["Body"].read().decode("utf-8")
    return list(csv.DictReader(io.StringIO(content)))


def scan_image(api_url: str, s3_client, bucket: str, filename: str) -> dict | None:
    try:
        img = s3_client.get_object(Bucket=bucket, Key=f"processed/{filename}")
        img_bytes = img["Body"].read()
        resp = requests.post(
            f"{api_url.rstrip('/')}/forensics",
            files={"file": (filename, io.BytesIO(img_bytes))},
            params={"skip_modules": "semantic_forensics"},
            timeout=120,
        )
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as e:
        print(f"  ERROR: {filename}: {e}", file=sys.stderr)
        return None


def classify_image(report: dict, original_label: str) -> tuple[str, str]:
    """Returns (suggested_label, reason)."""
    risk = report.get("overall_risk_score", 0)

    # Extract key module scores
    modules = {}
    for m in report.get("modules", []):
        name = m.get("module_name", m.get("moduleName", ""))
        score = m.get("risk_score", m.get("riskScore", 0))
        if name:
            modules[name] = score

    dinov2 = modules.get("dinov2_ai_detection", 0)
    safe = modules.get("safe_ai_detection", 0)
    commfor = modules.get("community_forensics_detection", 0)
    clip = modules.get("clip_ai_detection", 0)
    effnet = modules.get("efficientnet_ai_detection", 0)
    mod_det = modules.get("modification_detection", 0)
    mesorch = modules.get("mesorch_detection", 0)

    ai_detectors_high = sum(1 for s in [dinov2, safe, commfor, clip, effnet] if s >= 0.50)
    tampering_high = sum(1 for s in [mod_det, mesorch] if s >= 0.40)

    if original_label == "authentic":
        # Flag if multiple AI detectors agree
        if ai_detectors_high >= 3:
            return "ai_generated", f"3+ AI detectors high (risk={risk:.2f})"
        if ai_detectors_high >= 2 and risk >= 0.50:
            return "ai_generated", f"2+ AI detectors + high risk ({risk:.2f})"
        if tampering_high >= 2:
            return "tampered", f"2+ tampering detectors high"
        if risk >= 0.40:
            return "REVIEW", f"High risk ({risk:.2f}) but ambiguous signals"

    elif original_label == "ai_generated":
        # Flag if no AI detectors fire
        if ai_detectors_high == 0 and risk < 0.10:
            return "authentic", f"No AI signals at all (risk={risk:.2f})"
        if ai_detectors_high <= 1 and risk < 0.15:
            return "REVIEW", f"Weak AI signal (risk={risk:.2f})"

    elif original_label == "tampered":
        # Flag if no tampering signals
        if tampering_high == 0 and ai_detectors_high == 0 and risk < 0.10:
            return "authentic", f"No tampering or AI signals (risk={risk:.2f})"

    return original_label, "OK"


def main():
    parser = argparse.ArgumentParser(description="Clean calibration dataset labels")
    parser.add_argument("--api-url", default="https://dent.xyler.ai/ml")
    parser.add_argument("--bucket", default="dent-calibration-data")
    parser.add_argument("--region", default="eu-central-1")
    parser.add_argument("--jsonl", help="Use existing JSONL instead of API")
    parser.add_argument("--dry-run", action="store_true", help="Report only, don't upload")
    parser.add_argument("--batch-size", type=int, default=100, help="Process N images then save")
    parser.add_argument("--output-dir", default="data", help="Local output directory")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    s3 = boto3.client("s3", region_name=args.region)
    labels = load_labels(s3, args.bucket)
    print(f"Loaded {len(labels)} labels")

    # Count originals
    orig_counts = {}
    for row in labels:
        gt = row["ground_truth"]
        orig_counts[gt] = orig_counts.get(gt, 0) + 1
    print(f"Original: {orig_counts}")

    corrections = []  # (filename, original, suggested, reason)
    reviews = []

    if args.jsonl:
        # Fast mode: use existing JSONL
        records = {}
        with open(args.jsonl) as f:
            for line in f:
                r = json.loads(line.strip())
                records[r["id"]] = r

        for row in labels:
            fn = row["filename"]
            if fn not in records:
                continue
            report = records[fn]
            suggested, reason = classify_image(
                {"overall_risk_score": report["overall_risk_score"],
                 "modules": [{"module_name": k, "risk_score": v["risk_score"]}
                             for k, v in report.get("modules", {}).items()]},
                row["ground_truth"],
            )
            if suggested != row["ground_truth"]:
                if suggested == "REVIEW":
                    reviews.append((fn, row["ground_truth"], reason))
                else:
                    corrections.append((fn, row["ground_truth"], suggested, reason))

    else:
        # Full scan mode
        t0 = time.time()
        for i, row in enumerate(labels, 1):
            fn = row["filename"]
            gt = row["ground_truth"]

            if i % 50 == 0:
                elapsed = time.time() - t0
                eta = elapsed / i * (len(labels) - i)
                print(f"  [{i}/{len(labels)}] ({elapsed:.0f}s elapsed, ~{eta:.0f}s remaining)")

            report = scan_image(args.api_url, s3, args.bucket, fn)
            if report is None:
                continue

            suggested, reason = classify_image(report, gt)
            if suggested != gt:
                if suggested == "REVIEW":
                    reviews.append((fn, gt, reason))
                else:
                    corrections.append((fn, gt, suggested, reason))
                    print(f"  RELABEL: {fn} [{gt}] → [{suggested}]: {reason}")

    # Report
    print(f"\n{'='*60}")
    print(f"DATASET CLEANING REPORT")
    print(f"{'='*60}")
    print(f"Total images: {len(labels)}")
    print(f"Auto-corrections: {len(corrections)}")
    print(f"Needs review: {len(reviews)}")
    print()

    for fn, orig, suggested, reason in corrections[:20]:
        print(f"  {fn}: {orig} → {suggested} ({reason})")
    if len(corrections) > 20:
        print(f"  ... and {len(corrections) - 20} more")

    print(f"\nReview needed ({len(reviews)}):")
    for fn, orig, reason in reviews[:10]:
        print(f"  {fn}: {orig} — {reason}")

    # Write clean labels
    clean_path = os.path.join(args.output_dir, "clean_labels.csv")
    correction_map = {fn: suggested for fn, _, suggested, _ in corrections}

    new_counts = {}
    with open(clean_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["filename", "ground_truth"])
        for row in labels:
            fn = row["filename"]
            gt = correction_map.get(fn, row["ground_truth"])
            writer.writerow([fn, gt])
            new_counts[gt] = new_counts.get(gt, 0) + 1

    print(f"\nOriginal distribution: {orig_counts}")
    print(f"Cleaned distribution:  {new_counts}")
    print(f"Written to: {clean_path}")

    if not args.dry_run and corrections:
        print(f"\nUploading clean_labels.csv to s3://{args.bucket}/processed/labels_clean.csv ...")
        with open(clean_path, "rb") as f:
            s3.put_object(
                Bucket=args.bucket,
                Key="processed/labels_clean.csv",
                Body=f.read(),
                ContentType="text/csv",
            )
        print("Uploaded.")


if __name__ == "__main__":
    main()
