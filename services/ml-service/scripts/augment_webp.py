#!/usr/bin/env python3
"""Augment calibration dataset with WebP-compressed copies of each image.

WebP lossy compression destroys pixel-level AI artifacts that forensic
detectors rely on, creating a blind spot. This script re-saves existing
images as WebP at various quality levels so probes can learn to detect
AI images regardless of compression format.

Usage:
  cd /root/DENT/services/ml-service
  python3 -m scripts.augment_webp \
    --bucket dent-calibration-data \
    --input-prefix train_v5 \
    --output-prefix train_v5_webp \
    --qualities 60,75,85,95
"""
import argparse
import csv
import io
import os
import sys

import boto3
from PIL import Image

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(it, **kw):
        total = kw.get("total", "?")
        for i, x in enumerate(it, 1):
            if i % 50 == 0:
                print(f"  [{i}/{total}]", flush=True)
            yield x


VALID_CLASSES = {"authentic", "ai_generated", "tampered"}

# How many WebP quality levels per class
# AI images get more augmentation (4 levels) to ensure good coverage
# Authentic get fewer (2 levels) to avoid class imbalance
QUALITIES_BY_CLASS = {
    "ai_generated": None,   # all qualities (set from args)
    "tampered": None,       # all qualities
    "authentic": [75, 90],  # fewer to avoid imbalance
}


def main():
    parser = argparse.ArgumentParser(description="Augment calibration data with WebP copies")
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--input-prefix", default="train_v5", help="S3 prefix for source images")
    parser.add_argument("--output-prefix", default="train_v5_webp", help="S3 prefix for output")
    parser.add_argument("--qualities", default="60,75,85,95", help="Comma-separated WebP quality levels")
    parser.add_argument("--region", default="eu-central-1")
    parser.add_argument("--max-images", type=int, default=0, help="Limit source images (0=all)")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without uploading")
    args = parser.parse_args()

    all_qualities = [int(q) for q in args.qualities.split(",")]
    QUALITIES_BY_CLASS["ai_generated"] = all_qualities
    QUALITIES_BY_CLASS["tampered"] = all_qualities

    s3 = boto3.client("s3", region_name=args.region)
    input_prefix = args.input_prefix
    output_prefix = args.output_prefix

    # ── Load existing labels ────────────────────────────────────────
    print(f"Loading labels from s3://{args.bucket}/{input_prefix}/labels.csv ...")
    resp = s3.get_object(Bucket=args.bucket, Key=f"{input_prefix}/labels.csv")
    content = resp["Body"].read().decode("utf-8")
    labels = {}
    for row in csv.DictReader(io.StringIO(content)):
        fn = row.get("filename", "").strip()
        gt = row.get("ground_truth", "").strip().lower()
        if fn and gt in VALID_CLASSES:
            labels[fn] = gt

    items = sorted(labels.items())
    if args.max_images > 0:
        items = items[:args.max_images]

    # Count per class
    class_counts = {}
    for fn, gt in items:
        class_counts[gt] = class_counts.get(gt, 0) + 1
    print(f"Source images: {len(items)} ({class_counts})")

    # ── Plan augmentation ────────────────────────────────────────────
    augmented_labels = []  # (filename, ground_truth) for new labels.csv
    total_to_create = 0

    for fn, gt in items:
        # Keep original
        augmented_labels.append((fn, gt))

        # WebP copies
        qualities = QUALITIES_BY_CLASS.get(gt, [75])
        for q in qualities:
            base, _ = os.path.splitext(fn)
            webp_fn = f"{base}_webp_q{q}.webp"
            augmented_labels.append((webp_fn, gt))
            total_to_create += 1

    print(f"Will create {total_to_create} WebP copies")
    new_class_counts = {}
    for fn, gt in augmented_labels:
        new_class_counts[gt] = new_class_counts.get(gt, 0) + 1
    print(f"Augmented totals: {new_class_counts}")

    if args.dry_run:
        print("DRY RUN — no uploads performed")
        return

    # ── Copy originals + create WebP copies ──────────────────────────
    print(f"\nCopying originals and creating WebP copies to s3://{args.bucket}/{output_prefix}/ ...")
    errors = 0
    uploaded = 0

    for fn, gt in tqdm(items, desc="Processing images", total=len(items)):
        try:
            # Download original
            resp = s3.get_object(Bucket=args.bucket, Key=f"{input_prefix}/{fn}")
            image_bytes = resp["Body"].read()

            # Copy original to output prefix
            s3.put_object(
                Bucket=args.bucket,
                Key=f"{output_prefix}/{fn}",
                Body=image_bytes,
                ContentType="image/jpeg",
            )
            uploaded += 1

            # Open as PIL for WebP conversion
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

            # Create WebP copies at each quality level
            qualities = QUALITIES_BY_CLASS.get(gt, [75])
            for q in qualities:
                base, _ = os.path.splitext(fn)
                webp_fn = f"{base}_webp_q{q}.webp"

                buf = io.BytesIO()
                img.save(buf, format="WEBP", quality=q)
                webp_bytes = buf.getvalue()

                s3.put_object(
                    Bucket=args.bucket,
                    Key=f"{output_prefix}/{webp_fn}",
                    Body=webp_bytes,
                    ContentType="image/webp",
                )
                uploaded += 1

        except Exception as e:
            errors += 1
            if errors <= 10:
                print(f"  Error {fn}: {e}")

    # ── Upload augmented labels.csv ──────────────────────────────────
    print(f"\nUploaded {uploaded} files ({errors} errors)")
    print("Writing augmented labels.csv ...")

    csv_buf = io.StringIO()
    writer = csv.DictWriter(csv_buf, fieldnames=["filename", "ground_truth"])
    writer.writeheader()
    for fn, gt in augmented_labels:
        writer.writerow({"filename": fn, "ground_truth": gt})

    s3.put_object(
        Bucket=args.bucket,
        Key=f"{output_prefix}/labels.csv",
        Body=csv_buf.getvalue().encode("utf-8"),
        ContentType="text/csv",
    )
    print(f"Saved labels.csv with {len(augmented_labels)} entries to s3://{args.bucket}/{output_prefix}/labels.csv")
    print("Done! Now retrain probes with:")
    print(f"  python3 -m scripts.train_clip_probe --bucket {args.bucket} --s3-prefix {output_prefix}")
    print(f"  python3 -m scripts.train_dinov2_probe --bucket {args.bucket} --s3-prefix {output_prefix}")


if __name__ == "__main__":
    main()
