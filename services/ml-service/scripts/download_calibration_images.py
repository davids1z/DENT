#!/usr/bin/env python3
"""
Download calibration images from public datasets and upload directly to S3.

Downloads 500+ images per category (authentic, ai_generated, tampered)
from public academic datasets and uploads directly to S3 without local storage.

Usage:
  # Set AWS credentials first:
  export AWS_ACCESS_KEY_ID=AKIA...
  export AWS_SECRET_ACCESS_KEY=...
  export AWS_DEFAULT_REGION=eu-central-1

  python -m scripts.download_calibration_images \
    --bucket dent-calibration-data \
    --category authentic \
    --limit 600

  python -m scripts.download_calibration_images \
    --bucket dent-calibration-data \
    --category ai_generated \
    --limit 600

  python -m scripts.download_calibration_images \
    --bucket dent-calibration-data \
    --category tampered \
    --limit 600

Sources:
  authentic:    RAISE dataset, COCO val2017, Flickr CC
  ai_generated: GenImage (HuggingFace), DiffusionForensics
  tampered:     CASIA v2, Columbia, CoMoFoD
"""

from __future__ import annotations

import argparse
import io
import sys
import uuid
from typing import Iterator

import boto3
import requests
from PIL import Image

S3_PREFIX_RAW = "raw"


def _upload_to_s3(
    s3_client,
    bucket: str,
    category: str,
    image_bytes: bytes,
    extension: str = ".jpg",
    source: str = "unknown",
) -> str:
    """Upload image bytes directly to S3 with random filename."""
    random_name = uuid.uuid4().hex[:12] + extension
    key = f"{S3_PREFIX_RAW}/{category}/{random_name}"

    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=image_bytes,
        ContentType="image/jpeg",
        Metadata={"source": source, "category": category},
    )
    return key


def _standardize_image(image_bytes: bytes, quality: int = 90) -> bytes:
    """Standardize image: convert to RGB JPEG, strip ALL metadata, quality 90."""
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")

    # Save as JPEG without EXIF (Pillow strips metadata by default when not copying)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


# ── Dataset downloaders ─────────────────────────────────────────────


def download_coco_val2017(limit: int = 600) -> Iterator[tuple[bytes, str]]:
    """Download real photos from COCO val2017 dataset (5000 images available)."""
    print("  Downloading from COCO val2017...")

    # COCO val2017 image list from official API
    coco_api = "http://images.cocodataset.org/val2017/"

    # Get image IDs from COCO annotations
    ann_url = "http://images.cocodataset.org/annotations/instances_val2017.json"

    # Alternative: use a predefined list of COCO image IDs
    # These are the first N image IDs from val2017
    # COCO image filenames are zero-padded 12-digit numbers
    import json

    try:
        print("    Fetching COCO annotation index...")
        resp = requests.get(
            "http://images.cocodataset.org/annotations/image_info_val2017.json",
            timeout=60,
            stream=True,
        )
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}")

        data = json.loads(resp.content)
        images = data.get("images", [])[:limit]
        print(f"    Found {len(images)} images in COCO val2017")
    except Exception as e:
        print(f"    COCO annotation download failed: {e}")
        print("    Falling back to sequential IDs...")
        # Fallback: generate sequential filenames
        images = [{"file_name": f"{str(i).zfill(12)}.jpg"} for i in range(1, limit + 1)]

    count = 0
    for img_info in images:
        if count >= limit:
            break

        filename = img_info.get("file_name", img_info.get("coco_url", "").split("/")[-1])
        url = f"http://images.cocodataset.org/val2017/{filename}"

        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 200 and len(resp.content) > 1000:
                yield resp.content, f"coco_val2017/{filename}"
                count += 1
        except Exception:
            continue

    print(f"    Downloaded {count} COCO images")


def download_huggingface_dataset(
    dataset_name: str,
    split: str = "test",
    image_column: str = "image",
    limit: int = 600,
    label_column: str | None = None,
    label_value: int | str | None = None,
) -> Iterator[tuple[bytes, str]]:
    """Download images from a HuggingFace dataset using the datasets library."""
    print(f"  Downloading from HuggingFace: {dataset_name} ({split})...")

    try:
        from datasets import load_dataset

        ds = load_dataset(dataset_name, split=split, streaming=True)

        count = 0
        for i, sample in enumerate(ds):
            if count >= limit:
                break

            # Filter by label if specified
            if label_column and label_value is not None:
                if sample.get(label_column) != label_value:
                    continue

            img = sample.get(image_column)
            if img is None:
                continue

            # Convert PIL Image to bytes
            if hasattr(img, "save"):
                buf = io.BytesIO()
                if img.mode != "RGB":
                    img = img.convert("RGB")
                img.save(buf, format="JPEG", quality=90)
                yield buf.getvalue(), f"{dataset_name}/{i}"
                count += 1

        print(f"    Downloaded {count} images from {dataset_name}")

    except ImportError:
        print("    ERROR: 'datasets' package not installed. Run: pip install datasets")
    except Exception as e:
        print(f"    ERROR downloading {dataset_name}: {e}")


def download_genimage_ai(limit: int = 600) -> Iterator[tuple[bytes, str]]:
    """Download AI-generated images from GenImage dataset on HuggingFace."""
    # GenImage has images from multiple generators
    generators = [
        ("Yijun0/GenImage_MJ", "test", "image", None, None, limit // 4),
        ("Yijun0/GenImage_SDXL", "test", "image", None, None, limit // 4),
        ("Yijun0/GenImage_DALLE3", "test", "image", None, None, limit // 4),
        ("Yijun0/GenImage_SD", "test", "image", None, None, limit // 4),
    ]

    total = 0
    for ds_name, split, img_col, lbl_col, lbl_val, sub_limit in generators:
        try:
            for img_bytes, source in download_huggingface_dataset(
                ds_name, split, img_col, sub_limit, lbl_col, lbl_val
            ):
                yield img_bytes, source
                total += 1
        except Exception as e:
            print(f"    Skipping {ds_name}: {e}")
            continue

    # Fallback: use InfImagine FakeImageDataset if GenImage not available
    if total < limit // 2:
        remaining = limit - total
        print(f"    GenImage gave {total} images, trying FakeImageDataset for {remaining} more...")
        try:
            for img_bytes, source in download_huggingface_dataset(
                "InfImagine/FakeImageDataset",
                "train",
                "image",
                remaining,
            ):
                yield img_bytes, source
                total += 1
        except Exception:
            pass

    print(f"    Total AI-generated: {total}")


def download_casia_tampered(limit: int = 600) -> Iterator[tuple[bytes, str]]:
    """Download tampered images from CASIA v2 dataset."""
    print("  Downloading tampered images from CASIA v2 / IMD2020...")

    # Try CASIA v2 from HuggingFace
    count = 0
    try:
        for img_bytes, source in download_huggingface_dataset(
            "InfImagine/CASIA2",
            "test",
            "image",
            limit,
            "label",
            1,  # 1 = tampered
        ):
            yield img_bytes, source
            count += 1
    except Exception as e:
        print(f"    CASIA2 failed: {e}")

    # Fallback: Columbia dataset
    if count < limit // 2:
        remaining = limit - count
        try:
            for img_bytes, source in download_huggingface_dataset(
                "InfImagine/Columbia",
                "test",
                "image",
                remaining,
                "label",
                1,
            ):
                yield img_bytes, source
                count += 1
        except Exception:
            pass

    print(f"    Total tampered: {count}")


# ── Main ────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Download calibration images to S3")
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument(
        "--category",
        required=True,
        choices=["authentic", "ai_generated", "tampered", "all"],
        help="Image category to download",
    )
    parser.add_argument("--limit", type=int, default=600, help="Max images per category")
    parser.add_argument("--region", default="eu-central-1", help="AWS region")
    args = parser.parse_args()

    s3 = boto3.client("s3", region_name=args.region)

    # Verify bucket exists
    try:
        s3.head_bucket(Bucket=args.bucket)
        print(f"S3 bucket: {args.bucket} (verified)")
    except Exception as e:
        print(f"ERROR: Cannot access bucket {args.bucket}: {e}")
        sys.exit(1)

    categories = (
        ["authentic", "ai_generated", "tampered"]
        if args.category == "all"
        else [args.category]
    )

    for category in categories:
        print(f"\n{'='*60}")
        print(f"Downloading: {category} (limit: {args.limit})")
        print(f"{'='*60}")

        if category == "authentic":
            source_iter = download_coco_val2017(args.limit)
        elif category == "ai_generated":
            source_iter = download_genimage_ai(args.limit)
        elif category == "tampered":
            source_iter = download_casia_tampered(args.limit)
        else:
            continue

        uploaded = 0
        errors = 0

        for raw_bytes, source_name in source_iter:
            try:
                # Standardize: RGB JPEG quality=90, strip ALL metadata
                std_bytes = _standardize_image(raw_bytes, quality=90)
                key = _upload_to_s3(s3, args.bucket, category, std_bytes, ".jpg", source_name)
                uploaded += 1

                if uploaded % 50 == 0:
                    print(f"    Uploaded {uploaded} images to s3://{args.bucket}/{S3_PREFIX_RAW}/{category}/")

            except Exception as e:
                errors += 1
                if errors <= 5:
                    print(f"    Error processing image from {source_name}: {e}")
                continue

        print(f"\n  {category}: {uploaded} uploaded, {errors} errors")

    print(f"\n{'='*60}")
    print("Download complete!")
    print(f"Images are in s3://{args.bucket}/raw/<category>/")
    print(f"\nNext step: python -m scripts.prepare_calibration_dataset --bucket {args.bucket}")


if __name__ == "__main__":
    main()
