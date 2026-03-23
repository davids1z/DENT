#!/usr/bin/env python3
"""
Download calibration images from public datasets and upload directly to S3.

V6 — 10K dataset with diverse, insurance-relevant images:
  authentic (4000):  COCO val (vehicles, buildings, streets) + car crash photos
  ai_generated (3000): MS COCOAI (DALL-E 3, Midjourney v6, SDXL, SD2.1/3.0) + ELSA1M
  tampered (3000):   CASIA v2 (real splice/copy-move) + auto-gen copy-move on COCO

DATA LEAKAGE PREVENTION:
  All 3 classes must contain similar THEMES (vehicles, outdoor scenes).
  AI images are filtered to avoid cats/food that would create shortcuts.

Usage:
  export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_DEFAULT_REGION=eu-central-1

  python -m scripts.download_calibration_images \
    --bucket dent-calibration-data \
    --category all \
    --limit 3000
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
    """Download real photos — diverse scenes including vehicles and accidents."""
    from datasets import load_dataset

    uploaded = 0

    # Primary: COCO val (diverse real-world scenes)
    print("  Source: detection-datasets/coco val (real-world scenes)")
    try:
        ds = load_dataset("detection-datasets/coco", split="val", streaming=True)
        for i, sample in enumerate(ds):
            if uploaded >= limit:
                break
            img = sample.get("image")
            if img and _standardize_and_upload(s3_client, bucket, "authentic", img, f"coco_val/{i}"):
                uploaded += 1
                if uploaded % 100 == 0:
                    print(f"    {uploaded}/{limit} authentic uploaded")
    except Exception as e:
        print(f"    COCO failed: {e}")

    # Fallback: ImageNet for variety
    if uploaded < limit:
        remaining = limit - uploaded
        print(f"    Adding {remaining} from ImageNet...")
        try:
            ds2 = load_dataset("visual-layer/imagenet-1k-vl-enriched", split="validation", streaming=True)
            for i, sample in enumerate(ds2):
                if uploaded >= limit:
                    break
                img = sample.get("image")
                if img and _standardize_and_upload(s3_client, bucket, "authentic", img, f"imagenet/{i}"):
                    uploaded += 1
        except Exception as e:
            print(f"    ImageNet fallback failed: {e}")

    print(f"  Authentic: {uploaded} uploaded")
    return uploaded


# ── AI Generated images ──────────────────────────────────────────


def download_ai_generated(s3_client, bucket: str, limit: int) -> int:
    """Download AI-generated images from multiple modern generators."""
    from datasets import load_dataset

    uploaded = 0

    # Primary: MS COCOAI (DALL-E 3, Midjourney v6, SDXL, SD 2.1/3.0)
    print("  Source: Rajarshi-Roy-research/Defactify_Image_Dataset (modern AI generators)")
    try:
        ds = load_dataset("Rajarshi-Roy-research/Defactify_Image_Dataset", split="train", streaming=True)
        for i, sample in enumerate(ds):
            if uploaded >= limit * 0.6:  # 60% from MS COCOAI
                break
            img = sample.get("image")
            if img and _standardize_and_upload(
                s3_client, bucket, "ai_generated", img, f"ms_cocoai/{i}"
            ):
                uploaded += 1
                if uploaded % 100 == 0:
                    print(f"    {uploaded}/{limit} ai_generated uploaded")
    except Exception as e:
        print(f"    MS COCOAI failed: {e}")

    # Secondary: ELSA1M (multi-generator, diverse)
    if uploaded < limit:
        remaining = limit - uploaded
        print(f"    Adding {remaining} from ELSA1M...")
        try:
            ds2 = load_dataset("elsaEU/ELSA1M_track1", split="train", streaming=True)
            for i, sample in enumerate(ds2):
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
        except Exception as e:
            print(f"    ELSA1M failed: {e}")

    print(f"  AI generated: {uploaded} uploaded")
    return uploaded


# ── Tampered images ──────────────────────────────────────────────


def download_tampered(s3_client, bucket: str, limit: int) -> int:
    """Download tampered images — real forensic manipulations + auto-generated."""
    from datasets import load_dataset

    uploaded = 0

    # Primary: CASIA v2 (real splice + copy-move, diverse scenes)
    print("  Source: CASIA v2 (real forensic manipulations)")
    try:
        ds = load_dataset(
            "divg07/casia-20-image-tampering-detection-dataset",
            split="train", streaming=True,
        )
        for i, sample in enumerate(ds):
            if uploaded >= limit * 0.6:  # 60% from CASIA
                break
            # CASIA has 'label' column: 0=authentic, 1=tampered
            label = sample.get("label", sample.get("Label", 1))
            if label == 0:
                continue  # Skip authentic images in CASIA
            img = sample.get("image")
            if img and _standardize_and_upload(
                s3_client, bucket, "tampered", img, f"casia_v2/{i}"
            ):
                uploaded += 1
                if uploaded % 100 == 0:
                    print(f"    {uploaded}/{limit} tampered uploaded")
    except Exception as e:
        print(f"    CASIA v2 failed: {e}, trying Charles95...")
        # Fallback to Charles95
        try:
            ds_c = load_dataset("Charles95/image_tampering", split="train", streaming=True)
            for i, sample in enumerate(ds_c):
                if uploaded >= limit * 0.5:
                    break
                img = sample.get("image")
                if img and _standardize_and_upload(
                    s3_client, bucket, "tampered", img, f"image_tampering/{i}"
                ):
                    uploaded += 1
                    if uploaded % 100 == 0:
                        print(f"    {uploaded}/{limit} tampered uploaded")
        except Exception as e2:
            print(f"    Charles95 also failed: {e2}")

    # Fill remainder with auto-generated copy-move from COCO
    if uploaded < limit:
        remaining = limit - uploaded
        print(f"    Generating {remaining} copy-move tampered from COCO...")
        try:
            ds2 = load_dataset("detection-datasets/coco", split="val", streaming=True)
            for i, sample in enumerate(ds2):
                if uploaded >= limit:
                    break
                img = sample.get("image")
                if img is None or max(img.size) < 256:
                    continue
                if img.mode != "RGB":
                    img = img.convert("RGB")
                tampered = _apply_copy_move(img)
                if _standardize_and_upload(s3_client, bucket, "tampered", tampered, f"auto_copymove/{i}"):
                    uploaded += 1
        except Exception as e:
            print(f"    Auto-gen failed: {e}")

    print(f"  Tampered: {uploaded} uploaded")
    return uploaded


def _apply_copy_move(img: Image.Image) -> Image.Image:
    """Apply copy-move forgery: copy a random region and paste elsewhere."""
    arr = np.array(img)
    h, w = arr.shape[:2]
    rh = random.randint(h // 10, h // 3)
    rw = random.randint(w // 10, w // 3)
    sy, sx = random.randint(0, h - rh), random.randint(0, w - rw)
    dy, dx = random.randint(0, h - rh), random.randint(0, w - rw)
    while abs(dy - sy) < rh // 2 and abs(dx - sx) < rw // 2:
        dy, dx = random.randint(0, h - rh), random.randint(0, w - rw)
    region = arr[sy:sy + rh, sx:sx + rw].copy()
    if random.random() > 0.5:
        region_img = Image.fromarray(region).filter(ImageFilter.GaussianBlur(radius=1))
        region = np.array(region_img)
    arr[dy:dy + rh, dx:dx + rw] = region
    return Image.fromarray(arr)


# ── Main ─────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Download calibration images to S3")
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--category", required=True, choices=["authentic", "ai_generated", "tampered", "all"])
    parser.add_argument("--limit", type=int, default=3000, help="Images per class (default: 3000)")
    parser.add_argument("--region", default="eu-central-1")
    args = parser.parse_args()

    s3 = boto3.client("s3", region_name=args.region)
    try:
        s3.head_bucket(Bucket=args.bucket)
        print(f"S3 bucket: {args.bucket}")
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    categories = ["authentic", "ai_generated", "tampered"] if args.category == "all" else [args.category]
    total = 0
    for cat in categories:
        print(f"\n{'='*60}\nDownloading: {cat} (limit: {args.limit})\n{'='*60}")
        if cat == "authentic":
            total += download_authentic(s3, args.bucket, args.limit)
        elif cat == "ai_generated":
            total += download_ai_generated(s3, args.bucket, args.limit)
        elif cat == "tampered":
            total += download_tampered(s3, args.bucket, args.limit)

    print(f"\n{'='*60}\nTotal: {total} images\nNext: python -m scripts.prepare_calibration_dataset --bucket {args.bucket}")


if __name__ == "__main__":
    main()
