"""
B-Free AI Image Detection Module (CVPR 2025)

Bias-Free Training Paradigm for More General AI-generated Image Detection.
Uses DINOv2 ViT-Base with 4 register tokens, fine-tuned end-to-end on
27 generators including Flux and SD 3.5 with a bias-free training strategy.

Key insight: Standard training creates biases toward training-set compression
formats and generators. B-Free generates training fakes from real images via
SD conditioning, ensuring semantic alignment.

Architecture (Wrapper5crops):
1. Input: RGB image at original resolution (no fixed resize)
2. patch_embed.proj (Conv2d 14x14) -> embedding grid
3. Pad grid to at least 36x36 if smaller (replicate padding)
4. Extract 5 spatial crops (center + 4 corners) of 36x36 from the grid
5. Flatten + norm each crop -> 1296 tokens
6. Forward each crop through the ViT backbone (pos_embed sized for 36x36)
7. Average 5 logits -> sigmoid -> AI probability

The 5-crop approach provides spatial diversity: different regions of the
image may contain different AI artifacts. For images exactly 504px, the
5 crops are identical (36x36 grid = full grid). For larger images, each
crop captures a different spatial region.

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
    import torch.nn.functional as F

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

# B-Free model config
_GRID_SIZE = 504  # set_input_size(504) -> 36x36 patch grid (504/14=36)
_PATCH_DIM = 14   # ViT patch size
_GRID_DIM = _GRID_SIZE // _PATCH_DIM  # 36

# Cap the input image longest edge to limit memory. The model benefits from
# larger images (more spatial diversity in 5-crop), but beyond ~1008px the
# embedding grid exceeds 72x72 (5184 tokens per crop forward) which is
# expensive. 756px (54x54 grid) is a good balance: meaningful crop diversity
# without excessive memory.
_MAX_EDGE = 756


class BFreeDetectionAnalyzer(BaseAnalyzer):
    """B-Free DINOv2 ViT-Base for AI image detection.

    Implements the official Wrapper5crops inference:
    1. Run patch_embed.proj separately on the full image
    2. Crop 5 regions of 36x36 from the embedding grid (center + 4 corners)
    3. Flatten + norm each crop to (1296, 768) token sequences
    4. Forward each through the ViT backbone (Identity patch_embed)
    5. Average the 5 logits

    The model is created WITHOUT dynamic_img_size (matching official code).
    pos_embed is sized for 36x36 = 1296 tokens via set_input_size(504).
    """

    MODULE_NAME = "bfree_detection"
    MODULE_LABEL = "B-Free AI detekcija"

    def __init__(self) -> None:
        self._models_loaded = False
        self._model = None          # ViT backbone (with Identity patch_embed)
        self._patch_embed = None    # Real PatchEmbed (Conv2d 14x14 + norm)
        self._grid_size = None      # (36, 36) — crop target size
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

        cache_dir = getattr(
            settings,
            "forensics_bfree_model_dir",
            os.path.join(settings.forensics_model_cache_dir, "bfree"),
        )
        weights_path = os.path.join(cache_dir, "model_epoch_best.pth")

        if not os.path.exists(weights_path):
            logger.warning("B-Free weights not found at %s", weights_path)
            self._models_loaded = True
            return

        try:
            self._device = "cuda" if torch.cuda.is_available() else "cpu"

            # -------------------------------------------------------
            # 1. Create model exactly as official code does:
            #    timm.create_model(name, num_classes=1)
            #    NO dynamic_img_size (official doesn't use it)
            # -------------------------------------------------------
            model = timm.create_model(
                "vit_base_patch14_reg4_dinov2.lvd142m",
                pretrained=False,
                num_classes=1,
            )

            # Set input size to 504 -> pos_embed resized to 36x36 = 1296 tokens
            model.set_input_size(img_size=_GRID_SIZE)

            # -------------------------------------------------------
            # 2. Extract real patch_embed (Conv2d proj + norm)
            #    and replace with Identity (official Wrapper5crops approach)
            # -------------------------------------------------------
            self._patch_embed = model.patch_embed
            self._grid_size = self._patch_embed.grid_size  # (36, 36)
            model.patch_embed = torch.nn.Identity()

            # -------------------------------------------------------
            # 3. Load checkpoint
            #    Checkpoint["model"] contains Wrapper5crops state_dict:
            #    - "patch_embed.*" keys -> real patch_embed
            #    - everything else     -> inner model (Identity patch_embed)
            # -------------------------------------------------------
            checkpoint = torch.load(
                weights_path, map_location=self._device, weights_only=True
            )

            if "model" in checkpoint:
                raw_sd = checkpoint["model"]
            elif "state_dict" in checkpoint:
                raw_sd = checkpoint["state_dict"]
            else:
                raw_sd = checkpoint

            # Split keys: patch_embed.* -> real patch_embed, rest -> model
            pe_sd = {}
            model_sd = {}
            for k, v in raw_sd.items():
                if k.startswith("patch_embed."):
                    pe_sd[k[len("patch_embed."):]] = v
                else:
                    model_sd[k] = v

            # Load patch_embed weights
            pe_missing, pe_unexpected = self._patch_embed.load_state_dict(
                pe_sd, strict=False
            )

            # Load model weights (backbone + head)
            model_missing, model_unexpected = model.load_state_dict(
                model_sd, strict=False
            )

            # Total loaded
            n_pe_loaded = len(pe_sd) - len(pe_unexpected)
            n_model_loaded = len(model_sd) - len(model_unexpected)
            n_total_loaded = n_pe_loaded + n_model_loaded
            all_missing = list(pe_missing) + [
                f"patch_embed.{k}" for k in model_missing
            ]
            all_unexpected = list(pe_unexpected) + list(model_unexpected)

            if n_total_loaded < 10:
                logger.error(
                    "B-Free: only %d keys loaded! %d missing, %d unexpected.",
                    n_total_loaded,
                    len(all_missing),
                    len(all_unexpected),
                )
                self._model = None
                self._patch_embed = None
                self._models_loaded = True
                return

            model.to(self._device)
            model.eval()
            self._patch_embed.to(self._device)
            self._patch_embed.eval()
            self._model = model

            param_count = sum(p.numel() for p in model.parameters()) / 1e6
            pe_param_count = sum(p.numel() for p in self._patch_embed.parameters()) / 1e6
            logger.info(
                "B-Free model loaded on %s: %.1fM backbone + %.1fM patch_embed params, "
                "grid=%dx%d (%d tokens), %d keys matched (%d pe + %d backbone), "
                "%d missing, %d unexpected",
                self._device,
                param_count,
                pe_param_count,
                self._grid_size[0],
                self._grid_size[1],
                self._grid_size[0] * self._grid_size[1],
                n_total_loaded,
                n_pe_loaded,
                n_model_loaded,
                len(all_missing),
                len(all_unexpected),
            )
            if all_missing:
                logger.debug("B-Free missing keys (first 5): %s", all_missing[:5])
            if all_unexpected:
                logger.debug(
                    "B-Free unexpected keys (first 5): %s", all_unexpected[:5]
                )

        except Exception as e:
            logger.warning("Failed to load B-Free model: %s", e, exc_info=True)
            self._model = None
            self._patch_embed = None

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

            if self._model is None or self._patch_embed is None:
                return self._make_result(
                    [],
                    int((time.monotonic() - start) * 1000),
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
                [],
                int((time.monotonic() - start) * 1000),
                error=str(e),
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
        """Compute AI probability via B-Free with 5-crop wrapper.

        Follows the official Wrapper5crops inference exactly:
        1. patch_embed.proj(image) -> NCHW embedding grid
        2. Pad grid if smaller than 36x36 (replicate padding)
        3. Extract 5 crops of 36x36 (center + 4 corners)
        4. Flatten + norm -> (5, 1296, 768) token sequences
        5. Forward each through ViT backbone -> (5, 1) logits
        6. Average logits -> sigmoid -> AI probability
        """
        import torch

        # Cap image size for memory safety. Scale preserving aspect ratio
        # so longest edge <= _MAX_EDGE. Ensure both dimensions are multiples
        # of _PATCH_DIM (14) for clean patch grid.
        w, h = img.size
        scale = min(_MAX_EDGE / max(w, h), 1.0)
        if scale < 1.0:
            new_w = int(w * scale)
            new_h = int(h * scale)
        else:
            new_w, new_h = w, h

        # Round to nearest multiple of patch size (14)
        new_w = max(_PATCH_DIM, (new_w // _PATCH_DIM) * _PATCH_DIM)
        new_h = max(_PATCH_DIM, (new_h // _PATCH_DIM) * _PATCH_DIM)

        img_resized = img.resize((new_w, new_h), Image.LANCZOS)

        # Normalize: [0,255] -> [0,1] -> ImageNet standardization
        arr = np.array(img_resized, dtype=np.float32) / 255.0
        arr = (arr - _IMAGENET_MEAN) / _IMAGENET_STD
        tensor = (
            torch.from_numpy(arr.transpose(2, 0, 1))
            .unsqueeze(0)
            .to(self._device)
        )

        with torch.no_grad():
            # Step 1: Run real patch_embed Conv2d projection
            embeddings = self._patch_embed.proj(tensor)  # (1, 768, H', W')

            gs = self._grid_size  # (36, 36)

            # Step 2: Pad if embedding grid is smaller than target 36x36
            ph = max(gs[0] - embeddings.shape[-2], 0)
            pw = max(gs[1] - embeddings.shape[-1], 0)
            if ph > 0 or pw > 0:
                embeddings = F.pad(embeddings, (0, pw, 0, ph), mode="replicate")

            # Step 3: Extract 5 spatial crops of 36x36
            hs = max((embeddings.shape[-2] - gs[0]) // 2, 0)
            ws = max((embeddings.shape[-1] - gs[1]) // 2, 0)

            crops = torch.cat(
                [
                    embeddings[:, :, hs : gs[0] + hs, ws : gs[1] + ws],  # center
                    embeddings[:, :, : gs[0], : gs[1]],                   # top-left
                    embeddings[:, :, -gs[0] :, : gs[1]],                  # bottom-left
                    embeddings[:, :, -gs[0] :, -gs[1] :],                 # bottom-right
                    embeddings[:, :, : gs[0], -gs[1] :],                  # top-right
                ],
                dim=0,
            )  # (5, 768, 36, 36)

            # Step 4: Flatten + norm (matching PatchEmbed.forward behavior)
            if self._patch_embed.flatten:
                # flatten=True: NCHW -> flatten(2) -> (5, 768, 1296) -> transpose -> (5, 1296, 768)
                crops = crops.flatten(2).transpose(1, 2)
            elif self._patch_embed.output_fmt is not None:
                # flatten=False + NHWC: permute to (5, 36, 36, 768)
                crops = crops.permute(0, 2, 3, 1)
            crops = self._patch_embed.norm(crops)

            # Step 5: Forward each crop through backbone
            y = self._model(crops)  # (5, 1)

            # Step 6: Average logits and sigmoid
            y_avg = y.mean(dim=0)  # (1,)
            score = float(torch.sigmoid(y_avg.squeeze()).cpu().item())

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
                    evidence={"bfree_score": round(score, 4), "method": "bfree_5crop"},
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
                    evidence={"bfree_score": round(score, 4), "method": "bfree_5crop"},
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
                    evidence={"bfree_score": round(score, 4), "method": "bfree_5crop"},
                )
            )
