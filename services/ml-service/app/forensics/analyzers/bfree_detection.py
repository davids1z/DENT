"""
B-Free AI Image Detection Module (CVPR 2025)

Bias-Free Training Paradigm for More General AI-generated Image Detection.
Uses DINOv2 ViT-Base with 4 register tokens, fine-tuned end-to-end on
27 generators including Flux and SD 3.5 with a bias-free training strategy.

Key insight: Standard training creates biases toward training-set compression
formats and generators. B-Free generates training fakes from real images via
SD conditioning, ensuring semantic alignment. The 5-crop wrapper captures both
local and global AI artifacts.

Architecture:
1. Input: 504×504 RGB image
2. Extract 14×14 patch embeddings from DINOv2 ViT-Base (with registers)
3. 5-crop spatial splits (center + 4 corners) through the ViT
4. Average 5 predictions → sigmoid score
5. Score > 0.50 → AI-generated

Paper: https://arxiv.org/abs/2412.17671
GitHub: https://github.com/grip-unina/B-Free
License: Nonprofit/informational use (GRIP-UNINA)
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
    pass

if _TORCH_AVAILABLE:
    try:
        import timm  # noqa: F401
        _TIMM_AVAILABLE = True
    except ImportError:
        pass

# ImageNet normalization (ResNet-style, as used in B-Free)
_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
_INPUT_SIZE = 504  # B-Free expects 504×504 for 36×36 patch grid


class BFreeDetectionAnalyzer(BaseAnalyzer):
    """B-Free DINOv2 ViT-Base with 5-crop for AI image detection."""

    MODULE_NAME = "bfree_detection"
    MODULE_LABEL = "B-Free AI detekcija"

    def __init__(self) -> None:
        self._models_loaded = False
        self._model = None
        self._device = "cpu"

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _ensure_models(self) -> None:
        if self._models_loaded:
            return

        if not _TORCH_AVAILABLE or not _TIMM_AVAILABLE:
            self._models_loaded = True
            return

        if not getattr(settings, "forensics_bfree_enabled", False):
            self._models_loaded = True
            return

        import torch
        import timm

        cache_dir = getattr(settings, "forensics_bfree_model_dir",
                            os.path.join(settings.forensics_model_cache_dir, "bfree"))
        weights_path = os.path.join(cache_dir, "model_epoch_best.pth")

        if not os.path.exists(weights_path):
            logger.warning("B-Free weights not found at %s", weights_path)
            self._models_loaded = True
            return

        try:
            self._device = "cuda" if torch.cuda.is_available() else "cpu"

            # Create DINOv2 ViT-Base with 4 register tokens
            base_model = timm.create_model(
                "vit_base_patch14_reg4_dinov2.lvd142m",
                pretrained=False,
                num_classes=1,
            )

            # Wrap in 5-crop strategy
            self._model = _Wrapper5Crops(base_model).to(self._device)

            # Load fine-tuned weights
            state_dict = torch.load(weights_path, map_location=self._device, weights_only=True)
            # Handle nested state_dict (some checkpoints wrap in 'state_dict' key)
            if "state_dict" in state_dict:
                state_dict = state_dict["state_dict"]
            self._model.load_state_dict(state_dict, strict=False)
            self._model.eval()

            param_count = sum(p.numel() for p in self._model.parameters()) / 1e6
            logger.info(
                "B-Free model loaded on %s: %.1fM params, input=%dx%d",
                self._device, param_count, _INPUT_SIZE, _INPUT_SIZE,
            )

        except Exception as e:
            logger.warning("Failed to load B-Free model: %s", e)
            self._model = None

        self._models_loaded = True

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        start = time.monotonic()
        findings: list[AnalyzerFinding] = []

        if not getattr(settings, "forensics_bfree_enabled", False):
            return self._make_result([], int((time.monotonic() - start) * 1000))

        try:
            self._ensure_models()

            if self._model is None:
                return self._make_result(
                    [], int((time.monotonic() - start) * 1000),
                    error="B-Free model not available",
                )

            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")

            score = self._compute_score(img)
            self._emit_findings(score, findings)

        except Exception as e:
            logger.warning("B-Free detection error: %s", e)
            return self._make_result(
                [], int((time.monotonic() - start) * 1000), error=str(e),
            )

        elapsed = int((time.monotonic() - start) * 1000)
        result = self._make_result(findings, elapsed)
        # Raw score passthrough for fusion — _make_result derives risk_score
        # from findings which have scaled/capped values, losing signal.
        result.risk_score = round(score, 4)
        result.risk_score100 = round(score * 100)
        return result

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([], 0)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _compute_score(self, img: Image.Image) -> float:
        """Compute AI-generation probability via B-Free 5-crop inference."""
        import torch

        # Resize to 504×504 and normalize
        img_resized = img.resize((_INPUT_SIZE, _INPUT_SIZE), Image.LANCZOS)
        arr = np.array(img_resized, dtype=np.float32) / 255.0
        arr = (arr - _IMAGENET_MEAN) / _IMAGENET_STD
        # HWC → CHW → batch
        tensor = torch.from_numpy(arr.transpose(2, 0, 1)).unsqueeze(0).to(self._device)

        with torch.no_grad():
            logit = self._model(tensor)
            # B-Free outputs a single logit (or 2 logits where score = logit[1] - logit[0])
            if logit.dim() > 1 and logit.shape[-1] == 2:
                logit = logit[:, 1] - logit[:, 0]
            score = float(torch.sigmoid(logit.squeeze()).cpu().item())

        return float(np.clip(score, 0.0, 1.0))

    # ------------------------------------------------------------------
    # Findings
    # ------------------------------------------------------------------

    @staticmethod
    def _emit_findings(score: float, findings: list[AnalyzerFinding]) -> None:
        if score > 0.70:
            findings.append(
                AnalyzerFinding(
                    code="BFREE_AI_DETECTED",
                    title="B-Free detekcija AI-generiranog sadrzaja",
                    description=(
                        f"B-Free model (CVPR 2025, 27 generatora) detektirao je "
                        f"snazne indikatore AI generiranja (rezultat: {score:.0%})."
                    ),
                    risk_score=min(0.90, max(0.65, score * 0.90)),
                    confidence=min(0.90, 0.60 + score * 0.25),
                    evidence={"bfree_score": round(score, 4), "method": "bfree_dinov2_5crop"},
                )
            )
        elif score > 0.45:
            findings.append(
                AnalyzerFinding(
                    code="BFREE_AI_SUSPECTED",
                    title="B-Free sumnja na AI sadrzaj",
                    description=(
                        f"B-Free bias-free analiza pokazuje umjerenu vjerojatnost "
                        f"({score:.0%}) da je slika umjetno generirana."
                    ),
                    risk_score=max(0.40, score * 0.75),
                    confidence=min(0.80, 0.45 + score * 0.30),
                    evidence={"bfree_score": round(score, 4), "method": "bfree_dinov2_5crop"},
                )
            )
        elif score > 0.25:
            findings.append(
                AnalyzerFinding(
                    code="BFREE_AI_LOW",
                    title="B-Free blagi AI indikatori",
                    description=(
                        f"B-Free analiza pokazuje blage indikatore "
                        f"({score:.0%}) moguceg AI generiranja."
                    ),
                    risk_score=score * 0.50,
                    confidence=0.40 + score * 0.15,
                    evidence={"bfree_score": round(score, 4), "method": "bfree_dinov2_5crop"},
                )
            )


# ---------------------------------------------------------------------------
# 5-crop wrapper (reimplemented from B-Free paper)
# ---------------------------------------------------------------------------

class _Wrapper5Crops(torch.nn.Module if _TORCH_AVAILABLE else object):
    """Wraps a ViT model with 5-crop spatial augmentation at inference time.

    Extracts patch embeddings, creates 5 spatial crops (center + 4 corners),
    processes each through the backbone, and averages the predictions.
    """

    def __init__(self, base_model):
        if not _TORCH_AVAILABLE:
            return
        import torch.nn as nn
        super().__init__()
        self.base = base_model

    def forward(self, x):
        """
        x: (B, 3, 504, 504)
        Returns: (B, 1) average logit across 5 crops
        """
        import torch

        # Simple approach: resize to 5 different crops and average
        B, C, H, W = x.shape
        crop_size = H * 3 // 4  # 378px from 504px input

        crops = []
        # Center crop
        s = (H - crop_size) // 2
        crops.append(x[:, :, s:s + crop_size, s:s + crop_size])
        # 4 corner crops
        crops.append(x[:, :, :crop_size, :crop_size])          # top-left
        crops.append(x[:, :, :crop_size, W - crop_size:])      # top-right
        crops.append(x[:, :, H - crop_size:, :crop_size])      # bottom-left
        crops.append(x[:, :, H - crop_size:, W - crop_size:])  # bottom-right

        # Resize all crops to the model's expected input size (224×224 or whatever timm uses)
        import torch.nn.functional as F
        default_size = 518  # DINOv2 reg4 default: 518 = 37 patches × 14
        resized = [
            F.interpolate(crop, size=(default_size, default_size), mode="bilinear", align_corners=False)
            for crop in crops
        ]

        # Forward each crop
        logits = []
        for crop_tensor in resized:
            out = self.base(crop_tensor)
            logits.append(out)

        # Average predictions
        stacked = torch.stack(logits, dim=0)  # (5, B, num_classes)
        avg = stacked.mean(dim=0)  # (B, num_classes)
        return avg
