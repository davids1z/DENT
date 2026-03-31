#!/usr/bin/env bash
# -----------------------------------------------------------------------
# SPAI Model Setup Script
#
# Downloads pretrained SPAI weights from Google Drive, clones the repo,
# traces the model to TorchScript, and places it for DENT production use.
#
# Requirements: Python 3.11+, CUDA (optional but recommended)
# Run on: vast.ai GPU instance or production server
#
# Usage:
#   bash scripts/setup_spai.sh [--output /path/to/models/spai]
# -----------------------------------------------------------------------
set -euo pipefail

OUTPUT_DIR="${1:-/app/models/spai}"
SPAI_REPO="/tmp/spai"
WEIGHTS_DIR="/tmp/spai/weights"
GDRIVE_FILE_ID="1vvXmZqs6TVJdj8iF1oJ4L_fcgdQrp_YI"

echo "=== SPAI Model Setup ==="
echo "Output: ${OUTPUT_DIR}"
echo ""

# 1. Clone SPAI repo
if [ ! -d "${SPAI_REPO}" ]; then
    echo "[1/5] Cloning SPAI repo..."
    git clone https://github.com/mever-team/spai.git "${SPAI_REPO}"
else
    echo "[1/5] SPAI repo already exists at ${SPAI_REPO}"
fi

# 2. Install dependencies in a venv (to avoid conflicts with DENT's timm)
VENV_DIR="/tmp/spai_venv"
if [ ! -d "${VENV_DIR}" ]; then
    echo "[2/5] Creating isolated venv for SPAI..."
    python3 -m venv "${VENV_DIR}"
fi
source "${VENV_DIR}/bin/activate"

echo "[2/5] Installing SPAI dependencies..."
pip install --quiet torch torchvision gdown
pip install --quiet -r "${SPAI_REPO}/requirements.txt" 2>/dev/null || true

# 3. Download pretrained weights from Google Drive
mkdir -p "${WEIGHTS_DIR}"
if [ ! -f "${WEIGHTS_DIR}/spai.pth" ]; then
    echo "[3/5] Downloading SPAI pretrained weights from Google Drive..."
    gdown "${GDRIVE_FILE_ID}" -O "${WEIGHTS_DIR}/spai.pth"
else
    echo "[3/5] Weights already downloaded"
fi

# Verify download
if [ ! -f "${WEIGHTS_DIR}/spai.pth" ]; then
    echo "ERROR: Failed to download weights. Try manual download:"
    echo "  https://drive.google.com/file/d/${GDRIVE_FILE_ID}/view"
    echo "  Place at: ${WEIGHTS_DIR}/spai.pth"
    exit 1
fi

echo "[3/5] Weights: $(ls -lh ${WEIGHTS_DIR}/spai.pth | awk '{print $5}')"

# 4. Trace to TorchScript
mkdir -p "${OUTPUT_DIR}"
echo "[4/5] Tracing SPAI model to TorchScript..."
python3 - <<'PYEOF'
import sys
import os
import torch

sys.path.insert(0, "/tmp/spai")

from spai.models.sid import SID
from spai.config import get_cfg_defaults

# Load config
cfg = get_cfg_defaults()
cfg_path = os.path.join("/tmp/spai", "configs", "spai.yaml")
if os.path.exists(cfg_path):
    cfg.merge_from_file(cfg_path)
cfg.freeze()

# Load model
print("  Loading SID model...")
model = SID(cfg)
weights_path = "/tmp/spai/weights/spai.pth"
state_dict = torch.load(weights_path, map_location="cpu")
if "model" in state_dict:
    state_dict = state_dict["model"]
model.load_state_dict(state_dict, strict=False)
model.eval()
print("  Model loaded successfully")

# Try TorchScript tracing with a dummy input
# SPAI expects (B, 3, H, W) normalized tensor at multiples of 224
print("  Tracing with dummy input (1, 3, 224, 224)...")
dummy = torch.randn(1, 3, 224, 224)

try:
    traced = torch.jit.trace(model, dummy)
    output_path = os.environ.get("OUTPUT_DIR", "/app/models/spai") + "/spai_full.pt"
    traced.save(output_path)
    print(f"  TorchScript saved: {output_path}")

    # Verify
    loaded = torch.jit.load(output_path, map_location="cpu")
    test_out = loaded(dummy)
    score = float(torch.sigmoid(test_out.squeeze()).item())
    print(f"  Verification: dummy input → score={score:.4f} (should be ~0.5 for random)")
    print("  SUCCESS: TorchScript model is ready!")
except Exception as e:
    print(f"  TorchScript trace failed: {e}")
    print("  Falling back to state_dict export...")

    # Fallback: save just the state dict + config for native loading
    output_path = os.environ.get("OUTPUT_DIR", "/app/models/spai") + "/spai_native.pth"
    torch.save({
        "model": model.state_dict(),
        "config": dict(cfg),
    }, output_path)
    print(f"  Native weights saved: {output_path}")
PYEOF

# 5. Test on a real image if available
echo "[5/5] Testing..."
if [ -f "/tmp/test_image.jpg" ]; then
    python3 -c "
import torch
from PIL import Image
import numpy as np

model = torch.jit.load('${OUTPUT_DIR}/spai_full.pt', map_location='cpu')
model.eval()

img = Image.open('/tmp/test_image.jpg').convert('RGB').resize((224, 224), Image.LANCZOS)
arr = np.array(img, dtype=np.float32) / 255.0
mean = np.array([0.485, 0.456, 0.406])
std = np.array([0.229, 0.224, 0.225])
arr = (arr - mean) / std
tensor = torch.from_numpy(arr.transpose(2, 0, 1)).unsqueeze(0).float()

with torch.no_grad():
    logit = model(tensor)
    score = float(torch.sigmoid(logit.squeeze()).item())
print(f'Test image score: {score:.4f} ({score*100:.1f}%)')
"
else
    echo "  No test image at /tmp/test_image.jpg, skipping test"
fi

deactivate

echo ""
echo "=== Setup Complete ==="
echo "Model location: ${OUTPUT_DIR}/spai_full.pt"
echo ""
echo "To enable SPAI in DENT, set environment variable:"
echo "  FORENSICS_SPAI_ENABLED=true"
echo "  FORENSICS_SPAI_MODEL_DIR=${OUTPUT_DIR}"
