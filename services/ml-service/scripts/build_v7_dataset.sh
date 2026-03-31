#!/bin/bash
# Build v7 training dataset: download → sanitize → augment → train probes
#
# Prerequisites:
#   - AWS credentials configured (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
#   - pip install datasets boto3 Pillow numpy tqdm scikit-learn
#   - For probe training: torch, transformers (run on vast.ai GPU)
#
# Total: ~14,000 base images → ~70,000+ with all augmentations
#   AI generated:  ~4400 (OpenFake 12 generators + Gemini)
#   Authentic:     ~6000 (COCO + ImageNet)
#   Tampered:      ~4000 (CASIA v2 + auto copy-move/splice)
#
# Augmentations: WebP (4 qualities) + JPEG (2 qualities) + resize (2 widths) + phone noise
#
# Usage:
#   cd /root/DENT/services/ml-service
#   bash scripts/build_v7_dataset.sh

set -euo pipefail

BUCKET="dent-calibration-data"
REGION="eu-central-1"

echo "============================================================"
echo "  DENT v7 Dataset Build Pipeline"
echo "============================================================"
echo ""

# ── Step 1: Download AI images from OpenFake ─────────────────────
echo "[1/7] Downloading AI images from OpenFake (HuggingFace)..."
echo "  Target: ~3400 images from 12 generators"
python3 -m scripts.download_openfake \
    --bucket "$BUCKET" \
    --per-model 400

# ── Step 2: Download authentic + tampered images ─────────────────
echo ""
echo "[2/7] Downloading authentic images (COCO + ImageNet)..."
python3 -m scripts.download_real_tampered \
    --bucket "$BUCKET" \
    --category authentic \
    --limit 5000

echo ""
echo "[3/7] Downloading tampered images (CASIA + auto-generated)..."
python3 -m scripts.download_real_tampered \
    --bucket "$BUCKET" \
    --category tampered \
    --limit 3000

# ── Step 3: Sanitize dataset ────────────────────────────────────
echo ""
echo "[4/7] Sanitizing dataset (strip EXIF, random names, labels.csv)..."
python3 -m scripts.prepare_calibration_dataset \
    --bucket "$BUCKET" \
    --raw-prefix raw \
    --out-prefix train_v7

# ── Step 4: WebP augmentation ───────────────────────────────────
echo ""
echo "[5/7] Creating WebP augmented copies..."
python3 -m scripts.augment_webp \
    --bucket "$BUCKET" \
    --input-prefix train_v7 \
    --output-prefix train_v7_webp \
    --qualities 60,75,85,95

# ── Step 5: JPEG + resize augmentation ──────────────────────────
echo ""
echo "[6/7] Adding JPEG + social-media resize augmentation..."
python3 -m scripts.augment_jpeg_resize \
    --bucket "$BUCKET" \
    --prefix train_v7_webp \
    --jpeg-qualities 50,70 \
    --resize-widths 800,1080

# ── Step 6: Phone-quality augmentation (authentic only) ─────────
echo ""
echo "[7/7] Adding phone-quality noise to authentic images..."
python3 -m scripts.augment_phone_quality \
    --bucket "$BUCKET" \
    --prefix train_v7_webp \
    --sample-rate 0.3

echo ""
echo "============================================================"
echo "  Dataset v7 ready!"
echo "============================================================"
echo ""
echo "  Base:      s3://$BUCKET/train_v7/"
echo "  Augmented: s3://$BUCKET/train_v7_webp/"
echo ""
echo "Next: train MLP probes on vast.ai GPU:"
echo "  python3 -m scripts.train_clip_probe \\"
echo "    --bucket $BUCKET --s3-prefix train_v7_webp"
echo ""
echo "  python3 -m scripts.train_dinov2_probe \\"
echo "    --bucket $BUCKET --s3-prefix train_v7_webp"
