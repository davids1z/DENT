FROM python:3.12-slim

# System dependencies for Pillow, python-magic, pyexiftool, opencv
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    libimage-exiftool-perl \
    libgl1 \
    libglib2.0-0 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install PyTorch CPU separately (large layer, cached independently)
RUN pip install --no-cache-dir \
    torch>=2.2.0 --index-url https://download.pytorch.org/whl/cpu

# Install PhotoHolmes (depends on torch, may not be available on all platforms)
RUN pip install --no-cache-dir photoholmes>=1.0.0 || true

# Install Transformers for AI-generated image detection (Swin Transformer classifiers)
RUN pip install --no-cache-dir transformers>=4.36.0 || true

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create model cache directory and copy pre-trained probe weights
RUN mkdir -p /app/models/clip_ai
COPY models/clip_ai/probe_weights.npz /app/models/clip_ai/probe_weights.npz

COPY app/ app/

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
