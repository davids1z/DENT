"""
Organika SDXL Detector — Swin Transformer AI Image Detection

Fine-tuned Swin Transformer trained on Wikimedia vs SDXL-generated images.
Covers general images (not just faces/art), 98.1% accuracy, F1=0.973.

Model: Organika/sdxl-detector (86.8M params, ~350MB)
Training: Wikimedia real images vs SDXL synthetic images
Accuracy: 98.1%, F1=0.973, AUC=0.998

Key advantage: trained on general Wikimedia images (landscapes, objects,
buildings, people) — not just faces. Swin Transformer architecture is
fundamentally different from CLIP/DINOv2 (CNN-like hierarchical windows
vs global attention), providing an independent signal.

License: Open
"""

import io
import logging
import os
import time

import numpy as np
from PIL import Image

from ..base import AnalyzerFinding, BaseAnalyzer, ModuleResult

logger = logging.getLogger(__name__)

_TORCH_AVAILABLE = False
try:
    import torch
    _TORCH_AVAILABLE = True
except ImportError:
    pass


class OrganikaDetectionAnalyzer(BaseAnalyzer):
    """Organika/sdxl-detector — Swin Transformer binary classifier."""

    MODULE_NAME = "organika_ai_detection"
    MODULE_LABEL = "Organika AI detekcija (Swin)"

    def __init__(self) -> None:
        self._models_loaded = False
        self._pipe = None

    def _ensure_models(self) -> None:
        if self._models_loaded:
            return

        if not _TORCH_AVAILABLE:
            logger.warning("PyTorch not available — Organika disabled")
            self._models_loaded = True
            return

        try:
            from transformers import pipeline

            hf_home = os.environ.get("HF_HOME", "/app/models/huggingface")
            os.environ["HF_HOME"] = hf_home

            self._pipe = pipeline(
                "image-classification",
                model="Organika/sdxl-detector",
                device=-1,  # CPU
            )

            logger.info("Organika SDXL detector loaded (Swin Transformer)")

        except Exception as e:
            logger.warning("Failed to load Organika: %s", e)
            self._pipe = None

        self._models_loaded = True

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        start = time.monotonic()
        findings: list[AnalyzerFinding] = []

        try:
            self._ensure_models()

            if self._pipe is None:
                return self._make_result(
                    [], int((time.monotonic() - start) * 1000),
                    error="Organika model not available",
                )

            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            score = self._compute_score(img)
            self._emit_findings(score, findings)

        except Exception as e:
            logger.warning("Organika detection error: %s", e)
            return self._make_result(
                [], int((time.monotonic() - start) * 1000), error=str(e),
            )

        elapsed = int((time.monotonic() - start) * 1000)
        result = self._make_result(findings, elapsed)
        result.risk_score = round(score, 4)
        result.risk_score100 = round(score * 100)
        return result

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([], 0)

    def _compute_score(self, img: Image.Image) -> float:
        """Classify image as artificial vs human."""
        results = self._pipe(img)
        # Results: [{'label': 'artificial', 'score': 0.98}, {'label': 'human', 'score': 0.02}]
        ai_score = 0.0
        for r in results:
            if r["label"].lower() in ("artificial", "ai", "fake", "synthetic"):
                ai_score = float(r["score"])
                break
        return float(np.clip(ai_score, 0.0, 1.0))

    @staticmethod
    def _emit_findings(score: float, findings: list[AnalyzerFinding]) -> None:
        if score > 0.70:
            findings.append(AnalyzerFinding(
                code="ORGANIKA_AI_DETECTED",
                title="Organika: detektiran AI-generiran sadrzaj",
                description=(
                    f"Swin Transformer detektor (treniran na Wikimedia slikama) "
                    f"detektirao je AI artefakte ({score:.0%}). Pokriva SDXL "
                    f"i slicne diffusion generatore."
                ),
                risk_score=min(0.95, score),
                confidence=min(0.95, score),
                evidence={"organika_score": round(score, 4), "method": "swin_sdxl_detector"},
            ))
        elif score > 0.45:
            findings.append(AnalyzerFinding(
                code="ORGANIKA_AI_SUSPECTED",
                title="Organika: sumnja na AI sadrzaj",
                description=(
                    f"Swin Transformer analiza pokazuje umjerenu sumnju "
                    f"({score:.0%}) da je slika umjetno generirana."
                ),
                risk_score=max(0.40, score * 0.80),
                confidence=min(0.80, 0.50 + score * 0.30),
                evidence={"organika_score": round(score, 4), "method": "swin_sdxl_detector"},
            ))
