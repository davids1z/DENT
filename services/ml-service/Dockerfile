FROM python:3.12-slim

# System dependencies for Pillow, python-magic, pyexiftool, opencv
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    libimage-exiftool-perl \
    libgl1 \
    libglib2.0-0 \
    fonts-dejavu-core \
    git \
    build-essential \
    libjpeg-dev \
    tesseract-ocr \
    tesseract-ocr-hrv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install PyTorch CPU separately (large layer, cached independently)
RUN pip install --no-cache-dir \
    torch>=2.2.0 torchvision --index-url https://download.pytorch.org/whl/cpu

# Install PhotoHolmes from GitHub (not on PyPI yet) for CNN tampering detection
RUN pip install --no-cache-dir "photoholmes @ git+https://github.com/photoholmes/photoholmes.git" || true

# Install Transformers for AI-generated image detection (Swin Transformer classifiers)
RUN pip install --no-cache-dir transformers>=4.36.0

# Install Diffusers for VAE reconstruction error detection (separate layer for caching)
RUN pip install --no-cache-dir diffusers>=0.27.0

# gdown for reliable Google Drive model weight downloads (CatNet weights)
RUN pip install --no-cache-dir gdown>=5.0.0

# timm for Community Forensics ViT-Small (CVPR 2025) + future Mesorch
RUN pip install --no-cache-dir timm>=1.0.0 safetensors>=0.4.0

# ONNX Runtime for 2-3x faster CPU inference (separate layer for caching)
RUN pip install --no-cache-dir onnxruntime>=1.17.0

# OpenAI CLIP for RINE AI detection (ECCV 2024) — uses OpenAI's CLIP
# implementation, NOT HuggingFace transformers CLIP (numerically different)
RUN pip install --no-cache-dir "clip @ git+https://github.com/openai/CLIP.git"

# pytorch_wavelets for SAFE AI detector DWT preprocessing
RUN pip install --no-cache-dir pytorch-wavelets>=1.3.0

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage probe weights so entrypoint.sh can copy them into the volume
RUN mkdir -p /app/models/clip_ai /app/models_stage/clip_ai \
            /app/models/dinov2 /app/models_stage/dinov2
COPY models/clip_ai/probe_weights.npz /app/models/clip_ai/probe_weights.npz
COPY models/clip_ai/probe_weights.npz /app/models_stage/clip_ai/probe_weights.npz
COPY models/dinov2/dinov2_probe_weights.npz /app/models/dinov2/dinov2_probe_weights.npz
COPY models/dinov2/dinov2_probe_weights.npz /app/models_stage/dinov2/dinov2_probe_weights.npz

# Stage meta-learner GBM + LogReg weights
RUN mkdir -p /app/models/stacking_meta /app/models_stage/stacking_meta
COPY models/meta/gbm_binary.joblib /app/models/stacking_meta/gbm_binary.joblib
COPY models/meta/gbm_multi.joblib /app/models/stacking_meta/gbm_multi.joblib
COPY models/meta/meta_weights.npz /app/models/stacking_meta/meta_weights.npz
COPY models/meta/gbm_meta.json /app/models/stacking_meta/gbm_meta.json
COPY models/meta/gbm_binary.joblib /app/models_stage/stacking_meta/gbm_binary.joblib
COPY models/meta/gbm_multi.joblib /app/models_stage/stacking_meta/gbm_multi.joblib
COPY models/meta/meta_weights.npz /app/models_stage/stacking_meta/meta_weights.npz
COPY models/meta/gbm_meta.json /app/models_stage/stacking_meta/gbm_meta.json

# RINE checkpoint (ECCV 2024, 25MB)
RUN mkdir -p /app/models/rine
COPY models/rine/model_4class_trainable.pth /app/models/rine/model_4class_trainable.pth

COPY app/ app/
COPY scripts/ scripts/
COPY gunicorn.conf.py /app/gunicorn.conf.py
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
# Use uvicorn directly — gunicorn heartbeat kills async workers during
# long-running analyses (known UvicornWorker + gunicorn issue).
# Models loaded at startup via FastAPI lifespan in app/main.py.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "300", "--log-level", "info"]
