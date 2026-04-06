"""
RA-Det Simplified — Robustness Asymmetry AI Detection

Based on "RA-Det: Towards Universal Detection of AI-Generated Images via
Robustness Asymmetry" (arXiv 2603.01544, March 2026).

Core insight: Real photographs maintain stable deep feature representations
under small perturbations, while AI-generated images exhibit significantly
larger feature drift ("collapse"). This behavioral difference is a generator-
agnostic detection signal.

Simplified implementation:
- Reuses the existing DINOv2-large encoder (no new model download)
- Uses Gaussian noise perturbation (full RA-Det uses a learned UNet)
- Measures L2 drift + cosine similarity across N trials
- Classifies via calibrated thresholds (no training needed)

Expected: ~5-10% less accurate than full RA-Det (learned UNet), but zero
additional VRAM cost and no training required. Upgrade path: replace Gaussian
noise with learned UNet when GPU server is available.
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

_TORCH_AVAILABLE = False
_TRANSFORMERS_AVAILABLE = False

try:
    import torch
    import torch.nn.functional as F

    _TORCH_AVAILABLE = True
except ImportError:
    pass

if _TORCH_AVAILABLE:
    try:
        import transformers  # noqa: F401

        _TRANSFORMERS_AVAILABLE = True
    except ImportError:
        pass

# Perturbation parameters (from RA-Det paper, Section 3.2)
_DEFAULT_EPSILON = 16 / 255  # ~0.063, standard adversarial perturbation bound
_DEFAULT_N_TRIALS = 5  # Number of perturbation trials for averaging
# Thresholds calibrated from local testing:
# Real car photos: L2 = 4-5, cosine = 0.995
# AI faces (StyleGAN): L2 = 16-17, cosine = 0.91
# Threshold set conservatively to minimize FP on authentic images.
_DEFAULT_L2_THRESHOLD_LOW = 8.0   # Below this = likely authentic
_DEFAULT_L2_THRESHOLD_HIGH = 14.0  # Above this = likely AI
_DEFAULT_COSINE_THRESHOLD = 0.960  # Below this = likely AI


class RADetAnalyzer(BaseAnalyzer):
    """RA-Det simplified: perturbation robustness probe for AI detection.

    Reuses DINOv2-large from the existing DINOv2AiDetectionAnalyzer.
    No additional model downloads required.
    """

    MODULE_NAME = "radet_detection"
    MODULE_LABEL = "RA-Det robusnost AI detekcija"

    def __init__(self) -> None:
        self._models_loaded = False
        self._processor = None
        self._model = None
        self._device = "cpu"

    def _ensure_models(self) -> None:
        if self._models_loaded:
            return

        if not _TORCH_AVAILABLE or not _TRANSFORMERS_AVAILABLE:
            self._models_loaded = True
            return

        from transformers import AutoImageProcessor, AutoModel

        model_name = "facebook/dinov2-large"
        cache_dir = os.path.join(settings.forensics_model_cache_dir, "dinov2")
        os.makedirs(cache_dir, exist_ok=True)

        try:
            self._processor = AutoImageProcessor.from_pretrained(
                model_name, cache_dir=cache_dir
            )
            self._device = (
                "cuda" if _TORCH_AVAILABLE and torch.cuda.is_available() else "cpu"
            )
            self._model = AutoModel.from_pretrained(
                model_name, cache_dir=cache_dir
            ).to(self._device)
            self._model.eval()
            logger.info("RA-Det loaded DINOv2-large on %s", self._device)
        except Exception as e:
            logger.warning("RA-Det failed to load DINOv2: %s", e)
            self._processor = None
            self._model = None

        self._models_loaded = True

    def _extract_cls_embedding(self, pixel_values: "torch.Tensor") -> "torch.Tensor":
        """Extract CLS token embedding from DINOv2."""
        with torch.no_grad():
            outputs = self._model(pixel_values=pixel_values)
            # DINOv2 CLS token is first position in last_hidden_state
            return outputs.last_hidden_state[:, 0, :]  # [B, 1024]

    def _measure_robustness(
        self,
        pixel_values: "torch.Tensor",
        epsilon: float = _DEFAULT_EPSILON,
        n_trials: int = _DEFAULT_N_TRIALS,
    ) -> tuple[float, float, float]:
        """Measure embedding stability under Gaussian perturbation.

        Returns:
            (mean_l2_drift, mean_cosine_sim, drift_std)
        """
        # Clean embedding
        clean_emb = self._extract_cls_embedding(pixel_values)  # [1, 1024]
        clean_emb_norm = F.normalize(clean_emb, p=2, dim=1)

        l2_drifts = []
        cosine_sims = []

        for _ in range(n_trials):
            # Gaussian perturbation clamped to epsilon ball
            noise = torch.randn_like(pixel_values) * epsilon
            noise = noise.clamp(-epsilon, epsilon)
            perturbed = pixel_values + noise

            # Perturbed embedding
            noisy_emb = self._extract_cls_embedding(perturbed)
            noisy_emb_norm = F.normalize(noisy_emb, p=2, dim=1)

            # L2 distance (unnormalized embeddings)
            l2 = torch.norm(clean_emb - noisy_emb, p=2, dim=1).item()
            l2_drifts.append(l2)

            # Cosine similarity (normalized embeddings)
            cos = F.cosine_similarity(clean_emb_norm, noisy_emb_norm, dim=1).item()
            cosine_sims.append(cos)

        mean_l2 = float(np.mean(l2_drifts))
        mean_cos = float(np.mean(cosine_sims))
        std_l2 = float(np.std(l2_drifts))

        return mean_l2, mean_cos, std_l2

    def _compute_score(
        self, mean_l2: float, mean_cos: float, std_l2: float
    ) -> float:
        """Convert robustness metrics to AI probability score 0-1.

        Real images: small L2 drift, high cosine similarity, low variance
        AI images: large L2 drift, lower cosine similarity, higher variance
        """
        # L2 component: linear interpolation between thresholds
        l2_score = np.clip(
            (mean_l2 - _DEFAULT_L2_THRESHOLD_LOW)
            / (_DEFAULT_L2_THRESHOLD_HIGH - _DEFAULT_L2_THRESHOLD_LOW),
            0.0,
            1.0,
        )

        # Cosine component: how far below stable threshold
        cos_score = np.clip(
            (_DEFAULT_COSINE_THRESHOLD - mean_cos) / 0.030,
            0.0,
            1.0,
        )

        # Variance component: AI images have more variable drift
        var_score = np.clip(std_l2 / 2.0, 0.0, 1.0)

        # Weighted combination (L2 is most reliable per RA-Det ablation)
        score = 0.55 * l2_score + 0.30 * cos_score + 0.15 * var_score
        return float(np.clip(score, 0.0, 1.0))

    async def analyze_image(
        self, image_bytes: bytes, filename: str
    ) -> ModuleResult:
        start = time.monotonic()
        findings: list[AnalyzerFinding] = []

        try:
            self._ensure_models()
            if self._model is None or self._processor is None:
                return self._make_result([], 0, error="RA-Det model not available")

            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

            # Preprocess with DINOv2 processor
            inputs = self._processor(images=img, return_tensors="pt")
            pixel_values = inputs["pixel_values"].to(self._device)

            # Measure robustness (N forward passes)
            mean_l2, mean_cos, std_l2 = self._measure_robustness(pixel_values)

            # Convert to score
            score = self._compute_score(mean_l2, mean_cos, std_l2)

            evidence = {
                "radet_score": round(score, 4),
                "l2_drift": round(mean_l2, 4),
                "cosine_sim": round(mean_cos, 6),
                "drift_std": round(std_l2, 4),
                "n_trials": _DEFAULT_N_TRIALS,
                "epsilon": round(_DEFAULT_EPSILON, 4),
                "method": "radet_gaussian_simplified",
            }

            logger.info(
                "RA-Det: L2=%.3f cos=%.5f std=%.3f → score=%.4f (%s)",
                mean_l2,
                mean_cos,
                std_l2,
                score,
                filename,
            )

            self._emit_findings(score, evidence, findings)

        except Exception as e:
            logger.warning("RA-Det detection error: %s", e)
            return self._make_result([], 0, error=str(e))

        elapsed = int((time.monotonic() - start) * 1000)
        result = self._make_result(findings, elapsed)
        result.risk_score = round(score, 4)
        result.risk_score100 = round(score * 100)
        return result

    async def analyze_document(
        self, doc_bytes: bytes, filename: str
    ) -> ModuleResult:
        return self._make_result([], 0)

    @staticmethod
    def _emit_findings(
        score: float,
        evidence: dict,
        findings: list[AnalyzerFinding],
    ) -> None:
        if score > 0.70:
            findings.append(
                AnalyzerFinding(
                    code="RADET_AI_DETECTED",
                    title="RA-Det detekcija AI-generiranog sadrzaja",
                    description=(
                        f"RA-Det analiza robusnosti detektirala je nestabilnost "
                        f"dubinskih znacajki pod perturbacijom (L2 drift: "
                        f"{evidence['l2_drift']:.3f}, cosine: {evidence['cosine_sim']:.5f}). "
                        f"Autenticne slike su stabilne, AI slike 'kolabiraju' — "
                        f"ovo ukazuje na AI-generirani sadrzaj (rezultat: {score:.0%})."
                    ),
                    risk_score=min(0.93, max(0.70, score * 0.93)),
                    confidence=min(0.93, 0.65 + score * 0.25),
                    evidence=evidence,
                )
            )
        elif score > 0.45:
            findings.append(
                AnalyzerFinding(
                    code="RADET_AI_SUSPECTED",
                    title="RA-Det sumnja na AI sadrzaj",
                    description=(
                        f"RA-Det analiza robusnosti pokazuje umjerenu nestabilnost "
                        f"(L2 drift: {evidence['l2_drift']:.3f}), sto moze ukazivati "
                        f"na AI-generirani sadrzaj (rezultat: {score:.0%})."
                    ),
                    risk_score=max(0.40, score * 0.78),
                    confidence=min(0.80, 0.45 + score * 0.30),
                    evidence=evidence,
                )
            )
