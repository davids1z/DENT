#!/usr/bin/env python3
"""
Create tampered insurance images from authentic sources on S3.
10 tampering methods + SD inpainting (GPU). All output to S3 directly.
Supports --resume to continue interrupted runs.

Methods:
  1. Copy-move (seamlessClone) — 800
  2. Splice + perspective warp — 700
  3. Inpaint removal (TELEA + NS) — 600
  4. Document manipulation (OCR → whiteout → redraw) — 500
  5. Color/exposure region — 400
  6. Clone stamp (seamlessClone + circular mask) — 300
  7. JPEG ghost (mixed quality regions) — 200
  8. Resize artifact (upscale small patch) — 200
  9. CASIA v2 (HuggingFace academic dataset) — 500
  10. Noise injection (regional Gaussian) — 300
  11. SD Inpainting (vast.ai GPU) — 1,000

Usage:
  python3 -m scripts.create_insurance_tampered \
      --bucket dent-calibration-data \
      --authentic-prefix raw_v8/authentic \
      --output-prefix raw_v8/tampered \
      --target 5500

  # SD inpainting (on GPU):
  python3 -m scripts.create_insurance_tampered \
      --mode sd-inpaint --target 1000 ...
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import random
import sys
import time
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

def copy_move_seamless(img: Image.Image) -> Image.Image:
    """Copy-move with cv2.seamlessClone for realistic blending."""
    if cv2 is None:
        return copy_move_basic(img)

    arr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    h, w = arr.shape[:2]

    # Source region (10-25% of image)
    rw = random.randint(w // 10, w // 4)
    rh = random.randint(h // 10, h // 4)
    sx = random.randint(0, w - rw)
    sy = random.randint(0, h - rh)

    # Destination (different location)
    dx, dy = sx, sy
    for _ in range(30):
        dx = random.randint(rw // 2, w - rw // 2)
        dy = random.randint(rh // 2, h - rh // 2)
        if abs(dx - sx - rw // 2) > rw // 2 or abs(dy - sy - rh // 2) > rh // 2:
            break

    # Extract source region
    source = arr[sy:sy + rh, sx:sx + rw].copy()

    # Create elliptical mask
    mask = np.zeros((rh, rw), dtype=np.uint8)
    cv2.ellipse(mask, (rw // 2, rh // 2), (rw // 2 - 2, rh // 2 - 2), 0, 0, 360, 255, -1)

    # seamlessClone
    center = (dx, dy)
    try:
        result = cv2.seamlessClone(source, arr, mask, center, cv2.NORMAL_CLONE)
        return Image.fromarray(cv2.cvtColor(result, cv2.COLOR_BGR2RGB))
    except Exception:
        return copy_move_basic(img)


def copy_move_basic(img: Image.Image) -> Image.Image:
    """Fallback copy-move with Gaussian blending."""
    w, h = img.size
    arr = np.array(img)

    rw = random.randint(w // 10, w // 4)
    rh = random.randint(h // 10, h // 4)
    sx = random.randint(0, w - rw)
    sy = random.randint(0, h - rh)

    dx = random.randint(0, w - rw)
    dy = random.randint(0, h - rh)

    region = arr[sy:sy + rh, sx:sx + rw].copy()
    mask = np.ones((rh, rw), dtype=np.float32)
    blur_px = max(3, min(rw, rh) // 10) | 1
    if cv2 is not None:
        mask = cv2.GaussianBlur(mask, (blur_px, blur_px), 0)

    for c in range(3):
        arr[dy:dy + rh, dx:dx + rw, c] = (
            region[:, :, c] * mask + arr[dy:dy + rh, dx:dx + rw, c] * (1 - mask)
        ).astype(np.uint8)

    return Image.fromarray(arr)


def splice_perspective(img1: Image.Image, img2: Image.Image) -> Image.Image:
    """Splice region from img2 into img1 with perspective warp + seamlessClone."""
    if cv2 is None:
        return splice_basic(img1, img2)

    arr1 = cv2.cvtColor(np.array(img1), cv2.COLOR_RGB2BGR)
    arr2 = cv2.cvtColor(np.array(img2), cv2.COLOR_RGB2BGR)
    h1, w1 = arr1.shape[:2]
    h2, w2 = arr2.shape[:2]

    # Region from img2
    rw = random.randint(w1 // 6, w1 // 3)
    rh = random.randint(h1 // 6, h1 // 3)
    sx = random.randint(0, max(0, w2 - rw))
    sy = random.randint(0, max(0, h2 - rh))
    rw = min(rw, w2 - sx)
    rh = min(rh, h2 - sy)

    region = arr2[sy:sy + rh, sx:sx + rw].copy()

    # Apply slight perspective/affine warp
    angle = random.uniform(-10, 10)
    scale = random.uniform(0.85, 1.15)
    M = cv2.getRotationMatrix2D((rw / 2, rh / 2), angle, scale)
    region = cv2.warpAffine(region, M, (rw, rh), borderMode=cv2.BORDER_REFLECT)

    # Create mask
    mask = np.zeros((rh, rw), dtype=np.uint8)
    cv2.ellipse(mask, (rw // 2, rh // 2), (rw // 2 - 2, rh // 2 - 2), 0, 0, 360, 255, -1)

    # Paste with seamlessClone
    dx = random.randint(rw // 2, max(rw // 2 + 1, w1 - rw // 2))
    dy = random.randint(rh // 2, max(rh // 2 + 1, h1 - rh // 2))

    try:
        result = cv2.seamlessClone(region, arr1, mask, (dx, dy), cv2.NORMAL_CLONE)
        return Image.fromarray(cv2.cvtColor(result, cv2.COLOR_BGR2RGB))
    except Exception:
        return splice_basic(img1, img2)


def splice_basic(img1: Image.Image, img2: Image.Image) -> Image.Image:
    """Fallback splice with feathered blending."""
    w1, h1 = img1.size
    w2, h2 = img2.size
    arr1 = np.array(img1)

    rw = random.randint(w1 // 7, w1 // 3)
    rh = random.randint(h1 // 7, h1 // 3)
    sx = random.randint(0, max(0, w2 - rw))
    sy = random.randint(0, max(0, h2 - rh))
    rw = min(rw, w2 - sx)
    rh = min(rh, h2 - sy)

    region = np.array(img2)[sy:sy + rh, sx:sx + rw]
    dx = random.randint(0, max(0, w1 - rw))
    dy = random.randint(0, max(0, h1 - rh))

    mask = np.ones((rh, rw), dtype=np.float32)
    fade = max(5, min(rw, rh) // 8)
    for i in range(fade):
        f = i / fade
        mask[i, :] *= f
        mask[-(i + 1), :] *= f
        mask[:, i] *= f
        mask[:, -(i + 1)] *= f

    rh_a = min(rh, h1 - dy)
    rw_a = min(rw, w1 - dx)
    for c in range(3):
        arr1[dy:dy + rh_a, dx:dx + rw_a, c] = (
            region[:rh_a, :rw_a, c] * mask[:rh_a, :rw_a]
            + arr1[dy:dy + rh_a, dx:dx + rw_a, c] * (1 - mask[:rh_a, :rw_a])
        ).astype(np.uint8)

    return Image.fromarray(arr1)


def inpaint_removal(img: Image.Image) -> Image.Image:
    """Remove region using cv2.inpaint (TELEA or NS)."""
    if cv2 is None:
        return remove_region_blur(img)

    arr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    h, w = arr.shape[:2]

    mask = np.zeros((h, w), dtype=np.uint8)
    cx = random.randint(w // 4, 3 * w // 4)
    cy = random.randint(h // 4, 3 * h // 4)
    rx = random.randint(w // 10, w // 4)
    ry = random.randint(h // 10, h // 4)
    cv2.ellipse(mask, (cx, cy), (rx, ry), 0, 0, 360, 255, -1)

    # Randomly choose TELEA or NS
    method = random.choice([cv2.INPAINT_TELEA, cv2.INPAINT_NS])
    result = cv2.inpaint(arr, mask, inpaintRadius=5, flags=method)
    return Image.fromarray(cv2.cvtColor(result, cv2.COLOR_BGR2RGB))


def remove_region_blur(img: Image.Image) -> Image.Image:
    """Fallback: blur region heavily."""
    w, h = img.size
    rw = random.randint(w // 8, w // 3)
    rh = random.randint(h // 8, h // 3)
    x = random.randint(0, w - rw)
    y = random.randint(0, h - rh)
    region = img.crop((x, y, x + rw, y + rh))
    blurred = region.filter(ImageFilter.GaussianBlur(radius=15))
    img.paste(blurred, (x, y))
    return img


def document_manipulation(img: Image.Image) -> Image.Image:
    """Modify text-like regions — whiteout + redraw fake text."""
    w, h = img.size
    draw = ImageDraw.Draw(img)

    for _ in range(random.randint(1, 4)):
        rw = random.randint(w // 8, w // 3)
        rh = random.randint(15, 40)
        x = random.randint(0, max(1, w - rw))
        y = random.randint(0, max(1, h - rh))

        # Sample background color
        try:
            bg_color = img.getpixel((min(x + rw + 5, w - 1), y + rh // 2))
        except Exception:
            bg_color = (255, 255, 255)

        draw.rectangle([x, y, x + rw, y + rh], fill=bg_color)

        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", rh - 4)
        except Exception:
            font = ImageFont.load_default()

        fake_text = random.choice([
            f"{random.randint(100, 9999)}.{random.randint(0, 99):02d}",
            f"{random.randint(1, 28):02d}.{random.randint(1, 12):02d}.{random.randint(2020, 2026)}",
            f"EUR {random.randint(50, 5000)},{random.randint(0, 99):02d}",
            f"#{random.randint(10000, 99999)}",
            f"HRK {random.randint(100, 50000)},{random.randint(0, 99):02d}",
            f"INV-{random.randint(1000, 9999)}",
        ])
        text_color = random.choice([(0, 0, 0), (30, 30, 30), (50, 50, 50)])
        draw.text((x + 2, y + 1), fake_text, fill=text_color, font=font)

    # Add slight noise
    arr = np.array(img).astype(np.float32)
    noise = np.random.normal(0, 2, arr.shape)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def color_exposure_edit(img: Image.Image) -> Image.Image:
    """Change color/exposure of a region with feathered mask."""
    w, h = img.size
    arr = np.array(img).astype(np.float32)

    rw = random.randint(w // 4, w // 2)
    rh = random.randint(h // 4, h // 2)
    x = random.randint(0, w - rw)
    y = random.randint(0, h - rh)

    region = arr[y:y + rh, x:x + rw].copy()

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
        shift = np.array([random.randint(-40, 40) for _ in range(3)])
        region = np.clip(region + shift, 0, 255)

    # Feathered mask
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


def clone_stamp_seamless(img: Image.Image) -> Image.Image:
    """Clone texture using seamlessClone with circular mask."""
    if cv2 is None:
        return clone_stamp_basic(img)

    arr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    h, w = arr.shape[:2]

    rw = random.randint(w // 8, w // 4)
    rh = random.randint(h // 8, h // 4)

    sx = random.randint(0, w - rw)
    sy = random.randint(0, h - rh)
    source = arr[sy:sy + rh, sx:sx + rw].copy()

    # Circular mask
    mask = np.zeros((rh, rw), dtype=np.uint8)
    cv2.circle(mask, (rw // 2, rh // 2), min(rw, rh) // 2 - 2, 255, -1)

    # Different destination
    dx = random.randint(rw // 2, max(rw // 2 + 1, w - rw // 2))
    dy = random.randint(rh // 2, max(rh // 2 + 1, h - rh // 2))

    try:
        result = cv2.seamlessClone(source, arr, mask, (dx, dy), cv2.NORMAL_CLONE)
        return Image.fromarray(cv2.cvtColor(result, cv2.COLOR_BGR2RGB))
    except Exception:
        return clone_stamp_basic(img)


def clone_stamp_basic(img: Image.Image) -> Image.Image:
    """Fallback clone stamp."""
    w, h = img.size
    arr = np.array(img)

    rw = random.randint(w // 8, w // 4)
    rh = random.randint(h // 8, h // 4)
    sx = random.randint(0, w - rw)
    sy = random.randint(0, h - rh)
    dx = random.randint(0, w - rw)
    dy = random.randint(0, h - rh)

    source = arr[sy:sy + rh, sx:sx + rw].copy()
    mask = np.zeros((rh, rw), dtype=np.float32)
    cy, cx = rh // 2, rw // 2
    for y in range(rh):
        for x in range(rw):
            dist = ((x - cx) / max(rw / 2, 1)) ** 2 + ((y - cy) / max(rh / 2, 1)) ** 2
            if dist < 1:
                mask[y, x] = max(0, 1 - dist)

    for c in range(3):
        arr[dy:dy + rh, dx:dx + rw, c] = (
            source[:, :, c] * mask + arr[dy:dy + rh, dx:dx + rw, c] * (1 - mask)
        ).astype(np.uint8)

    return Image.fromarray(arr)


def jpeg_ghost(img: Image.Image) -> Image.Image:
    """JPEG ghost: save region at different quality, paste into high-quality image."""
    w, h = img.size

    # Region to double-compress
    rw = random.randint(w // 4, w // 2)
    rh = random.randint(h // 4, h // 2)
    x = random.randint(0, w - rw)
    y = random.randint(0, h - rh)

    region = img.crop((x, y, x + rw, y + rh))

    # Save region at low quality
    buf = io.BytesIO()
    low_q = random.choice([30, 40, 50])
    region.save(buf, format="JPEG", quality=low_q)
    buf.seek(0)
    degraded = Image.open(buf).convert("RGB")

    # Paste back
    img.paste(degraded, (x, y))

    # Save full image at high quality
    buf2 = io.BytesIO()
    img.save(buf2, format="JPEG", quality=95)
    buf2.seek(0)
    return Image.open(buf2).convert("RGB")


def resize_artifact(img: Image.Image) -> Image.Image:
    """Upscale a small patch to create visible pixelization artifacts."""
    w, h = img.size

    # Small patch
    pw = random.randint(w // 8, w // 4)
    ph = random.randint(h // 8, h // 4)
    x = random.randint(0, w - pw)
    y = random.randint(0, h - ph)

    region = img.crop((x, y, x + pw, y + ph))

    # Downscale then upscale (creates artifacts)
    small = region.resize(
        (pw // random.randint(3, 5), ph // random.randint(3, 5)),
        Image.NEAREST,
    )
    upscaled = small.resize((pw, ph), Image.BICUBIC)

    # Blend edges
    arr = np.array(img)
    up_arr = np.array(upscaled)

    mask = np.ones((ph, pw), dtype=np.float32)
    fade = max(3, min(pw, ph) // 10)
    for i in range(fade):
        f = i / fade
        mask[i, :] *= f
        mask[-(i + 1), :] *= f
        mask[:, i] *= f
        mask[:, -(i + 1)] *= f

    for c in range(3):
        arr[y:y + ph, x:x + pw, c] = (
            up_arr[:, :, c] * mask + arr[y:y + ph, x:x + pw, c] * (1 - mask)
        ).astype(np.uint8)

    return Image.fromarray(arr)


def noise_injection(img: Image.Image) -> Image.Image:
    """Inject Gaussian noise into a specific region with feathered blending."""
    w, h = img.size
    arr = np.array(img).astype(np.float32)

    rw = random.randint(w // 5, w // 2)
    rh = random.randint(h // 5, h // 2)
    x = random.randint(0, w - rw)
    y = random.randint(0, h - rh)

    # Gaussian noise
    sigma = random.uniform(15, 40)
    noise = np.random.normal(0, sigma, (rh, rw, 3))

    # Feathered mask
    mask = np.ones((rh, rw, 1), dtype=np.float32)
    fade = max(5, min(rw, rh) // 6)
    for i in range(fade):
        f = i / fade
        mask[i, :] *= f
        mask[-(i + 1), :] *= f
        mask[:, i] *= f
        mask[:, -(i + 1)] *= f

    arr[y:y + rh, x:x + rw] = np.clip(
        arr[y:y + rh, x:x + rw] + noise * mask, 0, 255
    )

    return Image.fromarray(arr.astype(np.uint8))


# ── Method registry ──────────────────────────────────────────────────

TAMPER_METHODS = {
    "copy_move": {"fn": copy_move_seamless, "target": 800, "needs_pair": False},
    "splice": {"fn": splice_perspective, "target": 700, "needs_pair": True},
    "inpaint": {"fn": inpaint_removal, "target": 600, "needs_pair": False},
    "document": {"fn": document_manipulation, "target": 500, "needs_pair": False},
    "color_exposure": {"fn": color_exposure_edit, "target": 400, "needs_pair": False},
    "clone_stamp": {"fn": clone_stamp_seamless, "target": 300, "needs_pair": False},
    "jpeg_ghost": {"fn": jpeg_ghost, "target": 200, "needs_pair": False},
    "resize_artifact": {"fn": resize_artifact, "target": 200, "needs_pair": False},
    "noise_injection": {"fn": noise_injection, "target": 300, "needs_pair": False},
}
# CASIA v2 (500) and SD inpainting (1000) handled separately


# ── S3 helpers ───────────────────────────────────────────────────────

def load_authentic_images_s3(
    s3, bucket: str, prefix: str, limit: int = 500
) -> list[tuple[str, bytes]]:
    """Load a random sample of authentic images from S3 into RAM.

    Only downloads `limit` images (not all) to keep RAM usage low.
    All processing stays in RAM — no local disk files.
    """
    # First list all keys
    all_keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.lower().endswith((".jpg", ".jpeg", ".png")) and not key.endswith("labels.csv"):
                all_keys.append(key)

    print(f"  Found {len(all_keys)} authentic images on S3", flush=True)

    # Random sample to keep RAM usage reasonable
    if len(all_keys) > limit:
        random.shuffle(all_keys)
        all_keys = all_keys[:limit]

    print(f"  Downloading {len(all_keys)} images to RAM...", flush=True)
    images = []
    for i, key in enumerate(all_keys):
        try:
            resp = s3.get_object(Bucket=bucket, Key=key)
            data = resp["Body"].read()
            images.append((os.path.basename(key), data))
            if (i + 1) % 100 == 0:
                print(f"    [{i + 1}/{len(all_keys)}] loaded", flush=True)
        except Exception:
            continue

    print(f"  Loaded {len(images)} authentic images into RAM", flush=True)
    return images


def load_existing_records(s3, bucket: str, prefix: str) -> list[dict]:
    """Load existing labels.csv for resume."""
    try:
        resp = s3.get_object(Bucket=bucket, Key=f"{prefix}/labels.csv")
        content = resp["Body"].read().decode()
        return [dict(row) for row in csv.DictReader(io.StringIO(content))]
    except Exception:
        return []


def save_labels(records: list[dict], s3, bucket: str, prefix: str):
    """Save labels.csv to S3."""
    csv_buf = io.StringIO()
    writer = csv.DictWriter(
        csv_buf,
        fieldnames=["filename", "ground_truth", "method", "source"],
    )
    writer.writeheader()
    for rec in records:
        writer.writerow({
            "filename": rec.get("filename", ""),
            "ground_truth": rec.get("ground_truth", "tampered"),
            "method": rec.get("method", ""),
            "source": rec.get("source", ""),
        })
    s3.put_object(
        Bucket=bucket,
        Key=f"{prefix}/labels.csv",
        Body=csv_buf.getvalue().encode(),
        ContentType="text/csv",
    )


# ── CASIA v2 download ───────────────────────────────────────────────

def download_casia_v2(
    s3, bucket: str, prefix: str, target: int, existing_count: int,
) -> list[dict]:
    """Download tampered images from CASIA v2 dataset on HuggingFace."""
    remaining = target - existing_count
    if remaining <= 0:
        print(f"  CASIA v2: SKIP (already {existing_count}/{target})")
        return []

    print(f"  CASIA v2: downloading {remaining} tampered images...")

    try:
        from datasets import load_dataset
        ds = load_dataset("HuimingLi/CASIA2.0", trust_remote_code=True)
    except Exception as e:
        print(f"  CASIA v2 load failed: {e}")
        # Fallback: try alternative CASIA dataset names
        try:
            from datasets import load_dataset
            ds = load_dataset("namtranase/CASIA2", trust_remote_code=True)
        except Exception as e2:
            print(f"  CASIA v2 fallback also failed: {e2}")
            return []

    records = []
    count = 0

    for split_name in ds:
        if count >= remaining:
            break
        split = ds[split_name]
        for item in split:
            if count >= remaining:
                break

            try:
                # Check if tampered (label varies by dataset)
                label = item.get("label", item.get("Label", 1))
                if label == 0:  # authentic, skip
                    continue

                img = None
                for key in ["image", "Image", "img"]:
                    if key in item and item[key] is not None:
                        val = item[key]
                        if isinstance(val, Image.Image):
                            img = val
                        elif isinstance(val, bytes):
                            img = Image.open(io.BytesIO(val))
                        break

                if img is None:
                    continue

                img = img.convert("RGB")
                w, h = img.size
                if min(w, h) < 128:
                    continue
                if max(w, h) > 1024:
                    ratio = 1024 / max(w, h)
                    img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=90)
                jpeg_bytes = buf.getvalue()

                if len(jpeg_bytes) < 3000:
                    continue

                filename = f"{uuid.uuid4().hex[:12]}.jpg"
                s3.put_object(
                    Bucket=bucket,
                    Key=f"{prefix}/{filename}",
                    Body=jpeg_bytes,
                    ContentType="image/jpeg",
                    Metadata={"method": "casia_v2", "source": "casia"},
                )

                records.append({
                    "filename": filename,
                    "ground_truth": "tampered",
                    "method": "casia_v2",
                    "source": "casia",
                })
                count += 1

                if count % 100 == 0:
                    print(f"    CASIA v2: [{count}/{remaining}]")

            except Exception:
                continue

    print(f"  CASIA v2: downloaded {count}")
    return records


# ── SD Inpainting (GPU) ─────────────────────────────────────────────

def sd_inpaint_batch(
    s3, bucket: str, prefix: str, auth_images: list[tuple[str, bytes]],
    target: int, existing_count: int,
) -> list[dict]:
    """Generate SD-inpainted tampered images on GPU."""
    remaining = target - existing_count
    if remaining <= 0:
        print(f"  SD Inpainting: SKIP (already {existing_count}/{target})")
        return []

    print(f"  SD Inpainting: generating {remaining} images...")

    try:
        import torch
        from diffusers import StableDiffusionInpaintPipeline

        pipe = StableDiffusionInpaintPipeline.from_pretrained(
            "runwayml/stable-diffusion-inpainting",
            torch_dtype=torch.float16,
        )
        pipe.to("cuda")
    except Exception as e:
        print(f"  SD Inpainting load failed: {e}")
        return []

    records = []
    count = 0
    errors = 0

    inpaint_prompts = [
        "clean undamaged surface",
        "smooth car paint",
        "repaired wall surface",
        "new clean material",
        "pristine condition",
        "fixed and restored",
        "undamaged area",
        "clean background",
    ]

    for i in range(remaining + 50):
        if count >= remaining:
            break

        try:
            _, img_bytes = random.choice(auth_images)
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            w, h = img.size

            # Resize to 512 for SD inpainting
            img_512 = img.resize((512, 512), Image.LANCZOS)

            # Random mask (20-40% of image)
            mask = Image.new("L", (512, 512), 0)
            draw = ImageDraw.Draw(mask)
            cx = random.randint(128, 384)
            cy = random.randint(128, 384)
            rx = random.randint(40, 120)
            ry = random.randint(40, 120)
            draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=255)
            mask = mask.filter(ImageFilter.GaussianBlur(radius=10))

            prompt = random.choice(inpaint_prompts)

            import torch
            with torch.no_grad():
                result = pipe(
                    prompt=prompt,
                    image=img_512,
                    mask_image=mask,
                    num_inference_steps=30,
                    guidance_scale=7.5,
                ).images[0]

            # Resize back to original
            result = result.resize((w, h), Image.LANCZOS)

            buf = io.BytesIO()
            result.save(buf, format="JPEG", quality=90)
            jpeg_bytes = buf.getvalue()

            filename = f"{uuid.uuid4().hex[:12]}.jpg"
            s3.put_object(
                Bucket=bucket,
                Key=f"{prefix}/{filename}",
                Body=jpeg_bytes,
                ContentType="image/jpeg",
                Metadata={"method": "sd_inpaint", "source": "sd_inpaint"},
            )

            records.append({
                "filename": filename,
                "ground_truth": "tampered",
                "method": "sd_inpaint",
                "source": "sd_inpaint",
            })
            count += 1

            if count % 50 == 0:
                print(f"    SD Inpaint: [{count}/{remaining}]")

        except Exception as e:
            errors += 1
            if errors <= 5:
                print(f"    SD Inpaint error: {e}")
            continue

    import torch
    del pipe
    torch.cuda.empty_cache()

    print(f"  SD Inpainting: generated {count} ({errors} errors)")
    return records


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Create tampered insurance images")
    parser.add_argument("--bucket", default="dent-calibration-data")
    parser.add_argument("--authentic-prefix", default="raw_v8/authentic")
    parser.add_argument("--output-prefix", default="raw_v8/tampered")
    parser.add_argument("--target", type=int, default=5500)
    parser.add_argument("--region", default="eu-central-1")
    parser.add_argument("--resume", action="store_true", help="Resume from existing S3 data")
    parser.add_argument(
        "--mode", default="all",
        choices=["all", "programmatic", "casia", "sd-inpaint"],
        help="Which tampering modes to run",
    )
    args = parser.parse_args()

    if boto3 is None:
        print("ERROR: pip install boto3")
        sys.exit(1)

    s3 = boto3.client("s3", region_name=args.region)

    # Resume
    all_records = load_existing_records(s3, args.bucket, args.output_prefix) if args.resume else []
    existing_counts = {}
    for r in all_records:
        m = r.get("method", "unknown")
        existing_counts[m] = existing_counts.get(m, 0) + 1

    print(f"Target: {args.target} tampered images")
    print(f"Existing: {len(all_records)} ({existing_counts})")

    # Load authentic images
    print("\nLoading authentic images from S3...")
    auth_images = load_authentic_images_s3(
        s3, args.bucket, args.authentic_prefix
    )

    if len(auth_images) < 10:
        print("ERROR: Need at least 10 authentic images")
        sys.exit(1)

    # Scale targets
    total_base = sum(m["target"] for m in TAMPER_METHODS.values()) + 500 + 1000  # +CASIA +SD
    scale = args.target / total_base if total_base > 0 else 1.0

    # ── Programmatic tampering ────────────────────────────────────
    if args.mode in ("all", "programmatic"):
        for method_name, method_cfg in TAMPER_METHODS.items():
            method_target = int(method_cfg["target"] * scale)
            existing = existing_counts.get(method_name, 0)

            if existing >= method_target:
                print(f"\n  {method_name}: SKIP ({existing}/{method_target})")
                continue

            remaining = method_target - existing
            print(f"\n  {method_name}: generating {remaining} (target: {method_target})")

            count = 0
            errors = 0

            for _ in range(remaining + 30):
                if count >= remaining:
                    break

                try:
                    _, img_bytes = random.choice(auth_images)
                    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")

                    if method_cfg["needs_pair"]:
                        _, img2_bytes = random.choice(auth_images)
                        img2 = Image.open(io.BytesIO(img2_bytes)).convert("RGB")
                        tampered = method_cfg["fn"](img, img2)
                    else:
                        tampered = method_cfg["fn"](img)

                    # Resize if needed
                    w, h = tampered.size
                    if max(w, h) > 1024:
                        ratio = 1024 / max(w, h)
                        tampered = tampered.resize(
                            (int(w * ratio), int(h * ratio)), Image.LANCZOS
                        )

                    buf = io.BytesIO()
                    quality = random.choice([80, 85, 90, 90, 95])
                    tampered.save(buf, format="JPEG", quality=quality)
                    jpeg_bytes = buf.getvalue()

                    if len(jpeg_bytes) < 3000:
                        continue

                    filename = f"{uuid.uuid4().hex[:12]}.jpg"
                    s3.put_object(
                        Bucket=args.bucket,
                        Key=f"{args.output_prefix}/{filename}",
                        Body=jpeg_bytes,
                        ContentType="image/jpeg",
                        Metadata={"method": method_name},
                    )

                    all_records.append({
                        "filename": filename,
                        "ground_truth": "tampered",
                        "method": method_name,
                        "source": "programmatic",
                    })
                    count += 1

                except Exception as e:
                    errors += 1
                    if errors <= 3:
                        print(f"    Error ({method_name}): {e}")
                    continue

            print(f"    {method_name}: +{count} ({errors} errors)")

            # Save incrementally
            save_labels(all_records, s3, args.bucket, args.output_prefix)

    # ── CASIA v2 ──────────────────────────────────────────────────
    if args.mode in ("all", "casia"):
        casia_target = int(500 * scale)
        casia_existing = existing_counts.get("casia_v2", 0)
        casia_records = download_casia_v2(
            s3, args.bucket, args.output_prefix, casia_target, casia_existing,
        )
        all_records.extend(casia_records)
        save_labels(all_records, s3, args.bucket, args.output_prefix)

    # ── SD Inpainting (GPU) ───────────────────────────────────────
    if args.mode in ("all", "sd-inpaint"):
        sd_target = int(1000 * scale)
        sd_existing = existing_counts.get("sd_inpaint", 0)
        sd_records = sd_inpaint_batch(
            s3, args.bucket, args.output_prefix, auth_images,
            sd_target, sd_existing,
        )
        all_records.extend(sd_records)
        save_labels(all_records, s3, args.bucket, args.output_prefix)

    # ── Summary ───────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"DONE: {len(all_records)} tampered images")
    method_counts = {}
    for r in all_records:
        m = r.get("method", "unknown")
        method_counts[m] = method_counts.get(m, 0) + 1
    for m, c in sorted(method_counts.items()):
        print(f"  {m}: {c}")
    print(f"\nAll images at: s3://{args.bucket}/{args.output_prefix}/")


if __name__ == "__main__":
    main()
