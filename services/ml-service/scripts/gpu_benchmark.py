#!/usr/bin/env python3
"""GPU vs CPU inference benchmark for DENT ML models.

Run on a vast.ai GPU instance to measure real throughput.
Downloads models, runs inference, reports timing.

Usage:
    python gpu_benchmark.py [--device cuda|cpu] [--batch-size 10] [--num-images 50]
"""

import argparse
import os
import sys
import time

import numpy as np
from PIL import Image


def create_dummy_images(n: int, size: tuple = (640, 480)) -> list:
    """Create N random RGB images for benchmarking."""
    images = []
    for _ in range(n):
        arr = np.random.randint(0, 255, (*size, 3), dtype=np.uint8)
        images.append(Image.fromarray(arr))
    return images


def benchmark_clip(images: list, device: str) -> dict:
    """Benchmark CLIP ViT-L/14 vision encoder."""
    import torch
    from transformers import CLIPModel, CLIPProcessor

    print(f"\n--- CLIP ViT-L/14 ({device}) ---")
    processor = CLIPProcessor.from_pretrained("openai/clip-vit-large-patch14")
    model = CLIPModel.from_pretrained("openai/clip-vit-large-patch14").to(device)
    model.eval()

    # Warmup
    inputs = processor(images=images[0], return_tensors="pt").to(device)
    with torch.no_grad():
        model.vision_model(pixel_values=inputs["pixel_values"])

    # Single image benchmark
    times = []
    for img in images[:10]:
        inputs = processor(images=img, return_tensors="pt").to(device)
        start = time.perf_counter()
        with torch.no_grad():
            out = model.vision_model(pixel_values=inputs["pixel_values"].to(device))
            _ = model.visual_projection(out.pooler_output)
        if device == "cuda":
            torch.cuda.synchronize()
        times.append(time.perf_counter() - start)

    avg_single = np.mean(times) * 1000
    print(f"  Single image: {avg_single:.1f}ms avg ({1000/avg_single:.1f} img/s)")

    # Batch benchmark
    batch_sizes = [1, 4, 8, 16]
    for bs in batch_sizes:
        batch_imgs = images[:bs]
        inputs = processor(images=batch_imgs, return_tensors="pt", padding=True)
        pixel_values = inputs["pixel_values"].to(device)

        # Warmup
        with torch.no_grad():
            out = model.vision_model(pixel_values=pixel_values)
            _ = model.visual_projection(out.pooler_output)
        if device == "cuda":
            torch.cuda.synchronize()

        start = time.perf_counter()
        with torch.no_grad():
            out = model.vision_model(pixel_values=pixel_values)
            _ = model.visual_projection(out.pooler_output)
        if device == "cuda":
            torch.cuda.synchronize()
        elapsed = (time.perf_counter() - start) * 1000

        print(f"  Batch {bs}: {elapsed:.1f}ms total ({elapsed/bs:.1f}ms/img, {bs*1000/elapsed:.1f} img/s)")

    return {"model": "CLIP ViT-L/14", "single_ms": avg_single}


def benchmark_dinov2(images: list, device: str) -> dict:
    """Benchmark DINOv2-large."""
    import torch
    from transformers import AutoImageProcessor, AutoModel

    print(f"\n--- DINOv2-large ({device}) ---")
    processor = AutoImageProcessor.from_pretrained("facebook/dinov2-large")
    model = AutoModel.from_pretrained("facebook/dinov2-large").to(device)
    model.eval()

    # Warmup
    inputs = processor(images=images[0], return_tensors="pt")
    with torch.no_grad():
        model(pixel_values=inputs["pixel_values"].to(device))

    # Single image
    times = []
    for img in images[:10]:
        inputs = processor(images=img, return_tensors="pt")
        start = time.perf_counter()
        with torch.no_grad():
            model(pixel_values=inputs["pixel_values"].to(device))
        if device == "cuda":
            torch.cuda.synchronize()
        times.append(time.perf_counter() - start)

    avg_single = np.mean(times) * 1000
    print(f"  Single image: {avg_single:.1f}ms avg ({1000/avg_single:.1f} img/s)")

    # Batch
    for bs in [1, 4, 8, 16]:
        batch_imgs = images[:bs]
        inputs = processor(images=batch_imgs, return_tensors="pt", padding=True)
        pixel_values = inputs["pixel_values"].to(device)

        with torch.no_grad():
            model(pixel_values=pixel_values)
        if device == "cuda":
            torch.cuda.synchronize()

        start = time.perf_counter()
        with torch.no_grad():
            model(pixel_values=pixel_values)
        if device == "cuda":
            torch.cuda.synchronize()
        elapsed = (time.perf_counter() - start) * 1000

        print(f"  Batch {bs}: {elapsed:.1f}ms total ({elapsed/bs:.1f}ms/img, {bs*1000/elapsed:.1f} img/s)")

    return {"model": "DINOv2-large", "single_ms": avg_single}


def benchmark_onnx_clip(images: list) -> dict:
    """Benchmark CLIP with ONNX Runtime (CPU)."""
    try:
        import onnxruntime as ort
    except ImportError:
        print("\n--- CLIP ONNX (skipped, onnxruntime not installed) ---")
        return {}

    onnx_path = "/app/models/clip_ai/clip_vision.onnx"
    if not os.path.exists(onnx_path):
        print(f"\n--- CLIP ONNX (skipped, {onnx_path} not found) ---")
        return {}

    from transformers import CLIPProcessor

    print("\n--- CLIP ONNX Runtime (CPU) ---")
    processor = CLIPProcessor.from_pretrained("openai/clip-vit-large-patch14")

    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 4
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    session = ort.InferenceSession(onnx_path, opts, providers=["CPUExecutionProvider"])

    # Single image
    times = []
    for img in images[:10]:
        inputs = processor(images=img, return_tensors="np")
        pv = inputs["pixel_values"].astype(np.float32)
        start = time.perf_counter()
        session.run(None, {"pixel_values": pv})
        times.append(time.perf_counter() - start)

    avg = np.mean(times) * 1000
    print(f"  Single image: {avg:.1f}ms avg ({1000/avg:.1f} img/s)")
    return {"model": "CLIP ONNX CPU", "single_ms": avg}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="cuda" if _has_cuda() else "cpu")
    parser.add_argument("--num-images", type=int, default=20)
    args = parser.parse_args()

    print(f"Device: {args.device}")
    if args.device == "cuda":
        import torch
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"VRAM: {torch.cuda.get_device_properties(0).total_mem / 1e9:.1f} GB")

    images = create_dummy_images(args.num_images)
    print(f"Created {len(images)} dummy images (640x480)")

    results = []
    results.append(benchmark_clip(images, args.device))
    results.append(benchmark_dinov2(images, args.device))

    if args.device == "cpu":
        results.append(benchmark_onnx_clip(images))

    print("\n=== SUMMARY ===")
    for r in results:
        if r:
            print(f"  {r['model']}: {r['single_ms']:.1f}ms/image ({1000/r['single_ms']:.1f} img/s)")

    # Estimate full pipeline time
    clip_ms = next((r["single_ms"] for r in results if r and "CLIP" in r["model"] and "ONNX" not in r["model"]), 0)
    dino_ms = next((r["single_ms"] for r in results if r and "DINOv2" in r["model"]), 0)
    if clip_ms and dino_ms:
        # All models run in parallel, so total = max(all models)
        # CLIP and DINOv2 are the slowest, others (SAFE, EfficientNet) are faster
        est_pipeline = max(clip_ms, dino_ms) * 1.3  # 30% overhead for other modules
        print(f"\n  Estimated full pipeline per image: ~{est_pipeline:.0f}ms")
        print(f"  10 images (batch): ~{est_pipeline * 1.5:.0f}ms")  # batch is ~1.5x single
        print(f"  100 images (batch): ~{est_pipeline * 3:.0f}ms")  # batch scales sublinearly


def _has_cuda():
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


if __name__ == "__main__":
    main()
