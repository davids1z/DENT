"""
Community Forensics AI Detection Module (CVPR 2025)

Uses a ViT-Small classifier trained on 2.7M images from 4,803 different
generative models — the largest training diversity of any open-source
AI image detector.

Model: OwensLab/commfor-model-384 (HuggingFace, 87 MB safetensors)
Reference: https://github.com/JeongsooP/Community-Forensics

Performance: mAP=0.987, 75% mean accuracy across 291 generators (best
open-source in Feb 2026 benchmark). Zero-shot generalisation to unseen
generators.
"""

import io
import logging
import os
import time

import numpy as np
from PIL import Image

from ...config import settings
from ..base import AnalyzerFinding, BaseAnalyzer, ModuleResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------
_TORCH_AVAILABLE = False
_TIMM_AVAILABLE = False

try:
    import torch
    _TORCH_AVAILABLE = True
except ImportError:
    logger.info("PyTorch not installed, Community Forensics detection disabled")

if _TORCH_AVAILABLE:
    try:
        import timm  # noqa: F401
        _TIMM_AVAILABLE = True
    except ImportError:
        logger.info("timm not installed, Community Forensics detection disabled")

# HuggingFace model IDs
COMMFOR_MODEL_ID = "OwensLab/commfor-model-384"

# Preprocessing constants (from Community Forensics repo)
RESIZE_SIZE = 440
CROP_SIZE = 384
NORM_MEAN = [0.485, 0.456, 0.406]
NORM_STD = [0.229, 0.224, 0.225]


class CommunityForensicsAnalyzer(BaseAnalyzer):
    """AI-generated image detection using Community Forensics ViT-Small."""

    MODULE_NAME = "community_forensics_detection"
    MODULE_LABEL = "Community Forensics AI detekcija"

    def __init__(self) -> None:
        self._models_loaded = False
        self._model = None
        self._transform = None

    def _ensure_models(self) -> None:
        """Lazy-load model on first use."""
        if self._models_loaded:
            return

        if not _TORCH_AVAILABLE or not _TIMM_AVAILABLE:
            self._models_loaded = True
            return

        import torch.nn as nn
        from huggingface_hub import PyTorchModelHubMixin
        from torchvision import transforms

        cache_dir = os.path.join(
            settings.forensics_model_cache_dir, "community_forensics"
        )
        os.makedirs(cache_dir, exist_ok=True)

        # Build inference transform (matches repo's test-time preprocessing)
        self._transform = transforms.Compose([
            transforms.Resize(RESIZE_SIZE),
            transforms.CenterCrop(CROP_SIZE),
            transforms.ToTensor(),
            transforms.Normalize(mean=NORM_MEAN, std=NORM_STD),
        ])

        # Define the model class inline (vendored from models.py)
        class ViTClassifier(nn.Module, PyTorchModelHubMixin):
            def __init__(
                self,
                model_size="small",
                input_size=384,
                patch_size=16,
                freeze_backbone=False,
                device="cpu",
                dtype=torch.float32,
            ):
                super().__init__()
                self.device = device
                self.dtype = dtype
                model_name = (
                    f"vit_{model_size}_patch{patch_size}_{input_size}"
                    f".augreg_in21k_ft_in1k"
                )
                self.vit = timm.create_model(model_name, pretrained=False)
                in_features = 384 if model_size == "small" else 192
                self.vit.head = nn.Linear(
                    in_features=in_features,
                    out_features=1,
                    bias=True,
                    device=device,
                    dtype=dtype,
                )

            def forward(self, x):
                return self.vit(x)

        try:
            self._model = ViTClassifier.from_pretrained(
                COMMFOR_MODEL_ID,
                cache_dir=cache_dir,
                device="cpu",
            )
            self._model.eval()
            logger.info(
                "Community Forensics model loaded: %s (%.1f MB)",
                COMMFOR_MODEL_ID,
                sum(p.numel() * p.element_size() for p in self._model.parameters()) / 1e6,
            )
        except Exception as e:
            logger.warning("Failed to load Community Forensics model: %s", e)
            self._model = None

        self._models_loaded = True

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        start = time.monotonic()
        findings: list[AnalyzerFinding] = []

        if not settings.forensics_community_forensics_enabled:
            elapsed = int((time.monotonic() - start) * 1000)
            return self._make_result([], elapsed)

        try:
            self._ensure_models()

            if self._model is None or self._transform is None:
                elapsed = int((time.monotonic() - start) * 1000)
                return self._make_result(
                    [], elapsed,
                    error="Community Forensics model not available",
                )

            # Open and prepare image
            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")

            # Preprocess: Resize(440) → CenterCrop(384) → Normalize(ImageNet)
            tensor = self._transform(img).unsqueeze(0)  # [1, 3, 384, 384]

            # Inference
            with torch.no_grad():
                logit = self._model(tensor)
                prob = torch.sigmoid(logit).item()

            # Emit findings
            details = {
                "community_forensics_score": round(prob, 4),
                "model": COMMFOR_MODEL_ID,
                "generator_coverage": "4,803 generators",
            }

            if prob > 0.75:
                findings.append(AnalyzerFinding(
                    code="COMMFOR_AI_DETECTED",
                    title="Community Forensics: AI-generirana slika",
                    description=(
                        f"Community Forensics model (treniran na 2.7M slika iz 4,803 "
                        f"generatora) detektirao je s visokom pouzdanoscu da je ova "
                        f"slika umjetno generirana (rezultat: {prob:.0%})."
                    ),
                    risk_score=min(0.95, max(0.85, prob)),
                    confidence=min(0.98, 0.80 + prob * 0.15),
                    evidence=details,
                ))
            elif prob > 0.50:
                findings.append(AnalyzerFinding(
                    code="COMMFOR_AI_SUSPECTED",
                    title="Community Forensics: sumnja na AI generiranje",
                    description=(
                        f"Community Forensics model pokazuje umjerenu vjerojatnost "
                        f"({prob:.0%}) da je slika umjetno generirana."
                    ),
                    risk_score=max(0.55, prob * 0.95),
                    confidence=0.75 + prob * 0.10,
                    evidence=details,
                ))
            elif prob > 0.30:
                findings.append(AnalyzerFinding(
                    code="COMMFOR_AI_LOW",
                    title="Community Forensics: blagi AI indikatori",
                    description=(
                        f"Community Forensics model pokazuje niske indikatore "
                        f"({prob:.0%}) moguceg AI generiranja."
                    ),
                    risk_score=prob * 0.65,
                    confidence=0.60,
                    evidence=details,
                ))

        except Exception as e:
            logger.warning("Community Forensics detection error: %s", e)
            elapsed = int((time.monotonic() - start) * 1000)
            return self._make_result([], elapsed, error=str(e))

        elapsed = int((time.monotonic() - start) * 1000)
        result = self._make_result(findings, elapsed)
        # Pass raw score for fusion (same pattern as ai_generation.py)
        if self._model is not None:
            result.risk_score = round(prob, 4)
            result.risk_score100 = round(prob * 100)
        return result

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([], 0)
