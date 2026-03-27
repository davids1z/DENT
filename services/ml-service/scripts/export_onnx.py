#!/usr/bin/env python3
"""Export ML models to ONNX format for accelerated inference.

Run once on the server after models are downloaded. ONNX models are cached
in the ml_models Docker volume alongside their PyTorch originals.

Usage:
    python scripts/export_onnx.py [--models-dir /app/models] [--force]

Exports:
    - CLIP ViT-L/14 vision encoder → clip_ai/clip_vision.onnx
    - DINOv2-large → dinov2/dinov2.onnx
    - EfficientNet-B4 → efficientnet_ai/efficientnet.onnx
    - Community Forensics ViT-S → community_forensics/commfor.onnx
    - SAFE truncated ResNet → safe_ai/safe.onnx

ONNX models support dynamic batch axes for batch inference.
"""

import argparse
import logging
import os
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def export_clip(models_dir: str, force: bool = False) -> bool:
    """Export CLIP ViT-L/14 vision encoder to ONNX."""
    out_path = os.path.join(models_dir, "clip_ai", "clip_vision.onnx")
    if os.path.exists(out_path) and not force:
        logger.info("CLIP ONNX already exists: %s", out_path)
        return True

    try:
        import torch
        from transformers import CLIPModel

        cache_dir = os.path.join(models_dir, "clip_ai")
        model = CLIPModel.from_pretrained(
            "openai/clip-vit-large-patch14", cache_dir=cache_dir
        )
        model.eval()

        # Extract vision components
        vision_model = model.vision_model
        visual_projection = model.visual_projection

        class CLIPVisionONNX(torch.nn.Module):
            def __init__(self, vm, vp):
                super().__init__()
                self.vision_model = vm
                self.visual_projection = vp

            def forward(self, pixel_values):
                out = self.vision_model(pixel_values=pixel_values)
                pooled = out.pooler_output
                projected = self.visual_projection(pooled)
                return projected

        wrapper = CLIPVisionONNX(vision_model, visual_projection)
        wrapper.eval()

        dummy = torch.randn(1, 3, 224, 224)
        torch.onnx.export(
            wrapper,
            dummy,
            out_path,
            input_names=["pixel_values"],
            output_names=["embeddings"],
            dynamic_axes={
                "pixel_values": {0: "batch"},
                "embeddings": {0: "batch"},
            },
            opset_version=17,
            do_constant_folding=True,
        )
        size_mb = os.path.getsize(out_path) / 1e6
        logger.info("CLIP ONNX exported: %s (%.0f MB)", out_path, size_mb)
        return True
    except Exception as e:
        logger.error("CLIP ONNX export failed: %s", e)
        return False


def export_dinov2(models_dir: str, force: bool = False) -> bool:
    """Export DINOv2-large to ONNX."""
    out_path = os.path.join(models_dir, "dinov2", "dinov2.onnx")
    if os.path.exists(out_path) and not force:
        logger.info("DINOv2 ONNX already exists: %s", out_path)
        return True

    try:
        import torch
        from transformers import AutoModel

        cache_dir = os.path.join(models_dir, "dinov2")
        model = AutoModel.from_pretrained(
            "facebook/dinov2-large", cache_dir=cache_dir
        )
        model.eval()

        class DINOv2ONNX(torch.nn.Module):
            def __init__(self, m):
                super().__init__()
                self.model = m

            def forward(self, pixel_values):
                out = self.model(pixel_values=pixel_values)
                return out.last_hidden_state[:, 0, :]  # CLS token

        wrapper = DINOv2ONNX(model)
        wrapper.eval()

        dummy = torch.randn(1, 3, 518, 518)
        torch.onnx.export(
            wrapper,
            dummy,
            out_path,
            input_names=["pixel_values"],
            output_names=["cls_embedding"],
            dynamic_axes={
                "pixel_values": {0: "batch"},
                "cls_embedding": {0: "batch"},
            },
            opset_version=17,
            do_constant_folding=True,
        )
        size_mb = os.path.getsize(out_path) / 1e6
        logger.info("DINOv2 ONNX exported: %s (%.0f MB)", out_path, size_mb)
        return True
    except Exception as e:
        logger.error("DINOv2 ONNX export failed: %s", e)
        return False


def export_efficientnet(models_dir: str, force: bool = False) -> bool:
    """Export EfficientNet-B4 to ONNX."""
    out_path = os.path.join(models_dir, "efficientnet_ai", "efficientnet.onnx")
    if os.path.exists(out_path) and not force:
        logger.info("EfficientNet ONNX already exists: %s", out_path)
        return True

    try:
        import timm
        import torch

        model = timm.create_model("efficientnet_b4", pretrained=False, num_classes=2)
        weights_path = os.path.join(models_dir, "efficientnet_ai", "pytorch_model.pth")
        if not os.path.exists(weights_path):
            logger.warning("EfficientNet weights not found: %s", weights_path)
            return False

        state = torch.load(weights_path, map_location="cpu", weights_only=True)
        model.load_state_dict(state)
        model.eval()

        dummy = torch.randn(1, 3, 380, 380)
        torch.onnx.export(
            model,
            dummy,
            out_path,
            input_names=["pixel_values"],
            output_names=["logits"],
            dynamic_axes={
                "pixel_values": {0: "batch"},
                "logits": {0: "batch"},
            },
            opset_version=17,
            do_constant_folding=True,
        )
        size_mb = os.path.getsize(out_path) / 1e6
        logger.info("EfficientNet ONNX exported: %s (%.0f MB)", out_path, size_mb)
        return True
    except Exception as e:
        logger.error("EfficientNet ONNX export failed: %s", e)
        return False


def export_commfor(models_dir: str, force: bool = False) -> bool:
    """Export Community Forensics ViT-Small to ONNX."""
    out_path = os.path.join(models_dir, "community_forensics", "commfor.onnx")
    if os.path.exists(out_path) and not force:
        logger.info("CommForensics ONNX already exists: %s", out_path)
        return True

    try:
        import timm
        import torch
        import torch.nn as nn
        from huggingface_hub import PyTorchModelHubMixin

        class ViTClassifier(nn.Module, PyTorchModelHubMixin):
            def __init__(self, num_classes=1):
                super().__init__()
                self.base = timm.create_model(
                    "vit_small_patch16_384.augreg_in21k_ft_in1k", pretrained=False
                )
                self.base.head = nn.Linear(
                    in_features=self.base.head.in_features, out_features=num_classes
                )

            def forward(self, x):
                return self.base(x)

        cache_dir = os.path.join(models_dir, "community_forensics")
        model = ViTClassifier.from_pretrained(
            "OwensLab/commfor-model-384", cache_dir=cache_dir
        )
        model.eval()

        dummy = torch.randn(1, 3, 384, 384)
        torch.onnx.export(
            model,
            dummy,
            out_path,
            input_names=["pixel_values"],
            output_names=["logit"],
            dynamic_axes={
                "pixel_values": {0: "batch"},
                "logit": {0: "batch"},
            },
            opset_version=17,
            do_constant_folding=True,
        )
        size_mb = os.path.getsize(out_path) / 1e6
        logger.info("CommForensics ONNX exported: %s (%.0f MB)", out_path, size_mb)
        return True
    except Exception as e:
        logger.error("CommForensics ONNX export failed: %s", e)
        return False


def export_safe(models_dir: str, force: bool = False) -> bool:
    """Export SAFE truncated ResNet to ONNX."""
    out_path = os.path.join(models_dir, "safe_ai", "safe.onnx")
    if os.path.exists(out_path) and not force:
        logger.info("SAFE ONNX already exists: %s", out_path)
        return True

    try:
        import torch

        # Import SAFENet from the analyzer module
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from app.forensics.analyzers.safe_ai_detection import SAFENet

        model = SAFENet()
        ckpt_path = os.path.join(models_dir, "safe_ai", "checkpoint-best.pth")
        if not os.path.exists(ckpt_path):
            logger.warning("SAFE checkpoint not found: %s", ckpt_path)
            return False

        checkpoint = torch.load(ckpt_path, map_location="cpu", weights_only=False)
        state = checkpoint.get("model", checkpoint)
        model.load_state_dict(state)
        model.eval()

        dummy = torch.randn(1, 3, 256, 256)
        torch.onnx.export(
            model,
            dummy,
            out_path,
            input_names=["pixel_values"],
            output_names=["logits"],
            dynamic_axes={
                "pixel_values": {0: "batch"},
                "logits": {0: "batch"},
            },
            opset_version=17,
            do_constant_folding=True,
        )
        size_mb = os.path.getsize(out_path) / 1e6
        logger.info("SAFE ONNX exported: %s (%.0f MB)", out_path, size_mb)
        return True
    except Exception as e:
        logger.error("SAFE ONNX export failed: %s", e)
        return False


def main():
    parser = argparse.ArgumentParser(description="Export ML models to ONNX")
    parser.add_argument("--models-dir", default="/app/models")
    parser.add_argument("--force", action="store_true", help="Re-export even if ONNX exists")
    args = parser.parse_args()

    logger.info("Exporting models to ONNX (models_dir=%s, force=%s)", args.models_dir, args.force)
    start = time.time()

    results = {
        "clip": export_clip(args.models_dir, args.force),
        "dinov2": export_dinov2(args.models_dir, args.force),
        "efficientnet": export_efficientnet(args.models_dir, args.force),
        "commfor": export_commfor(args.models_dir, args.force),
        "safe": export_safe(args.models_dir, args.force),
    }

    elapsed = time.time() - start
    success = sum(1 for v in results.values() if v)
    total = len(results)
    logger.info(
        "ONNX export complete: %d/%d models exported in %.1fs",
        success, total, elapsed,
    )

    for name, ok in results.items():
        status = "OK" if ok else "FAILED"
        logger.info("  %s: %s", name, status)

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
