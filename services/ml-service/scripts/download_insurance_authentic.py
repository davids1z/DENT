#!/usr/bin/env python3
"""
Download authentic insurance-domain images using icrawler (Bing image search).
No API key needed. Downloads real photos of car damage, house damage, etc.

Usage:
  pip install icrawler boto3
  python3 -m scripts.download_insurance_authentic \
      --bucket dent-calibration-data \
      --output-prefix raw_v8/authentic \
      --target 5000
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

from PIL import Image

try:
    import boto3
except ImportError:
    boto3 = None


# ── Insurance domain search categories ───────────────────────────────

CATEGORIES = {
    "car_damage": {
        "queries": [
            "car damage dent photo",
            "car crash damage close up",
            "broken windshield car",
            "car scratch paint damage",
            "car bumper damage accident",
            "car door dent hail damage",
            "fender bender damage photo",
            "car rear end collision",
            "car side mirror broken",
            "damaged car parking lot",
            "car hood damage",
            "auto body repair before",
            "car insurance claim photo",
            "vehicle damage assessment",
            "car damage from accident",
        ],
        "target": 1500,
    },
    "house_damage": {
        "queries": [
            "flood damage house interior",
            "fire damage building room",
            "storm damage roof tiles",
            "cracked wall foundation",
            "water damage ceiling stain",
            "hurricane damage house",
            "tornado damage home",
            "hail damage roof shingles",
            "mold damage wall bathroom",
            "broken window house storm",
            "pipe burst water damage",
            "smoke damage kitchen walls",
            "earthquake crack building",
            "property damage insurance claim",
        ],
        "target": 1000,
    },
    "medical_injury": {
        "queries": [
            "bruise injury arm",
            "wound bandage treatment",
            "sprained ankle swollen",
            "cast broken arm hospital",
            "burn injury treatment",
            "stitches wound close up",
            "knee injury swollen",
            "back brace injury",
            "neck brace whiplash",
            "physical therapy session",
        ],
        "target": 500,
    },
    "invoices_receipts": {
        "queries": [
            "car repair invoice document",
            "hospital medical bill receipt",
            "insurance claim form",
            "handwritten receipt",
            "printed invoice office",
            "service receipt scanned",
            "repair estimate document",
            "medical prescription paper",
            "utility bill document",
            "construction estimate invoice",
        ],
        "target": 500,
    },
    "mobile_quality": {
        "queries": [
            "blurry phone photo accident",
            "low quality phone camera photo",
            "amateur photo dark room",
            "phone screenshot photo",
            "grainy dark photo phone",
            "whatsapp compressed photo",
            "overexposed photo outdoor",
            "motion blur photo phone",
        ],
        "target": 500,
    },
    "general_undamaged": {
        "queries": [
            "parked car exterior clean",
            "house exterior suburban",
            "new car showroom",
            "office desk with documents",
            "residential house front",
            "family car driveway",
            "clean kitchen interior",
            "living room interior modern",
            "apartment building exterior",
            "healthy arm hand photo",
        ],
        "target": 1000,
    },
}


def download_category(
    cat_name: str,
    queries: list[str],
    target: int,
    temp_dir: Path,
) -> list[Path]:
    """Download images for a category using icrawler Bing search."""
    from icrawler.builtin import BingImageCrawler

    cat_dir = temp_dir / cat_name
    cat_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    per_query = max(10, target // len(queries) + 5)  # Slightly more than needed

    for query in queries:
        if downloaded >= target:
            break

        remaining = target - downloaded
        num = min(per_query, remaining + 10)  # Extra buffer for failures

        query_dir = cat_dir / query.replace(" ", "_")[:40]
        query_dir.mkdir(parents=True, exist_ok=True)

        try:
            crawler = BingImageCrawler(
                storage={"root_dir": str(query_dir)},
                log_level=40,  # ERROR only
            )
            crawler.crawl(keyword=query, max_num=num)
        except Exception as e:
            print(f"    WARNING: {query}: {e}")
            continue

        new_files = list(query_dir.glob("*"))
        downloaded += len(new_files)
        print(f"    {query}: +{len(new_files)} (total: {downloaded}/{target})")

    # Collect all downloaded files
    all_files = []
    for f in cat_dir.rglob("*"):
        if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
            all_files.append(f)

    return all_files[:target]


def process_and_upload(
    files: list[Path],
    cat_name: str,
    s3_client,
    bucket: str,
    prefix: str,
    local_out: Path | None,
) -> list[dict]:
    """Process images (resize, JPEG, strip EXIF) and upload to S3 or local."""
    records = []

    for fpath in files:
        try:
            img = Image.open(fpath)
            if img.mode != "RGB":
                img = img.convert("RGB")

            w, h = img.size
            if min(w, h) < 128:
                continue

            # Resize if too large
            if max(w, h) > 1024:
                ratio = 1024 / max(w, h)
                img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90)
            jpeg_bytes = buf.getvalue()

            if len(jpeg_bytes) < 3000:
                continue

            filename = f"{uuid.uuid4().hex[:12]}.jpg"

            if s3_client:
                s3_client.put_object(
                    Bucket=bucket,
                    Key=f"{prefix}/{filename}",
                    Body=jpeg_bytes,
                    ContentType="image/jpeg",
                    Metadata={"category": cat_name},
                )
            elif local_out:
                (local_out / filename).write_bytes(jpeg_bytes)

            records.append({
                "filename": filename,
                "ground_truth": "authentic",
                "category": cat_name,
            })
        except Exception:
            continue

    return records


def main():
    parser = argparse.ArgumentParser(description="Download insurance-domain authentic images")
    parser.add_argument("--bucket", default="dent-calibration-data")
    parser.add_argument("--output-prefix", default="raw_v8/authentic")
    parser.add_argument("--target", type=int, default=5000)
    parser.add_argument("--region", default="eu-central-1")
    parser.add_argument("--local-dir", default="", help="Save locally instead of S3")
    parser.add_argument("--temp-dir", default="/tmp/insurance_authentic", help="Temp download dir")
    args = parser.parse_args()

    # Import icrawler
    try:
        from icrawler.builtin import BingImageCrawler  # noqa: F401
    except ImportError:
        print("ERROR: pip install icrawler")
        sys.exit(1)

    s3 = None
    if not args.local_dir:
        if boto3 is None:
            print("ERROR: pip install boto3 (or use --local-dir)")
            sys.exit(1)
        s3 = boto3.client("s3", region_name=args.region)

    local_out = Path(args.local_dir) if args.local_dir else None
    if local_out:
        local_out.mkdir(parents=True, exist_ok=True)

    temp_dir = Path(args.temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Scale targets
    total_target = sum(c["target"] for c in CATEGORIES.values())
    scale = args.target / total_target

    all_records: list[dict] = []

    print(f"Target: {args.target} authentic insurance images")
    print(f"Categories: {len(CATEGORIES)}")
    print(f"Temp dir: {temp_dir}\n")

    for cat_name, cat_config in CATEGORIES.items():
        cat_target = int(cat_config["target"] * scale)
        print(f"\n=== {cat_name} (target: {cat_target}) ===")

        files = download_category(
            cat_name, cat_config["queries"], cat_target, temp_dir
        )
        print(f"  Downloaded {len(files)} raw files")

        records = process_and_upload(
            files, cat_name, s3, args.bucket, args.output_prefix, local_out
        )
        all_records.extend(records)
        print(f"  Uploaded {len(records)} processed images")

    # Save labels.csv
    csv_content = "filename,ground_truth,category\n"
    for rec in all_records:
        csv_content += f"{rec['filename']},{rec['ground_truth']},{rec['category']}\n"

    if s3:
        s3.put_object(
            Bucket=args.bucket,
            Key=f"{args.output_prefix}/labels.csv",
            Body=csv_content.encode(),
            ContentType="text/csv",
        )
    elif local_out:
        (local_out / "labels.csv").write_text(csv_content)

    # Cleanup temp
    shutil.rmtree(temp_dir, ignore_errors=True)

    print(f"\n=== DONE ===")
    print(f"Total: {len(all_records)} images")
    cats = {}
    for r in all_records:
        cats[r["category"]] = cats.get(r["category"], 0) + 1
    for cat, count in sorted(cats.items()):
        print(f"  {cat}: {count}")


if __name__ == "__main__":
    main()
