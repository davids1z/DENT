#!/usr/bin/env python3
"""
Download VEHICLE-SPECIFIC calibration images for DENT V7.

V7 dataset structure (insurance domain-specific):
  authentic (5000):  Real car damage photos from VehiDE + CarDD datasets
  ai_generated (3000): AI-generated car crash/damage images via DALL-E/MJ prompts
  tampered (2000):   Synthetic splice/copy-move ON car images (not birds/faces)

Sources:
  authentic:     VehiDE (Kaggle, 13.9K images), CarDD (HuggingFace, 4K images)
  ai_generated:  DiffusionDB vehicle subset + manual prompt generation
  tampered:      Auto-generated copy-move/splice on VehiDE authentic images

Usage:
  # Prerequisites:
  pip install kaggle datasets boto3 Pillow tqdm

  # Set up Kaggle API: ~/.kaggle/kaggle.json
  # Set up AWS: export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...

  python -m scripts.download_vehicle_dataset \
    --bucket dent-calibration-data \
    --category authentic \
    --limit 5000

  python -m scripts.download_vehicle_dataset \
    --bucket dent-calibration-data \
    --category tampered \
    --limit 2000

  python -m scripts.download_vehicle_dataset \
    --bucket dent-calibration-data \
    --category ai_generated \
    --limit 3000
"""

from __future__ import annotations

import argparse
import io
import os
import random
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

import boto3
import numpy as np
from PIL import Image, ImageFilter

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):
        total = kwargs.get("total", "?")
        desc = kwargs.get("desc", "")
        for i, item in enumerate(iterable, 1):
            print(f"\r  {desc} [{i}/{total}]", end="", flush=True)
            yield item
        print()


S3_PREFIX_RAW = "v7_raw"
S3_PREFIX_PROCESSED = "v7_processed"


def _standardize_and_upload(
    s3_client, bucket: str, category: str, img: Image.Image,
    source: str, quality: int = 90, prefix: str = S3_PREFIX_RAW,
) -> bool:
    """Standardize image to JPEG, strip EXIF, upload to S3."""
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
        key = f"{prefix}/{category}/{random_name}"
        s3_client.put_object(
            Bucket=bucket, Key=key, Body=jpeg_bytes,
            ContentType="image/jpeg",
            Metadata={"source": source},
        )
        return True
    except Exception as e:
        print(f"  Upload error: {e}")
        return False


# ─── AUTHENTIC: VehiDE + CarDD ────────────────────────────────────────

def download_vehide(s3_client, bucket: str, limit: int) -> int:
    """Download VehiDE car damage dataset from Kaggle."""
    print(f"\n=== VehiDE (Kaggle) — up to {limit} images ===")
    tmpdir = tempfile.mkdtemp(prefix="vehide_")

    try:
        import subprocess
        result = subprocess.run(
            ["kaggle", "datasets", "download", "-d",
             "hendrichscullen/vehide-dataset-automatic-vehicle-damage-detection",
             "-p", tmpdir, "--unzip"],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            print(f"  Kaggle download failed: {result.stderr[:200]}")
            return 0
    except FileNotFoundError:
        print("  ERROR: kaggle CLI not installed. pip install kaggle")
        return 0
    except Exception as e:
        print(f"  ERROR: {e}")
        return 0

    # Find all jpg/jpeg/png images
    images = []
    for root, dirs, files in os.walk(tmpdir):
        for f in files:
            if f.lower().endswith((".jpg", ".jpeg", ".png")):
                images.append(os.path.join(root, f))

    print(f"  Found {len(images)} images in VehiDE")
    random.shuffle(images)

    count = 0
    for path in tqdm(images[:limit], desc="VehiDE upload", total=min(len(images), limit)):
        try:
            img = Image.open(path)
            if _standardize_and_upload(s3_client, bucket, "authentic", img, "vehide"):
                count += 1
        except Exception:
            continue

    shutil.rmtree(tmpdir, ignore_errors=True)
    print(f"  Uploaded {count} VehiDE images")
    return count


def download_cardd(s3_client, bucket: str, limit: int) -> int:
    """Download CarDD car damage dataset from HuggingFace."""
    print(f"\n=== CarDD (HuggingFace) — up to {limit} images ===")

    try:
        from datasets import load_dataset
        ds = load_dataset("harpreetsahota/CarDD", split="train")
    except Exception as e:
        print(f"  ERROR loading CarDD: {e}")
        return 0

    count = 0
    indices = list(range(len(ds)))
    random.shuffle(indices)

    for idx in tqdm(indices[:limit], desc="CarDD upload", total=min(len(ds), limit)):
        try:
            item = ds[idx]
            img = item.get("image")
            if img is None:
                continue
            if isinstance(img, Image.Image):
                if _standardize_and_upload(s3_client, bucket, "authentic", img, "cardd"):
                    count += 1
        except Exception:
            continue

    print(f"  Uploaded {count} CarDD images")
    return count


# ─── TAMPERED: Synthetic manipulations on car images ──────────────────

def generate_tampered(s3_client, bucket: str, limit: int) -> int:
    """Generate synthetic copy-move/splice on existing S3 authentic images."""
    print(f"\n=== Generating tampered car images — {limit} images ===")
    print("  (Downloads authentic images from S3, applies synthetic manipulations)")

    # List existing authentic images
    paginator = s3_client.get_paginator("list_objects_v2")
    auth_keys = []
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{S3_PREFIX_RAW}/authentic/"):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".jpg"):
                auth_keys.append(obj["Key"])

    if len(auth_keys) < 20:
        print(f"  ERROR: Need at least 20 authentic images, found {len(auth_keys)}")
        print("  Run with --category authentic first!")
        return 0

    random.shuffle(auth_keys)
    count = 0

    for key in tqdm(auth_keys[:limit * 2], desc="Tampered gen", total=min(len(auth_keys), limit * 2)):
        if count >= limit:
            break

        try:
            resp = s3_client.get_object(Bucket=bucket, Key=key)
            img_bytes = resp["Body"].read()
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            w, h = img.size

            # Random manipulation type
            manip_type = random.choice(["copy_move", "splice", "inpaint"])
            arr = np.array(img)

            if manip_type == "copy_move":
                # Copy a rectangular region and paste it elsewhere
                rw = random.randint(w // 8, w // 4)
                rh = random.randint(h // 8, h // 4)
                sx = random.randint(0, w - rw - 1)
                sy = random.randint(0, h - rh - 1)
                dx = random.randint(0, w - rw - 1)
                dy = random.randint(0, h - rh - 1)
                # Avoid same position
                while abs(dx - sx) < rw // 2 and abs(dy - sy) < rh // 2:
                    dx = random.randint(0, w - rw - 1)
                    dy = random.randint(0, h - rh - 1)
                region = arr[sy:sy + rh, sx:sx + rw].copy()
                arr[dy:dy + rh, dx:dx + rw] = region

            elif manip_type == "splice":
                # Take a patch from another image and splice it in
                other_key = random.choice(auth_keys)
                other_resp = s3_client.get_object(Bucket=bucket, Key=other_key)
                other_img = Image.open(io.BytesIO(other_resp["Body"].read())).convert("RGB")
                other_img = other_img.resize((w, h), Image.LANCZOS)
                other_arr = np.array(other_img)
                # Random region
                rw = random.randint(w // 6, w // 3)
                rh = random.randint(h // 6, h // 3)
                sx = random.randint(0, w - rw - 1)
                sy = random.randint(0, h - rh - 1)
                arr[sy:sy + rh, sx:sx + rw] = other_arr[sy:sy + rh, sx:sx + rw]

            elif manip_type == "inpaint":
                # Fill a region with blurred content (simulates inpainting)
                rw = random.randint(w // 8, w // 4)
                rh = random.randint(h // 8, h // 4)
                sx = random.randint(0, w - rw - 1)
                sy = random.randint(0, h - rh - 1)
                patch = Image.fromarray(arr[sy:sy + rh, sx:sx + rw])
                blurred = patch.filter(ImageFilter.GaussianBlur(radius=8))
                arr[sy:sy + rh, sx:sx + rw] = np.array(blurred)

            result = Image.fromarray(arr)
            if _standardize_and_upload(s3_client, bucket, "tampered", result, f"synthetic_{manip_type}"):
                count += 1

        except Exception:
            continue

    print(f"  Generated {count} tampered images")
    return count


# ─── AI GENERATED: Download from DiffusionDB vehicle subset ──────────

def download_ai_generated(s3_client, bucket: str, limit: int) -> int:
    """Download AI-generated vehicle images from DiffusionDB."""
    print(f"\n=== AI-Generated vehicle images (DiffusionDB) — {limit} images ===")

    try:
        from datasets import load_dataset
        # Load a manageable subset
        ds = load_dataset("poloclub/diffusiondb", "2m_random_1k", split="train")
    except Exception as e:
        print(f"  ERROR loading DiffusionDB: {e}")
        return 0

    # Vehicle-related keywords to filter prompts
    vehicle_kw = [
        "car", "vehicle", "automobile", "truck", "suv", "sedan",
        "crash", "accident", "damage", "dent", "broken",
        "wreck", "collision", "fender", "bumper", "hood",
        "parking", "road", "highway", "garage",
    ]

    count = 0
    scanned = 0

    for item in tqdm(ds, desc="DiffusionDB scan", total=len(ds)):
        scanned += 1
        if count >= limit:
            break

        prompt = (item.get("prompt") or "").lower()
        if not any(kw in prompt for kw in vehicle_kw):
            continue

        img = item.get("image")
        if img is None:
            continue

        try:
            if isinstance(img, Image.Image):
                if _standardize_and_upload(s3_client, bucket, "ai_generated", img, "diffusiondb"):
                    count += 1
        except Exception:
            continue

    print(f"  Scanned {scanned}, found {count} vehicle AI images")

    if count < limit:
        print(f"  Only found {count}/{limit} from DiffusionDB.")
        print("  For more AI car images, manually generate with prompts like:")
        print('    "car crash on highway, photo realistic, DSLR"')
        print('    "close up dented car door, insurance claim photo"')
        print('    "smashed windshield, night time, flash photography"')

    return count


def main():
    parser = argparse.ArgumentParser(
        description="Download vehicle-specific calibration images for DENT V7"
    )
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--category", required=True,
                        choices=["authentic", "tampered", "ai_generated", "all"])
    parser.add_argument("--limit", type=int, default=3000)
    parser.add_argument("--region", default="eu-central-1")
    args = parser.parse_args()

    s3 = boto3.client("s3", region_name=args.region)

    if args.category in ("authentic", "all"):
        vehide_count = download_vehide(s3, args.bucket, args.limit)
        remaining = max(0, args.limit - vehide_count)
        if remaining > 0:
            download_cardd(s3, args.bucket, remaining)

    if args.category in ("tampered", "all"):
        generate_tampered(s3, args.bucket, args.limit)

    if args.category in ("ai_generated", "all"):
        download_ai_generated(s3, args.bucket, args.limit)

    print("\n=== Done! ===")
    print(f"Images uploaded to s3://{args.bucket}/{S3_PREFIX_RAW}/")
    print("Next step: run prepare_calibration_dataset.py to anonymize + create labels.csv")


if __name__ == "__main__":
    main()
