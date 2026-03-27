"""
SPAI AI Image Detection Module (CVPR 2025)

Any-Resolution AI-Generated Image Detection by Spectral Learning.
Uses FFT frequency decomposition + ViT-B/16 encoder + cross-attention
aggregator to detect AI-generated images from their spectral signatures.

Key insight: AI generators leave characteristic patterns in the frequency
domain that are INVARIANT to pixel-level compression (WebP, AVIF, JPEG).
This makes SPAI robust where pixel-domain detectors fail.

Uses a TorchScript traced model (spai_full.pt) that internally handles
FFT decomposition and patchification. Input: (B, 3, H, W) normalized
tensor. Output: (B, 1) logit.

Paper: https://arxiv.org/abs/2411.19417
GitHub: https://github.com/mever-team/spai
License: Apache 2.0
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
try:
    import torch
    _TORCH_AVAILABLE = True
except ImportError:
    pass

# ImageNet normalization
_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


class SPAIDetectionAnalyzer(BaseAnalyzer):
    """SPAI spectral-learning AI image detector via TorchScript."""

    MODULE_NAME = "spai_detection"
    MODULE_LABEL = "SPAI spektralna AI detekcija"

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

        if not _TORCH_AVAILABLE:
            logger.warning("torch not available — SPAI disabled")
            self._models_loaded = True
            return

        if not getattr(settings, "forensics_spai_enabled", False):
            self._models_loaded = True
            return

        model_dir = getattr(
            settings, "forensics_spai_model_dir",
            os.path.join(settings.forensics_model_cache_dir, "spai"),
        )
        model_path = os.path.join(model_dir, "spai_full.pt")

        if not os.path.exists(model_path):
            logger.warning("SPAI TorchScript model not found at %s", model_path)
            self._models_loaded = True
            return

        try:
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
            self._model = torch.jit.load(model_path, map_location=self._device)
            self._model.eval()
            logger.info("SPAI TorchScript model loaded on %s from %s", self._device, model_path)
        except Exception as e:
            logger.warning("Failed to load SPAI model: %s", e)
            self._model = None

        self._models_loaded = True

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        start = time.monotonic()
        findings: list[AnalyzerFinding] = []

        if not getattr(settings, "forensics_spai_enabled", False):
            return self._make_result([], int((time.monotonic() - start) * 1000))

        try:
            self._ensure_models()

            if self._model is None:
                return self._make_result(
                    [], int((time.monotonic() - start) * 1000),
                    error="SPAI model not available",
                )

            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")

            score = self._compute_score(img)
            self._emit_findings(score, findings)

        except Exception as e:
            logger.warning("SPAI detection error: %s", e)
            return self._make_result(
                [], int((time.monotonic() - start) * 1000), error=str(e),
            )

        elapsed = int((time.monotonic() - start) * 1000)
        return self._make_result(findings, elapsed)

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([], 0)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _compute_score(self, img: Image.Image) -> float:
        """Run SPAI traced model. Input is normalized (B, 3, H, W).

        The traced model internally handles FFT decomposition and
        patchification for arbitrary-resolution images. We just need
        to resize to a multiple of 224 and normalize.
        """
        # Resize to nearest multiple of 224 (min 224x224)
        w, h = img.size
        new_h = max(224, (h // 224) * 224)
        new_w = max(224, (w // 224) * 224)
        if (new_h, new_w) != (h, w):
            img = img.resize((new_w, new_h), Image.LANCZOS)

        # Convert to tensor: (3, H, W) float32 in [0, 1]
        arr = np.array(img, dtype=np.float32) / 255.0  # (H, W, 3)
        # ImageNet normalize
        arr = (arr - _IMAGENET_MEAN) / _IMAGENET_STD
        # HWC → CHW → batch
        tensor = torch.from_numpy(arr.transpose(2, 0, 1)).unsqueeze(0).to(self._device)

        with torch.no_grad():
            logit = self._model(tensor)  # (1, 1)
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
                    code="SPAI_AI_DETECTED",
                    title="SPAI spektralna detekcija AI sadrzaja",
                    description=(
                        f"SPAI frekvencijska analiza (CVPR 2025) detektirala je "
                        f"snazne spektralne anomalije tipicne za AI generiranje "
                        f"(rezultat: {score:.0%}). Ova metoda je otporna na "
                        f"kompresiju (WebP, JPEG, AVIF)."
                    ),
                    risk_score=min(0.90, max(0.65, score * 0.90)),
                    confidence=min(0.90, 0.60 + score * 0.25),
                    evidence={"spai_score": round(score, 4), "method": "spai_torchscript"},
                )
            )
        elif score > 0.45:
            findings.append(
                AnalyzerFinding(
                    code="SPAI_AI_SUSPECTED",
                    title="SPAI sumnja na AI sadrzaj",
                    description=(
                        f"Spektralna analiza pokazuje umjerenu vjerojatnost "
                        f"({score:.0%}) da je slika umjetno generirana."
                    ),
                    risk_score=max(0.40, score * 0.75),
                    confidence=min(0.80, 0.45 + score * 0.30),
                    evidence={"spai_score": round(score, 4), "method": "spai_torchscript"},
                )
            )
        elif score > 0.25:
            findings.append(
                AnalyzerFinding(
                    code="SPAI_AI_LOW",
                    title="SPAI blagi spektralni indikatori",
                    description=(
                        f"Frekvencijska analiza pokazuje blage indikatore "
                        f"({score:.0%}) moguceg AI generiranja."
                    ),
                    risk_score=score * 0.50,
                    confidence=0.40 + score * 0.15,
                    evidence={"spai_score": round(score, 4), "method": "spai_torchscript"},
                )
            )
