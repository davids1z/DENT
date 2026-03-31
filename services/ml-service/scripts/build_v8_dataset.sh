#!/bin/bash
# DENT v8 Insurance-Domain Dataset Builder
# 15,000+ images: 5.5K authentic + 5.5K AI + 5.5K tampered
# ALL data on S3. All scripts support --resume.
#
# Pipeline:
#   1. Download authentic (HuggingFace + icrawler Bing) → S3
#   2. Download AI from OpenFake/JourneyDB → S3
#   3. Create tampered (programmatic + CASIA v2) → S3
#   4. Quality filter (blur/dedup/validate) → S3
#   5. Sanitize (strip EXIF, random names, labels.csv) → S3
#   6. Augment (WebP + JPEG + phone quality) → S3
#
# NOTE: Local AI generation (Step 2b) and SD inpainting (Step 3b)
#       must run on vast.ai GPU — see vastai_generate.sh
#
# Usage:
#   cd services/ml-service
#   bash scripts/build_v8_dataset.sh
#
# Requirements:
#   pip install icrawler boto3 pillow opencv-python-headless numpy datasets imagehash
#   AWS credentials configured

set -euo pipefail

BUCKET="dent-calibration-data"

echo "============================================================"
echo "  DENT v8 Insurance-Domain Dataset Builder"
echo "============================================================"
echo "  Target: 15,000+ images (5.5K per class)"
echo "  All data stored on S3: s3://$BUCKET/raw_v8/"
echo "  All scripts support --resume for interrupted runs"
echo ""

# ── Step 1: Download authentic insurance images ──────────────────
echo "=== Step 1/8: Authentic images (5,500) ==="
echo "  Sources: CarDD, SROIE, CORD (HuggingFace) + Bing image search"
python3 -m scripts.download_insurance_authentic \
    --bucket $BUCKET \
    --output-prefix raw_v8/authentic \
    --target 5500 \
    --resume

# ── Step 2a: Download AI images from OpenFake/JourneyDB ─────────
echo ""
echo "=== Step 2a/8: AI images — OpenFake + JourneyDB (3,300) ==="
python3 -m scripts.generate_insurance_ai \
    --mode openfake \
    --target 3300 \
    --bucket $BUCKET \
    --output-prefix raw_v8/ai_generated \
    --resume

# ── Step 2b: Local AI generation (vast.ai GPU) ──────────────────
echo ""
echo "NOTE: Local AI generation (2,200 images from 15 models) requires GPU."
echo "  Run on vast.ai: bash scripts/vastai_generate.sh"
echo "  This also generates SD inpainting tampered images."

# ── Step 3: Create tampered images (programmatic + CASIA v2) ─────
echo ""
echo "=== Step 3/8: Tampered images — programmatic + CASIA (4,500) ==="
python3 -m scripts.create_insurance_tampered \
    --bucket $BUCKET \
    --authentic-prefix raw_v8/authentic \
    --output-prefix raw_v8/tampered \
    --target 4500 \
    --mode programmatic \
    --resume

echo ""
echo "=== Step 3b/8: Tampered images — CASIA v2 (500) ==="
python3 -m scripts.create_insurance_tampered \
    --bucket $BUCKET \
    --authentic-prefix raw_v8/authentic \
    --output-prefix raw_v8/tampered \
    --target 500 \
    --mode casia \
    --resume

# ── Step 4: Quality filter ───────────────────────────────────────
echo ""
echo "=== Step 4/8: Quality filter (blur/dedup/validate) ==="
for CLASS in authentic ai_generated tampered; do
    echo "  Filtering: $CLASS"
    python3 -m scripts.quality_filter \
        --bucket $BUCKET \
        --prefix raw_v8/$CLASS
done

# ── Step 5: Sanitize (strip EXIF, random names, labels.csv) ─────
echo ""
echo "=== Step 5/8: Sanitize ==="
python3 -m scripts.prepare_calibration_dataset \
    --bucket $BUCKET \
    --raw-prefix raw_v8 \
    --out-prefix train_v8

# ── Step 6: Augment — WebP ───────────────────────────────────────
echo ""
echo "=== Step 6/8: WebP augmentation ==="
python3 -m scripts.augment_webp \
    --bucket $BUCKET \
    --input-prefix train_v8 \
    --output-prefix train_v8_aug \
    --qualities 60,75,85,95

# ── Step 7: Augment — JPEG + resize ─────────────────────────────
echo ""
echo "=== Step 7/8: JPEG + resize augmentation ==="
python3 -m scripts.augment_jpeg_resize \
    --bucket $BUCKET \
    --prefix train_v8_aug \
    --jpeg-qualities 50,70 \
    --resize-widths 800,1080

# ── Step 8: Augment — Phone quality (authentic only) ─────────────
echo ""
echo "=== Step 8/8: Phone quality augmentation ==="
python3 -m scripts.augment_phone_quality \
    --bucket $BUCKET \
    --prefix train_v8_aug \
    --sample-rate 0.3

# ── Summary ──────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo "  Dataset v8 Ready!"
echo "============================================================"
echo ""
echo "  Raw:       s3://$BUCKET/raw_v8/"
echo "  Sanitized: s3://$BUCKET/train_v8/"
echo "  Augmented: s3://$BUCKET/train_v8_aug/"
echo ""
echo "Next steps:"
echo "  1. If not done: run vastai_generate.sh for local AI + SD inpainting"
echo "  2. Calibrate on vast.ai (3 workers):"
echo "     ssh root@host 'bash -s' < scripts/vastai_setup.sh 0 3"
echo "     ssh root@host 'bash -s' < scripts/vastai_setup.sh 1 3"
echo "     ssh root@host 'bash -s' < scripts/vastai_setup.sh 2 3"
echo ""
echo "  3. Train meta-learner:"
echo "     cat data/labeled_dataset_w*.jsonl > data/labeled_dataset_v8.jsonl"
echo "     python3 -m scripts.train_stacking_meta --data data/labeled_dataset_v8.jsonl"
echo ""
echo "  4. Deploy: commit meta_weights.npz + push"
