#!/bin/bash
set -e

echo "==========================================="
echo "  DENT Full Calibration Pipeline"
echo "==========================================="
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

DATA_DIR="${1:-data}"
API_URL="${2:-http://localhost:8000}"

IMAGES_DIR="$DATA_DIR/calibration_images"
LABELS_FILE="$DATA_DIR/labels.csv"
DATASET_FILE="$DATA_DIR/labeled_dataset.jsonl"
THRESHOLDS_FILE="config/calibrated_thresholds.json"
META_WEIGHTS_FILE="models/stacking_meta/meta_weights.npz"

# Validate inputs
if [ ! -d "$IMAGES_DIR" ]; then
    echo "ERROR: Images directory not found: $IMAGES_DIR"
    echo ""
    echo "Please create it with calibration images:"
    echo "  mkdir -p $IMAGES_DIR"
    echo "  # Add 100+ real photos and 100+ AI-generated images"
    echo ""
    echo "Then create labels CSV:"
    echo "  echo 'filename,ground_truth' > $LABELS_FILE"
    echo "  echo 'real_car1.jpg,authentic' >> $LABELS_FILE"
    echo "  echo 'ai_car1.png,manipulated' >> $LABELS_FILE"
    exit 1
fi

IMAGE_COUNT=$(find "$IMAGES_DIR" -type f \( -name "*.jpg" -o -name "*.jpeg" -o -name "*.png" -o -name "*.webp" \) | wc -l | tr -d ' ')
echo "Found $IMAGE_COUNT images in $IMAGES_DIR"

if [ "$IMAGE_COUNT" -lt 20 ]; then
    echo "WARNING: Only $IMAGE_COUNT images. Recommend 200+ for stable calibration."
fi

# Step 1: Build dataset
echo ""
echo "--- Step 1: Building calibration dataset ---"
python3 -m scripts.build_calibration_dataset \
    --images-dir "$IMAGES_DIR" \
    --labels "$LABELS_FILE" \
    --output "$DATASET_FILE" \
    --api-url "$API_URL"

SAMPLE_COUNT=$(wc -l < "$DATASET_FILE" | tr -d ' ')
echo "Dataset: $SAMPLE_COUNT samples"

if [ "$SAMPLE_COUNT" -lt 10 ]; then
    echo "ERROR: Too few samples ($SAMPLE_COUNT). Need at least 10."
    exit 1
fi

# Step 2: GHOST threshold calibration
echo ""
echo "--- Step 2: GHOST threshold calibration ---"
mkdir -p "$(dirname "$THRESHOLDS_FILE")"
python3 -m scripts.calibrate_ghost \
    --data "$DATASET_FILE" \
    --tiers 1,2 \
    --output "$THRESHOLDS_FILE"

echo "Thresholds saved to: $THRESHOLDS_FILE"

# Step 3: Stacking meta-learner training
echo ""
echo "--- Step 3: Training stacking meta-learner ---"
mkdir -p "$(dirname "$META_WEIGHTS_FILE")"
python3 -m scripts.train_stacking_meta \
    --data "$DATASET_FILE" \
    --output "$META_WEIGHTS_FILE" \
    --compare

echo "Meta-learner weights saved to: $META_WEIGHTS_FILE"

# Summary
echo ""
echo "==========================================="
echo "  Calibration Complete!"
echo "==========================================="
echo ""
echo "Outputs:"
echo "  $THRESHOLDS_FILE"
echo "  $META_WEIGHTS_FILE"
echo ""
echo "To deploy:"
echo "  1. Copy $THRESHOLDS_FILE to server /app/config/"
echo "  2. Copy $META_WEIGHTS_FILE to server /app/models/stacking_meta/"
echo "  3. Set env vars:"
echo "     DENT_FORENSICS_CALIBRATION_FILE=/app/config/calibrated_thresholds.json"
echo "     DENT_FORENSICS_STACKING_META_ENABLED=true"
echo "     DENT_FORENSICS_STACKING_META_WEIGHTS=/app/models/stacking_meta/meta_weights.npz"
echo "  4. Restart ML service"
