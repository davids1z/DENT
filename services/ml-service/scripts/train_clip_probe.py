#!/usr/bin/env python3
"""
Train a CLIP linear probe for AI image detection.

Usage:
    # Auto-download dataset from HuggingFace (easiest):
    python scripts/train_clip_probe.py --auto-download

    # With custom sample count:
    python scripts/train_clip_probe.py --auto-download --num-samples 500

    # Manual folders:
    python scripts/train_clip_probe.py --real <real_dir> --ai <ai_dir>

Requires:
    - CLIP model (auto-downloaded on first run)
    - For --auto-download: `pip install datasets` (HuggingFace datasets library)

Output:
    probe_weights.npz containing weights (768,) and bias (scalar)
    for sigmoid(w . x + b) classification on L2-normalised CLIP embeddings.

The output file is placed in the CLIP model cache directory by default
so the ClipAiDetectionAnalyzer picks it up automatically.
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# Auto-download from HuggingFace
# ---------------------------------------------------------------------------

def auto_download_dataset(num_samples: int, tmp_dir: str) -> tuple[str, str]:
    """
    Download real and AI-generated images from public HuggingFace datasets.
    - Real images: CIFAR-10 test set (real photographs)
    - AI images: InfImagine/FakeImageDataset (SD, IF, etc.)
    Returns (real_dir, ai_dir) paths.
    """
    try:
        from datasets import load_dataset
    except ImportError:
        print("Error: `datasets` library required for --auto-download.")
        print("Install with: pip install datasets")
        sys.exit(1)

    real_dir = os.path.join(tmp_dir, "real")
    ai_dir = os.path.join(tmp_dir, "ai")
    os.makedirs(real_dir, exist_ok=True)
    os.makedirs(ai_dir, exist_ok=True)

    # --- Real images from CIFAR-10 ---
    print(f"Downloading {num_samples} real images (CIFAR-10)...")
    ds_real = load_dataset("cifar10", split="test", streaming=True)
    real_count = 0
    for sample in ds_real:
        if real_count >= num_samples:
            break
        img = sample["img"]
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(os.path.join(real_dir, f"real_{real_count:04d}.png"))
        real_count += 1
        if real_count % 50 == 0:
            print(f"  {real_count}/{num_samples} real images...")
    print(f"  Done: {real_count} real images\n")

    # --- AI images from FakeImageDataset ---
    print(f"Downloading {num_samples} AI images (InfImagine/FakeImageDataset)...")
    ds_ai = load_dataset("InfImagine/FakeImageDataset", split="train", streaming=True)
    ai_count = 0
    for sample in ds_ai:
        if ai_count >= num_samples:
            break
        img = sample["png"]
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(os.path.join(ai_dir, f"ai_{ai_count:04d}.png"))
        ai_count += 1
        if ai_count % 50 == 0:
            print(f"  {ai_count}/{num_samples} AI images...")
    print(f"  Done: {ai_count} AI images\n")

    if real_count < 10 or ai_count < 10:
        print("Error: Not enough images downloaded.")
        sys.exit(1)

    return real_dir, ai_dir


# ---------------------------------------------------------------------------
# CLIP embedding extraction
# ---------------------------------------------------------------------------

def extract_embeddings(image_dir: str, processor, model, torch) -> np.ndarray:
    """Extract L2-normalised CLIP embeddings for all images in a directory."""
    supported = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
    paths = sorted(
        p for p in Path(image_dir).iterdir()
        if p.suffix.lower() in supported
    )

    if not paths:
        print(f"  No images found in {image_dir}")
        sys.exit(1)

    embeddings = []
    for i, p in enumerate(paths):
        try:
            img = Image.open(p).convert("RGB")
            inputs = processor(images=img, return_tensors="pt")
            with torch.no_grad():
                feat = model.get_image_features(**inputs)
            emb = feat[0].cpu().numpy()
            norm = np.linalg.norm(emb)
            if norm > 0:
                emb = emb / norm
            embeddings.append(emb)
            if (i + 1) % 20 == 0 or i == len(paths) - 1:
                print(f"  {i + 1}/{len(paths)} processed")
        except Exception as e:
            print(f"  Skipping {p.name}: {e}")

    return np.array(embeddings)


# ---------------------------------------------------------------------------
# Logistic regression (numpy-only, no sklearn needed)
# ---------------------------------------------------------------------------

def train_logistic_regression(
    X: np.ndarray,
    y: np.ndarray,
    lr: float = 0.1,
    epochs: int = 1000,
    reg: float = 0.01,
) -> tuple[np.ndarray, float]:
    """
    Train binary logistic regression via gradient descent.
    X: (N, D) normalised features
    y: (N,) labels — 0=real, 1=AI
    Returns (weights, bias).
    """
    n, d = X.shape
    w = np.zeros(d)
    b = 0.0

    for epoch in range(epochs):
        logits = X @ w + b
        # Numerically stable sigmoid
        probs = 1.0 / (1.0 + np.exp(-np.clip(logits, -500, 500)))

        # Gradients
        diff = probs - y
        grad_w = (X.T @ diff) / n + reg * w
        grad_b = diff.mean()

        w -= lr * grad_w
        b -= lr * grad_b

        if (epoch + 1) % 200 == 0:
            loss = -np.mean(y * np.log(probs + 1e-8) + (1 - y) * np.log(1 - probs + 1e-8))
            acc = ((probs > 0.5) == y).mean()
            print(f"  Epoch {epoch + 1}/{epochs} — loss: {loss:.4f}, acc: {acc:.1%}")

    return w, b


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Train CLIP linear probe for AI detection")
    parser.add_argument("--real", default=None, help="Directory of real photographs")
    parser.add_argument("--ai", default=None, help="Directory of AI-generated images")
    parser.add_argument("--auto-download", action="store_true",
                        help="Auto-download CIFAKE dataset from HuggingFace")
    parser.add_argument("--num-samples", type=int, default=200,
                        help="Images per class when using --auto-download (default: 200)")
    parser.add_argument("--output", default=None, help="Output path for probe_weights.npz")
    parser.add_argument("--model", default="openai/clip-vit-large-patch14", help="CLIP model name")
    parser.add_argument("--cache-dir", default=None, help="Model cache directory")
    args = parser.parse_args()

    # Validate arguments
    if not args.auto_download and (args.real is None or args.ai is None):
        parser.error("Either --auto-download or both --real and --ai are required")

    # Determine output path
    if args.output:
        output_path = args.output
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
    else:
        cache_dir = args.cache_dir or os.environ.get(
            "DENT_FORENSICS_MODEL_CACHE_DIR", "/app/models"
        )
        clip_cache = os.path.join(cache_dir, "clip_ai")
        os.makedirs(clip_cache, exist_ok=True)
        output_path = os.path.join(clip_cache, "probe_weights.npz")

    # Auto-download if requested
    tmp_dir = None
    if args.auto_download:
        tmp_dir = tempfile.mkdtemp(prefix="clip_probe_data_")
        args.real, args.ai = auto_download_dataset(args.num_samples, tmp_dir)

    print(f"CLIP probe trainer")
    print(f"  Model:  {args.model}")
    print(f"  Real:   {args.real}")
    print(f"  AI:     {args.ai}")
    print(f"  Output: {output_path}")
    print()

    # Load CLIP
    import torch
    from transformers import CLIPModel, CLIPProcessor

    print("Loading CLIP model...")
    processor = CLIPProcessor.from_pretrained(args.model, cache_dir=args.cache_dir)
    model = CLIPModel.from_pretrained(args.model, cache_dir=args.cache_dir)
    model.eval()
    print("  Done.\n")

    # Extract embeddings
    print(f"Extracting real image embeddings from {args.real}...")
    real_emb = extract_embeddings(args.real, processor, model, torch)
    print(f"  {len(real_emb)} real embeddings\n")

    print(f"Extracting AI image embeddings from {args.ai}...")
    ai_emb = extract_embeddings(args.ai, processor, model, torch)
    print(f"  {len(ai_emb)} AI embeddings\n")

    # Prepare training data
    X = np.vstack([real_emb, ai_emb])
    y = np.concatenate([np.zeros(len(real_emb)), np.ones(len(ai_emb))])

    # Shuffle
    indices = np.random.default_rng(42).permutation(len(X))
    X, y = X[indices], y[indices]

    print(f"Training logistic regression ({len(X)} samples, {X.shape[1]} features)...")
    weights, bias = train_logistic_regression(X, y)

    # Final accuracy
    logits = X @ weights + bias
    probs = 1.0 / (1.0 + np.exp(-np.clip(logits, -500, 500)))
    acc = ((probs > 0.5) == y).mean()
    print(f"\n  Final training accuracy: {acc:.1%}")

    # Save
    np.savez(output_path, weights=weights, bias=np.array([bias]))
    print(f"\n  Saved probe weights to {output_path}")
    print(f"  Weights shape: {weights.shape}, bias: {bias:.4f}")

    # Cleanup temp dir
    if tmp_dir:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print(f"  Cleaned up temp directory")


if __name__ == "__main__":
    main()
