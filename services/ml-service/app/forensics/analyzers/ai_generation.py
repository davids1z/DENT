"""
AI-Generated Image Detection Module

Uses an ensemble of two Swin Transformer classifiers trained specifically
on real-vs-fake image classification:

1. Organika/sdxl-detector  — fine-tuned on Wikimedia-SDXL pairs (98.1% acc)
   Better on modern diffusion model outputs (SDXL, DALLE-3, Midjourney v5+)

2. umm-maybe/AI-image-detector — trained on diverse AI generators (94.2% acc)
   Better coverage of older generators (VQGAN+CLIP, early Stable Diffusion)

Ensemble scoring provides robustness across generator types.
"""

import logging
import os
import time

import numpy as np
from PIL import Image
import io

from ...config import settings
from ..base import AnalyzerFinding, BaseAnalyzer, ModuleResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports — PyTorch and Transformers are heavy, only load when needed
# ---------------------------------------------------------------------------
_TORCH_AVAILABLE = False
_TRANSFORMERS_AVAILABLE = False

try:
    import torch  # noqa: F401

    _TORCH_AVAILABLE = True
except ImportError:
    logger.info("PyTorch not installed, AI generation detection disabled")

if _TORCH_AVAILABLE:
    try:
        import transformers  # noqa: F401

        _TRANSFORMERS_AVAILABLE = True
    except ImportError:
        logger.info("Transformers not installed, AI generation detection disabled")

# Model identifiers
MODEL_SDXL_DETECTOR = "Organika/sdxl-detector"
MODEL_AI_IMAGE_DETECTOR = "umm-maybe/AI-image-detector"

# Ensemble weights
SDXL_WEIGHT = 0.55  # Primary — better on modern generators
VIT_WEIGHT = 0.45   # Secondary — broader coverage


class AiGenerationAnalyzer(BaseAnalyzer):
    """AI-generated image detection using ensemble of trained classifiers."""

    MODULE_NAME = "ai_generation_detection"
    MODULE_LABEL = "Detekcija AI-generiranog sadrzaja"

    def __init__(self) -> None:
        self._models_loaded = False
        self._sdxl_pipe = None
        self._vit_pipe = None

    def _ensure_models(self) -> None:
        """Lazy-load detection models on first use. Downloads weights if not cached."""
        if self._models_loaded:
            return

        if not _TORCH_AVAILABLE or not _TRANSFORMERS_AVAILABLE:
            self._models_loaded = True
            return

        from transformers import pipeline as hf_pipeline

        cache_dir = os.path.join(settings.forensics_model_cache_dir, "ai_generation")
        os.makedirs(cache_dir, exist_ok=True)

        enabled_methods = [
            m.strip().lower()
            for m in settings.forensics_aigen_methods.split(",")
            if m.strip()
        ]

        # Load SDXL detector (primary)
        if "clip" in enabled_methods or "sdxl" in enabled_methods:
            try:
                self._sdxl_pipe = hf_pipeline(
                    "image-classification",
                    model=MODEL_SDXL_DETECTOR,
                    device=-1,  # CPU
                    model_kwargs={"cache_dir": cache_dir},
                )
                logger.info("SDXL detector loaded: %s", MODEL_SDXL_DETECTOR)
            except Exception as e:
                logger.warning("Failed to load SDXL detector: %s", e)
                self._sdxl_pipe = None

        # Load ViT AI image detector (secondary)
        if "vit" in enabled_methods:
            try:
                self._vit_pipe = hf_pipeline(
                    "image-classification",
                    model=MODEL_AI_IMAGE_DETECTOR,
                    device=-1,  # CPU
                    model_kwargs={"cache_dir": cache_dir},
                )
                logger.info("ViT AI detector loaded: %s", MODEL_AI_IMAGE_DETECTOR)
            except Exception as e:
                logger.warning("Failed to load ViT AI detector: %s", e)
                self._vit_pipe = None

        self._models_loaded = True

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        start = time.monotonic()
        findings: list[AnalyzerFinding] = []

        if not settings.forensics_aigen_enabled:
            elapsed = int((time.monotonic() - start) * 1000)
            return self._make_result([], elapsed)

        try:
            self._ensure_models()

            if self._sdxl_pipe is None and self._vit_pipe is None:
                elapsed = int((time.monotonic() - start) * 1000)
                return self._make_result(
                    [], elapsed,
                    error="No AI detection models available (transformers not installed?)"
                )

            # Open and prepare image
            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")

            # Run models sequentially (memory — CPU-only server)
            sdxl_score = self._run_sdxl_detector(img)
            vit_score = self._run_vit_detector(img)

            # Compute ensemble score
            ensemble_score, model_details = self._compute_ensemble(
                sdxl_score, vit_score
            )

            # Emit findings based on ensemble score
            self._emit_findings(ensemble_score, model_details, findings)

        except Exception as e:
            logger.warning("AI generation detection error: %s", e)
            elapsed = int((time.monotonic() - start) * 1000)
            return self._make_result([], elapsed, error=str(e))

        elapsed = int((time.monotonic() - start) * 1000)
        return self._make_result(findings, elapsed)

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([], 0)

    # ------------------------------------------------------------------
    # Model runners
    # ------------------------------------------------------------------

    def _run_sdxl_detector(self, img: Image.Image) -> float | None:
        """Run Organika/sdxl-detector. Returns P(artificial) or None if unavailable."""
        if self._sdxl_pipe is None:
            return None

        try:
            results = self._sdxl_pipe(img)
            # results = [{"label": "artificial", "score": 0.95}, {"label": "human", ...}]
            for r in results:
                if r["label"] == "artificial":
                    return float(r["score"])
            # If "artificial" label not found, return 0
            return 0.0
        except Exception as e:
            logger.warning("SDXL detector inference failed: %s", e)
            return None

    def _run_vit_detector(self, img: Image.Image) -> float | None:
        """Run umm-maybe/AI-image-detector. Returns P(artificial) or None if unavailable."""
        if self._vit_pipe is None:
            return None

        try:
            results = self._vit_pipe(img)
            for r in results:
                if r["label"] == "artificial":
                    return float(r["score"])
            return 0.0
        except Exception as e:
            logger.warning("ViT AI detector inference failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Ensemble
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_ensemble(
        sdxl_score: float | None, vit_score: float | None
    ) -> tuple[float, dict]:
        """
        Confidence-weighted ensemble of two models.
        Returns (ensemble_score, model_details_dict).
        """
        details: dict = {}

        if sdxl_score is not None:
            details["sdxl_detector_score"] = round(sdxl_score, 4)
        if vit_score is not None:
            details["vit_detector_score"] = round(vit_score, 4)

        # Both models available — weighted ensemble
        if sdxl_score is not None and vit_score is not None:
            ensemble = sdxl_score * SDXL_WEIGHT + vit_score * VIT_WEIGHT

            # If either model is very confident (>0.85), boost ensemble
            max_score = max(sdxl_score, vit_score)
            if max_score > 0.85:
                ensemble = max(ensemble, max_score * 0.90)

            # Agreement bonus: both models agree strongly
            if sdxl_score > 0.70 and vit_score > 0.70:
                ensemble = max(ensemble, (sdxl_score + vit_score) / 2 * 1.05)
                ensemble = min(ensemble, 1.0)

            details["ensemble_method"] = "weighted_average"
            details["agreement"] = "high" if abs(sdxl_score - vit_score) < 0.20 else "low"

        # Only one model available — use it directly
        elif sdxl_score is not None:
            ensemble = sdxl_score
            details["ensemble_method"] = "sdxl_only"
        elif vit_score is not None:
            ensemble = vit_score
            details["ensemble_method"] = "vit_only"
        else:
            ensemble = 0.0
            details["ensemble_method"] = "none"

        details["ensemble_score"] = round(ensemble, 4)
        return ensemble, details

    # ------------------------------------------------------------------
    # Findings
    # ------------------------------------------------------------------

    @staticmethod
    def _emit_findings(
        score: float, details: dict, findings: list[AnalyzerFinding]
    ) -> None:
        """Emit findings based on ensemble AI-generation score."""

        # Compute confidence based on model agreement
        agreement = details.get("agreement", "low")
        base_confidence = 0.90 if agreement == "high" else 0.75

        if score > 0.75:
            findings.append(
                AnalyzerFinding(
                    code="AIGEN_DETECTED",
                    title="Detektiran AI-generiran sadrzaj",
                    description=(
                        f"Ansambl neuronskih mreza (Swin Transformer klasifikatori "
                        f"obuceni na stvarnim i AI-generiranim slikama) detektirao je "
                        f"s visokom pouzdanoscu da je ova slika umjetno generirana "
                        f"(rezultat: {score:.0%}). Modeli prepoznaju statisticke "
                        f"obrasce karakteristicne za difuzijske generatore (Stable "
                        f"Diffusion, DALL-E, Midjourney)."
                    ),
                    risk_score=min(0.95, max(0.85, score)),
                    confidence=min(0.98, base_confidence + score * 0.08),
                    evidence=details,
                )
            )
        elif score > 0.50:
            findings.append(
                AnalyzerFinding(
                    code="AIGEN_SUSPECTED",
                    title="Sumnja na AI-generiran sadrzaj",
                    description=(
                        f"Ansambl detektora AI-generiranog sadrzaja pokazuje umjerenu "
                        f"vjerojatnost ({score:.0%}) da je slika umjetno generirana. "
                        f"Preporuca se dodatna rucna provjera."
                    ),
                    risk_score=max(0.50, score * 0.85),
                    confidence=base_confidence * 0.85,
                    evidence=details,
                )
            )
        elif score > 0.30:
            findings.append(
                AnalyzerFinding(
                    code="AIGEN_LOW_INDICATORS",
                    title="Blagi indikatori AI generiranja",
                    description=(
                        f"Detektori AI sadrzaja pokazuju niske indikatore "
                        f"({score:.0%}) moguceg AI generiranja. Vjerojatno "
                        f"autenticna slika s nekim neobicnim karakteristikama."
                    ),
                    risk_score=score * 0.65,
                    confidence=base_confidence * 0.70,
                    evidence=details,
                )
            )
