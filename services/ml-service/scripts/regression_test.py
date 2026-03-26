"""
End-to-end regression test for DENT forensic pipeline.

Uploads sampled images from S3 to the /forensics API endpoint and verifies:
  - Authentic images get risk < 15% (FP rate < 10%)
  - AI-generated images get risk > 60% (FN rate < 15%)
  - Tampered images get risk > 40% (FN rate < 20%)

Usage:
  # Against local dev server
  python -m scripts.regression_test --api-url http://localhost:8000 --sample 50

  # Against production
  python -m scripts.regression_test --api-url https://dent.xyler.ai --sample 100

  # From existing JSONL (no API calls)
  python -m scripts.regression_test --jsonl data/labeled_dataset.jsonl

Requires: boto3 (for S3), requests (for API calls)
S3 bucket: dent-calibration-data, prefix: processed/
"""

import argparse
import csv
import io
import json
import os
import random
import sys
import time


def load_labels_from_s3(bucket: str, region: str) -> list[dict]:
    """Load labels.csv from S3 processed/ prefix."""
    import boto3

    s3 = boto3.client("s3", region_name=region)
    resp = s3.get_object(Bucket=bucket, Key="processed/labels.csv")
    content = resp["Body"].read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    return list(reader)


def sample_balanced(
    labels: list[dict], n_total: int
) -> list[dict]:
    """Sample images with balanced class distribution."""
    by_class: dict[str, list[dict]] = {}
    for row in labels:
        gt = row.get("ground_truth", "authentic")
        by_class.setdefault(gt, []).append(row)

    # Target: 50% authentic, 25% AI, 25% tampered
    n_auth = n_total // 2
    n_ai = n_total // 4
    n_tamp = n_total - n_auth - n_ai

    sampled = []
    for cls, count in [("authentic", n_auth), ("ai_generated", n_ai), ("tampered", n_tamp)]:
        pool = by_class.get(cls, [])
        if len(pool) <= count:
            sampled.extend(pool)
        else:
            sampled.extend(random.sample(pool, count))

    random.shuffle(sampled)
    return sampled


def run_forensics(
    api_url: str, img_bytes: bytes, filename: str, skip_modules: str = ""
) -> dict | None:
    """POST image to /forensics and return the JSON report."""
    import requests

    params = {}
    if skip_modules:
        params["skip_modules"] = skip_modules

    try:
        resp = requests.post(
            f"{api_url.rstrip('/')}/forensics",
            files={"file": (filename, io.BytesIO(img_bytes))},
            params=params,
            timeout=600,
        )
        if resp.status_code != 200:
            print(f"  ERROR: {filename} → HTTP {resp.status_code}", file=sys.stderr)
            return None
        return resp.json()
    except Exception as e:
        print(f"  ERROR: {filename} → {e}", file=sys.stderr)
        return None


def evaluate_results(records: list[dict]) -> dict:
    """Compute pass/fail metrics from collected results."""
    import numpy as np

    metrics: dict[str, dict] = {}

    for cls in ("authentic", "ai_generated", "tampered"):
        cls_records = [r for r in records if r["ground_truth"] == cls]
        if not cls_records:
            continue

        scores = np.array([r["overall_risk_score"] for r in cls_records])

        if cls == "authentic":
            # False positive: authentic with risk >= 0.15
            fp_count = int(np.sum(scores >= 0.15))
            fp_rate = fp_count / len(cls_records)
            metrics[cls] = {
                "count": len(cls_records),
                "mean_risk": round(float(np.mean(scores)), 4),
                "median_risk": round(float(np.median(scores)), 4),
                "max_risk": round(float(np.max(scores)), 4),
                "fp_count": fp_count,
                "fp_rate": round(fp_rate, 4),
                "threshold": 0.15,
                "pass": fp_rate < 0.10,
            }
        elif cls == "ai_generated":
            # False negative: AI with risk < 0.60
            fn_count = int(np.sum(scores < 0.60))
            fn_rate = fn_count / len(cls_records)
            metrics[cls] = {
                "count": len(cls_records),
                "mean_risk": round(float(np.mean(scores)), 4),
                "median_risk": round(float(np.median(scores)), 4),
                "min_risk": round(float(np.min(scores)), 4),
                "fn_count": fn_count,
                "fn_rate": round(fn_rate, 4),
                "threshold": 0.60,
                "pass": fn_rate < 0.15,
            }
        elif cls == "tampered":
            # False negative: tampered with risk < 0.40
            fn_count = int(np.sum(scores < 0.40))
            fn_rate = fn_count / len(cls_records)
            metrics[cls] = {
                "count": len(cls_records),
                "mean_risk": round(float(np.mean(scores)), 4),
                "median_risk": round(float(np.median(scores)), 4),
                "min_risk": round(float(np.min(scores)), 4),
                "fn_count": fn_count,
                "fn_rate": round(fn_rate, 4),
                "threshold": 0.40,
                "pass": fn_rate < 0.20,
            }

    all_pass = all(m.get("pass", False) for m in metrics.values())
    return {"classes": metrics, "overall_pass": all_pass}


def print_report(results: dict) -> None:
    """Pretty-print the regression test report."""
    print("\n" + "=" * 60)
    print("DENT REGRESSION TEST REPORT")
    print("=" * 60)

    for cls, m in results["classes"].items():
        status = "PASS" if m["pass"] else "FAIL"
        print(f"\n[{status}] {cls.upper()} ({m['count']} images)")
        print(f"  Mean risk:   {m['mean_risk']:.2%}")
        print(f"  Median risk: {m['median_risk']:.2%}")

        if cls == "authentic":
            print(f"  Max risk:    {m['max_risk']:.2%}")
            print(f"  FP count:    {m['fp_count']} (risk >= {m['threshold']:.0%})")
            print(f"  FP rate:     {m['fp_rate']:.1%} (limit: <10%)")
        else:
            print(f"  Min risk:    {m['min_risk']:.2%}")
            print(f"  FN count:    {m['fn_count']} (risk < {m['threshold']:.0%})")
            print(f"  FN rate:     {m['fn_rate']:.1%} (limit: <{'15' if cls == 'ai_generated' else '20'}%)")

    overall = "PASS" if results["overall_pass"] else "FAIL"
    print(f"\n{'=' * 60}")
    print(f"OVERALL: {overall}")
    print(f"{'=' * 60}\n")


def live_evaluate(
    api_url: str,
    bucket: str,
    region: str,
    sample_size: int,
    skip_modules: str,
    output_path: str | None,
) -> list[dict]:
    """Run live evaluation against the API."""
    import boto3

    print(f"Loading labels from s3://{bucket}/processed/labels.csv ...")
    labels = load_labels_from_s3(bucket, region)
    print(f"Found {len(labels)} labeled images")

    sampled = sample_balanced(labels, sample_size)
    print(f"Sampled {len(sampled)} images (balanced)")

    s3 = boto3.client("s3", region_name=region)
    records = []
    t0 = time.time()

    for i, row in enumerate(sampled, 1):
        filename = row["filename"]
        ground_truth = row["ground_truth"]
        s3_key = f"processed/{filename}"

        try:
            img_resp = s3.get_object(Bucket=bucket, Key=s3_key)
            img_bytes = img_resp["Body"].read()
        except Exception as e:
            print(f"  [{i}/{len(sampled)}] SKIP {filename}: S3 error {e}")
            continue

        print(f"  [{i}/{len(sampled)}] {filename} ({ground_truth}) ...", end=" ", flush=True)
        report = run_forensics(api_url, img_bytes, filename, skip_modules)

        if report is None:
            continue

        risk = report.get("overall_risk_score", 0)
        print(f"risk={risk:.2%}")

        record = {
            "filename": filename,
            "ground_truth": ground_truth,
            "overall_risk_score": risk,
            "overall_risk_level": report.get("overall_risk_level", "?"),
            "verdict_probabilities": report.get("verdict_probabilities"),
        }
        records.append(record)

    elapsed = time.time() - t0
    print(f"\nProcessed {len(records)} images in {elapsed:.0f}s "
          f"({elapsed / max(len(records), 1):.1f}s/image)")

    if output_path:
        with open(output_path, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        print(f"Results saved to {output_path}")

    return records


def load_jsonl(path: str) -> list[dict]:
    """Load records from a JSONL file."""
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def main():
    parser = argparse.ArgumentParser(description="DENT forensic regression test")
    parser.add_argument("--api-url", default="http://localhost:8000",
                        help="ML service API URL")
    parser.add_argument("--bucket", default="dent-calibration-data",
                        help="S3 bucket with test images")
    parser.add_argument("--region", default="eu-central-1",
                        help="AWS region")
    parser.add_argument("--sample", type=int, default=100,
                        help="Number of images to test (default: 100)")
    parser.add_argument("--skip-modules", default="semantic_forensics",
                        help="Comma-separated modules to skip")
    parser.add_argument("--jsonl", help="Load from existing JSONL instead of live API")
    parser.add_argument("--output", help="Save results to JSONL file")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducible sampling")
    args = parser.parse_args()

    random.seed(args.seed)

    if args.jsonl:
        print(f"Loading results from {args.jsonl} ...")
        records = load_jsonl(args.jsonl)
        print(f"Loaded {len(records)} records")
    else:
        records = live_evaluate(
            api_url=args.api_url,
            bucket=args.bucket,
            region=args.region,
            sample_size=args.sample,
            skip_modules=args.skip_modules,
            output_path=args.output,
        )

    if not records:
        print("No records to evaluate!", file=sys.stderr)
        sys.exit(1)

    results = evaluate_results(records)
    print_report(results)

    sys.exit(0 if results["overall_pass"] else 1)


if __name__ == "__main__":
    main()
