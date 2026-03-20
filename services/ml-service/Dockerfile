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

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage probe weights so entrypoint.sh can copy them into the volume
RUN mkdir -p /app/models/clip_ai /app/models_stage/clip_ai
COPY models/clip_ai/probe_weights.npz /app/models/clip_ai/probe_weights.npz
COPY models/clip_ai/probe_weights.npz /app/models_stage/clip_ai/probe_weights.npz

COPY app/ app/
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
