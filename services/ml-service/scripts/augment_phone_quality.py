#!/usr/bin/env python3
"""Add phone-quality augmentation to authentic images in training dataset.

Creates copies of authentic images with realistic phone camera artifacts:
- Gaussian noise (low-light phone photos)
- Motion blur (shaky hands)
- JPEG artifacts (old phones with bad cameras)
- Slight overexposure/underexposure

This prevents the probe from learning "clean = real, noisy = fake" shortcuts.
Only augments AUTHENTIC images (AI/tampered don't need this).

Run AFTER augment_webp.py and augment_jpeg_resize.py.

Usage:
  python -m scripts.augment_phone_quality \
    --bucket dent-calibration-data \
    --prefix train_v7_webp
"""

from __future__ import annotations

import argparse
import csv
import io
import random
import sys

import boto3
import numpy as np
from PIL import Image, ImageFilter, ImageEnhance

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(it, **kw):
        total = kw.get("total", "?")
        for i, x in enumerate(it, 1):
            if i % 100 == 0:
                print(f"  [{i}/{total}]", flush=True)
            yield x


def add_gaussian_noise(img: Image.Image, sigma: float = 15.0) -> Image.Image:
    """Add Gaussian noise to simulate low-light phone photos."""
    arr = np.array(img, dtype=np.float32)
    noise = np.random.normal(0, sigma, arr.shape)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def add_motion_blur(img: Image.Image, size: int = 5) -> Image.Image:
    """Add slight motion blur to simulate shaky hands."""
    return img.filter(ImageFilter.GaussianBlur(radius=random.uniform(0.5, 1.5)))


def adjust_exposure(img: Image.Image) -> Image.Image:
    """Randomly over/underexpose."""
    enhancer = ImageEnhance.Brightness(img)
    factor = random.choice([0.6, 0.7, 1.3, 1.5])  # under or overexpose
    return enhancer.enhance(factor)


def heavy_jpeg_compress(img: Image.Image, quality: int = 30) -> Image.Image:
    """Simulate very aggressive JPEG compression (old phone)."""
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return Image.open(io.BytesIO(buf.getvalue()))


AUGMENTATIONS = [
    ("noise", lambda img: add_gaussian_noise(img, sigma=random.uniform(10, 25))),
    ("blur", add_motion_blur),
    ("exposure", adjust_exposure),
    ("heavyjpeg", lambda img: heavy_jpeg_compress(img, quality=random.randint(25, 40))),
]


def main():
    parser = argparse.ArgumentParser(description="Add phone-quality augmentation to authentic images")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--region", default="eu-central-1")
    parser.add_argument("--sample-rate", type=float, default=0.3,
                        help="Fraction of authentic originals to augment (default: 0.3)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    s3 = boto3.client("s3", region_name=args.region)

    # Load labels
    print(f"Loading labels from s3://{args.bucket}/{args.prefix}/labels.csv ...", flush=True)
    resp = s3.get_object(Bucket=args.bucket, Key=f"{args.prefix}/labels.csv")
    content = resp["Body"].read().decode("utf-8")
    labels = {}
    for row in csv.DictReader(io.StringIO(content)):
        fn = row.get("filename", "").strip()
        gt = row.get("ground_truth", "").strip().lower()
        if fn and gt:
            labels[fn] = gt

    # Only augment original authentic images
    auth_originals = [fn for fn, gt in labels.items()
                      if gt == "authentic"
                      and not fn.endswith(".webp")
                      and "_jpeg_q" not in fn
                      and "_rsz" not in fn
                      and "_phone_" not in fn]

    sampled = [fn for fn in auth_originals if random.random() < args.sample_rate]
    print(f"Authentic originals: {len(auth_originals)}, sampled: {len(sampled)}", flush=True)

    # Each sampled image gets 1-2 random augmentations
    plan = []
    new_labels = []
    for fn in sampled:
        base, ext = fn.rsplit(".", 1)
        # Pick 1-2 random augmentations
        n_augs = random.randint(1, 2)
        chosen = random.sample(AUGMENTATIONS, n_augs)
        for aug_name, aug_fn in chosen:
            new_fn = f"{base}_phone_{aug_name}.jpg"
            plan.append((fn, new_fn, aug_fn))
            new_labels.append((new_fn, "authentic"))

    print(f"Will create {len(plan)} phone-quality copies", flush=True)

    if args.dry_run:
        print("DRY RUN", flush=True)
        return

    errors = 0
    uploaded = 0

    for src_fn, dst_fn, aug_fn in tqdm(plan, desc="Phone augmentation", total=len(plan)):
        try:
            resp = s3.get_object(Bucket=args.bucket, Key=f"{args.prefix}/{src_fn}")
            img = Image.open(io.BytesIO(resp["Body"].read())).convert("RGB")

            # Apply augmentation
            img = aug_fn(img)

            # Save as JPEG
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85, optimize=True)

            s3.put_object(
                Bucket=args.bucket,
                Key=f"{args.prefix}/{dst_fn}",
                Body=buf.getvalue(),
                ContentType="image/jpeg",
            )
            uploaded += 1
        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"  Error {src_fn}: {e}", flush=True)

    # Update labels.csv
    print(f"\nUploaded {uploaded} phone-quality copies ({errors} errors)", flush=True)

    all_labels = list(labels.items()) + new_labels
    csv_buf = io.StringIO()
    writer = csv.DictWriter(csv_buf, fieldnames=["filename", "ground_truth"])
    writer.writeheader()
    for fn, gt in all_labels:
        writer.writerow({"filename": fn, "ground_truth": gt})

    s3.put_object(
        Bucket=args.bucket,
        Key=f"{args.prefix}/labels.csv",
        Body=csv_buf.getvalue().encode("utf-8"),
        ContentType="text/csv",
    )
    print(f"Updated labels.csv: {len(labels)} → {len(all_labels)} entries", flush=True)


if __name__ == "__main__":
    main()
