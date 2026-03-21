#!/usr/bin/env python3
"""
Prepare calibration dataset: download from S3 raw/, randomize filenames,
strip EXIF, standardize to JPEG 90%, upload to S3 processed/, generate labels.csv.

This step ELIMINATES data leakage by:
1. Renaming ALL files to random hashes (no AI generator names)
2. Stripping ALL EXIF/metadata (no camera vs AI signal from metadata)
3. Standardizing format (all JPEG quality 90, no format-based shortcuts)

Usage:
  export AWS_ACCESS_KEY_ID=AKIA...
  export AWS_SECRET_ACCESS_KEY=...

  python -m scripts.prepare_calibration_dataset \
    --bucket dent-calibration-data \
    [--region eu-central-1]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import uuid

import boto3
from PIL import Image

S3_PREFIX_RAW = "raw"
S3_PREFIX_PROCESSED = "processed"
CATEGORIES = ["authentic", "ai_generated", "tampered"]


def list_s3_images(s3_client, bucket: str, prefix: str) -> list[str]:
    """List all image keys under an S3 prefix."""
    keys = []
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff")):
                keys.append(key)
    return keys


def process_and_upload(
    s3_client,
    bucket: str,
    source_key: str,
    category: str,
) -> tuple[str, dict] | None:
    """Download image from S3, strip EXIF, standardize, upload with random name."""
    try:
        # Download from raw/
        resp = s3_client.get_object(Bucket=bucket, Key=source_key)
        raw_bytes = resp["Body"].read()

        # Get original metadata (source info)
        metadata = resp.get("Metadata", {})
        original_source = metadata.get("source", source_key.split("/")[-1])

        # Open with Pillow — this STRIPS all EXIF/metadata
        img = Image.open(io.BytesIO(raw_bytes))
        if img.mode != "RGB":
            img = img.convert("RGB")

        # Resize if too large (max 1024px on longest side for consistency)
        max_side = 1024
        if max(img.size) > max_side:
            ratio = max_side / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, Image.LANCZOS)

        # Save as JPEG quality=90 — NO EXIF, standardized format
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90, optimize=True)
        clean_bytes = buf.getvalue()

        # Random filename — eliminates data leakage
        random_name = uuid.uuid4().hex[:12] + ".jpg"
        dest_key = f"{S3_PREFIX_PROCESSED}/{random_name}"

        # Upload to processed/
        s3_client.put_object(
            Bucket=bucket,
            Key=dest_key,
            Body=clean_bytes,
            ContentType="image/jpeg",
        )

        return random_name, {
            "original_key": source_key,
            "original_source": original_source,
            "category": category,
            "size_bytes": len(clean_bytes),
            "dimensions": f"{img.size[0]}x{img.size[1]}",
        }

    except Exception as e:
        print(f"    Error processing {source_key}: {e}")
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare calibration dataset")
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--region", default="eu-central-1", help="AWS region")
    args = parser.parse_args()

    s3 = boto3.client("s3", region_name=args.region)

    print(f"S3 bucket: {args.bucket}")
    print(f"{'='*60}")

    all_mappings: list[dict] = []
    labels_rows: list[tuple[str, str]] = []

    for category in CATEGORIES:
        prefix = f"{S3_PREFIX_RAW}/{category}/"
        print(f"\nProcessing: {category}")
        print(f"  Listing s3://{args.bucket}/{prefix}...")

        keys = list_s3_images(s3, args.bucket, prefix)
        print(f"  Found {len(keys)} images")

        if not keys:
            print(f"  WARNING: No images for {category}!")
            continue

        processed = 0
        errors = 0

        for i, key in enumerate(keys, 1):
            result = process_and_upload(s3, args.bucket, key, category)

            if result:
                random_name, mapping = result
                all_mappings.append({"random_name": random_name, **mapping})
                labels_rows.append((random_name, category))
                processed += 1
            else:
                errors += 1

            if i % 100 == 0:
                print(f"  [{i}/{len(keys)}] processed={processed}, errors={errors}")

        print(f"  {category}: {processed} processed, {errors} errors")

    # Upload labels.csv to S3
    print(f"\n{'='*60}")
    print("Generating labels.csv...")

    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(["filename", "ground_truth"])
    for filename, gt in labels_rows:
        writer.writerow([filename, gt])

    s3.put_object(
        Bucket=args.bucket,
        Key=f"{S3_PREFIX_PROCESSED}/labels.csv",
        Body=csv_buf.getvalue().encode("utf-8"),
        ContentType="text/csv",
    )
    print(f"  Uploaded labels.csv ({len(labels_rows)} rows)")

    # Upload mapping.json for traceability
    s3.put_object(
        Bucket=args.bucket,
        Key=f"{S3_PREFIX_PROCESSED}/mapping.json",
        Body=json.dumps(all_mappings, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    print(f"  Uploaded mapping.json ({len(all_mappings)} entries)")

    # Summary
    counts = {}
    for _, gt in labels_rows:
        counts[gt] = counts.get(gt, 0) + 1

    print(f"\n{'='*60}")
    print("Dataset prepared:")
    for cat in CATEGORIES:
        print(f"  {cat}: {counts.get(cat, 0)}")
    print(f"  Total: {sum(counts.values())}")
    print(f"\nAll images in s3://{args.bucket}/{S3_PREFIX_PROCESSED}/")
    print(f"Labels: s3://{args.bucket}/{S3_PREFIX_PROCESSED}/labels.csv")
    print(f"\nNext step:")
    print(f"  python -m scripts.build_calibration_dataset \\")
    print(f"    --bucket {args.bucket} --output data/labeled_dataset.jsonl")


if __name__ == "__main__":
    main()
