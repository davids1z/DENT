#!/usr/bin/env python3
"""
Download authentic insurance-domain images from multiple sources.
All images go directly to S3. Supports --resume to continue interrupted runs.

Sources:
  1. CarDD (HuggingFace) — car damage photos (1,200)
  2. icrawler Bing — car damage queries (400)
  3. icrawler Bing — house damage queries (1,000)
  4. SROIE (HuggingFace) — receipts/invoices (500)
  5. CORD (HuggingFace) — receipts/invoices (300)
  6. icrawler Bing — medical injuries (500)
  7. icrawler Bing — mobile phone quality (300)
  8. icrawler Bing — undamaged baseline (800)
  9. icrawler Bing — HR/EU specific (500)

Quality pipeline:
  - PIL verify → corrupt rejected
  - min(w,h) >= 256px → too small rejected
  - file_size >= 5KB → broken rejected
  - cv2.Laplacian variance > 50 → too blurry (except mobile_quality)
  - Strip EXIF, resize max 1024px, JPEG q90
  - phash dedup (Hamming < 10)
  - Upload to S3 with metadata: {source, category, query}

Usage:
  pip install icrawler boto3 pillow opencv-python-headless imagehash datasets
  python3 -m scripts.download_insurance_authentic \
      --bucket dent-calibration-data \
      --output-prefix raw_v8/authentic \
      --target 5500
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

import numpy as np
from PIL import Image

try:
    import boto3
except ImportError:
    boto3 = None

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import imagehash
except ImportError:
    imagehash = None


# ── Source definitions ────────────────────────────────────────────────

SOURCES = {
    # HuggingFace datasets
    "cardd": {
        "type": "huggingface",
        "dataset": "harpreetsahota/CarDD",
        "category": "car_damage",
        "target": 1200,
    },
    "cord_v2": {
        "type": "huggingface",
        "dataset": "naver-clova-ix/cord-v2",
        "category": "invoices_receipts",
        "target": 800,
    },

    # icrawler Bing — car damage
    "bing_car_damage": {
        "type": "icrawler",
        "category": "car_damage",
        "target": 400,
        "queries": [
            "car damage dent photo -stock -illustration -vector",
            "car crash damage close up real photo -stock",
            "broken windshield car hail -stock -illustration",
            "car scratch paint damage real -stock",
            "car bumper damage accident photo -stock",
            "car door dent hail damage -stock -illustration",
            "fender bender damage photo real -stock",
            "car rear end collision damage -stock",
            "car side mirror broken accident -stock",
            "auto body repair before photo -stock",
            "car insurance claim damage photo -stock",
            "vehicle damage assessment photo real -stock",
            "car hood damage dent real photo -stock",
            "car undercarriage rust damage -stock",
            "car parking lot damage scratch -stock",
        ],
    },

    # icrawler Bing — house damage
    "bing_house_damage": {
        "type": "icrawler",
        "category": "house_damage",
        "target": 1000,
        "queries": [
            "flood damage house interior real photo -stock -illustration",
            "fire damage building room photo -stock",
            "storm damage roof tiles real -stock -illustration",
            "cracked wall foundation damage -stock",
            "water damage ceiling stain photo -stock",
            "hurricane damage house exterior -stock",
            "tornado damage home debris -stock -illustration",
            "hail damage roof shingles photo -stock",
            "mold damage wall bathroom photo -stock",
            "broken window house storm damage -stock",
            "pipe burst water damage interior -stock",
            "smoke damage kitchen walls photo -stock",
            "earthquake crack building wall -stock",
            "property damage insurance claim photo -stock",
        ],
    },

    # icrawler Bing — medical injuries
    "bing_medical": {
        "type": "icrawler",
        "category": "medical_injury",
        "target": 500,
        "queries": [
            "bruise injury arm medical photo -stock -illustration",
            "wound bandage treatment photo -stock",
            "sprained ankle swollen injury photo -stock",
            "cast broken arm hospital patient -stock",
            "burn injury treatment bandage -stock -illustration",
            "stitches wound close up medical -stock",
            "knee injury swollen brace -stock",
            "neck brace whiplash patient -stock",
            "shoulder sling arm injury medical -stock",
            "black eye injury photo medical -stock",
        ],
    },

    # icrawler Bing — mobile quality (intentionally bad photos)
    "bing_mobile_quality": {
        "type": "icrawler",
        "category": "mobile_quality",
        "target": 300,
        "queries": [
            "blurry phone photo accident night -stock",
            "low quality phone camera photo damage -stock",
            "amateur photo dark room phone -stock",
            "grainy dark photo phone camera -stock",
            "overexposed photo outdoor phone -stock",
            "motion blur photo phone handheld -stock",
            "whatsapp compressed photo low quality -stock",
            "phone screenshot photo damage -stock",
        ],
    },

    # icrawler Bing — undamaged baseline
    "bing_undamaged": {
        "type": "icrawler",
        "category": "general_undamaged",
        "target": 800,
        "queries": [
            "parked car exterior clean new -stock",
            "house exterior suburban photo -stock",
            "new car showroom photo -stock",
            "office desk with documents photo -stock",
            "residential house front photo -stock",
            "family car driveway photo -stock",
            "clean kitchen interior photo -stock",
            "living room interior modern photo -stock",
            "apartment building exterior photo -stock",
            "healthy arm hand photo medical -stock",
        ],
    },

    # icrawler Bing — HR/EU specific
    "bing_hr_eu": {
        "type": "icrawler",
        "category": "hr_eu_specific",
        "target": 500,
        "queries": [
            "oštećenje automobila fotografija",
            "prometna nesreća šteta automobil",
            "poplava Hrvatska šteta kuća",
            "oštećenje krova oluja Hrvatska",
            "požar šteta kuća",
            "car damage Europe insurance photo",
            "flood damage Europe house photo",
            "storm damage Europe roof photo",
            "car accident damage EU photo",
            "hail damage car Europe photo",
        ],
    },
}


# ── Quality pipeline ─────────────────────────────────────────────────

def quality_check(
    img: Image.Image,
    raw_bytes: bytes,
    category: str,
    seen_hashes: set,
) -> tuple[bool, str]:
    """Run quality pipeline. Returns (passed, reason)."""
    # Size check
    if len(raw_bytes) < 5000:
        return False, "too_small_bytes"

    w, h = img.size
    if min(w, h) < 256:
        return False, "too_small_resolution"

    # Blur check (skip for mobile_quality category)
    if cv2 is not None and category != "mobile_quality":
        arr = np.array(img.convert("L"))
        laplacian_var = cv2.Laplacian(arr, cv2.CV_64F).var()
        if laplacian_var < 50:
            return False, "too_blurry"

    # phash dedup
    if imagehash is not None:
        phash = imagehash.phash(img)
        for existing in seen_hashes:
            if phash - existing < 10:
                return False, "duplicate"
        seen_hashes.add(phash)

    return True, "ok"


def process_image(img: Image.Image) -> bytes | None:
    """Strip EXIF, resize max 1024px, save as JPEG q90."""
    try:
        if img.mode != "RGB":
            img = img.convert("RGB")

        w, h = img.size
        if max(w, h) > 1024:
            ratio = 1024 / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90, optimize=True)
        return buf.getvalue()
    except Exception:
        return None


# ── Source downloaders ────────────────────────────────────────────────

def download_huggingface(
    source_config: dict,
    s3,
    bucket: str,
    prefix: str,
    existing_keys: set,
    seen_hashes: set,
) -> list[dict]:
    """Download images from a HuggingFace dataset using streaming."""
    from datasets import load_dataset

    dataset_name = source_config["dataset"]
    category = source_config["category"]
    target = source_config["target"]

    print(f"  Loading HF dataset (streaming): {dataset_name}", flush=True)

    records = []
    errors = 0

    # Try each split with streaming
    for split_name in ["train", "validation", "test"]:
        if len(records) >= target:
            break

        try:
            ds = load_dataset(dataset_name, split=split_name, streaming=True)
        except Exception:
            continue

        print(f"    Streaming split: {split_name}", flush=True)

        for item in ds:
            if len(records) >= target:
                break

            try:
                # Find image field
                img = None
                for key in ["image", "Image", "img", "photo"]:
                    if key in item and item[key] is not None:
                        val = item[key]
                        if isinstance(val, Image.Image):
                            img = val
                        elif isinstance(val, bytes):
                            img = Image.open(io.BytesIO(val))
                        elif isinstance(val, dict) and "bytes" in val:
                            img = Image.open(io.BytesIO(val["bytes"]))
                        break

                if img is None:
                    continue

                img = img.convert("RGB")

                # Quality check
                buf_check = io.BytesIO()
                img.save(buf_check, format="JPEG", quality=90)
                raw_bytes = buf_check.getvalue()

                passed, reason = quality_check(img, raw_bytes, category, seen_hashes)
                if not passed:
                    continue

                # Process
                jpeg_bytes = process_image(img)
                if jpeg_bytes is None or len(jpeg_bytes) < 5000:
                    continue

                filename = f"{uuid.uuid4().hex[:12]}.jpg"
                s3_key = f"{prefix}/{filename}"

                if s3_key in existing_keys:
                    continue

                s3.put_object(
                    Bucket=bucket,
                    Key=s3_key,
                    Body=jpeg_bytes,
                    ContentType="image/jpeg",
                    Metadata={"source": dataset_name, "category": category},
                )

                records.append({
                    "filename": filename,
                    "ground_truth": "authentic",
                    "category": category,
                    "source": dataset_name,
                })

                if len(records) % 100 == 0:
                    print(f"    [{len(records)}/{target}] from {dataset_name}", flush=True)

            except Exception:
                errors += 1
                continue

    print(f"  {dataset_name}: {len(records)} uploaded ({errors} errors)", flush=True)
    return records


def download_icrawler(
    source_config: dict,
    s3,
    bucket: str,
    prefix: str,
    existing_keys: set,
    seen_hashes: set,
    temp_dir: Path,
) -> list[dict]:
    """Download images using icrawler Bing search."""
    from icrawler.builtin import BingImageCrawler

    category = source_config["category"]
    target = source_config["target"]
    queries = source_config["queries"]

    records = []
    downloaded_total = 0
    per_query = max(10, target // len(queries) + 10)

    for query in queries:
        if len(records) >= target:
            break

        remaining = target - len(records)
        num = min(per_query, remaining + 20)

        query_dir = temp_dir / category / query.replace(" ", "_")[:40]
        query_dir.mkdir(parents=True, exist_ok=True)

        try:
            crawler = BingImageCrawler(
                storage={"root_dir": str(query_dir)},
                log_level=40,  # ERROR only
            )
            crawler.crawl(keyword=query, max_num=num)
        except Exception as e:
            print(f"    WARNING: {query[:40]}: {e}")
            continue

        # Process downloaded files
        for fpath in sorted(query_dir.rglob("*")):
            if len(records) >= target:
                break
            if not fpath.is_file():
                continue
            if fpath.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
                continue

            try:
                raw_bytes = fpath.read_bytes()
                img = Image.open(io.BytesIO(raw_bytes))
                img.verify()
                img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")

                passed, reason = quality_check(img, raw_bytes, category, seen_hashes)
                if not passed:
                    continue

                jpeg_bytes = process_image(img)
                if jpeg_bytes is None or len(jpeg_bytes) < 5000:
                    continue

                filename = f"{uuid.uuid4().hex[:12]}.jpg"
                s3_key = f"{prefix}/{filename}"

                s3.put_object(
                    Bucket=bucket,
                    Key=s3_key,
                    Body=jpeg_bytes,
                    ContentType="image/jpeg",
                    Metadata={
                        "source": "bing",
                        "category": category,
                        "query": query[:200],
                    },
                )

                records.append({
                    "filename": filename,
                    "ground_truth": "authentic",
                    "category": category,
                    "source": "bing",
                    "query": query,
                })
                downloaded_total += 1

            except Exception:
                continue

        print(f"    {query[:40]}: +{downloaded_total} (total: {len(records)}/{target})")

    return records


# ── Resume support ───────────────────────────────────────────────────

def get_existing_keys(s3, bucket: str, prefix: str) -> set[str]:
    """List existing S3 keys under prefix for resume support."""
    keys = set()
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.add(obj["Key"])
    except Exception:
        pass
    return keys


def load_existing_labels(s3, bucket: str, prefix: str) -> list[dict]:
    """Load existing labels.csv from S3 for resume."""
    try:
        resp = s3.get_object(Bucket=bucket, Key=f"{prefix}/labels.csv")
        content = resp["Body"].read().decode()
        records = []
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            records.append(dict(row))
        return records
    except Exception:
        return []


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Download insurance-domain authentic images"
    )
    parser.add_argument("--bucket", default="dent-calibration-data")
    parser.add_argument("--output-prefix", default="raw_v8/authentic")
    parser.add_argument("--target", type=int, default=5500)
    parser.add_argument("--region", default="eu-central-1")
    parser.add_argument("--temp-dir", default="/tmp/insurance_authentic")
    parser.add_argument("--resume", action="store_true", help="Resume from existing S3 data")
    parser.add_argument(
        "--sources", default="all",
        help="Comma-separated source names or 'all'",
    )
    args = parser.parse_args()

    # Validate deps
    if boto3 is None:
        print("ERROR: pip install boto3")
        sys.exit(1)

    s3 = boto3.client("s3", region_name=args.region)
    temp_dir = Path(args.temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Resume support
    existing_keys = set()
    all_records = []
    if args.resume:
        print("Checking existing data for resume...")
        existing_keys = get_existing_keys(s3, args.bucket, args.output_prefix)
        all_records = load_existing_labels(s3, args.bucket, args.output_prefix)
        print(f"  Found {len(existing_keys)} existing files, {len(all_records)} labels")

    seen_hashes: set = set()

    # Filter sources
    sources_to_run = SOURCES
    if args.sources != "all":
        names = [s.strip() for s in args.sources.split(",")]
        sources_to_run = {k: v for k, v in SOURCES.items() if k in names}

    # Scale targets
    total_base = sum(s["target"] for s in sources_to_run.values())
    scale = args.target / total_base if total_base > 0 else 1.0

    print(f"Target: {args.target} authentic insurance images")
    print(f"Sources: {len(sources_to_run)} ({', '.join(sources_to_run.keys())})")
    print(f"Scale factor: {scale:.2f}")
    print(f"Existing records: {len(all_records)}")
    print()

    for source_name, source_config in sources_to_run.items():
        scaled_target = int(source_config["target"] * scale)

        # Count how many we already have for this category/source
        existing_count = sum(
            1 for r in all_records
            if r.get("source", "") == source_config.get("dataset", "bing")
            or (r.get("source") == "bing" and r.get("category") == source_config["category"]
                and source_config["type"] == "icrawler")
        )
        if existing_count >= scaled_target:
            print(f"\n=== {source_name} — SKIP (already {existing_count}/{scaled_target}) ===")
            continue

        remaining = scaled_target - existing_count
        adjusted_config = {**source_config, "target": remaining}

        print(f"\n=== {source_name} (need: {remaining}, total target: {scaled_target}) ===")

        if source_config["type"] == "huggingface":
            try:
                records = download_huggingface(
                    adjusted_config, s3, args.bucket, args.output_prefix,
                    existing_keys, seen_hashes,
                )
            except ImportError:
                print("  WARNING: pip install datasets (skipping HF source)")
                records = []
        elif source_config["type"] == "icrawler":
            try:
                records = download_icrawler(
                    adjusted_config, s3, args.bucket, args.output_prefix,
                    existing_keys, seen_hashes, temp_dir,
                )
            except ImportError:
                print("  WARNING: pip install icrawler (skipping Bing source)")
                records = []
        else:
            records = []

        all_records.extend(records)
        print(f"  Subtotal: {len(records)} new, {len(all_records)} cumulative")

        # Save labels incrementally
        _save_labels(all_records, s3, args.bucket, args.output_prefix)

    # Final labels save
    _save_labels(all_records, s3, args.bucket, args.output_prefix)

    # Cleanup temp
    shutil.rmtree(temp_dir, ignore_errors=True)

    # Summary
    print(f"\n{'='*60}")
    print(f"DONE: {len(all_records)} authentic images")
    cats = {}
    for r in all_records:
        cat = r.get("category", "unknown")
        cats[cat] = cats.get(cat, 0) + 1
    for cat, count in sorted(cats.items()):
        print(f"  {cat}: {count}")
    print(f"\nAll images at: s3://{args.bucket}/{args.output_prefix}/")


def _save_labels(records: list[dict], s3, bucket: str, prefix: str):
    """Save labels.csv to S3."""
    csv_buf = io.StringIO()
    writer = csv.DictWriter(
        csv_buf,
        fieldnames=["filename", "ground_truth", "category", "source"],
    )
    writer.writeheader()
    for rec in records:
        writer.writerow({
            "filename": rec.get("filename", ""),
            "ground_truth": rec.get("ground_truth", "authentic"),
            "category": rec.get("category", ""),
            "source": rec.get("source", ""),
        })

    s3.put_object(
        Bucket=bucket,
        Key=f"{prefix}/labels.csv",
        Body=csv_buf.getvalue().encode(),
        ContentType="text/csv",
    )


if __name__ == "__main__":
    main()
