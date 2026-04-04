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
    """B-Free DINOv2 ViT-Base with 5-crop for AI image detection."""

    MODULE_NAME = "bfree_detection"
    MODULE_LABEL = "B-Free AI detekcija"

    _CROP_PERCENTAGE = 0.75  # 75% of grid = 27 patches from 36

    def __init__(self) -> None:
        self._models_loaded = False
        self._model = None       # ViT backbone (patch_embed replaced with Identity)
        self._patch_embed = None  # Extracted patch_embed Conv2d
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
            # dynamic_img_size=True allows variable token counts (needed for
            # 5-crop: each crop is 27×27=729 tokens, pos_embed is for 36×36=1296)
            model = timm.create_model(
                "vit_base_patch14_reg4_dinov2.lvd142m",
                pretrained=False,
                num_classes=1,
                dynamic_img_size=True,
            )

            # Set input size to 504 to match checkpoint (36×36 patch grid)
            if hasattr(model, 'set_input_size'):
                model.set_input_size(img_size=_INPUT_SIZE)

            # Load checkpoint — B-Free wraps state_dict under "model" key
            checkpoint = torch.load(weights_path, map_location=self._device, weights_only=True)

            # Extract nested state_dict
            if "model" in checkpoint:
                raw_sd = checkpoint["model"]
            elif "state_dict" in checkpoint:
                raw_sd = checkpoint["state_dict"]
            else:
                raw_sd = checkpoint

            # Remap keys from official Wrapper5crops format:
            # Official structure: "patch_embed.*" stays, "model.X" → "X"
            state_dict = {}
            for k, v in raw_sd.items():
                if k.startswith("model."):
                    state_dict[k[len("model."):]] = v
                else:
                    state_dict[k] = v

            missing, unexpected = model.load_state_dict(state_dict, strict=False)

            n_loaded = len(state_dict) - len(unexpected)
            if n_loaded < 10:
                logger.error(
                    "B-Free: only %d keys loaded! %d missing, %d unexpected.",
                    n_loaded, len(missing), len(unexpected),
                )
                self._model = None
                self._models_loaded = True
                return

            # Extract patch_embed and replace with Identity (official 5-crop approach)
            # The ViT backbone will receive pre-computed embeddings, not raw pixels
            self._patch_embed = model.patch_embed
            model.patch_embed = torch.nn.Identity()

            model.to(self._device)
            model.eval()
            self._model = model

            param_count = sum(p.numel() for p in model.parameters()) / 1e6
            pe_count = sum(p.numel() for p in self._patch_embed.parameters()) / 1e6
            logger.info(
                "B-Free model loaded on %s: %.1fM params (backbone) + %.2fM (patch_embed), "
                "input=%dx%d, 5-crop=%d patches, %d keys matched, %d missing, %d unexpected",
                self._device, param_count, pe_count, _INPUT_SIZE, _INPUT_SIZE,
                int((_INPUT_SIZE // 14 * self._CROP_PERCENTAGE) ** 2),
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

    # ------------------------------------------------------------------
    # Scoring — single forward pass (no 5-crop for simplicity)
    # ------------------------------------------------------------------

    def _compute_score(self, img: Image.Image) -> float:
        """Compute AI probability via B-Free 5-crop in embedding space.

        Official approach (Wrapper5crops):
        1. patch_embed(504×504 image) → 36×36 embedding grid
        2. Crop 5 regions of 27×27 from the grid (center + 4 corners)
        3. Run each crop through ViT backbone (729 tokens per crop)
        4. Average 5 sigmoid outputs
        """
        import torch

        # Resize to 504×504 and normalize
        img_resized = img.resize((_INPUT_SIZE, _INPUT_SIZE), Image.LANCZOS)
        arr = np.array(img_resized, dtype=np.float32) / 255.0
        arr = (arr - _IMAGENET_MEAN) / _IMAGENET_STD
        tensor = torch.from_numpy(arr.transpose(2, 0, 1)).unsqueeze(0).to(self._device)

        with torch.no_grad():
            # Step 1: Run patch_embed on full 504×504 image
            embeddings = self._patch_embed(tensor)
            # timm patch_embed may return (B, N, D) or (B, H, W, D)
            if embeddings.dim() == 4:
                B, H, W, D = embeddings.shape
                embeddings = embeddings.reshape(B, H * W, D)
            B, N, D = embeddings.shape

            # Step 2: Reshape to 2D spatial grid
            side = int(N ** 0.5)  # 36
            grid = embeddings.reshape(B, side, side, D)

            # Step 3: Create 5 crops (center + 4 corners)
            crop_side = int(side * self._CROP_PERCENTAGE)  # 27
            s = (side - crop_side) // 2  # offset for center crop = 4

            crops = [
                grid[:, s:s + crop_side, s:s + crop_side, :],    # center
                grid[:, :crop_side, :crop_side, :],               # top-left
                grid[:, :crop_side, -crop_side:, :],              # top-right
                grid[:, -crop_side:, :crop_side, :],              # bottom-left
                grid[:, -crop_side:, -crop_side:, :],             # bottom-right
            ]

            # Flatten spatial dims and concatenate along batch
            flat_crops = [c.reshape(B, crop_side * crop_side, D) for c in crops]
            batch_crops = torch.cat(flat_crops, dim=0)  # (5, 729, 768)

            # Step 4: Forward through ViT backbone (patch_embed = Identity)
            # dynamic_img_size=True handles pos_embed interpolation from 36×36 to 27×27
            logits = self._model(batch_crops)  # (5, 1)

            # Step 5: Average the 5 predictions
            avg_logit = logits.mean(dim=0)
            score = float(torch.sigmoid(avg_logit.squeeze()).cpu().item())

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
