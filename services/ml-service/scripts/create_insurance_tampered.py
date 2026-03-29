#!/usr/bin/env python3
"""
Create tampered insurance images programmatically from authentic sources.

Methods: copy-paste damage, splice forgery, inpainting removal, document
manipulation, clone stamp. No manual Photoshop needed.

Usage:
  python3 -m scripts.create_insurance_tampered \
      --bucket dent-calibration-data \
      --authentic-prefix raw_v8/authentic \
      --output-prefix raw_v8/tampered \
      --target 5000
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import random
import sys
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import boto3
except ImportError:
    boto3 = None


# ── Tampering methods ────────────────────────────────────────────────

def copy_move_forgery(img: Image.Image) -> Image.Image:
    """Copy a random region and paste it elsewhere in the same image."""
    w, h = img.size
    arr = np.array(img)

    # Source region (10-25% of image)
    rw = random.randint(w // 10, w // 4)
    rh = random.randint(h // 10, h // 4)
    sx = random.randint(0, w - rw)
    sy = random.randint(0, h - rh)

    # Destination (different location)
    for _ in range(20):
        dx = random.randint(0, w - rw)
        dy = random.randint(0, h - rh)
        if abs(dx - sx) > rw // 2 or abs(dy - sy) > rh // 2:
            break

    # Copy region
    region = arr[sy:sy + rh, sx:sx + rw].copy()

    # Create smooth mask for blending
    mask = np.ones((rh, rw), dtype=np.float32)
    blur_px = max(3, min(rw, rh) // 10)
    if blur_px % 2 == 0:
        blur_px += 1
    if cv2 is not None:
        mask = cv2.GaussianBlur(mask, (blur_px, blur_px), 0)

    # Blend
    for c in range(3):
        arr[dy:dy + rh, dx:dx + rw, c] = (
            region[:, :, c] * mask + arr[dy:dy + rh, dx:dx + rw, c] * (1 - mask)
        ).astype(np.uint8)

    return Image.fromarray(arr)


def splice_forgery(img1: Image.Image, img2: Image.Image) -> Image.Image:
    """Splice a region from img2 into img1 (different source images)."""
    w1, h1 = img1.size
    w2, h2 = img2.size
    arr1 = np.array(img1)

    # Region from img2 (15-30% of img1 dimensions)
    rw = random.randint(w1 // 7, w1 // 3)
    rh = random.randint(h1 // 7, h1 // 3)

    # Sample from img2
    sx = random.randint(0, max(0, w2 - rw))
    sy = random.randint(0, max(0, h2 - rh))
    rw = min(rw, w2 - sx)
    rh = min(rh, h2 - sy)

    region = np.array(img2)[sy:sy + rh, sx:sx + rw]

    # Paste into img1
    dx = random.randint(0, max(0, w1 - rw))
    dy = random.randint(0, max(0, h1 - rh))

    # Feathered blending
    mask = np.ones((rh, rw), dtype=np.float32)
    fade = max(5, min(rw, rh) // 8)
    for i in range(fade):
        f = i / fade
        mask[i, :] *= f
        mask[-(i + 1), :] *= f
        mask[:, i] *= f
        mask[:, -(i + 1)] *= f

    rh_actual = min(rh, h1 - dy)
    rw_actual = min(rw, w1 - dx)

    for c in range(3):
        arr1[dy:dy + rh_actual, dx:dx + rw_actual, c] = (
            region[:rh_actual, :rw_actual, c] * mask[:rh_actual, :rw_actual]
            + arr1[dy:dy + rh_actual, dx:dx + rw_actual, c] * (1 - mask[:rh_actual, :rw_actual])
        ).astype(np.uint8)

    return Image.fromarray(arr1)


def inpaint_removal(img: Image.Image) -> Image.Image:
    """Remove a region using inpainting (simulates hiding damage)."""
    if cv2 is None:
        return remove_region_simple(img)

    arr = np.array(img)
    h, w = arr.shape[:2]

    # Create mask for region to remove (oval shape)
    mask = np.zeros((h, w), dtype=np.uint8)
    cx = random.randint(w // 4, 3 * w // 4)
    cy = random.randint(h // 4, 3 * h // 4)
    rx = random.randint(w // 10, w // 4)
    ry = random.randint(h // 10, h // 4)
    cv2.ellipse(mask, (cx, cy), (rx, ry), 0, 0, 360, 255, -1)

    # Inpaint
    result = cv2.inpaint(arr, mask, inpaintRadius=5, flags=cv2.INPAINT_TELEA)
    return Image.fromarray(result)


def remove_region_simple(img: Image.Image) -> Image.Image:
    """Simple region removal by blurring (fallback without OpenCV)."""
    w, h = img.size
    rw = random.randint(w // 8, w // 3)
    rh = random.randint(h // 8, h // 3)
    x = random.randint(0, w - rw)
    y = random.randint(0, h - rh)

    # Blur the region heavily
    region = img.crop((x, y, x + rw, y + rh))
    blurred = region.filter(ImageFilter.GaussianBlur(radius=15))
    img.paste(blurred, (x, y))
    return img


def document_manipulation(img: Image.Image) -> Image.Image:
    """Modify text-like regions in document images."""
    w, h = img.size
    draw = ImageDraw.Draw(img)

    # White-out a rectangular region (simulate changing text)
    for _ in range(random.randint(1, 3)):
        rw = random.randint(w // 8, w // 3)
        rh = random.randint(15, 40)
        x = random.randint(0, max(1, w - rw))
        y = random.randint(0, max(1, h - rh))

        # Sample background color from surrounding pixels
        sample_x = min(x + rw + 5, w - 1)
        try:
            bg_color = img.getpixel((sample_x, y + rh // 2))
        except Exception:
            bg_color = (255, 255, 255)

        # White-out
        draw.rectangle([x, y, x + rw, y + rh], fill=bg_color)

        # Draw fake text
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", rh - 4)
        except Exception:
            font = ImageFont.load_default()

        fake_text = random.choice([
            f"{random.randint(100, 9999)}.{random.randint(0, 99):02d}",
            f"{random.randint(1, 28):02d}.{random.randint(1, 12):02d}.{random.randint(2020, 2026)}",
            f"EUR {random.randint(50, 5000)},{random.randint(0, 99):02d}",
            f"#{random.randint(10000, 99999)}",
        ])
        text_color = random.choice([(0, 0, 0), (30, 30, 30), (50, 50, 50)])
        draw.text((x + 2, y + 1), fake_text, fill=text_color, font=font)

    # Add slight noise to make it look natural
    arr = np.array(img).astype(np.float32)
    noise = np.random.normal(0, 2, arr.shape)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)

    return Image.fromarray(arr)


def color_exposure_edit(img: Image.Image) -> Image.Image:
    """Change color/exposure of a region to hide or exaggerate damage."""
    w, h = img.size
    arr = np.array(img).astype(np.float32)

    # Select region
    rw = random.randint(w // 4, w // 2)
    rh = random.randint(h // 4, h // 2)
    x = random.randint(0, w - rw)
    y = random.randint(0, h - rh)

    region = arr[y:y + rh, x:x + rw]

    # Random manipulation
    op = random.choice(["brighten", "darken", "saturate", "desaturate", "hue_shift"])
    if op == "brighten":
        region = np.clip(region * random.uniform(1.2, 1.6), 0, 255)
    elif op == "darken":
        region = np.clip(region * random.uniform(0.4, 0.7), 0, 255)
    elif op == "saturate":
        mean = region.mean(axis=2, keepdims=True)
        region = np.clip(mean + (region - mean) * random.uniform(1.5, 2.5), 0, 255)
    elif op == "desaturate":
        mean = region.mean(axis=2, keepdims=True)
        region = np.clip(mean + (region - mean) * random.uniform(0.1, 0.4), 0, 255)
    elif op == "hue_shift":
        shift = np.array([random.randint(-40, 40), random.randint(-40, 40), random.randint(-40, 40)])
        region = np.clip(region + shift, 0, 255)

    # Blend edges
    mask = np.ones((rh, rw, 1), dtype=np.float32)
    fade = max(10, min(rw, rh) // 6)
    for i in range(fade):
        f = i / fade
        mask[i, :] *= f
        mask[-(i + 1), :] *= f
        mask[:, i] *= f
        mask[:, -(i + 1)] *= f

    arr[y:y + rh, x:x + rw] = region * mask + arr[y:y + rh, x:x + rw] * (1 - mask)

    return Image.fromarray(arr.astype(np.uint8))


def clone_stamp(img: Image.Image) -> Image.Image:
    """Clone texture from one area to another (simulates hiding damage)."""
    w, h = img.size
    arr = np.array(img)

    rw = random.randint(w // 8, w // 4)
    rh = random.randint(h // 8, h // 4)

    # Source (clean-looking area)
    sx = random.randint(0, w - rw)
    sy = random.randint(0, h - rh)

    # Destination (different area)
    dx = random.randint(0, w - rw)
    dy = random.randint(0, h - rh)

    source_region = arr[sy:sy + rh, sx:sx + rw].copy()

    # Circular mask
    mask = np.zeros((rh, rw), dtype=np.float32)
    cy, cx = rh // 2, rw // 2
    for y in range(rh):
        for x in range(rw):
            dist = ((x - cx) / (rw / 2)) ** 2 + ((y - cy) / (rh / 2)) ** 2
            if dist < 1:
                mask[y, x] = max(0, 1 - dist)

    for c in range(3):
        arr[dy:dy + rh, dx:dx + rw, c] = (
            source_region[:, :, c] * mask + arr[dy:dy + rh, dx:dx + rw, c] * (1 - mask)
        ).astype(np.uint8)

    return Image.fromarray(arr)


# ── Main ─────────────────────────────────────────────────────────────

TAMPER_METHODS = {
    "copy_move": {"fn": copy_move_forgery, "weight": 25, "needs_pair": False},
    "splice": {"fn": splice_forgery, "weight": 20, "needs_pair": True},
    "inpaint": {"fn": inpaint_removal, "weight": 15, "needs_pair": False},
    "document": {"fn": document_manipulation, "weight": 10, "needs_pair": False},
    "color_exposure": {"fn": color_exposure_edit, "weight": 15, "needs_pair": False},
    "clone_stamp": {"fn": clone_stamp, "weight": 15, "needs_pair": False},
}


def load_authentic_images(
    bucket: str, prefix: str, region: str, local_dir: str, limit: int = 10000
) -> list[tuple[str, bytes]]:
    """Load authentic images from S3 or local directory."""
    images = []

    if local_dir:
        local_path = Path(local_dir)
        for f in sorted(local_path.glob("*.jpg"))[:limit]:
            images.append((f.name, f.read_bytes()))
    else:
        s3 = boto3.client("s3", region_name=region)
        # List images
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith((".jpg", ".jpeg", ".png")):
                    try:
                        resp = s3.get_object(Bucket=bucket, Key=key)
                        data = resp["Body"].read()
                        images.append((os.path.basename(key), data))
                    except Exception:
                        continue
                if len(images) >= limit:
                    break
            if len(images) >= limit:
                break

    print(f"Loaded {len(images)} authentic images")
    return images


def main():
    parser = argparse.ArgumentParser(description="Create tampered insurance images")
    parser.add_argument("--bucket", default="dent-calibration-data")
    parser.add_argument("--authentic-prefix", default="raw_v8/authentic")
    parser.add_argument("--output-prefix", default="raw_v8/tampered")
    parser.add_argument("--target", type=int, default=5000)
    parser.add_argument("--region", default="eu-central-1")
    parser.add_argument("--local-dir", default="", help="Local authentic dir")
    parser.add_argument("--local-out", default="", help="Local output dir")
    args = parser.parse_args()

    s3 = None
    if not args.local_out:
        if boto3 is None:
            print("ERROR: pip install boto3 (or use --local-out)")
            sys.exit(1)
        s3 = boto3.client("s3", region_name=args.region)

    local_out = Path(args.local_out) if args.local_out else None
    if local_out:
        local_out.mkdir(parents=True, exist_ok=True)

    # Load authentic images
    print("Loading authentic images...")
    auth_images = load_authentic_images(
        args.bucket, args.authentic_prefix, args.region, args.local_dir
    )

    if len(auth_images) < 10:
        print("ERROR: Need at least 10 authentic images")
        sys.exit(1)

    # Build weighted method list
    methods = []
    for name, cfg in TAMPER_METHODS.items():
        methods.extend([(name, cfg)] * cfg["weight"])

    records = []
    errors = 0

    print(f"\nGenerating {args.target} tampered images...")

    for i in range(args.target):
        method_name, method_cfg = random.choice(methods)

        try:
            # Pick random authentic image
            _, img_bytes = random.choice(auth_images)
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")

            if method_cfg["needs_pair"]:
                _, img2_bytes = random.choice(auth_images)
                img2 = Image.open(io.BytesIO(img2_bytes)).convert("RGB")
                tampered = method_cfg["fn"](img, img2)
            else:
                tampered = method_cfg["fn"](img)

            # Save as JPEG
            w, h = tampered.size
            if max(w, h) > 1024:
                ratio = 1024 / max(w, h)
                tampered = tampered.resize(
                    (int(w * ratio), int(h * ratio)), Image.LANCZOS
                )

            buf = io.BytesIO()
            # Randomly vary JPEG quality to match real-world conditions
            quality = random.choice([80, 85, 90, 90, 95])
            tampered.save(buf, format="JPEG", quality=quality)
            jpeg_bytes = buf.getvalue()

            if len(jpeg_bytes) < 3000:
                continue

            filename = f"{uuid.uuid4().hex[:12]}.jpg"

            if s3:
                s3.put_object(
                    Bucket=args.bucket,
                    Key=f"{args.output_prefix}/{filename}",
                    Body=jpeg_bytes,
                    ContentType="image/jpeg",
                    Metadata={"method": method_name},
                )
            elif local_out:
                (local_out / filename).write_bytes(jpeg_bytes)

            records.append({
                "filename": filename,
                "ground_truth": "tampered",
                "method": method_name,
            })

            if (i + 1) % 500 == 0:
                method_counts = {}
                for r in records:
                    method_counts[r["method"]] = method_counts.get(r["method"], 0) + 1
                print(f"  [{len(records)}/{args.target}] methods: {method_counts}")

        except Exception as e:
            errors += 1
            if errors <= 10:
                print(f"  Error ({method_name}): {e}")
            continue

    # Save labels
    csv_content = "filename,ground_truth,method\n"
    for rec in records:
        csv_content += f"{rec['filename']},{rec['ground_truth']},{rec['method']}\n"

    if s3:
        s3.put_object(
            Bucket=args.bucket,
            Key=f"{args.output_prefix}/labels.csv",
            Body=csv_content.encode(),
            ContentType="text/csv",
        )
    elif local_out:
        (local_out / "labels.csv").write_text(csv_content)

    print(f"\n=== DONE ===")
    print(f"Total: {len(records)} tampered images ({errors} errors)")
    method_counts = {}
    for r in records:
        method_counts[r["method"]] = method_counts.get(r["method"], 0) + 1
    for m, c in sorted(method_counts.items()):
        print(f"  {m}: {c}")


if __name__ == "__main__":
    main()
