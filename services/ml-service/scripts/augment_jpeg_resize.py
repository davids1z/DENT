#!/usr/bin/env python3
"""Add JPEG compression + social-media resize augmentation to training dataset.

Complements WebP augmentation by adding:
1. JPEG re-compression at various quality levels (simulates real-world uploads)
2. Resize-down + re-compress (simulates social media: Instagram, WhatsApp)

Run AFTER augment_webp.py. Adds new images to the same S3 prefix and
updates labels.csv.

Usage:
  python -m scripts.augment_jpeg_resize \
    --bucket dent-calibration-data \
    --prefix train_v7_webp \
    --jpeg-qualities 50,70 \
    --resize-widths 800,1080
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import random
import sys

import boto3
from PIL import Image

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(it, **kw):
        total = kw.get("total", "?")
        for i, x in enumerate(it, 1):
            if i % 100 == 0:
                print(f"  [{i}/{total}]", flush=True)
            yield x

VALID_CLASSES = {"authentic", "ai_generated", "tampered"}

# Only augment a fraction of originals to avoid dataset explosion
# AI + tampered get both JPEG + resize; authentic gets only JPEG (1 quality)
SAMPLE_RATE_BY_CLASS = {
    "ai_generated": 0.5,   # 50% of AI originals get JPEG/resize copies
    "tampered": 0.5,       # 50% of tampered originals
    "authentic": 0.3,      # 30% of authentic (fewer to maintain balance)
}


def main():
    parser = argparse.ArgumentParser(description="Add JPEG + resize augmentation")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", required=True, help="S3 prefix (e.g. train_v7_webp)")
    parser.add_argument("--region", default="eu-central-1")
    parser.add_argument("--jpeg-qualities", default="50,70",
                        help="JPEG quality levels for re-compression")
    parser.add_argument("--resize-widths", default="800,1080",
                        help="Resize widths (simulates social media)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    jpeg_qualities = [int(q) for q in args.jpeg_qualities.split(",")]
    resize_widths = [int(w) for w in args.resize_widths.split(",")]

    s3 = boto3.client("s3", region_name=args.region)
    prefix = args.prefix

    # Load existing labels
    print(f"Loading labels from s3://{args.bucket}/{prefix}/labels.csv ...", flush=True)
    resp = s3.get_object(Bucket=args.bucket, Key=f"{prefix}/labels.csv")
    content = resp["Body"].read().decode("utf-8")
    labels = {}
    for row in csv.DictReader(io.StringIO(content)):
        fn = row.get("filename", "").strip()
        gt = row.get("ground_truth", "").strip().lower()
        if fn and gt in VALID_CLASSES:
            labels[fn] = gt

    # Only augment ORIGINAL images (not already-augmented WebP copies)
    originals = {fn: gt for fn, gt in labels.items()
                 if not fn.endswith(".webp") and "_jpeg_q" not in fn and "_rsz" not in fn}

    print(f"Total labels: {len(labels)}, Original images: {len(originals)}", flush=True)

    # Plan augmentations
    new_labels = []
    plan = []

    for fn, gt in originals.items():
        sample_rate = SAMPLE_RATE_BY_CLASS.get(gt, 0.3)
        if random.random() > sample_rate:
            continue

        base, ext = os.path.splitext(fn)

        # JPEG re-compression
        for q in jpeg_qualities:
            new_fn = f"{base}_jpeg_q{q}.jpg"
            plan.append((fn, new_fn, "jpeg", q, None))
            new_labels.append((new_fn, gt))

        # Resize + JPEG (simulate social media)
        for w in resize_widths:
            new_fn = f"{base}_rsz{w}.jpg"
            plan.append((fn, new_fn, "resize", 80, w))  # JPEG q80 after resize
            new_labels.append((new_fn, gt))

    print(f"Will create {len(plan)} augmented copies", flush=True)
    class_counts = {}
    for fn, gt in new_labels:
        class_counts[gt] = class_counts.get(gt, 0) + 1
    print(f"  New copies per class: {class_counts}", flush=True)

    if args.dry_run:
        print("DRY RUN — no uploads", flush=True)
        return

    # Process
    errors = 0
    uploaded = 0

    for src_fn, dst_fn, aug_type, quality, width in tqdm(plan, desc="Augmenting", total=len(plan)):
        try:
            resp = s3.get_object(Bucket=args.bucket, Key=f"{prefix}/{src_fn}")
            img = Image.open(io.BytesIO(resp["Body"].read())).convert("RGB")

            if aug_type == "resize" and width:
                # Resize to target width maintaining aspect ratio
                w, h = img.size
                if w > width:
                    ratio = width / w
                    img = img.resize((width, int(h * ratio)), Image.LANCZOS)

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)

            s3.put_object(
                Bucket=args.bucket,
                Key=f"{prefix}/{dst_fn}",
                Body=buf.getvalue(),
                ContentType="image/jpeg",
            )
            uploaded += 1

        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  Error {src_fn}: {e}", flush=True)

    # Update labels.csv
    print(f"\nUploaded {uploaded} augmented copies ({errors} errors)", flush=True)
    print("Updating labels.csv ...", flush=True)

    all_labels = list(labels.items()) + new_labels
    csv_buf = io.StringIO()
    writer = csv.DictWriter(csv_buf, fieldnames=["filename", "ground_truth"])
    writer.writeheader()
    for fn, gt in all_labels:
        writer.writerow({"filename": fn, "ground_truth": gt})

    s3.put_object(
        Bucket=args.bucket,
        Key=f"{prefix}/labels.csv",
        Body=csv_buf.getvalue().encode("utf-8"),
        ContentType="text/csv",
    )
    print(f"Updated labels.csv: {len(labels)} → {len(all_labels)} entries", flush=True)

    # Final counts
    final_counts = {}
    for fn, gt in all_labels:
        final_counts[gt] = final_counts.get(gt, 0) + 1
    print(f"Final dataset: {final_counts}", flush=True)


if __name__ == "__main__":
    main()
