#!/bin/bash
# DENT v8 — vast.ai GPU generation script
# Generates AI images (local models) + SD inpainted tampered images
#
# Prerequisites:
#   - vast.ai GPU instance (24GB+ VRAM recommended, 16GB minimum)
#   - AWS credentials: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
#
# Usage:
#   ssh root@host 'bash -s' < vastai_generate.sh
#
# Or on the instance:
#   cd /root/DENT/services/ml-service
#   bash scripts/vastai_generate.sh

set -e

BUCKET="dent-calibration-data"
AWS_KEY="${AWS_ACCESS_KEY_ID:?Set AWS_ACCESS_KEY_ID before running}"
AWS_SECRET="${AWS_SECRET_ACCESS_KEY:?Set AWS_SECRET_ACCESS_KEY before running}"

echo "========================================"
echo "  DENT v8 — vast.ai AI Generation"
echo "========================================"
echo ""

# ── Step 1: System deps ──────────────────────────────────────────
echo "=== Step 1: System dependencies ==="
apt-get update -qq && apt-get install -y -qq libmagic1 git 2>&1 | tail -1

# ── Step 2: Clone repo ───────────────────────────────────────────
echo "=== Step 2: Clone repo ==="
cd /root
if [ -d "DENT" ]; then
    cd DENT && git pull 2>&1 | tail -1
    cd services/ml-service
else
    git clone --depth 1 https://github.com/davids1z/DENT.git 2>&1 | tail -1
    cd DENT/services/ml-service
fi

# ── Step 3: Python deps ──────────────────────────────────────────
echo "=== Step 3: Python dependencies ==="
pip install -q boto3 pillow numpy opencv-python-headless 2>&1 | tail -1
pip install -q torch torchvision --index-url https://download.pytorch.org/whl/cu121 2>&1 | tail -1
pip install -q diffusers transformers accelerate safetensors sentencepiece protobuf 2>&1 | tail -1
pip install -q datasets imagehash 2>&1 | tail -1

# ── Step 4: AWS credentials ──────────────────────────────────────
echo "=== Step 4: AWS credentials ==="
mkdir -p /root/.aws
cat > /root/.aws/credentials << EOF
[default]
aws_access_key_id = $AWS_KEY
aws_secret_access_key = $AWS_SECRET
region = eu-central-1
EOF

# ── Step 5: Verify GPU ───────────────────────────────────────────
echo "=== Step 5: Verify GPU ==="
python3 -c "
import torch
print(f'PyTorch {torch.__version__}')
print(f'CUDA: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
    print(f'VRAM: {torch.cuda.get_device_properties(0).total_mem / 1e9:.1f} GB')
"

# ── Step 6: Verify S3 ────────────────────────────────────────────
echo "=== Step 6: Verify S3 ==="
python3 -c "
import boto3
s3 = boto3.client('s3', region_name='eu-central-1')
r = s3.list_objects_v2(Bucket='$BUCKET', Prefix='raw_v8/', MaxKeys=5)
count = len(r.get('Contents', []))
print(f'S3 OK: {count} objects in raw_v8/')
"

# ── Step 7: Generate AI images (local models) ────────────────────
echo ""
echo "========================================"
echo "  Phase 1: Local AI Generation (2,200)"
echo "========================================"
echo ""
python3 -m scripts.generate_insurance_ai \
    --mode local \
    --target 2200 \
    --bucket $BUCKET \
    --output-prefix raw_v8/ai_generated \
    --resume

# ── Step 8: SD Inpainting tampered images ─────────────────────────
echo ""
echo "========================================"
echo "  Phase 2: SD Inpainting Tampered (1,000)"
echo "========================================"
echo ""
python3 -m scripts.create_insurance_tampered \
    --mode sd-inpaint \
    --target 1000 \
    --bucket $BUCKET \
    --authentic-prefix raw_v8/authentic \
    --output-prefix raw_v8/tampered \
    --resume

# ── Step 9: Summary ──────────────────────────────────────────────
echo ""
echo "========================================"
echo "  DONE: vast.ai Generation Complete"
echo "========================================"
echo ""
python3 -c "
import boto3
s3 = boto3.client('s3', region_name='eu-central-1')
for cls in ['authentic', 'ai_generated', 'tampered']:
    prefix = f'raw_v8/{cls}/'
    count = 0
    paginator = s3.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket='$BUCKET', Prefix=prefix):
        for obj in page.get('Contents', []):
            if obj['Key'].endswith(('.jpg', '.jpeg', '.png')):
                count += 1
    print(f'  {cls}: {count} images')
"
echo ""
echo "Next: run quality filter, sanitize, augment, then calibrate"
