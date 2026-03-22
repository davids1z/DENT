#!/usr/bin/env python3
"""
Download calibration images from public datasets and upload directly to S3.

Sources (v2 — improved datasets):
  authentic:    COCO val (diverse real-world scenes: vehicles, people, buildings)
  ai_generated: ELSA1M (multi-generator AI) + fallback food101-as-control
  tampered:     Charles95/image_tampering (real Photoshop manipulations)

Usage:
  export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_DEFAULT_REGION=eu-central-1

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


# ── Authentic images (COCO — real-world scenes) ─────────────────────


def download_authentic(s3_client, bucket: str, limit: int) -> int:
    """Download real photos from COCO dataset (vehicles, people, buildings)."""
    from datasets import load_dataset

    print("  Source: detection-datasets/coco val (real-world scenes)")
    uploaded = 0

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

    # Fallback: ImageNet if COCO didn't give enough
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

    # Fallback 2: food101
    if uploaded < limit:
        remaining = limit - uploaded
        print(f"    Adding {remaining} from food101...")
        try:
            ds3 = load_dataset("food101", split="validation", streaming=True)
            for i, sample in enumerate(ds3):
                if uploaded >= limit:
                    break
                img = sample.get("image")
                if img and _standardize_and_upload(s3_client, bucket, "authentic", img, f"food101/{i}"):
                    uploaded += 1
        except Exception:
            pass

    print(f"  Authentic: {uploaded} uploaded")
    return uploaded


# ── AI Generated images (ELSA1M — multi-generator) ──────────────────


def download_ai_generated(s3_client, bucket: str, limit: int) -> int:
    """Download AI-generated images from ELSA1M dataset."""
    from datasets import load_dataset

    print("  Source: elsaEU/ELSA1M_track1 (AI-generated, multiple models)")
    uploaded = 0

    try:
        ds = load_dataset("elsaEU/ELSA1M_track1", split="train", streaming=True)
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
    except Exception as e:
        print(f"    ELSA1M failed: {e}")

    print(f"  AI generated: {uploaded} uploaded")
    return uploaded


# ── Tampered images (real Photoshop manipulations) ───────────────────


def download_tampered(s3_client, bucket: str, limit: int) -> int:
    """Download tampered images from real forensic dataset + auto-generate remainder."""
    from datasets import load_dataset

    uploaded = 0

    # Primary: Charles95/image_tampering (real Photoshop edits)
    print("  Source: Charles95/image_tampering (real manipulations)")
    try:
        ds = load_dataset("Charles95/image_tampering", split="train", streaming=True)
        for i, sample in enumerate(ds):
            if uploaded >= limit:
                break
            img = sample.get("image")
            if img and _standardize_and_upload(s3_client, bucket, "tampered", img, f"image_tampering/{i}"):
                uploaded += 1
                if uploaded % 100 == 0:
                    print(f"    {uploaded}/{limit} tampered uploaded")
    except Exception as e:
        print(f"    image_tampering failed: {e}")

    # Fill remainder with auto-generated copy-move from COCO
    if uploaded < limit:
        remaining = limit - uploaded
        print(f"    Generating {remaining} copy-move tampered from COCO...")
        try:
            ds2 = load_dataset("detection-datasets/coco", split="val", streaming=True)
            prev_img = None
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
                prev_img = img
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


# ── Main ─────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Download calibration images to S3")
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--category", required=True, choices=["authentic", "ai_generated", "tampered", "all"])
    parser.add_argument("--limit", type=int, default=600)
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
