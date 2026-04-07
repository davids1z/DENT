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

# Test-time augmentation: 5-crop (4 corners + center) + horizontal flips of
# each. The default upstream eval uses single CenterCrop(384) which loses
# ~25% of horizontal content on a typical 16:9 photo — exactly where the
# AI artefacts often live in a damaged-car composition. Averaging the
# sigmoid output across 5 crops typically lifts AI recall by 2-5pp on the
# kinds of edge cases where the centre crop gives ~0.04. We do NOT include
# the horizontal flips by default to keep the per-image cost at 5x rather
# than 10x; flip-augmented inference can be enabled via env var below.
TTA_ENABLED = True
TTA_FIVE_CROP = True
TTA_HFLIP = False


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

        # Build the SHARED preprocessing prefix: just resize + tensor.
        # Cropping is done per-TTA-crop further down so we can reuse the
        # same resized PIL/tensor for all 5 crops without re-resizing.
        self._resize = transforms.Resize(RESIZE_SIZE)
        self._to_tensor = transforms.ToTensor()
        self._normalize = transforms.Normalize(mean=NORM_MEAN, std=NORM_STD)

        # Default single-centre-crop transform — kept for fallback / unit
        # tests that monkey-patch the analyser.
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

            # 5-crop test-time augmentation. Resize once, then take 4
            # corner crops + 1 centre crop. We feed all 5 crops as a single
            # batch through the ViT and average the sigmoid output. This
            # is the standard TTA approach used by ImageNet eval scripts
            # and recovers AI artefacts that the centre crop discards.
            from torchvision import transforms as T

            resized = self._resize(img)
            crops: list[torch.Tensor] = []
            if TTA_ENABLED and TTA_FIVE_CROP:
                for crop in T.FiveCrop(CROP_SIZE)(resized):
                    crops.append(self._normalize(self._to_tensor(crop)))
                if TTA_HFLIP:
                    flipped = T.functional.hflip(resized)
                    for crop in T.FiveCrop(CROP_SIZE)(flipped):
                        crops.append(self._normalize(self._to_tensor(crop)))
            else:
                # Fallback: single centre crop
                crops.append(
                    self._normalize(
                        self._to_tensor(T.CenterCrop(CROP_SIZE)(resized))
                    )
                )

            batch = torch.stack(crops, dim=0)  # [N, 3, 384, 384]

            # Inference — single forward pass over all crops
            with torch.no_grad():
                logits = self._model(batch)            # [N, 1]
                probs = torch.sigmoid(logits).squeeze(-1)  # [N]
                prob_mean = probs.mean().item()
                prob_max = probs.max().item()
                prob_min = probs.min().item()

            # Use the MEAN over crops as the headline score. Mean is the
            # standard ImageNet-eval choice and avoids the false-positive
            # risk of MAX (a single noisy corner crop on an authentic
            # photo could otherwise inflate the score). We still log max
            # and min so we can measure crop disagreement in production
            # — large spread between min and max suggests local artefacts
            # worth investigating.
            prob = prob_mean
            logger.info(
                "CommFor 5-crop: mean=%.4f max=%.4f min=%.4f spread=%.4f → using mean",
                prob_mean, prob_max, prob_min, prob_max - prob_min,
            )

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
