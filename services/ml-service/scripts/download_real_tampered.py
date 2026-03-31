#!/usr/bin/env python3
"""Download authentic (real) and tampered images from HuggingFace to S3.

Authentic sources:
  - COCO val2017 (detection-datasets/coco) — diverse real-world scenes
  - ImageNet validation (visual-layer/imagenet-1k-vl-enriched) — fallback

Tampered sources:
  - CASIA v2 (divg07/casia-20-image-tampering-detection-dataset) — splice + copy-move
  - Auto-generated copy-move from COCO authentic images

All images standardized to JPEG q90, max 1024px, EXIF stripped, random filenames.
Uploads directly to S3 raw/{authentic,tampered}/.

Usage:
  python -m scripts.download_real_tampered \
    --bucket dent-calibration-data \
    --category all \
    --limit 5000

  python -m scripts.download_real_tampered \
    --bucket dent-calibration-data \
    --category authentic \
    --limit 5000
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
    s3_client, bucket: str, category: str, img: Image.Image,
    source: str, quality: int = 90,
) -> bool:
    """Standardize image to JPEG, strip EXIF, upload to S3 with random name."""
    try:
        if img.mode != "RGB":
            img = img.convert("RGB")
        min_side, max_side = 256, 1024
        w, h = img.size
        if max(w, h) < min_side:
            return False
        if max(w, h) > max_side:
            ratio = max_side / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        jpeg_bytes = buf.getvalue()
        if len(jpeg_bytes) < 5000:
            return False
        random_name = uuid.uuid4().hex[:12] + ".jpg"
        key = f"{S3_PREFIX_RAW}/{category}/{random_name}"
        s3_client.put_object(
            Bucket=bucket, Key=key, Body=jpeg_bytes,
            ContentType="image/jpeg",
            Metadata={"source": source, "category": category},
        )
        return True
    except Exception:
        return False


# ── Authentic images ─────────────────────────────────────────────


def download_authentic(s3_client, bucket: str, limit: int) -> int:
    """Download real photos from COCO + ImageNet."""
    from datasets import load_dataset

    uploaded = 0

    # Primary: COCO val (diverse real-world scenes)
    print("  Source: detection-datasets/coco val2017")
    try:
        ds = load_dataset("detection-datasets/coco", split="val", streaming=True)
        for i, sample in enumerate(ds):
            if uploaded >= limit:
                break
            img = sample.get("image")
            if img and _standardize_and_upload(
                s3_client, bucket, "authentic", img, f"coco_val/{i}"
            ):
                uploaded += 1
                if uploaded % 200 == 0:
                    print(f"    {uploaded}/{limit} authentic uploaded")
    except Exception as e:
        print(f"    COCO failed: {e}")

    # If COCO wasn't enough, add from COCO train
    if uploaded < limit:
        remaining = limit - uploaded
        print(f"    Need {remaining} more, trying COCO train split...")
        try:
            ds2 = load_dataset("detection-datasets/coco", split="train", streaming=True)
            count = 0
            for i, sample in enumerate(ds2):
                if uploaded >= limit:
                    break
                # Skip some to get diversity (don't take first N)
                if random.random() > 0.3:
                    continue
                img = sample.get("image")
                if img and _standardize_and_upload(
                    s3_client, bucket, "authentic", img, f"coco_train/{i}"
                ):
                    uploaded += 1
                    count += 1
                    if count % 200 == 0:
                        print(f"    {uploaded}/{limit} authentic uploaded")
        except Exception as e:
            print(f"    COCO train failed: {e}")

    # Fallback: ImageNet validation
    if uploaded < limit:
        remaining = limit - uploaded
        print(f"    Need {remaining} more, trying ImageNet validation...")
        try:
            ds3 = load_dataset(
                "visual-layer/imagenet-1k-vl-enriched",
                split="validation", streaming=True,
            )
            for i, sample in enumerate(ds3):
                if uploaded >= limit:
                    break
                img = sample.get("image")
                if img and _standardize_and_upload(
                    s3_client, bucket, "authentic", img, f"imagenet/{i}"
                ):
                    uploaded += 1
                    if uploaded % 200 == 0:
                        print(f"    {uploaded}/{limit} authentic uploaded")
        except Exception as e:
            print(f"    ImageNet fallback failed: {e}")

    print(f"  Authentic total: {uploaded}")
    return uploaded


# ── Tampered images ──────────────────────────────────────────────


def _apply_copy_move(img: Image.Image) -> Image.Image:
    """Apply copy-move forgery: copy a random region and paste elsewhere."""
    arr = np.array(img)
    h, w = arr.shape[:2]
    rh = random.randint(h // 10, h // 3)
    rw = random.randint(w // 10, w // 3)
    sy, sx = random.randint(0, h - rh), random.randint(0, w - rw)
    dy, dx = random.randint(0, h - rh), random.randint(0, w - rw)
    # Ensure source and dest don't overlap too much
    while abs(dy - sy) < rh // 2 and abs(dx - sx) < rw // 2:
        dy, dx = random.randint(0, h - rh), random.randint(0, w - rw)
    region = arr[sy:sy + rh, sx:sx + rw].copy()
    # Sometimes apply slight blur for realism
    if random.random() > 0.5:
        region_img = Image.fromarray(region).filter(
            ImageFilter.GaussianBlur(radius=random.uniform(0.5, 1.5))
        )
        region = np.array(region_img)
    arr[dy:dy + rh, dx:dx + rw] = region
    return Image.fromarray(arr)


def _apply_splice(img1: Image.Image, img2: Image.Image) -> Image.Image:
    """Splice a region from img2 into img1."""
    arr1 = np.array(img1)
    arr2 = np.array(img2)
    h1, w1 = arr1.shape[:2]
    h2, w2 = arr2.shape[:2]
    # Take a region from img2
    rh = min(random.randint(h2 // 6, h2 // 3), h1 // 2)
    rw = min(random.randint(w2 // 6, w2 // 3), w1 // 2)
    sy, sx = random.randint(0, h2 - rh), random.randint(0, w2 - rw)
    dy, dx = random.randint(0, h1 - rh), random.randint(0, w1 - rw)
    region = arr2[sy:sy + rh, sx:sx + rw].copy()
    # Blend edges slightly
    if random.random() > 0.3:
        region_img = Image.fromarray(region).filter(
            ImageFilter.GaussianBlur(radius=random.uniform(0.3, 1.0))
        )
        region = np.array(region_img)
    arr1[dy:dy + rh, dx:dx + rw] = region
    return Image.fromarray(arr1)


def download_tampered(s3_client, bucket: str, limit: int) -> int:
    """Download tampered images from CASIA + auto-generate copy-move/splice."""
    from datasets import load_dataset

    uploaded = 0

    # Primary: CASIA v2 (real splice + copy-move)
    casia_target = int(limit * 0.5)
    print(f"  Source: CASIA v2 (target: {casia_target})")
    try:
        ds = load_dataset(
            "divg07/casia-20-image-tampering-detection-dataset",
            split="train", streaming=True,
        )
        for i, sample in enumerate(ds):
            if uploaded >= casia_target:
                break
            # CASIA has label: 0=authentic, 1=tampered
            label = sample.get("label", sample.get("Label", 1))
            if label == 0:
                continue
            img = sample.get("image")
            if img and _standardize_and_upload(
                s3_client, bucket, "tampered", img, f"casia_v2/{i}"
            ):
                uploaded += 1
                if uploaded % 200 == 0:
                    print(f"    {uploaded}/{limit} tampered uploaded")
    except Exception as e:
        print(f"    CASIA v2 failed: {e}")

    # Fill remainder with auto-generated copy-move + splice from COCO
    if uploaded < limit:
        remaining = limit - uploaded
        print(f"    Generating {remaining} auto-tampered from COCO...")
        try:
            ds2 = load_dataset("detection-datasets/coco", split="val", streaming=True)
            buffer: list[Image.Image] = []  # keep recent images for splicing

            for i, sample in enumerate(ds2):
                if uploaded >= limit:
                    break
                img = sample.get("image")
                if img is None or max(img.size) < 256:
                    continue
                if img.mode != "RGB":
                    img = img.convert("RGB")

                buffer.append(img)
                if len(buffer) > 20:
                    buffer.pop(0)

                # Alternate between copy-move and splice
                if random.random() > 0.4 and len(buffer) >= 3:
                    # Splice from another image
                    donor = random.choice(buffer[:-1])
                    tampered = _apply_splice(img, donor)
                    source = f"auto_splice/{i}"
                else:
                    # Copy-move within same image
                    tampered = _apply_copy_move(img)
                    source = f"auto_copymove/{i}"

                if _standardize_and_upload(
                    s3_client, bucket, "tampered", tampered, source
                ):
                    uploaded += 1
                    if uploaded % 200 == 0:
                        print(f"    {uploaded}/{limit} tampered uploaded")
        except Exception as e:
            print(f"    Auto-gen failed: {e}")

    print(f"  Tampered total: {uploaded}")
    return uploaded


# ── Main ─────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download authentic + tampered images to S3"
    )
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--category", required=True,
                        choices=["authentic", "tampered", "all"])
    parser.add_argument("--limit", type=int, default=5000,
                        help="Images per category (default: 5000)")
    parser.add_argument("--region", default="eu-central-1")
    args = parser.parse_args()

    s3 = boto3.client("s3", region_name=args.region)
    try:
        s3.head_bucket(Bucket=args.bucket)
        print(f"S3 bucket: {args.bucket}")
    except Exception as e:
        print(f"ERROR: Cannot access bucket: {e}")
        sys.exit(1)

    categories = (
        ["authentic", "tampered"]
        if args.category == "all"
        else [args.category]
    )
    total = 0
    for cat in categories:
        print(f"\n{'='*60}\nDownloading: {cat} (limit: {args.limit})\n{'='*60}")
        if cat == "authentic":
            total += download_authentic(s3, args.bucket, args.limit)
        elif cat == "tampered":
            total += download_tampered(s3, args.bucket, args.limit)

    print(f"\n{'='*60}")
    print(f"Total: {total} images uploaded to s3://{args.bucket}/raw/")
    print(f"\nNext steps:")
    print(f"  1. python -m scripts.prepare_calibration_dataset --bucket {args.bucket}")
    print(f"  2. python -m scripts.augment_webp --bucket {args.bucket} "
          f"--input-prefix processed --output-prefix train_v7_webp")


if __name__ == "__main__":
    main()
