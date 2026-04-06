#!/usr/bin/env python3
"""Local end-to-end test for all forensic modules.

Processes an image through each analyzer sequentially (avoids threading
deadlocks with transformers) and shows scores + fusion result.

Usage:
    python -m scripts.test_local path/to/image.jpg
    python -m scripts.test_local --url https://example.com/image.jpg
    python -m scripts.test_local --generate-ai   # test with synthetic AI-like image
    python -m scripts.test_local --generate-auth  # test with synthetic photo-like image
"""

import argparse
import asyncio
import io
import logging
import os
import sys
import time

os.environ.setdefault("DENT_FORENSICS_MODEL_CACHE_DIR", "/tmp/dent_models")
os.makedirs(os.environ["DENT_FORENSICS_MODEL_CACHE_DIR"], exist_ok=True)

import numpy as np
from PIL import Image, ImageFilter

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s: %(message)s",
)

# Module configs: (name, class_path, needs_model_download)
ANALYZERS = [
    ("pixel_forensics", "app.forensics.analyzers.pixel_forensics", "PixelForensicsAnalyzer", False),
    ("aide_detection", "app.forensics.analyzers.aide_detection", "AIDEAnalyzer", False),
    ("metadata_analysis", "app.forensics.analyzers.metadata", "MetadataAnalyzer", False),
    ("modification_detection", "app.forensics.analyzers.modification", "ModificationAnalyzer", False),
    ("clip_ai_detection", "app.forensics.analyzers.clip_ai_detection", "ClipAiDetectionAnalyzer", True),
    ("dinov2_ai_detection", "app.forensics.analyzers.dinov2_ai_detection", "DINOv2AiDetectionAnalyzer", True),
    ("radet_detection", "app.forensics.analyzers.radet_detection", "RADetAnalyzer", True),
    ("fatformer_detection", "app.forensics.analyzers.fatformer_detection", "FatFormerAnalyzer", True),
    ("safe_ai_detection", "app.forensics.analyzers.safe_ai_detection", "SAFEAiDetectionAnalyzer", True),
    ("organika_ai_detection", "app.forensics.analyzers.organika_detection", "OrganikaDetectionAnalyzer", True),
]


def generate_ai_image() -> bytes:
    """Generate a synthetic AI-like image (smooth gradients, clean)."""
    arr = np.zeros((512, 512, 3), dtype=np.uint8)
    for y in range(512):
        for x in range(512):
            arr[y, x] = [
                int(80 + 150 * (x / 512)),
                int(60 + 140 * (y / 512)),
                int(100 + 100 * ((x + y) / 1024)),
            ]
    img = Image.fromarray(arr)
    img = img.filter(ImageFilter.GaussianBlur(radius=0.5))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_auth_image() -> bytes:
    """Generate a synthetic authentic-like image (noisy, JPEG artifacts)."""
    np.random.seed(42)
    # Base natural-looking noise
    noise = np.random.normal(128, 35, (512, 512, 3)).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(noise)
    img = img.filter(ImageFilter.GaussianBlur(radius=1.2))
    # Save as JPEG (adds real compression artifacts)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=72)
    return buf.getvalue()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image", nargs="?", help="Path to image file")
    parser.add_argument("--url", help="URL to download image from")
    parser.add_argument("--generate-ai", action="store_true", help="Use synthetic AI-like image")
    parser.add_argument("--generate-auth", action="store_true", help="Use synthetic photo-like image")
    parser.add_argument("--skip-downloads", action="store_true", help="Skip modules needing model downloads")
    args = parser.parse_args()

    # Get image bytes
    if args.generate_ai:
        print("Using synthetic AI-like image (smooth gradients)")
        img_bytes = generate_ai_image()
        filename = "synthetic_ai.png"
    elif args.generate_auth:
        print("Using synthetic photo-like image (noisy, JPEG)")
        img_bytes = generate_auth_image()
        filename = "synthetic_photo.jpg"
    elif args.url:
        import urllib.request
        print(f"Downloading {args.url}")
        img_bytes = urllib.request.urlopen(args.url).read()
        filename = args.url.split("/")[-1].split("?")[0] or "downloaded.jpg"
    elif args.image:
        with open(args.image, "rb") as f:
            img_bytes = f.read()
        filename = os.path.basename(args.image)
    else:
        print("Provide an image path, --url, --generate-ai, or --generate-auth")
        sys.exit(1)

    img = Image.open(io.BytesIO(img_bytes))
    print(f"Image: {filename} ({img.size[0]}x{img.size[1]}, {len(img_bytes)} bytes)")
    print()

    # Run each analyzer sequentially
    results = {}
    total_time = 0

    for mod_name, mod_path, class_name, needs_download in ANALYZERS:
        if args.skip_downloads and needs_download:
            print(f"  {mod_name:30s}  SKIPPED (needs model download)")
            continue

        try:
            # Dynamic import
            module = __import__(mod_path, fromlist=[class_name])
            cls = getattr(module, class_name)
            analyzer = cls()

            start = time.time()
            result = asyncio.run(analyzer.analyze_image(img_bytes, filename))
            elapsed = time.time() - start
            total_time += elapsed

            err = ""
            if result.error:
                err = f" ERR: {str(result.error)[:60]}"

            findings_str = ""
            if result.findings:
                codes = [f.code for f in result.findings]
                findings_str = f" [{', '.join(codes)}]"

            print(f"  {mod_name:30s}  score={result.risk_score:.4f}  ({elapsed:.1f}s){err}{findings_str}")
            results[mod_name] = result

        except Exception as e:
            print(f"  {mod_name:30s}  FAILED: {e}")

    # Run fusion
    print(f"\n{'='*60}")
    print(f"Total analysis time: {total_time:.1f}s")

    if results:
        try:
            from app.forensics.fusion import fuse_scores
            from app.forensics.base import ModuleResult

            module_list = list(results.values())
            overall, overall_100, risk_level, verdict_probs = fuse_scores(module_list)
            print(f"\nFUSION RESULT:")
            print(f"  Overall risk: {overall:.4f} ({overall_100}%)")
            print(f"  Risk level:   {risk_level.value}")
            if verdict_probs:
                print(f"  Verdict:      authentic={verdict_probs['authentic']:.2f}  "
                      f"ai_generated={verdict_probs['ai_generated']:.2f}  "
                      f"tampered={verdict_probs['tampered']:.2f}")
        except Exception as e:
            print(f"\nFusion error: {e}")


if __name__ == "__main__":
    main()
