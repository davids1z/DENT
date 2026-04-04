"""
SigLIP AI Image Detection Module

Fine-tuned SigLIP (Sigmoid Loss for Language-Image Pre-training) model
for binary classification: AI-generated vs human-created images.

Model: Ateeqq/ai-vs-human-image-detector (92.9M params)
Training: 120K images (60K AI + 60K human)
Accuracy: 99.23% on test set, F1=0.9923

Key advantage over CLIP/DINOv2 probes: trained specifically for AI detection
on modern generators, not just embedding similarity.

License: Apache 2.0
"""

import io
import logging
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


class SigLIPAiDetectionAnalyzer(BaseAnalyzer):
    """SigLIP-based AI image detector — binary classifier (AI vs human)."""

    MODULE_NAME = "siglip_ai_detection"
    MODULE_LABEL = "SigLIP AI detekcija"

    def __init__(self) -> None:
        self._models_loaded = False
        self._model = None
        self._processor = None
        self._device = "cpu"

    def _ensure_models(self) -> None:
        if self._models_loaded:
            return

        if not _TORCH_AVAILABLE:
            logger.warning("PyTorch not available — SigLIP disabled")
            self._models_loaded = True
            return

        try:
            import os
            from transformers import AutoImageProcessor, SiglipForImageClassification

            # Use persistent HF cache in model volume
            hf_home = os.environ.get("HF_HOME", "/app/models/huggingface")
            os.environ["HF_HOME"] = hf_home

            model_id = "Ateeqq/ai-vs-human-image-detector"
            self._device = "cuda" if torch.cuda.is_available() else "cpu"

            self._processor = AutoImageProcessor.from_pretrained(model_id)
            self._model = SiglipForImageClassification.from_pretrained(model_id)
            self._model.to(self._device)
            self._model.eval()

            param_count = sum(p.numel() for p in self._model.parameters()) / 1e6
            logger.info("SigLIP AI detector loaded on %s: %.1fM params", self._device, param_count)

        except Exception as e:
            logger.warning("Failed to load SigLIP model: %s", e)
            self._model = None

        self._models_loaded = True

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        start = time.monotonic()
        findings: list[AnalyzerFinding] = []

        try:
            self._ensure_models()

            if self._model is None or self._processor is None:
                return self._make_result(
                    [], int((time.monotonic() - start) * 1000),
                    error="SigLIP model not available",
                )

            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")

            score = self._compute_score(img)
            self._emit_findings(score, findings)

        except Exception as e:
            logger.warning("SigLIP detection error: %s", e)
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
        """Compute AI probability via SigLIP classification."""
        inputs = self._processor(images=img, return_tensors="pt").to(self._device)

        with torch.no_grad():
            outputs = self._model(**inputs)
            logits = outputs.logits
            probs = torch.softmax(logits, dim=-1)

        # Find AI class index
        id2label = self._model.config.id2label
        ai_idx = None
        for idx, label in id2label.items():
            if label.lower() in ("ai", "ai_generated", "fake", "synthetic"):
                ai_idx = int(idx)
                break

        if ai_idx is not None:
            score = float(probs[0, ai_idx].cpu().item())
        else:
            # Fallback: assume class 0 = AI if label mapping unclear
            score = float(probs[0, 0].cpu().item())

        return float(np.clip(score, 0.0, 1.0))

    @staticmethod
    def _emit_findings(score: float, findings: list[AnalyzerFinding]) -> None:
        if score > 0.70:
            findings.append(
                AnalyzerFinding(
                    code="SIGLIP_AI_DETECTED",
                    title="SigLIP: detektiran AI-generiran sadrzaj",
                    description=(
                        f"SigLIP model (treniran na 120K slika) detektirao je "
                        f"snazne indikatore AI generiranja ({score:.0%}). "
                        f"Ovaj model pokriva moderne generatore ukljucujuci "
                        f"GPT Image, Flux, DALL-E 3 i Midjourney."
                    ),
                    risk_score=min(0.95, score),
                    confidence=min(0.95, score),
                    evidence={"siglip_score": round(score, 4), "method": "siglip_classifier"},
                )
            )
        elif score > 0.45:
            findings.append(
                AnalyzerFinding(
                    code="SIGLIP_AI_SUSPECTED",
                    title="SigLIP: sumnja na AI sadrzaj",
                    description=(
                        f"SigLIP analiza pokazuje umjerenu sumnju ({score:.0%}) "
                        f"da je slika umjetno generirana."
                    ),
                    risk_score=max(0.40, score * 0.80),
                    confidence=min(0.80, 0.50 + score * 0.30),
                    evidence={"siglip_score": round(score, 4), "method": "siglip_classifier"},
                )
            )
