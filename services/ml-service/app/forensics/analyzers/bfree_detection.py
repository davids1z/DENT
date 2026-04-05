"""
B-Free AI Image Detection Module (CVPR 2025)

Bias-Free Training Paradigm for More General AI-generated Image Detection.
Uses DINOv2 ViT-Base with 4 register tokens, fine-tuned end-to-end on
27 generators including Flux and SD 3.5 with a bias-free training strategy.

Key insight: Standard training creates biases toward training-set compression
formats and generators. B-Free generates training fakes from real images via
SD conditioning, ensuring semantic alignment.

Architecture:
1. Input: 504×504 RGB image (36×36 patch grid)
2. DINOv2 ViT-Base with 4 register tokens → single logit
3. sigmoid(logit) → AI probability
4. Score > 0.50 → AI-generated

Official results: 0.3% on real, 98.8% on AI (demo images).
Validated on 27 generators across 4 benchmarks (Synthbuster, GenImage,
FakeInversion, SynthWildX), including Flux and SD 3.5.

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

# ImageNet normalization (as used in B-Free / DINOv2)
_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
_INPUT_SIZE = 504  # B-Free expects 504×504 for 36×36 patch grid (504/14=36)


class BFreeDetectionAnalyzer(BaseAnalyzer):
    """B-Free DINOv2 ViT-Base for AI image detection.

    Uses 378×378 input (27×27 patch grid = 729 tokens) to match the
    token count the model was fine-tuned on via 5-crop training.
    dynamic_img_size=True interpolates pos_embed from 36×36→27×27.
    """

    MODULE_NAME = "bfree_detection"
    MODULE_LABEL = "B-Free AI detekcija"

    # 27 patches × 14 pixels = 378 — matches 5-crop token count (729)
    _INFER_SIZE = 378

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

            # Create DINOv2 ViT-Base with 4 register tokens, single output.
            # dynamic_img_size=True lets timm interpolate pos_embed for any input size
            self._model = timm.create_model(
                "vit_base_patch14_reg4_dinov2.lvd142m",
                pretrained=False,
                num_classes=1,
                dynamic_img_size=True,
            )

            # Set input size to 504 to match checkpoint pos_embed (36×36 grid)
            if hasattr(self._model, 'set_input_size'):
                self._model.set_input_size(img_size=_INPUT_SIZE)

            # Load checkpoint — B-Free wraps state_dict under "model" key
            checkpoint = torch.load(weights_path, map_location=self._device, weights_only=True)

            if "model" in checkpoint:
                raw_sd = checkpoint["model"]
            elif "state_dict" in checkpoint:
                raw_sd = checkpoint["state_dict"]
            else:
                raw_sd = checkpoint

            # Remap keys from Wrapper5crops: "model.X" → "X", "patch_embed.*" stays
            state_dict = {}
            for k, v in raw_sd.items():
                if k.startswith("model."):
                    state_dict[k[len("model."):]] = v
                else:
                    state_dict[k] = v

            missing, unexpected = self._model.load_state_dict(state_dict, strict=False)

            n_loaded = len(state_dict) - len(unexpected)
            if n_loaded < 10:
                logger.error(
                    "B-Free: only %d keys loaded! %d missing, %d unexpected.",
                    n_loaded, len(missing), len(unexpected),
                )
                self._model = None
                self._models_loaded = True
                return

            self._model.to(self._device)
            self._model.eval()

            param_count = sum(p.numel() for p in self._model.parameters()) / 1e6
            logger.info(
                "B-Free model loaded on %s: %.1fM params, infer=%dx%d (%d patches), "
                "%d keys matched, %d missing, %d unexpected",
                self._device, param_count, self._INFER_SIZE, self._INFER_SIZE,
                (self._INFER_SIZE // 14) ** 2,
                n_loaded, len(missing), len(unexpected),
            )
            if missing:
                logger.debug("B-Free missing keys (first 5): %s", missing[:5])
            if unexpected:
                logger.debug("B-Free unexpected keys (first 5): %s", unexpected[:5])

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
        # Raw score passthrough for fusion
        result.risk_score = round(score, 4)
        result.risk_score100 = round(score * 100)
        return result

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([], 0)

    def _compute_score(self, img: Image.Image) -> float:
        """Compute AI probability via B-Free at 378×378 (27×27 patch grid).

        The model was fine-tuned with 5-crop where each crop = 729 tokens.
        Using 378×378 input gives the same 729 tokens (27×27) in a single
        forward pass. dynamic_img_size=True interpolates pos_embed from
        the checkpoint's 36×36 to inference 27×27.
        """
        import torch

        # Resize to 378×378 (27 patches × 14 pixels — matches 5-crop token count)
        img_resized = img.resize((self._INFER_SIZE, self._INFER_SIZE), Image.LANCZOS)
        arr = np.array(img_resized, dtype=np.float32) / 255.0
        arr = (arr - _IMAGENET_MEAN) / _IMAGENET_STD
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
                    code="BFREE_AI_DETECTED",
                    title="B-Free detekcija AI-generiranog sadrzaja",
                    description=(
                        f"B-Free model (CVPR 2025, 27 generatora) detektirao je "
                        f"snazne indikatore AI generiranja (rezultat: {score:.0%})."
                    ),
                    risk_score=min(0.90, max(0.65, score * 0.90)),
                    confidence=min(0.90, 0.60 + score * 0.25),
                    evidence={"bfree_score": round(score, 4), "method": "bfree_dinov2"},
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
                    evidence={"bfree_score": round(score, 4), "method": "bfree_dinov2"},
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
                    evidence={"bfree_score": round(score, 4), "method": "bfree_dinov2"},
                )
            )
