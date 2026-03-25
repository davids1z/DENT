#!/usr/bin/env python3
"""Build diverse calibration dataset from public forensics benchmarks.

Downloads Synthbuster (real + 9 AI generators) and samples from existing
CarDD + Gemini data. Uploads everything to S3 with proper labels.

Usage:
  pip install boto3 pillow tqdm requests
  export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_DEFAULT_REGION=eu-central-1
  python3 build_diverse_dataset.py --bucket dent-calibration-data
"""
import argparse
import csv
import hashlib
import io
import os
import random
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

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

S3_PREFIX = "processed_v2"
MAX_DIM = 1024  # Resize to max 1024px on longest side
JPEG_QUALITY = 90


def resize_and_save(img_path: str, out_dir: str, filename: str) -> str | None:
    """Resize image to max MAX_DIM, save as JPEG, return output path."""
    try:
        img = Image.open(img_path)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        elif img.mode == "L":
            img = img.convert("RGB")

        # Resize if too large
        w, h = img.size
        if max(w, h) > MAX_DIM:
            ratio = MAX_DIM / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

        out_path = os.path.join(out_dir, filename)
        img.save(out_path, "JPEG", quality=JPEG_QUALITY)
        return out_path
    except Exception as e:
        print(f"  Skip {img_path}: {e}")
        return None


def download_synthbuster(work_dir: str) -> str:
    """Download Synthbuster from Zenodo (~10GB)."""
    sb_dir = os.path.join(work_dir, "synthbuster")
    if os.path.isdir(sb_dir) and len(os.listdir(sb_dir)) > 5:
        print(f"Synthbuster already downloaded at {sb_dir}")
        return sb_dir

    zip_path = os.path.join(work_dir, "synthbuster.zip")
    url = "https://zenodo.org/records/10066460/files/synthbuster.zip?download=1"

    if not os.path.exists(zip_path):
        print(f"Downloading Synthbuster (~10GB)...")
        subprocess.run(["wget", "-q", "--show-progress", "-O", zip_path, url], check=True)

    print("Extracting Synthbuster...")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(work_dir)

    if os.path.exists(zip_path):
        os.remove(zip_path)

    return sb_dir


def collect_synthbuster_images(sb_dir: str, out_dir: str) -> list[tuple[str, str]]:
    """Collect Synthbuster images: real + AI generators."""
    labels = []

    # Real images (RAISE-based)
    real_dir = os.path.join(sb_dir, "real")
    if os.path.isdir(real_dir):
        real_images = sorted([f for f in os.listdir(real_dir) if f.lower().endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff"))])
        print(f"Synthbuster real: {len(real_images)} images")
        for f in tqdm(real_images, desc="Real images", total=len(real_images)):
            out_name = f"sb_real_{f.rsplit('.', 1)[0]}.jpg"
            result = resize_and_save(os.path.join(real_dir, f), out_dir, out_name)
            if result:
                labels.append((out_name, "authentic"))

    # AI generators
    ai_dirs = [d for d in os.listdir(sb_dir) if os.path.isdir(os.path.join(sb_dir, d)) and d != "real"]
    for gen_name in sorted(ai_dirs):
        gen_dir = os.path.join(sb_dir, gen_name)
        gen_images = sorted([f for f in os.listdir(gen_dir) if f.lower().endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff"))])
        # Take max 200 per generator to keep balanced
        sample_size = min(200, len(gen_images))
        sampled = random.sample(gen_images, sample_size) if len(gen_images) > sample_size else gen_images
        print(f"Synthbuster {gen_name}: {len(sampled)}/{len(gen_images)} images")
        for f in tqdm(sampled, desc=gen_name, total=len(sampled)):
            out_name = f"sb_{gen_name}_{f.rsplit('.', 1)[0]}.jpg"
            result = resize_and_save(os.path.join(gen_dir, f), out_dir, out_name)
            if result:
                labels.append((out_name, "ai_generated"))

    return labels


def sample_existing_s3(s3, bucket: str, out_dir: str, n_auth: int = 500, n_ai: int = 500) -> list[tuple[str, str]]:
    """Download a sample of existing CarDD + Gemini images from S3."""
    print(f"Loading existing labels from S3...")
    resp = s3.get_object(Bucket=bucket, Key="processed/labels.csv")
    content = resp["Body"].read().decode("utf-8")

    existing = {"authentic": [], "ai_generated": [], "tampered": []}
    for row in csv.DictReader(io.StringIO(content)):
        fn = row.get("filename", "").strip()
        gt = row.get("ground_truth", "").strip().lower()
        if fn and gt in existing:
            existing[gt].append(fn)

    labels = []

    # Sample authentic (CarDD)
    auth_sample = random.sample(existing["authentic"], min(n_auth, len(existing["authentic"])))
    print(f"Sampling {len(auth_sample)} existing authentic from S3...")
    for fn in tqdm(auth_sample, desc="Existing auth"):
        try:
            resp = s3.get_object(Bucket=bucket, Key=f"processed/{fn}")
            img_bytes = resp["Body"].read()
            out_name = f"cardd_{fn}"
            with open(os.path.join(out_dir, out_name), "wb") as f:
                f.write(img_bytes)
            labels.append((out_name, "authentic"))
        except Exception:
            pass

    # Sample AI (Gemini)
    ai_sample = random.sample(existing["ai_generated"], min(n_ai, len(existing["ai_generated"])))
    print(f"Sampling {len(ai_sample)} existing AI from S3...")
    for fn in tqdm(ai_sample, desc="Existing AI"):
        try:
            resp = s3.get_object(Bucket=bucket, Key=f"processed/{fn}")
            img_bytes = resp["Body"].read()
            out_name = f"gemini_{fn}"
            with open(os.path.join(out_dir, out_name), "wb") as f:
                f.write(img_bytes)
            labels.append((out_name, "ai_generated"))
        except Exception:
            pass

    # All tampered
    print(f"Downloading all {len(existing['tampered'])} tampered from S3...")
    for fn in tqdm(existing["tampered"], desc="Tampered"):
        try:
            resp = s3.get_object(Bucket=bucket, Key=f"processed/{fn}")
            img_bytes = resp["Body"].read()
            out_name = f"tamp_{fn}"
            with open(os.path.join(out_dir, out_name), "wb") as f:
                f.write(img_bytes)
            labels.append((out_name, "tampered"))
        except Exception:
            pass

    return labels


def upload_to_s3(s3, bucket: str, out_dir: str, labels: list[tuple[str, str]]):
    """Upload processed images and labels.csv to S3."""
    # Write labels.csv
    csv_path = os.path.join(out_dir, "labels.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["filename", "ground_truth"])
        writer.writeheader()
        for fn, gt in sorted(labels):
            writer.writerow({"filename": fn, "ground_truth": gt})

    print(f"\nUploading {len(labels)} images + labels.csv to s3://{bucket}/{S3_PREFIX}/...")

    # Upload labels.csv first
    s3.upload_file(csv_path, bucket, f"{S3_PREFIX}/labels.csv")

    # Upload images
    for fn, _ in tqdm(labels, desc="Uploading", total=len(labels)):
        filepath = os.path.join(out_dir, fn)
        if os.path.exists(filepath):
            s3.upload_file(filepath, bucket, f"{S3_PREFIX}/{fn}")

    print(f"Done! {len(labels)} images uploaded to {S3_PREFIX}/")


def main():
    parser = argparse.ArgumentParser(description="Build diverse calibration dataset")
    parser.add_argument("--bucket", default="dent-calibration-data")
    parser.add_argument("--work-dir", default="/tmp/dent_dataset")
    parser.add_argument("--region", default="eu-central-1")
    parser.add_argument("--skip-synthbuster", action="store_true", help="Skip Synthbuster download")
    parser.add_argument("--skip-existing", action="store_true", help="Skip existing S3 data")
    args = parser.parse_args()

    random.seed(42)  # Reproducible sampling

    work_dir = args.work_dir
    out_dir = os.path.join(work_dir, "output")
    os.makedirs(out_dir, exist_ok=True)

    s3 = boto3.client("s3", region_name=args.region)
    all_labels = []

    # 1. Synthbuster (real + AI)
    if not args.skip_synthbuster:
        sb_dir = download_synthbuster(work_dir)
        sb_labels = collect_synthbuster_images(sb_dir, out_dir)
        all_labels.extend(sb_labels)
        print(f"Synthbuster: {len(sb_labels)} images")

    # 2. Existing S3 data (CarDD + Gemini + tampered)
    if not args.skip_existing:
        existing_labels = sample_existing_s3(s3, args.bucket, out_dir)
        all_labels.extend(existing_labels)
        print(f"Existing: {len(existing_labels)} images")

    # Summary
    counts = {}
    for _, gt in all_labels:
        counts[gt] = counts.get(gt, 0) + 1
    print(f"\n=== Dataset Summary ===")
    for gt in ["authentic", "ai_generated", "tampered"]:
        print(f"  {gt}: {counts.get(gt, 0)}")
    print(f"  Total: {len(all_labels)}")

    # 3. Upload to S3
    upload_to_s3(s3, args.bucket, out_dir, all_labels)

    # 4. Cleanup
    print(f"\nCleanup: removing {work_dir}...")
    shutil.rmtree(work_dir, ignore_errors=True)
    print("Done!")


if __name__ == "__main__":
    main()
