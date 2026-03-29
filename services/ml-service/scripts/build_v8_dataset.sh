#!/bin/bash
# DENT v8 Insurance-Domain Dataset Builder
# 15,000 images: 5K authentic + 5K AI + 5K tampered
#
# Usage:
#   cd services/ml-service
#   bash scripts/build_v8_dataset.sh
#
# Requirements:
#   pip install icrawler boto3 pillow opencv-python-headless numpy
#   AWS credentials configured

set -e
BUCKET="dent-calibration-data"

echo "=== DENT v8 Dataset Builder ==="
echo "Target: 15,000 insurance-domain images (5K per class)"
echo ""

# Step 1: Download authentic insurance images (Bing image search, no API key)
echo "=== Step 1/5: Authentic images (5,000) ==="
python3 -m scripts.download_insurance_authentic \
    --bucket $BUCKET \
    --output-prefix raw_v8/authentic \
    --target 5000

# Step 2: Generate AI images (OpenFake for closed-source generators)
echo "=== Step 2/5: AI images — OpenFake (3,000) ==="
python3 -m scripts.generate_insurance_ai \
    --mode openfake \
    --target 3000 \
    --bucket $BUCKET \
    --output-prefix raw_v8/ai_generated

# Step 2b: Generate AI images locally (run on vast.ai GPU separately)
# python3 -m scripts.generate_insurance_ai --mode local --target 2000 ...
echo "NOTE: For local AI generation (2K more), run on vast.ai GPU:"
echo "  python3 -m scripts.generate_insurance_ai --mode local --target 2000"

# Step 3: Create tampered images from authentic set
echo "=== Step 3/5: Tampered images (5,000) ==="
python3 -m scripts.create_insurance_tampered \
    --bucket $BUCKET \
    --authentic-prefix raw_v8/authentic \
    --output-prefix raw_v8/tampered \
    --target 5000

# Step 4: Sanitize (strip EXIF, random names, unified labels.csv)
echo "=== Step 4/5: Sanitize ==="
python3 -m scripts.prepare_calibration_dataset \
    --bucket $BUCKET \
    --raw-prefix raw_v8 \
    --out-prefix train_v8

# Step 5: Augment (WebP + JPEG + phone quality)
echo "=== Step 5/5: Augment ==="
python3 -m scripts.augment_webp \
    --bucket $BUCKET --prefix train_v8 --output train_v8_aug
python3 -m scripts.augment_jpeg_resize \
    --bucket $BUCKET --prefix train_v8_aug --output train_v8_aug
python3 -m scripts.augment_phone_quality \
    --bucket $BUCKET --prefix train_v8_aug --output train_v8_aug

echo ""
echo "=== DONE ==="
echo "Next steps:"
echo "  1. Run calibration on vast.ai (3 workers)"
echo "  2. Train meta-learner: python3 -m scripts.train_stacking_meta --data data/labeled_dataset_v8.jsonl"
echo "  3. Deploy meta weights to production"
