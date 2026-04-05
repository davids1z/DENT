#!/bin/sh
set -e

# ── First-run model downloads ────────────────────────────────────────
# Models are persisted in the ml_models Docker volume at /app/models.
# HF_HUB_OFFLINE=1 is set in docker-compose to skip version checks on
# subsequent starts.  On first run we temporarily disable it to
# download models that haven't been cached yet.

download_if_missing() {
    cache_dir="$1"
    model_id="$2"
    download_script="$3"

    # Check for HuggingFace cache structure (models--org--name dirs)
    if ls "$cache_dir"/models--* 1>/dev/null 2>&1; then
        echo "[entrypoint] $model_id already cached"
        return 0
    fi

    echo "[entrypoint] Downloading $model_id to $cache_dir ..."
    mkdir -p "$cache_dir"
    HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 python -c "$download_script" \
        && echo "[entrypoint] $model_id cached successfully" \
        || echo "[entrypoint] WARNING: failed to download $model_id (module will degrade gracefully)"
}

# CLIP ViT-L/14 for AI image detection (~1.7 GB)
download_if_missing "/app/models/clip_ai" "openai/clip-vit-large-patch14" "
from transformers import CLIPModel, CLIPProcessor
d = '/app/models/clip_ai'
CLIPProcessor.from_pretrained('openai/clip-vit-large-patch14', cache_dir=d)
CLIPModel.from_pretrained('openai/clip-vit-large-patch14', cache_dir=d)
"

# Stable Diffusion VAE for reconstruction error detection (~335 MB)
download_if_missing "/app/models/vae_recon" "stabilityai/sd-vae-ft-mse" "
from diffusers import AutoencoderKL
AutoencoderKL.from_pretrained('stabilityai/sd-vae-ft-mse', cache_dir='/app/models/vae_recon')
"

# Text AI detection models: RoBERTa classifier (~500 MB) + DistilGPT-2 (~80 MB)
download_if_missing "/app/models/text_ai" "fakespot-ai/roberta-base-ai-text-detection-v1" "
from transformers import pipeline, AutoModelForCausalLM, AutoTokenizer
d = '/app/models/text_ai'
pipeline('text-classification', model='fakespot-ai/roberta-base-ai-text-detection-v1', model_kwargs={'cache_dir': d})
AutoTokenizer.from_pretrained('distilgpt2', cache_dir=d)
AutoModelForCausalLM.from_pretrained('distilgpt2', cache_dir=d)
"

# Community Forensics ViT-Small (CVPR 2025, ~87 MB safetensors)
download_if_missing "/app/models/community_forensics" "OwensLab/commfor-model-384" "
from huggingface_hub import snapshot_download
snapshot_download('OwensLab/commfor-model-384', cache_dir='/app/models/community_forensics')
"

# NPR CVPR 2024 weights (~6 MB from GitHub — tiny!)
npr_path="/app/models/npr/NPR.pth"
if [ ! -f "$npr_path" ]; then
    echo "[entrypoint] Downloading NPR weights (~6 MB)..."
    mkdir -p "$(dirname "$npr_path")"
    python3 -c "
import urllib.request, sys
try:
    urllib.request.urlretrieve(
        'https://github.com/chuangchuangtan/NPR-DeepfakeDetection/raw/main/NPR.pth',
        '$npr_path'
    )
    print('[entrypoint] NPR weights downloaded')
except Exception as e:
    print(f'[entrypoint] WARNING: NPR download failed: {e}', file=sys.stderr)
" || true
else
    echo "[entrypoint] NPR weights already cached"
fi

# Mesorch AAAI 2025 weights (~976 MB from Google Drive)
mesorch_path="/app/models/cnn/mesorch/mesorch-98.pth"
if [ ! -f "$mesorch_path" ]; then
    echo "[entrypoint] Downloading Mesorch weights (~976 MB)..."
    mkdir -p "$(dirname "$mesorch_path")"
    python3 -c "
import sys, os
try:
    import gdown
    gdown.download(id='1PJxKteinMyaAYokKy0JhuzBnBc6bGsau', output='$mesorch_path', quiet=False)
    # If gdown downloaded an archive, try to extract .pth from it
    if os.path.exists('$mesorch_path'):
        import zipfile
        if zipfile.is_zipfile('$mesorch_path'):
            import shutil, tempfile
            tmp = tempfile.mkdtemp()
            with zipfile.ZipFile('$mesorch_path') as z:
                z.extractall(tmp)
            for root, dirs, files in os.walk(tmp):
                for f in files:
                    if f.endswith('.pth'):
                        shutil.copy(os.path.join(root, f), '$mesorch_path')
                        break
            shutil.rmtree(tmp, ignore_errors=True)
    print('[entrypoint] Mesorch weights downloaded')
except Exception as e:
    print(f'[entrypoint] WARNING: Mesorch download failed: {e}', file=sys.stderr)
" || true
else
    echo "[entrypoint] Mesorch weights already cached"
fi

# ── CNN forensics model weights (PhotoHolmes: CatNet + TruFor) ────────
# These are NOT on HuggingFace — downloaded from original author servers.
catnet_path="/app/models/cnn/catnet/weights.pth"
if [ ! -f "$catnet_path" ]; then
    echo "[entrypoint] Downloading CatNet weights (~110 MB)..."
    mkdir -p "$(dirname "$catnet_path")"
    python3 -c "
import sys
try:
    import gdown
    gdown.download(id='1tyOKVdx6UMys2OcNpUj9r6scxNIpcoLE', output='$catnet_path', quiet=False)
    print('[entrypoint] CatNet weights downloaded')
except Exception as e:
    print(f'[entrypoint] WARNING: CatNet download failed: {e}', file=sys.stderr)
" || true
else
    echo "[entrypoint] CatNet weights already cached"
fi

trufor_path="/app/models/cnn/trufor/trufor.pth.tar"
if [ ! -f "$trufor_path" ]; then
    echo "[entrypoint] Downloading TruFor weights (~200 MB)..."
    mkdir -p "$(dirname "$trufor_path")"
    python3 -c "
import urllib.request, zipfile, shutil, os, sys
try:
    urllib.request.urlretrieve(
        'https://www.grip.unina.it/download/prog/TruFor/TruFor_weights.zip',
        '/tmp/trufor_weights.zip'
    )
    with zipfile.ZipFile('/tmp/trufor_weights.zip') as z:
        z.extractall('/tmp/trufor_extract')
    # Find the weights file in the extracted archive
    for root, dirs, files in os.walk('/tmp/trufor_extract'):
        for f in files:
            if f.endswith('.pth.tar') or f.endswith('.pth'):
                shutil.copy(os.path.join(root, f), '$trufor_path')
                break
    shutil.rmtree('/tmp/trufor_extract', ignore_errors=True)
    os.remove('/tmp/trufor_weights.zip')
    print('[entrypoint] TruFor weights downloaded')
except Exception as e:
    print(f'[entrypoint] WARNING: TruFor download failed: {e}', file=sys.stderr)
    for p in ['/tmp/trufor_extract', '/tmp/trufor_weights.zip']:
        try:
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        except: pass
" || true
else
    echo "[entrypoint] TruFor weights already cached"
fi

# ── Always update probe weights from staged copies ───────────────────
# Force-copy ensures new Docker builds always deploy new probe weights,
# even when the persistent volume already has older versions cached.
if [ -f "/app/models_stage/clip_ai/probe_weights.npz" ]; then
    echo "[entrypoint] Updating CLIP probe weights"
    mkdir -p /app/models/clip_ai
    cp -f /app/models_stage/clip_ai/probe_weights.npz /app/models/clip_ai/probe_weights.npz
fi

if [ -f "/app/models_stage/dinov2/dinov2_probe_weights.npz" ]; then
    echo "[entrypoint] Updating DINOv2 probe weights"
    mkdir -p /app/models/dinov2
    cp -f /app/models_stage/dinov2/dinov2_probe_weights.npz /app/models/dinov2/dinov2_probe_weights.npz
fi

if [ -f "/app/models_stage/stacking_meta/gbm_binary.joblib" ]; then
    echo "[entrypoint] Updating meta-learner GBM weights"
    mkdir -p /app/models/stacking_meta
    cp -f /app/models_stage/stacking_meta/gbm_binary.joblib /app/models/stacking_meta/gbm_binary.joblib
    cp -f /app/models_stage/stacking_meta/gbm_multi.joblib /app/models/stacking_meta/gbm_multi.joblib
    cp -f /app/models_stage/stacking_meta/meta_weights.npz /app/models/stacking_meta/meta_weights.npz
    # Module order validation sidecar (generated by updated training script)
    if [ -f "/app/models_stage/stacking_meta/gbm_meta.json" ]; then
        cp -f /app/models_stage/stacking_meta/gbm_meta.json /app/models/stacking_meta/gbm_meta.json
    fi
fi

# EfficientNet-B4 AI detector (~75 MB, public HuggingFace repo)
efficientnet_path="/app/models/efficientnet_ai/pytorch_model.pth"
if [ ! -f "$efficientnet_path" ]; then
    echo "[entrypoint] Downloading EfficientNet-B4 AI detector (~75 MB)..."
    mkdir -p "$(dirname "$efficientnet_path")"
    HF_HUB_OFFLINE=0 python3 -c "
from huggingface_hub import hf_hub_download
hf_hub_download('Dafilab/ai-image-detector', 'pytorch_model.pth',
                local_dir='/app/models/efficientnet_ai')
" || echo "[entrypoint] WARNING: EfficientNet download failed"
else
    echo "[entrypoint] EfficientNet-B4 already cached"
fi

# SPAI TorchScript model (~560 MB, CPU-traced, from S3)
spai_path="/app/models/spai/spai_full.pt"
if [ ! -f "$spai_path" ]; then
    echo "[entrypoint] Downloading SPAI TorchScript model (~560 MB)..."
    mkdir -p "$(dirname "$spai_path")"
    python3 -c "
import sys, os
try:
    import boto3
    s3 = boto3.client('s3', region_name='eu-central-1')
    s3.download_file('dent-calibration-data', 'models/spai_full_cpu.pt', '$spai_path')
    size = os.path.getsize('$spai_path')
    print(f'[entrypoint] SPAI model downloaded ({size/1e6:.0f} MB)')
except Exception as e:
    print(f'[entrypoint] WARNING: SPAI download failed: {e}', file=sys.stderr)
" || true
else
    echo "[entrypoint] SPAI model already cached"
fi

# SAFE AI detector (~6 MB, GitHub)
safe_path="/app/models/safe_ai/checkpoint-best.pth"
if [ ! -f "$safe_path" ]; then
    echo "[entrypoint] Downloading SAFE checkpoint (~6 MB)..."
    mkdir -p "$(dirname "$safe_path")"
    python3 -c "
import urllib.request, sys
try:
    urllib.request.urlretrieve(
        'https://raw.githubusercontent.com/Ouxiang-Li/SAFE/main/checkpoint/checkpoint-best.pth',
        '$safe_path'
    )
    print('[entrypoint] SAFE checkpoint downloaded')
except Exception as e:
    print(f'[entrypoint] WARNING: SAFE download failed: {e}', file=sys.stderr)
" || true
else
    echo "[entrypoint] SAFE checkpoint already cached"
fi

# OpenAI CLIP ViT-L/14 for RINE AI detection (~890 MB, cached in volume)
# Separate from HuggingFace CLIP — different package, different cache location.
# clip.load() uses download_root param, default ~/.cache/clip/
rine_clip_path="/app/models/clip_openai/ViT-L-14.pt"
if [ ! -f "$rine_clip_path" ]; then
    echo "[entrypoint] Downloading OpenAI CLIP ViT-L/14 for RINE (~890 MB)..."
    mkdir -p "$(dirname "$rine_clip_path")"
    python3 -c "
import sys
try:
    import clip
    clip.load('ViT-L/14', device='cpu', jit=False, download_root='/app/models/clip_openai')
    print('[entrypoint] OpenAI CLIP ViT-L/14 downloaded')
except Exception as e:
    print(f'[entrypoint] WARNING: OpenAI CLIP download failed: {e}', file=sys.stderr)
" || true
else
    echo "[entrypoint] OpenAI CLIP ViT-L/14 already cached"
fi

# ── ONNX export (one-time, cached in volume) ─────────────────────────
# Converts PyTorch models to ONNX for 2-3x faster CPU inference.
# Only runs if ONNX files don't exist yet. Safe to skip on failure.
clip_onnx="/app/models/clip_ai/clip_vision.onnx"
dinov2_onnx="/app/models/dinov2/dinov2.onnx"
if [ ! -f "$clip_onnx" ] || [ ! -f "$dinov2_onnx" ]; then
    echo "[entrypoint] Exporting models to ONNX (one-time)..."
    python3 /app/scripts/export_onnx.py --models-dir /app/models || \
        echo "[entrypoint] WARNING: ONNX export failed (will use PyTorch fallback)"
else
    echo "[entrypoint] ONNX models already cached"
fi

echo "[entrypoint] Starting server (workers=${DENT_UVICORN_WORKERS:-2})..."
exec "$@"
