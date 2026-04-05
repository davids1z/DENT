"""
AI Source Detector — ViT-Base Patch16 multi-class AI image classifier.

Identifies the SPECIFIC generator that produced an AI image: Stable Diffusion,
Midjourney, DALL-E, or other AI tools. Also classifies real/authentic images.

Model: yaya36095/ai-source-detector (86M params, ViT-Base Patch16)
Output classes: stable_diffusion, midjourney, dalle, real, other_ai
Accuracy: 91.6% test, Macro F1=0.914

Key advantage: not just binary AI/real — attributes the source generator,
providing evidence for insurance fraud investigation. Architecture is
ViT-Base (global self-attention), independent from CNN/Swin family.

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

# Classes that indicate AI generation (everything except "real")
_AI_CLASSES = frozenset({"stable_diffusion", "midjourney", "dalle", "other_ai"})

# Human-readable generator names for findings
_GENERATOR_LABELS = {
    "stable_diffusion": "Stable Diffusion",
    "midjourney": "Midjourney",
    "dalle": "DALL-E",
    "other_ai": "Drugi AI generator",
    "real": "Autentična slika",
}


class AiSourceDetectionAnalyzer(BaseAnalyzer):
    """yaya36095/ai-source-detector — ViT-Base multi-class AI source classifier."""

    MODULE_NAME = "ai_source_detection"
    MODULE_LABEL = "AI Source detekcija"

    def __init__(self) -> None:
        self._models_loaded = False
        self._pipe = None

    def _ensure_models(self) -> None:
        if self._models_loaded:
            return

        if not _TORCH_AVAILABLE:
            logger.warning("PyTorch not available — AI Source detector disabled")
            self._models_loaded = True
            return

        try:
            from transformers import pipeline

            hf_home = os.environ.get("HF_HOME", "/app/models/huggingface")
            os.environ["HF_HOME"] = hf_home

            self._pipe = pipeline(
                "image-classification",
                model="yaya36095/ai-source-detector",
                device=-1,  # CPU
            )

            logger.info("AI Source detector loaded (ViT-Base Patch16, 5 classes)")

        except Exception as e:
            logger.warning("Failed to load AI Source detector: %s", e)
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
                    error="AI Source detector model not available",
                )

            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            score, top_generator, top_gen_score, class_scores = self._compute_score(img)
            self._emit_findings(score, top_generator, top_gen_score, class_scores, findings)

        except Exception as e:
            logger.warning("AI Source detection error: %s", e)
            return self._make_result(
                [], int((time.monotonic() - start) * 1000), error=str(e),
            )

        elapsed = int((time.monotonic() - start) * 1000)
        result = self._make_result(findings, elapsed)
        # Raw score passthrough — no clamping by _make_result
        result.risk_score = round(score, 4)
        result.risk_score100 = round(score * 100)
        return result

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([], 0)

    def _compute_score(
        self, img: Image.Image
    ) -> tuple[float, str, float, dict[str, float]]:
        """Classify image and return (ai_score, top_generator, top_gen_score, all_class_scores).

        ai_score = 1.0 - P(real), i.e. sum of all non-"real" class probabilities.
        top_generator = class with highest score among AI classes.
        """
        results = self._pipe(img, top_k=5)  # Get all 5 classes

        # Build class score map
        class_scores: dict[str, float] = {}
        for r in results:
            class_scores[r["label"].lower()] = float(r["score"])

        # AI score = 1 - P(real)
        real_score = class_scores.get("real", 0.0)
        ai_score = 1.0 - real_score

        # Find top AI generator
        top_generator = "other_ai"
        top_gen_score = 0.0
        for cls in _AI_CLASSES:
            s = class_scores.get(cls, 0.0)
            if s > top_gen_score:
                top_gen_score = s
                top_generator = cls

        ai_score = float(np.clip(ai_score, 0.0, 1.0))
        return ai_score, top_generator, top_gen_score, class_scores

    @staticmethod
    def _emit_findings(
        score: float,
        top_generator: str,
        top_gen_score: float,
        class_scores: dict[str, float],
        findings: list[AnalyzerFinding],
    ) -> None:
        gen_label = _GENERATOR_LABELS.get(top_generator, top_generator)

        if score > 0.70:
            findings.append(AnalyzerFinding(
                code="AI_SOURCE_DETECTED",
                title=f"AI Source: detektiran {gen_label}",
                description=(
                    f"ViT-Base detektor identificirao je sliku kao AI-generiranu "
                    f"({score:.0%}) s najvecom vjerojatnošcu za {gen_label} "
                    f"({top_gen_score:.0%}). Model pokriva Stable Diffusion, "
                    f"Midjourney, DALL-E i druge generatore."
                ),
                risk_score=min(0.95, score),
                confidence=min(0.95, score),
                evidence={
                    "generator": top_generator,
                    "generator_label": gen_label,
                    "generator_score": round(top_gen_score, 4),
                    "ai_score": round(score, 4),
                    "class_scores": {k: round(v, 4) for k, v in class_scores.items()},
                    "method": "vit_base_ai_source_detector",
                },
            ))
        elif score > 0.45:
            findings.append(AnalyzerFinding(
                code="AI_SOURCE_SUSPECTED",
                title=f"AI Source: sumnja na {gen_label}",
                description=(
                    f"ViT-Base analiza pokazuje umjerenu sumnju ({score:.0%}) "
                    f"da je slika umjetno generirana. Najvjerojatniji izvor: "
                    f"{gen_label} ({top_gen_score:.0%})."
                ),
                risk_score=max(0.40, score * 0.80),
                confidence=min(0.80, 0.50 + score * 0.30),
                evidence={
                    "generator": top_generator,
                    "generator_label": gen_label,
                    "generator_score": round(top_gen_score, 4),
                    "ai_score": round(score, 4),
                    "class_scores": {k: round(v, 4) for k, v in class_scores.items()},
                    "method": "vit_base_ai_source_detector",
                },
            ))
