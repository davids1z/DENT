#!/usr/bin/env python3
"""Download AI-generated images from OpenFake dataset (HuggingFace) to S3.

Uses HF Datasets Server API to fetch images without downloading the full 1TB
dataset. Samples N images per generator, standardizes to JPEG, uploads to S3.

Covers modern generators missing from current probes:
  Flux, DALL-E 3, Midjourney v6, GPT Image 1, Grok 2, Ideogram 3.0,
  Imagen 4, SD 3.5, and more.

Usage:
  # List available generators first:
  python -m scripts.download_openfake --list-models

  # Download 300 per generator:
  python -m scripts.download_openfake \
    --bucket dent-calibration-data \
    --per-model 300
"""

from __future__ import annotations

import argparse
import io
import sys
import time
import uuid

import boto3
import requests as http_requests
from PIL import Image

# Target generators: model_name_in_dataset → count to download
# These cover the generators our current probes MISS.
TARGET_MODELS = {
    "flux.1-dev": 400,
    "flux.1-schnell": 300,
    "flux-1.1-pro": 200,
    "dalle-3": 400,
    "midjourney-6": 400,
    "gpt-image-1": 300,
    "grok-2-image-1212": 200,
    "ideogram-3.0": 300,
    "imagen-4.0": 200,
    "sd-3.5": 300,
    "sdxl": 200,
    "hidream-i1-full": 200,
}

HF_API = "https://datasets-server.huggingface.co/rows"
DATASET = "ComplexDataLab/OpenFake"
S3_PREFIX = "raw/ai_generated"
PAGE_SIZE = 100  # max rows per API call


def standardize_image(img: Image.Image, max_side: int = 1024) -> bytes | None:
    """Convert to JPEG, strip EXIF, resize if needed."""
    try:
        if img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        if max(w, h) < 128:
            return None
        if max(w, h) > max_side:
            ratio = max_side / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90, optimize=True)
        data = buf.getvalue()
        return data if len(data) >= 3000 else None
    except Exception:
        return None


def fetch_page(offset: int, length: int = PAGE_SIZE) -> list[dict] | None:
    """Fetch a page of rows from HF Datasets Server API."""
    try:
        resp = http_requests.get(
            HF_API,
            params={
                "dataset": DATASET,
                "config": "default",
                "split": "train",
                "offset": offset,
                "length": length,
            },
            timeout=60,
        )
        if resp.status_code == 200:
            return resp.json().get("rows", [])
        if resp.status_code == 429:
            print("  Rate limited, waiting 30s...", flush=True)
            time.sleep(30)
            return None
        return None
    except Exception as e:
        print(f"  API error at offset {offset}: {e}", flush=True)
        return None


def download_image(src_url: str) -> Image.Image | None:
    """Download image from HF URL."""
    try:
        resp = http_requests.get(src_url, timeout=30)
        if resp.status_code == 200:
            return Image.open(io.BytesIO(resp.content))
        return None
    except Exception:
        return None


def list_models_mode():
    """Scan dataset and print unique model values."""
    import collections
    print("Sampling OpenFake dataset for model names...", flush=True)
    models = collections.Counter()
    for offset in range(0, 1870000, 25000):
        rows = fetch_page(offset, 50)
        if rows:
            for r in rows:
                row = r.get("row", {})
                if row.get("label") == "fake":
                    models[row.get("model", "?")] += 1
        if offset % 200000 == 0:
            print(f"  Scanned offset {offset}...", flush=True)

    print(f"\n{'Model':<30} {'Sampled':>8}")
    print("-" * 40)
    for model, count in sorted(models.items(), key=lambda x: -x[1]):
        tag = " ← TARGET" if model in TARGET_MODELS else ""
        print(f"{model:<30} {count:>8}{tag}")


def download_mode(args):
    """Fetch images from OpenFake via HF API, upload to S3."""
    s3 = boto3.client("s3", region_name=args.region)

    targets = dict(TARGET_MODELS)
    if args.per_model:
        for k in targets:
            targets[k] = args.per_model

    print(f"Target: {sum(targets.values())} images from {len(targets)} generators", flush=True)
    for m, c in targets.items():
        print(f"  {m}: {c}", flush=True)
    print(flush=True)

    collected: dict[str, int] = {k: 0 for k in targets}
    total_needed = sum(targets.values())
    errors = 0

    # Scan through dataset in chunks, collecting target models
    # Dataset is ~1.87M rows, fake images are scattered throughout
    offset = 0
    consecutive_empty = 0

    while sum(collected.values()) < total_needed and offset < 1870000:
        rows = fetch_page(offset, PAGE_SIZE)
        if rows is None:
            time.sleep(2)
            consecutive_empty += 1
            if consecutive_empty > 10:
                offset += PAGE_SIZE
                consecutive_empty = 0
            continue

        consecutive_empty = 0
        found_any = False

        for r in rows:
            row = r.get("row", {})
            model = row.get("model", "")
            label = row.get("label", "")

            if label != "fake" or model not in targets:
                continue
            if collected[model] >= targets[model]:
                continue

            # Download and process image
            img_data = row.get("image", {})
            src_url = img_data.get("src", "")
            if not src_url:
                continue

            img = download_image(src_url)
            if img is None:
                errors += 1
                continue

            jpeg_bytes = standardize_image(img)
            if jpeg_bytes is None:
                continue

            # Upload to S3
            random_name = uuid.uuid4().hex[:12] + ".jpg"
            try:
                s3.put_object(
                    Bucket=args.bucket,
                    Key=f"{S3_PREFIX}/{random_name}",
                    Body=jpeg_bytes,
                    ContentType="image/jpeg",
                    Metadata={
                        "source": f"openfake/{model}",
                        "generator": model,
                    },
                )
                collected[model] += 1
                found_any = True

                total = sum(collected.values())
                if total % 25 == 0:
                    print(f"  [{total}/{total_needed}] "
                          f"{', '.join(f'{k}:{v}' for k, v in collected.items() if v > 0)}",
                          flush=True)
            except Exception as e:
                errors += 1
                if errors <= 5:
                    print(f"  S3 error: {e}", flush=True)

        offset += PAGE_SIZE

        # Check if all targets met
        if all(collected[k] >= targets[k] for k in targets):
            break

        # Small delay to respect API
        if not found_any:
            time.sleep(0.2)
        else:
            time.sleep(0.5)

    # Summary
    total = sum(collected.values())
    print(f"\n{'='*60}", flush=True)
    print(f"Download complete!", flush=True)
    print(f"  Uploaded: {total} images, Errors: {errors}", flush=True)
    print(f"\nPer generator:", flush=True)
    for k, v in sorted(collected.items(), key=lambda x: -x[1]):
        status = "OK" if v >= targets[k] else f"SHORT ({v}/{targets[k]})"
        print(f"  {k:<30} {v:>5}  {status}", flush=True)
    print(f"\nAll images at: s3://{args.bucket}/{S3_PREFIX}/", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Download AI images from OpenFake (HuggingFace) to S3"
    )
    parser.add_argument("--bucket", default="dent-calibration-data")
    parser.add_argument("--region", default="eu-central-1")
    parser.add_argument("--per-model", type=int, default=0,
                        help="Override: images per generator (0=use defaults)")
    parser.add_argument("--list-models", action="store_true",
                        help="Scan dataset and list available model names, then exit")
    args = parser.parse_args()

    if args.list_models:
        list_models_mode()
        return

    if not args.bucket:
        print("ERROR: --bucket required")
        sys.exit(1)

    download_mode(args)


if __name__ == "__main__":
    main()
