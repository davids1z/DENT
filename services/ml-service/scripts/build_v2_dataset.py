#!/usr/bin/env python3
"""
Build V2 calibration dataset from RAISE camera RAWs + AI generators.

This script builds a clean, verified dataset for probe retraining:
  authentic: RAISE-1k camera RAW images (verified, never AI)
  ai_generated: Defactify (DALL-E 3, Midjourney v6, SDXL) + ELSA1M
  tampered: Auto-generated copy-move forgeries from RAISE images

Usage:
  # Step 1: Download RAISE-1k from http://loki.disi.unitn.it/RAISE/
  # Step 2: Extract to a local directory

  # Step 3: Run this script
  python -m scripts.build_v2_dataset \
    --raise-dir /path/to/RAISE-1k \
    --bucket dent-calibration-data \
    --auth-limit 1000 \
    --ai-limit 1000 \
    --tamp-limit 500

  # Step 4: Prepare (randomize names, strip EXIF)
  python -m scripts.prepare_calibration_dataset \
    --bucket dent-calibration-data \
    --raw-prefix raw_v2 \
    --out-prefix processed_v2

  # Step 5: Retrain probes
  python -m scripts.train_dinov2_probe --bucket dent-calibration-data --s3-prefix processed_v2
  python -m scripts.train_clip_probe --bucket dent-calibration-data --s3-prefix processed_v2
"""

from __future__ import annotations

import argparse
import io
import os
import random
import sys
import time
import uuid

import boto3
import numpy as np
from PIL import Image, ImageFilter

BUCKET_DEFAULT = "dent-calibration-data"
S3_PREFIX = "raw_v2"


def upload_image(s3, bucket: str, category: str, img: Image.Image, source: str) -> bool:
    """Standardize to JPEG 90 and upload to S3."""
    try:
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        if max(w, h) < 256:
            return False
        if max(w, h) > 1024:
            ratio = 1024 / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90, optimize=True)
        data = buf.getvalue()
        if len(data) < 5000:
            return False
        name = uuid.uuid4().hex[:12] + ".jpg"
        s3.put_object(
            Bucket=bucket,
            Key=f"{S3_PREFIX}/{category}/{name}",
            Body=data,
            ContentType="image/jpeg",
            Metadata={"source": source, "category": category},
        )
        return True
    except Exception:
        return False


def upload_raise(s3, bucket: str, raise_dir: str, limit: int) -> int:
    """Upload RAISE camera images as authentic."""
    print(f"\n{'='*60}")
    print(f"AUTHENTIC: RAISE camera images from {raise_dir}")
    print(f"{'='*60}")

    # Find all image files in RAISE directory
    extensions = {".nef", ".tif", ".tiff", ".jpg", ".jpeg", ".png", ".cr2", ".arw"}
    image_files = []
    for root, _, files in os.walk(raise_dir):
        for f in files:
            if os.path.splitext(f)[1].lower() in extensions:
                image_files.append(os.path.join(root, f))

    random.shuffle(image_files)
    print(f"  Found {len(image_files)} image files")

    if not image_files:
        print("  ERROR: No image files found in RAISE directory!")
        print(f"  Looked in: {raise_dir}")
        print(f"  Extensions: {extensions}")
        return 0

    uploaded = 0
    errors = 0
    for i, filepath in enumerate(image_files):
        if uploaded >= limit:
            break
        try:
            # For RAW files (NEF, CR2, ARW), use rawpy if available
            ext = os.path.splitext(filepath)[1].lower()
            if ext in {".nef", ".cr2", ".arw"}:
                try:
                    import rawpy
                    with rawpy.imread(filepath) as raw:
                        rgb = raw.postprocess()
                    img = Image.fromarray(rgb)
                except ImportError:
                    # Fall back to Pillow (may not work for all RAW)
                    img = Image.open(filepath)
            else:
                img = Image.open(filepath)

            source = f"RAISE/{os.path.basename(filepath)}"
            if upload_image(s3, bucket, "authentic", img, source):
                uploaded += 1
                if uploaded % 100 == 0:
                    print(f"    {uploaded}/{limit} authentic uploaded")
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"    Error: {filepath}: {e}")

    print(f"  Authentic: {uploaded} uploaded, {errors} errors")
    return uploaded


def download_ai_generated(s3, bucket: str, limit: int) -> int:
    """Download AI-generated images from HuggingFace datasets."""
    from datasets import load_dataset

    print(f"\n{'='*60}")
    print(f"AI GENERATED: diverse generators from HuggingFace")
    print(f"{'='*60}")

    uploaded = 0

    # Defactify: DALL-E 3, Midjourney v6, SDXL, SD 2.1/3.0
    print("\n  Source 1: Defactify (DALL-E 3, Midjourney, SDXL)...")
    try:
        ds = load_dataset(
            "Rajarshi-Roy-research/Defactify_Image_Dataset",
            split="train", streaming=True,
        )
        for i, sample in enumerate(ds):
            if uploaded >= int(limit * 0.6):
                break
            img = sample.get("Image") or sample.get("image")
            if img and upload_image(s3, bucket, "ai_generated", img, f"defactify/{i}"):
                uploaded += 1
                if uploaded % 100 == 0:
                    print(f"    {uploaded}/{limit}")
    except Exception as e:
        print(f"    Defactify failed: {e}")

    # ELSA1M: SD, Midjourney, DALL-E, Flux, PixArt
    if uploaded < limit:
        remaining = limit - uploaded
        print(f"\n  Source 2: ELSA1M (multi-generator)... [{uploaded} so far]")
        try:
            ds2 = load_dataset("elsaEU/ELSA1M_track1", split="train", streaming=True)
            elsa_count = 0
            for i, sample in enumerate(ds2):
                if elsa_count >= remaining:
                    break
                img = sample.get("image")
                model = sample.get("model", "unknown")
                if img and upload_image(s3, bucket, "ai_generated", img, f"ELSA1M/{model}/{i}"):
                    uploaded += 1
                    elsa_count += 1
                    if elsa_count % 100 == 0:
                        print(f"    {elsa_count} from ELSA1M (total {uploaded})")
        except Exception as e:
            print(f"    ELSA1M failed: {e}")

    print(f"  AI Generated: {uploaded} uploaded")
    return uploaded


def generate_tampered(s3, bucket: str, raise_dir: str, limit: int) -> int:
    """Generate tampered images by applying copy-move to RAISE photos."""
    print(f"\n{'='*60}")
    print(f"TAMPERED: copy-move forgeries from RAISE images")
    print(f"{'='*60}")

    # Find RAISE images to use as base for tampering
    extensions = {".nef", ".tif", ".tiff", ".jpg", ".jpeg", ".png", ".cr2", ".arw"}
    image_files = []
    for root, _, files in os.walk(raise_dir):
        for f in files:
            if os.path.splitext(f)[1].lower() in extensions:
                image_files.append(os.path.join(root, f))

    random.shuffle(image_files)
    uploaded = 0

    for filepath in image_files:
        if uploaded >= limit:
            break
        try:
            ext = os.path.splitext(filepath)[1].lower()
            if ext in {".nef", ".cr2", ".arw"}:
                try:
                    import rawpy
                    with rawpy.imread(filepath) as raw:
                        rgb = raw.postprocess()
                    img = Image.fromarray(rgb)
                except ImportError:
                    img = Image.open(filepath)
            else:
                img = Image.open(filepath)

            if img.mode != "RGB":
                img = img.convert("RGB")
            if max(img.size) < 256:
                continue

            tampered = _apply_copy_move(img)
            if upload_image(s3, bucket, "tampered", tampered, f"copymove_RAISE/{os.path.basename(filepath)}"):
                uploaded += 1
                if uploaded % 100 == 0:
                    print(f"    {uploaded}/{limit} tampered generated")
        except Exception:
            continue

    print(f"  Tampered: {uploaded} generated")
    return uploaded


def _apply_copy_move(img: Image.Image) -> Image.Image:
    """Apply copy-move forgery."""
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
        region = np.array(Image.fromarray(region).filter(ImageFilter.GaussianBlur(radius=1)))
    arr[dy:dy + rh, dx:dx + rw] = region
    return Image.fromarray(arr)


def main():
    parser = argparse.ArgumentParser(description="Build V2 calibration dataset from RAISE + AI generators")
    parser.add_argument("--raise-dir", required=True, help="Path to extracted RAISE-1k directory")
    parser.add_argument("--bucket", default=BUCKET_DEFAULT, help="S3 bucket")
    parser.add_argument("--region", default="eu-central-1")
    parser.add_argument("--auth-limit", type=int, default=1000, help="Max authentic images")
    parser.add_argument("--ai-limit", type=int, default=1000, help="Max AI images")
    parser.add_argument("--tamp-limit", type=int, default=500, help="Max tampered images")
    args = parser.parse_args()

    if not os.path.isdir(args.raise_dir):
        print(f"ERROR: RAISE directory not found: {args.raise_dir}")
        print(f"Download from: http://loki.disi.unitn.it/RAISE/confirm.php?package=RAISE-1k")
        sys.exit(1)

    s3 = boto3.client("s3", region_name=args.region)
    t0 = time.time()

    n_auth = upload_raise(s3, args.bucket, args.raise_dir, args.auth_limit)
    n_ai = download_ai_generated(s3, args.bucket, args.ai_limit)
    n_tamp = generate_tampered(s3, args.bucket, args.raise_dir, args.tamp_limit)

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"DATASET V2 COMPLETE: {n_auth + n_ai + n_tamp} images in {elapsed:.0f}s")
    print(f"  Authentic (RAISE): {n_auth}")
    print(f"  AI generated: {n_ai}")
    print(f"  Tampered: {n_tamp}")
    print(f"\nNext steps:")
    print(f"  1. python -m scripts.prepare_calibration_dataset --bucket {args.bucket} --raw-prefix raw_v2 --out-prefix processed_v2")
    print(f"  2. python -m scripts.train_dinov2_probe --bucket {args.bucket} --s3-prefix processed_v2")
    print(f"  3. python -m scripts.train_clip_probe --bucket {args.bucket} --s3-prefix processed_v2")


if __name__ == "__main__":
    main()
