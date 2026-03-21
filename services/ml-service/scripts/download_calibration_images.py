#!/usr/bin/env python3
"""
Download calibration images from public datasets and upload directly to S3.

Sources:
  authentic:    food101 (HuggingFace, 512x512 real photos)
  ai_generated: ELSA1M_track1 (HuggingFace, AI-generated images from multiple models)
  tampered:     Auto-generated from authentic images using copy-move/splice transforms

Usage:
  export AWS_ACCESS_KEY_ID=AKIA...
  export AWS_SECRET_ACCESS_KEY=...
  export AWS_DEFAULT_REGION=eu-central-1

  python -m scripts.download_calibration_images \
    --bucket dent-calibration-data \
    --category all \
    --limit 600
"""

from __future__ import annotations

import argparse
import io
import random
import sys
import uuid

import boto3
import numpy as np
from PIL import Image, ImageFilter

S3_PREFIX_RAW = "raw"


def _standardize_and_upload(
    s3_client,
    bucket: str,
    category: str,
    img: Image.Image,
    source: str,
    quality: int = 90,
) -> bool:
    """Standardize image to JPEG, strip EXIF, upload to S3 with random name."""
    try:
        if img.mode != "RGB":
            img = img.convert("RGB")

        # Resize if too small or too large
        min_side = 256
        max_side = 1024
        w, h = img.size
        if max(w, h) < min_side:
            # Skip tiny images
            return False
        if max(w, h) > max_side:
            ratio = max_side / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

        # Save as JPEG without ANY metadata
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        jpeg_bytes = buf.getvalue()

        if len(jpeg_bytes) < 5000:
            return False  # Skip very small files

        random_name = uuid.uuid4().hex[:12] + ".jpg"
        key = f"{S3_PREFIX_RAW}/{category}/{random_name}"

        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=jpeg_bytes,
            ContentType="image/jpeg",
            Metadata={"source": source, "category": category},
        )
        return True
    except Exception as e:
        print(f"    Error: {e}")
        return False


# ── Authentic images ────────────────────────────────────────────────


def download_authentic(s3_client, bucket: str, limit: int) -> int:
    """Download real photos from food101 dataset."""
    from datasets import load_dataset

    print("  Source: food101 (HuggingFace, real food photos 512x512)")
    ds = load_dataset("food101", split="validation", streaming=True)

    uploaded = 0
    for i, sample in enumerate(ds):
        if uploaded >= limit:
            break
        img = sample.get("image")
        if img and _standardize_and_upload(s3_client, bucket, "authentic", img, f"food101/{i}"):
            uploaded += 1
            if uploaded % 100 == 0:
                print(f"    {uploaded}/{limit} authentic uploaded")

    print(f"  Authentic: {uploaded} uploaded")
    return uploaded


# ── AI Generated images ─────────────────────────────────────────────


def download_ai_generated(s3_client, bucket: str, limit: int) -> int:
    """Download AI-generated images from ELSA1M dataset."""
    from datasets import load_dataset

    print("  Source: elsaEU/ELSA1M_track1 (AI-generated, multiple models)")
    ds = load_dataset("elsaEU/ELSA1M_track1", split="train", streaming=True)

    uploaded = 0
    for i, sample in enumerate(ds):
        if uploaded >= limit:
            break
        img = sample.get("image")
        model = sample.get("model", "unknown")
        if img and _standardize_and_upload(
            s3_client, bucket, "ai_generated", img, f"ELSA1M/{model}/{i}"
        ):
            uploaded += 1
            if uploaded % 100 == 0:
                print(f"    {uploaded}/{limit} ai_generated uploaded")

    print(f"  AI generated: {uploaded} uploaded")
    return uploaded


# ── Tampered images (auto-generated) ────────────────────────────────


def _apply_copy_move(img: Image.Image) -> Image.Image:
    """Apply copy-move forgery: copy a random region and paste elsewhere."""
    arr = np.array(img)
    h, w = arr.shape[:2]

    # Random source region (10-30% of image)
    rh = random.randint(h // 10, h // 3)
    rw = random.randint(w // 10, w // 3)
    sy = random.randint(0, h - rh)
    sx = random.randint(0, w - rw)

    # Random destination (different from source)
    dy = random.randint(0, h - rh)
    dx = random.randint(0, w - rw)
    # Ensure some distance between source and destination
    while abs(dy - sy) < rh // 2 and abs(dx - sx) < rw // 2:
        dy = random.randint(0, h - rh)
        dx = random.randint(0, w - rw)

    # Copy region
    region = arr[sy:sy + rh, sx:sx + rw].copy()

    # Optionally apply slight transform to copied region
    if random.random() > 0.5:
        # Slight blur to blend edges
        region_img = Image.fromarray(region)
        region_img = region_img.filter(ImageFilter.GaussianBlur(radius=1))
        region = np.array(region_img)

    # Paste
    arr[dy:dy + rh, dx:dx + rw] = region
    return Image.fromarray(arr)


def _apply_splice(img1: Image.Image, img2: Image.Image) -> Image.Image:
    """Splice: take a region from img2 and paste into img1."""
    arr1 = np.array(img1)
    arr2 = np.array(img2)

    h1, w1 = arr1.shape[:2]
    h2, w2 = arr2.shape[:2]

    # Region size (20-40% of image)
    rh = min(h1, h2) // 3
    rw = min(w1, w2) // 3

    # Source from img2
    sy = random.randint(0, h2 - rh)
    sx = random.randint(0, w2 - rw)

    # Destination in img1
    dy = random.randint(0, h1 - rh)
    dx = random.randint(0, w1 - rw)

    arr1[dy:dy + rh, dx:dx + rw] = arr2[sy:sy + rh, sx:sx + rw]
    return Image.fromarray(arr1)


def download_tampered(s3_client, bucket: str, limit: int) -> int:
    """Generate tampered images from authentic images using copy-move and splice."""
    from datasets import load_dataset

    print("  Source: Auto-generated from food101 (copy-move + splice transforms)")
    ds = load_dataset("food101", split="validation", streaming=True)

    uploaded = 0
    prev_img = None

    for i, sample in enumerate(ds):
        if uploaded >= limit:
            break

        img = sample.get("image")
        if img is None:
            continue
        if img.mode != "RGB":
            img = img.convert("RGB")

        # Skip tiny images
        if max(img.size) < 256:
            continue

        # Alternate between copy-move and splice
        if random.random() > 0.4:
            # Copy-move (60% of tampered images)
            tampered = _apply_copy_move(img)
            method = "copy_move"
        elif prev_img is not None:
            # Splice with previous image (40%)
            # Resize prev to match current
            prev_resized = prev_img.resize(img.size, Image.LANCZOS)
            tampered = _apply_splice(img, prev_resized)
            method = "splice"
        else:
            prev_img = img
            continue

        if _standardize_and_upload(
            s3_client, bucket, "tampered", tampered, f"auto_{method}/{i}"
        ):
            uploaded += 1
            if uploaded % 100 == 0:
                print(f"    {uploaded}/{limit} tampered uploaded")

        prev_img = img

    print(f"  Tampered: {uploaded} uploaded")
    return uploaded


# ── Main ────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Download calibration images to S3")
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument(
        "--category",
        required=True,
        choices=["authentic", "ai_generated", "tampered", "all"],
    )
    parser.add_argument("--limit", type=int, default=600, help="Max images per category")
    parser.add_argument("--region", default="eu-central-1")
    args = parser.parse_args()

    s3 = boto3.client("s3", region_name=args.region)

    try:
        s3.head_bucket(Bucket=args.bucket)
        print(f"S3 bucket: {args.bucket} (verified)")
    except Exception as e:
        print(f"ERROR: Cannot access bucket {args.bucket}: {e}")
        sys.exit(1)

    categories = ["authentic", "ai_generated", "tampered"] if args.category == "all" else [args.category]
    total = 0

    for cat in categories:
        print(f"\n{'='*60}")
        print(f"Downloading: {cat} (limit: {args.limit})")
        print(f"{'='*60}")

        if cat == "authentic":
            count = download_authentic(s3, args.bucket, args.limit)
        elif cat == "ai_generated":
            count = download_ai_generated(s3, args.bucket, args.limit)
        elif cat == "tampered":
            count = download_tampered(s3, args.bucket, args.limit)
        else:
            count = 0

        total += count

    print(f"\n{'='*60}")
    print(f"Download complete! Total: {total} images")
    print(f"All images in s3://{args.bucket}/raw/")
    print(f"\nNext: python -m scripts.prepare_calibration_dataset --bucket {args.bucket}")


if __name__ == "__main__":
    main()
