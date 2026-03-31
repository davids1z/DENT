#!/usr/bin/env python3
"""
Quality filter for v8 dataset — works directly on S3.
Downloads batches, validates, deletes bad images from S3, updates labels.csv.

Checks per class:
  1. PIL verify (corrupt → delete)
  2. Resolution: min(w,h) >= 256px → delete
  3. File size: < 5KB → delete
  4. Blur: cv2.Laplacian variance < 50 → delete (skip mobile_quality)
  5. phash dedup within class (Hamming < 10 → delete duplicate)
  6. Update labels.csv on S3
  7. Report: counts per category, balance

Usage:
  python3 -m scripts.quality_filter \
      --bucket dent-calibration-data \
      --prefix raw_v8/authentic

  python3 -m scripts.quality_filter \
      --bucket dent-calibration-data \
      --prefix raw_v8/ai_generated

  python3 -m scripts.quality_filter \
      --bucket dent-calibration-data \
      --prefix raw_v8/tampered
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from collections import defaultdict

import numpy as np
from PIL import Image

try:
    import boto3
except ImportError:
    print("ERROR: pip install boto3")
    sys.exit(1)

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import imagehash
except ImportError:
    imagehash = None


BATCH_SIZE = 100  # Process images in batches


def list_s3_images(s3, bucket: str, prefix: str) -> list[str]:
    """List all image keys under prefix."""
    keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.lower().endswith((".jpg", ".jpeg", ".png", ".webp")) and not key.endswith("labels.csv"):
                keys.append(key)
    return keys


def load_labels(s3, bucket: str, prefix: str) -> dict[str, dict]:
    """Load labels.csv from S3 → {filename: row_dict}."""
    try:
        resp = s3.get_object(Bucket=bucket, Key=f"{prefix}/labels.csv")
        content = resp["Body"].read().decode()
        labels = {}
        for row in csv.DictReader(io.StringIO(content)):
            fn = row.get("filename", "").strip()
            if fn:
                labels[fn] = dict(row)
        return labels
    except Exception:
        return {}


def check_image(s3, bucket: str, key: str, category: str) -> tuple[bool, str, bytes | None]:
    """Download and validate a single image. Returns (passed, reason, image_bytes)."""
    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
        raw_bytes = resp["Body"].read()
    except Exception as e:
        return False, f"s3_error:{e}", None

    # File size check
    if len(raw_bytes) < 5000:
        return False, "too_small_bytes", None

    # PIL verify
    try:
        img_verify = Image.open(io.BytesIO(raw_bytes))
        img_verify.verify()
    except Exception:
        return False, "corrupt", None

    # Re-open for analysis
    try:
        img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
    except Exception:
        return False, "open_failed", None

    # Resolution check
    w, h = img.size
    if min(w, h) < 256:
        return False, "too_small_resolution", None

    # Blur check (skip for mobile_quality category)
    if cv2 is not None and category != "mobile_quality":
        arr = np.array(img.convert("L"))
        laplacian_var = cv2.Laplacian(arr, cv2.CV_64F).var()
        if laplacian_var < 50:
            return False, "too_blurry", None

    return True, "ok", raw_bytes


def dedup_within_class(
    s3, bucket: str, keys: list[str], labels: dict[str, dict],
) -> list[str]:
    """Identify duplicates using phash within a class. Returns keys to delete."""
    if imagehash is None:
        print("  WARNING: imagehash not installed, skipping dedup")
        return []

    hashes: list[tuple[str, object]] = []
    to_delete = []

    for key in keys:
        try:
            resp = s3.get_object(Bucket=bucket, Key=key)
            raw_bytes = resp["Body"].read()
            img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
            h = imagehash.phash(img)

            # Check against existing hashes
            is_dup = False
            for existing_key, existing_hash in hashes:
                if h - existing_hash < 10:
                    to_delete.append(key)
                    is_dup = True
                    break

            if not is_dup:
                hashes.append((key, h))

        except Exception:
            continue

    return to_delete


def main():
    parser = argparse.ArgumentParser(description="Quality filter for v8 dataset on S3")
    parser.add_argument("--bucket", default="dent-calibration-data")
    parser.add_argument("--prefix", required=True, help="S3 prefix (e.g. raw_v8/authentic)")
    parser.add_argument("--region", default="eu-central-1")
    parser.add_argument("--skip-blur", action="store_true", help="Skip blur check")
    parser.add_argument("--skip-dedup", action="store_true", help="Skip dedup check")
    parser.add_argument("--dry-run", action="store_true", help="Don't delete, just report")
    args = parser.parse_args()

    s3 = boto3.client("s3", region_name=args.region)

    # Load labels
    labels = load_labels(s3, args.bucket, args.prefix)
    print(f"Labels loaded: {len(labels)} entries")

    # List all images
    all_keys = list_s3_images(s3, args.bucket, args.prefix)
    print(f"Images on S3: {len(all_keys)}")

    # Group by category
    category_keys: dict[str, list[str]] = defaultdict(list)
    for key in all_keys:
        fn = key.rsplit("/", 1)[-1]
        cat = labels.get(fn, {}).get("category", "unknown")
        category_keys[cat].append(key)

    print(f"\nCategories: {dict((k, len(v)) for k, v in category_keys.items())}")

    # ── Quality checks ────────────────────────────────────────────
    to_delete: list[str] = []
    rejection_reasons: dict[str, int] = defaultdict(int)

    print(f"\n--- Quality Checks ---")
    for cat, keys in sorted(category_keys.items()):
        print(f"\n  Category: {cat} ({len(keys)} images)")
        cat_delete = []

        for i, key in enumerate(keys):
            passed, reason, _ = check_image(s3, args.bucket, key, cat)
            if not passed:
                cat_delete.append(key)
                rejection_reasons[reason] += 1

            if (i + 1) % 200 == 0:
                print(f"    [{i + 1}/{len(keys)}] checked, {len(cat_delete)} to delete")

        to_delete.extend(cat_delete)
        print(f"    {cat}: {len(cat_delete)} rejected out of {len(keys)}")

    # ── Dedup ─────────────────────────────────────────────────────
    # Skip dedup for tampered class — tampered images are derived from authentic
    # sources and will naturally have similar hashes
    is_tampered = "tampered" in args.prefix.lower()
    if is_tampered:
        print(f"\n--- Dedup SKIPPED (tampered class — similar to sources by design) ---")
    if not args.skip_dedup and not is_tampered:
        print(f"\n--- Dedup Check ---")
        # Only dedup keys that passed quality check
        surviving_keys = [k for k in all_keys if k not in set(to_delete)]
        surviving_by_cat: dict[str, list[str]] = defaultdict(list)
        for key in surviving_keys:
            fn = key.rsplit("/", 1)[-1]
            cat = labels.get(fn, {}).get("category", "unknown")
            surviving_by_cat[cat].append(key)

        for cat, keys in sorted(surviving_by_cat.items()):
            print(f"  Dedup: {cat} ({len(keys)} images)...")
            dup_keys = dedup_within_class(s3, args.bucket, keys, labels)
            to_delete.extend(dup_keys)
            rejection_reasons["duplicate"] += len(dup_keys)
            print(f"    {cat}: {len(dup_keys)} duplicates found")

    # ── Report ────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Quality Filter Report")
    print(f"{'='*60}")
    print(f"Total images: {len(all_keys)}")
    print(f"To delete: {len(to_delete)}")
    print(f"Remaining: {len(all_keys) - len(to_delete)}")
    print(f"\nRejection reasons:")
    for reason, count in sorted(rejection_reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {count}")

    # Remaining per category
    delete_set = set(to_delete)
    remaining_by_cat: dict[str, int] = defaultdict(int)
    for key in all_keys:
        if key not in delete_set:
            fn = key.rsplit("/", 1)[-1]
            cat = labels.get(fn, {}).get("category", "unknown")
            remaining_by_cat[cat] += 1

    print(f"\nRemaining per category:")
    for cat, count in sorted(remaining_by_cat.items()):
        print(f"  {cat}: {count}")

    if args.dry_run:
        print(f"\nDRY RUN — no deletions performed")
        return

    # ── Delete bad images from S3 ─────────────────────────────────
    print(f"\nDeleting {len(to_delete)} images from S3...")
    deleted = 0
    for key in to_delete:
        try:
            s3.delete_object(Bucket=args.bucket, Key=key)
            deleted += 1
        except Exception as e:
            print(f"  Delete error {key}: {e}")

    print(f"Deleted {deleted} images")

    # ── Update labels.csv ─────────────────────────────────────────
    deleted_filenames = set()
    for key in to_delete:
        deleted_filenames.add(key.rsplit("/", 1)[-1])

    updated_labels = {fn: row for fn, row in labels.items() if fn not in deleted_filenames}

    csv_buf = io.StringIO()
    if updated_labels:
        fieldnames = list(next(iter(updated_labels.values())).keys())
        writer = csv.DictWriter(csv_buf, fieldnames=fieldnames)
        writer.writeheader()
        for fn, row in updated_labels.items():
            writer.writerow(row)

    s3.put_object(
        Bucket=args.bucket,
        Key=f"{args.prefix}/labels.csv",
        Body=csv_buf.getvalue().encode(),
        ContentType="text/csv",
    )
    print(f"Updated labels.csv: {len(updated_labels)} entries (was {len(labels)})")

    print(f"\nDone! Remaining: {len(all_keys) - len(to_delete)} images")


if __name__ == "__main__":
    main()
