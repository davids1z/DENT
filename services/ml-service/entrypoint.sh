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

# ── Ensure probe weights are in the volume ───────────────────────────
if [ -f "/app/models_stage/clip_ai/probe_weights.npz" ] && [ ! -f "/app/models/clip_ai/probe_weights.npz" ]; then
    echo "[entrypoint] Copying CLIP probe weights to volume"
    mkdir -p /app/models/clip_ai
    cp /app/models_stage/clip_ai/probe_weights.npz /app/models/clip_ai/probe_weights.npz
fi

echo "[entrypoint] Starting uvicorn..."
exec "$@"
