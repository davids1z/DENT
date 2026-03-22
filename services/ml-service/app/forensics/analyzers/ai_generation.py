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
                    device=0 if _TORCH_AVAILABLE and torch.cuda.is_available() else -1,
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
                    device=0 if _TORCH_AVAILABLE and torch.cuda.is_available() else -1,
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

            # Apply SRM high-pass filter preprocessing to extract noise residuals.
            # CNNDetect (CVPR 2020) showed this is the most important factor for
            # cross-generator generalisation — removes semantic content and reveals
            # noise-pattern artefacts invisible in the RGB domain.
            img_srm = self._apply_srm_filter(img)

            # Run models sequentially (memory — CPU-only server)
            # Feed SRM-filtered image alongside original for richer signal
            sdxl_score = self._run_sdxl_detector(img)
            vit_score = self._run_vit_detector(img)

            # Run detectors on SRM-filtered version too for cross-validation
            sdxl_srm = self._run_sdxl_detector(img_srm)
            vit_srm = self._run_vit_detector(img_srm)

            # Combine original and SRM scores — SRM as secondary signal (30% weight).
            # Using weighted average instead of max() to avoid false amplification:
            # real JPEG compression boundaries appear similar to AI artefacts through SRM.
            if sdxl_score is not None and sdxl_srm is not None:
                sdxl_score = sdxl_score * 0.7 + sdxl_srm * 0.3
            if vit_score is not None and vit_srm is not None:
                vit_score = vit_score * 0.7 + vit_srm * 0.3

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
        result = self._make_result(findings, elapsed)
        # Always pass raw ensemble score — don't threshold to 0.0
        # Meta-learner needs raw float, not binary threshold
        if ensemble_score is not None:
            result.risk_score = round(ensemble_score, 4)
            result.risk_score100 = round(ensemble_score * 100)
        return result

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([], 0)

    # ------------------------------------------------------------------
    # SRM preprocessing
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_srm_filter(img: Image.Image) -> Image.Image:
        """
        Apply Spatial Rich Model (SRM) high-pass filter to extract noise
        residuals.  Removes semantic content and exposes generation artifacts
        that are invisible in the RGB domain.

        Uses three classic SRM kernels from Fridrich (2012) that capture
        horizontal, vertical, and edge noise patterns.  The filtered image
        is normalized to [0, 255] for compatibility with classification models.
        """
        arr = np.array(img, dtype=np.float32)

        # SRM filter kernels (3 basic high-pass filters)
        kernels = [
            # Horizontal edge
            np.array([[ 0, 0, 0],
                       [-1, 2,-1],
                       [ 0, 0, 0]], dtype=np.float32),
            # Vertical edge
            np.array([[ 0,-1, 0],
                       [ 0, 2, 0],
                       [ 0,-1, 0]], dtype=np.float32),
            # Diagonal edge / Laplacian variant
            np.array([[-1, 0,-1],
                       [ 0, 4, 0],
                       [-1, 0,-1]], dtype=np.float32),
        ]

        # Apply each kernel and accumulate absolute responses
        from scipy.ndimage import convolve
        residual = np.zeros_like(arr)
        for k in kernels:
            for c in range(min(3, arr.shape[2]) if arr.ndim == 3 else 1):
                channel = arr[:, :, c] if arr.ndim == 3 else arr
                residual_ch = convolve(channel, k, mode="reflect")
                if arr.ndim == 3:
                    residual[:, :, c] += np.abs(residual_ch)
                else:
                    residual += np.abs(residual_ch)

        # Normalize to 0-255 range
        rmin, rmax = residual.min(), residual.max()
        if rmax > rmin:
            residual = (residual - rmin) / (rmax - rmin) * 255.0
        residual = residual.clip(0, 255).astype(np.uint8)

        return Image.fromarray(residual)

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

            # If either model is confident, boost ensemble toward max
            max_score = max(sdxl_score, vit_score)
            if max_score > 0.85:
                ensemble = max(ensemble, max_score * 0.90)
            elif max_score > 0.75:
                ensemble = max(ensemble, max_score * 0.85)

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
    def _attribute_generator(details: dict) -> tuple[str | None, float]:
        """
        Attribute the most likely AI generator family based on relative
        classifier scores. The SDXL detector is fine-tuned on Stable Diffusion
        outputs while the ViT detector has broader training.

        Returns (generator_name, confidence).
        """
        sdxl = details.get("sdxl_detector_score", 0)
        vit = details.get("vit_detector_score", 0)

        if sdxl < 0.40 and vit < 0.40:
            return None, 0.0

        delta = sdxl - vit

        if delta > 0.20 and sdxl > 0.60:
            # SDXL-specialized detector scores much higher → likely SD family
            return "Stable Diffusion", min(0.85, 0.60 + delta)
        elif delta < -0.15 and vit > 0.60:
            # General detector scores higher → older/diverse generators
            return "GAN/Other AI", min(0.70, 0.50 + abs(delta))
        elif sdxl > 0.70 and vit > 0.70 and abs(delta) < 0.10:
            # Both score high and close → likely Midjourney or DALL-E
            # (these generators trigger both detectors equally)
            return "Midjourney/DALL-E", min(0.75, (sdxl + vit) / 2 * 0.85)
        elif sdxl > 0.50 or vit > 0.50:
            return "AI generator (neodredeni)", min(0.60, max(sdxl, vit) * 0.70)

        return None, 0.0

    @staticmethod
    def _emit_findings(
        score: float, details: dict, findings: list[AnalyzerFinding]
    ) -> None:
        """Emit findings based on ensemble AI-generation score."""

        # Compute confidence from model agreement and individual probabilities
        agreement = details.get("agreement", "low")
        sdxl_prob = details.get("sdxl_detector_score", 0)
        vit_prob = details.get("vit_detector_score", 0)
        if agreement == "high":
            base_confidence = min(0.95, 0.80 + (sdxl_prob + vit_prob) / 2 * 0.15)
        else:
            base_confidence = min(0.88, 0.65 + max(sdxl_prob, vit_prob) * 0.20)

        # Source generator attribution
        gen_name, gen_conf = AiGenerationAnalyzer._attribute_generator(details)
        if gen_name:
            details["predicted_generator"] = gen_name
            details["generator_confidence"] = round(gen_conf, 4)

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
                    risk_score=max(0.55, score * 0.95),
                    confidence=base_confidence * 0.92,
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
