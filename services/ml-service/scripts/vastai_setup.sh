#!/bin/bash
# DENT Calibration v8 — vast.ai one-shot setup and run
# Modules match production: CLIP, CommFor, EfficientNet, SAFE, DINOv2, B-Free, SPAI, Mesorch, PRNU
# Usage: ssh root@host 'bash -s' < vastai_setup.sh [WORKER_ID] [TOTAL_WORKERS]
set -e

WORKER_ID=${1:-0}
TOTAL_WORKERS=${2:-3}
BUCKET="dent-calibration-data"
AWS_KEY="${AWS_ACCESS_KEY_ID:?Set AWS_ACCESS_KEY_ID before running}"
AWS_SECRET="${AWS_SECRET_ACCESS_KEY:?Set AWS_SECRET_ACCESS_KEY before running}"

echo "=== DENT Calibration v8 Setup (Worker $WORKER_ID/$TOTAL_WORKERS) ==="
echo "=== Step 1: System deps ==="
apt-get update -qq && apt-get install -y -qq libmagic1 git tesseract-ocr 2>&1 | tail -1

echo "=== Step 2: Clone repo ==="
cd /root
rm -rf DENT
git clone --depth 1 https://github.com/davids1z/DENT.git 2>&1 | tail -1
cd DENT/services/ml-service

echo "=== Step 3: Python deps ==="
pip install -r requirements.txt 2>&1 | tail -1
pip install timm safetensors transformers diffusers gdown boto3 tqdm pydantic-settings huggingface_hub 2>&1 | tail -1
pip install "photoholmes @ git+https://github.com/photoholmes/photoholmes.git" 2>&1 | tail -1

echo "=== Step 4: AWS credentials ==="
mkdir -p /root/.aws
cat > /root/.aws/credentials << EOF
[default]
aws_access_key_id = $AWS_KEY
aws_secret_access_key = $AWS_SECRET
region = eu-central-1
EOF

echo "=== Step 5: Verify GPU ==="
python3 -c "import torch; print(f'PyTorch {torch.__version__}, CUDA: {torch.cuda.is_available()}, GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"NONE\"}')"

echo "=== Step 6: Verify S3 ==="
python3 -c "import boto3; s3=boto3.client('s3',region_name='eu-central-1'); r=s3.list_objects_v2(Bucket='$BUCKET',Prefix='train_v7/',MaxKeys=3); print(f'S3 OK: {len(r.get(\"Contents\",[]))} objects in train_v7/')"

echo "=== Step 7: Download SPAI model from S3 (~560MB) ==="
mkdir -p models/spai
python3 -c "
import boto3
s3 = boto3.client('s3', region_name='eu-central-1')
s3.download_file('$BUCKET', 'models/spai_full.pt', 'models/spai/spai_full.pt')
print('SPAI model downloaded')
" || echo "WARNING: SPAI download failed (will run without SPAI)"

echo "=== Step 8: Download B-Free model from S3 ==="
mkdir -p models/bfree
python3 -c "
import boto3
s3 = boto3.client('s3', region_name='eu-central-1')
s3.download_file('$BUCKET', 'models/bfree/model_epoch_best.pth', 'models/bfree/model_epoch_best.pth')
print('B-Free model downloaded')
" || echo "WARNING: B-Free download failed (will run without B-Free)"

echo "=== Step 9: Verify probe weights (from git clone) ==="
ls -la models/clip_ai/probe_weights.npz models/dinov2/dinov2_probe_weights.npz 2>/dev/null || echo "WARNING: probe weights missing"

echo "=== Step 10: Start calibration ==="
python3 -m scripts.fast_calibration \
    --bucket $BUCKET \
    --output data/labeled_dataset_w${WORKER_ID}.jsonl \
    --worker-id $WORKER_ID \
    --total-workers $TOTAL_WORKERS \
    --resume

echo "=== DONE: Worker $WORKER_ID complete ==="
wc -l data/labeled_dataset_w${WORKER_ID}.jsonl
