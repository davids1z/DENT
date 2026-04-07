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
            # 5-crop test-time augmentation. The Swin transformer was
            # trained on 224x224 centre-cropped Wikimedia images, which
            # means the centre crop loses ~25% of horizontal content on
            # 16:9 photos. Averaging the AI probability over 4 corners
            # plus the centre recovers artefacts that would otherwise be
            # discarded. Same rationale as the CommFor TTA in
            # community_forensics.py.
            score = self._compute_score_tta(img)
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

    # Recognised "AI / fake" labels emitted by checkpoints in this family.
    # The base Organika/sdxl-detector ships with {"artificial", "human"}, but
    # forks and re-uploads have used variations (some include "ai_generated",
    # "generated", "synthetic", or "fake"). We accept the union so the
    # analyzer doesn't silently return 0 if the checkpoint is swapped.
    _AI_LABELS = frozenset({
        "artificial", "ai", "ai_generated", "ai-generated",
        "fake", "synthetic", "generated", "machine",
    })
    _HUMAN_LABELS = frozenset({
        "human", "real", "authentic", "natural", "photo",
    })

    # 5-crop TTA configuration. Swin-T was trained on 224x224 — we resize
    # the shortest side to 256 then take 4 corners + centre at 224. The
    # cost is 5x model forwards (~250-400 ms total on CPU), well within
    # the 120 s per-module budget.
    _TTA_RESIZE = 256
    _TTA_CROP = 224

    def _compute_score_tta(self, img: Image.Image) -> float:
        """Five-crop TTA wrapper around the single-crop _compute_score().

        Falls back to the single-image path if the image is smaller than
        the crop size, which can happen for thumbnail uploads.
        """
        w, h = img.size
        if min(w, h) < self._TTA_CROP:
            # Image too small for TTA — fall back to single forward pass
            return self._compute_score(img)

        # Resize shortest side to 256 (preserve aspect ratio)
        scale = self._TTA_RESIZE / min(w, h)
        new_w = int(round(w * scale))
        new_h = int(round(h * scale))
        resized = img.resize((new_w, new_h), Image.BILINEAR)

        # Build 5 crops: 4 corners + centre
        c = self._TTA_CROP
        crops = [
            resized.crop((0, 0, c, c)),                           # top-left
            resized.crop((new_w - c, 0, new_w, c)),               # top-right
            resized.crop((0, new_h - c, c, new_h)),               # bottom-left
            resized.crop((new_w - c, new_h - c, new_w, new_h)),   # bottom-right
            resized.crop((                                         # centre
                (new_w - c) // 2, (new_h - c) // 2,
                (new_w - c) // 2 + c, (new_h - c) // 2 + c,
            )),
        ]

        scores = [self._compute_score(crop) for crop in crops]
        mean = float(np.mean(scores))
        max_s = float(np.max(scores))
        min_s = float(np.min(scores))
        logger.info(
            "Organika 5-crop: scores=%s mean=%.4f max=%.4f spread=%.4f → using mean",
            [round(s, 3) for s in scores], mean, max_s, max_s - min_s,
        )
        return mean

    def _compute_score(self, img: Image.Image) -> float:
        """Classify image as artificial vs human.

        We look at the FULL list of returned labels, find the AI-side and
        human-side probabilities, and renormalise to be safe (some pipelines
        return top_k subsets that don't sum to 1.0). The 39.27% mystery
        observed on car-damage AI photos turned out to be the model genuinely
        hedging — when both classes come back close to 50/50, the artificial
        side is ~0.39 because the human side is ~0.61. Logging both sides
        here makes that visible in production.
        """
        results = self._pipe(img)
        ai_score = 0.0
        human_score = 0.0
        unknown: list[tuple[str, float]] = []
        for r in results:
            label = str(r.get("label", "")).lower().strip()
            score = float(r.get("score", 0.0))
            if label in self._AI_LABELS:
                ai_score = max(ai_score, score)
            elif label in self._HUMAN_LABELS:
                human_score = max(human_score, score)
            else:
                unknown.append((label, score))

        if unknown:
            logger.warning(
                "Organika returned unknown labels: %s "
                "(known: ai=%.4f human=%.4f) — extend _AI_LABELS / _HUMAN_LABELS",
                unknown, ai_score, human_score,
            )

        total = ai_score + human_score
        if total > 0 and abs(total - 1.0) > 0.05:
            # Renormalise — some pipelines return softmax over top_k only
            ai_score = ai_score / total

        logger.info(
            "Organika scores: ai=%.4f human=%.4f → using ai_score=%.4f",
            ai_score, human_score, ai_score,
        )
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
