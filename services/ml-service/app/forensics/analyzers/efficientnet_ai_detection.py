"""
EfficientNet-B4 AI Image Detection

Lightweight CNN detector for AI-generated images, optimized for CPU inference.
Model: Dafilab/ai-image-detector (EfficientNet-B4, 19.3M params, ~75MB)
Trained on 200K images (100K AI + 100K real), val accuracy 98.59%.

CPU inference: ~0.5-1s per image (vs Swin 35s, CLIP 15s).
Replaces the Swin Transformer ensemble as the primary fast AI detector.
"""

import io
import logging
import os
import time

import numpy as np
from PIL import Image

from ..base import AnalyzerFinding, BaseAnalyzer, ModuleResult

logger = logging.getLogger(__name__)

try:
    import torch
    import torch.nn.functional as F
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False

try:
    import timm
    _TIMM_AVAILABLE = True
except ImportError:
    _TIMM_AVAILABLE = False

# HuggingFace model ID
EFFICIENTNET_MODEL_ID = "Dafilab/ai-image-detector"

# Preprocessing constants (EfficientNet-B4 standard)
IMG_SIZE = 380
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


class EfficientNetAiDetectionAnalyzer(BaseAnalyzer):
    """EfficientNet-B4 AI image detection — fast and accurate on CPU."""

    MODULE_NAME = "efficientnet_ai_detection"
    MODULE_LABEL = "EfficientNet AI detekcija"

    def __init__(self) -> None:
        self._models_loaded = False
        self._model = None
        self._transform = None

    def _ensure_models(self) -> None:
        """Lazy-load EfficientNet-B4 on first use."""
        if self._models_loaded:
            return

        if not _TORCH_AVAILABLE or not _TIMM_AVAILABLE:
            logger.warning("torch or timm not available, EfficientNet disabled")
            self._models_loaded = True
            return

        from torchvision import transforms
        from huggingface_hub import hf_hub_download

        try:
            from ..config import settings
        except Exception:
            from types import SimpleNamespace
            settings = SimpleNamespace(forensics_model_cache_dir="/app/models")

        cache_dir = os.path.join(
            getattr(settings, "forensics_model_cache_dir", "/app/models"),
            "efficientnet_ai",
        )
        os.makedirs(cache_dir, exist_ok=True)

        try:
            # Download weights from HuggingFace
            weights_path = hf_hub_download(
                repo_id=EFFICIENTNET_MODEL_ID,
                filename="pytorch_model.pth",
                cache_dir=cache_dir,
            )

            # Create EfficientNet-B4 with 2 classes (ai=0, human=1)
            self._model = timm.create_model(
                "efficientnet_b4",
                pretrained=False,
                num_classes=2,
            )

            # Load fine-tuned weights
            state_dict = torch.load(weights_path, map_location="cpu", weights_only=True)
            self._model.load_state_dict(state_dict)
            self._model.eval()

            logger.info(
                "EfficientNet-B4 loaded: %s (%.1fM params)",
                EFFICIENTNET_MODEL_ID,
                sum(p.numel() for p in self._model.parameters()) / 1e6,
            )

        except Exception as e:
            logger.warning("Failed to load EfficientNet-B4: %s", e)
            self._model = None

        # Standard ImageNet preprocessing for EfficientNet
        self._transform = transforms.Compose([
            transforms.Resize(IMG_SIZE + 20),
            transforms.CenterCrop(IMG_SIZE),
            transforms.ToTensor(),
            transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ])

        self._models_loaded = True

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        start = time.monotonic()
        findings: list[AnalyzerFinding] = []

        try:
            self._ensure_models()

            if self._model is None:
                elapsed = int((time.monotonic() - start) * 1000)
                return self._make_result([], elapsed, error="EfficientNet not loaded")

            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")

            tensor = self._transform(img).unsqueeze(0)  # (1, 3, 380, 380)

            with torch.no_grad():
                logits = self._model(tensor)  # (1, 2)
                probs = F.softmax(logits, dim=1)
                # Class 0 = AI, Class 1 = Human
                ai_prob = float(probs[0, 0])

            # Emit findings based on AI probability
            if ai_prob > 0.75:
                findings.append(AnalyzerFinding(
                    code="EFFICIENTNET_AI_DETECTED",
                    title="EfficientNet: detektiran AI-generiran sadrzaj",
                    description=(
                        f"EfficientNet-B4 CNN klasifikator prepoznaje sliku kao "
                        f"AI-generiranu s vjerojatnescu {ai_prob:.0%}. "
                        f"Model je treniran na 200.000 slika iz razlicitih generatora."
                    ),
                    risk_score=min(0.90, ai_prob),
                    confidence=min(0.95, ai_prob),
                    evidence={
                        "ai_probability": round(ai_prob, 4),
                        "human_probability": round(1.0 - ai_prob, 4),
                        "model": EFFICIENTNET_MODEL_ID,
                    },
                ))
            elif ai_prob > 0.50:
                findings.append(AnalyzerFinding(
                    code="EFFICIENTNET_AI_SUSPECTED",
                    title="EfficientNet: sumnja na AI sadrzaj",
                    description=(
                        f"EfficientNet-B4 pokazuje umjerenu sumnju na AI-generirani "
                        f"sadrzaj ({ai_prob:.0%})."
                    ),
                    risk_score=ai_prob * 0.80,
                    confidence=0.60 + ai_prob * 0.20,
                    evidence={
                        "ai_probability": round(ai_prob, 4),
                        "human_probability": round(1.0 - ai_prob, 4),
                    },
                ))

        except Exception as e:
            logger.warning("EfficientNet inference failed: %s", e)
            elapsed = int((time.monotonic() - start) * 1000)
            return self._make_result([], elapsed, error=str(e))

        elapsed = int((time.monotonic() - start) * 1000)
        result = self._make_result(findings, elapsed)
        # Raw score passthrough for meta-learner calibration
        result.risk_score = round(ai_prob, 4)
        result.risk_score100 = round(ai_prob * 100)
        return result

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([], 0)
