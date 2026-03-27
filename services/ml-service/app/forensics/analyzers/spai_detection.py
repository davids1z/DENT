"""
SPAI AI Image Detection Module (CVPR 2025)

Any-Resolution AI-Generated Image Detection by Spectral Learning.
Uses FFT frequency decomposition + ViT-B/16 encoder + cross-attention
aggregator to detect AI-generated images from their spectral signatures.

Key insight: AI generators leave characteristic patterns in the frequency
domain that are INVARIANT to pixel-level compression (WebP, AVIF, JPEG).
This makes SPAI robust where pixel-domain detectors fail.

Architecture:
1. Patchify input image into 224x224 non-overlapping patches
2. For each patch: FFT decompose into low-freq + high-freq components
3. Feed (original, low, high) through frozen ViT-B/16 encoder → 1096-dim features
4. Aggregate all patch features via cross-attention → single prediction
5. Sigmoid → score (higher = more likely AI-generated)

Inference uses ONNX Runtime (CPU) to avoid timm 0.4.12 version conflict.

Paper: https://arxiv.org/abs/2411.19417
GitHub: https://github.com/mever-team/spai
License: Apache 2.0
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
# Constants
# ---------------------------------------------------------------------------
_PATCH_SIZE = 224
_PATCH_STRIDE = 224
_MIN_PATCHES = 4
_MASK_RADIUS = 16
_FEATURE_DIM = 1096  # 6*12 (cosine similarities) + 1024 (original features)

_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(3, 1, 1)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(3, 1, 1)

# Pre-computed circular mask (224x224, radius=16)
_CIRCULAR_MASK: np.ndarray | None = None


def _get_circular_mask() -> np.ndarray:
    """Generate the FFT circular mask once (cached)."""
    global _CIRCULAR_MASK
    if _CIRCULAR_MASK is not None:
        return _CIRCULAR_MASK

    half = _PATCH_SIZE // 2  # 112
    coords_1d = np.arange(0, half, dtype=np.float32)  # [0, 1, ..., 111]
    coords_1d = np.concatenate([coords_1d[::-1], coords_1d])  # [111..0, 0..111]
    cx = np.tile(coords_1d, (_PATCH_SIZE, 1))  # (224, 224)
    cy = cx.T
    r = np.sqrt(cx ** 2 + cy ** 2)
    _CIRCULAR_MASK = (r < _MASK_RADIUS).astype(np.float32)
    return _CIRCULAR_MASK


# ---------------------------------------------------------------------------
# ONNX Runtime lazy import
# ---------------------------------------------------------------------------
_ORT_AVAILABLE = False
try:
    import onnxruntime as ort
    _ORT_AVAILABLE = True
except ImportError:
    pass


class SPAIDetectionAnalyzer(BaseAnalyzer):
    """SPAI spectral-learning AI image detector via ONNX Runtime."""

    MODULE_NAME = "spai_detection"
    MODULE_LABEL = "SPAI spektralna AI detekcija"

    def __init__(self) -> None:
        self._models_loaded = False
        self._encoder_session = None
        self._aggregator_session = None

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _ensure_models(self) -> None:
        if self._models_loaded:
            return

        if not _ORT_AVAILABLE:
            logger.warning("onnxruntime not available — SPAI disabled")
            self._models_loaded = True
            return

        if not getattr(settings, "forensics_spai_enabled", False):
            self._models_loaded = True
            return

        model_dir = getattr(
            settings, "forensics_spai_model_dir",
            os.path.join(settings.forensics_model_cache_dir, "spai"),
        )
        encoder_path = os.path.join(model_dir, "encoder.onnx")
        aggregator_path = os.path.join(model_dir, "aggregator.onnx")

        if not os.path.exists(encoder_path) or not os.path.exists(aggregator_path):
            logger.warning(
                "SPAI ONNX models not found at %s — need encoder.onnx + aggregator.onnx",
                model_dir,
            )
            self._models_loaded = True
            return

        try:
            sess_opts = ort.SessionOptions()
            sess_opts.inter_op_num_threads = 2
            sess_opts.intra_op_num_threads = 2

            self._encoder_session = ort.InferenceSession(
                encoder_path,
                sess_options=sess_opts,
                providers=["CPUExecutionProvider"],
            )
            self._aggregator_session = ort.InferenceSession(
                aggregator_path,
                sess_options=sess_opts,
                providers=["CPUExecutionProvider"],
            )
            logger.info(
                "SPAI ONNX models loaded: encoder=%s, aggregator=%s",
                encoder_path, aggregator_path,
            )
        except Exception as e:
            logger.warning("Failed to load SPAI ONNX models: %s", e)
            self._encoder_session = None
            self._aggregator_session = None

        self._models_loaded = True

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        start = time.monotonic()
        findings: list[AnalyzerFinding] = []

        if not getattr(settings, "forensics_spai_enabled", False):
            return self._make_result([], int((time.monotonic() - start) * 1000))

        try:
            self._ensure_models()

            if self._encoder_session is None or self._aggregator_session is None:
                return self._make_result(
                    [], int((time.monotonic() - start) * 1000),
                    error="SPAI ONNX models not available",
                )

            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")

            score = self._compute_score(img)
            self._emit_findings(score, findings)

        except Exception as e:
            logger.warning("SPAI detection error: %s", e)
            return self._make_result(
                [], int((time.monotonic() - start) * 1000), error=str(e),
            )

        elapsed = int((time.monotonic() - start) * 1000)
        return self._make_result(findings, elapsed)

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([], 0)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _compute_score(self, img: Image.Image) -> float:
        """Full SPAI pipeline: patchify → FFT → encode → aggregate → sigmoid."""
        from scipy.fft import fft2, ifft2, fftshift, ifftshift

        # Convert to (3, H, W) float32 in [0, 1]
        arr = np.array(img, dtype=np.float32) / 255.0
        arr = arr.transpose(2, 0, 1)  # (3, H, W)

        # Patchify
        patches = self._patchify(arr)
        mask = _get_circular_mask()

        # Encode each patch
        patch_features = []
        for patch in patches:
            # FFT decomposition
            spectrum = fft2(patch, axes=(-2, -1))
            spectrum = fftshift(spectrum, axes=(-2, -1))

            low = spectrum * mask
            high = spectrum * (1.0 - mask)

            low = ifft2(ifftshift(low, axes=(-2, -1)), axes=(-2, -1)).real
            high = ifft2(ifftshift(high, axes=(-2, -1)), axes=(-2, -1)).real

            low = np.clip(low, 0.0, 1.0).astype(np.float32)
            high = np.clip(high, 0.0, 1.0).astype(np.float32)

            # ImageNet normalize all three
            x_norm = (patch - _IMAGENET_MEAN) / _IMAGENET_STD
            x_low = (low - _IMAGENET_MEAN) / _IMAGENET_STD
            x_high = (high - _IMAGENET_MEAN) / _IMAGENET_STD

            # Batch dim
            inputs = {
                "x": x_norm[np.newaxis].astype(np.float32),
                "x_low": x_low[np.newaxis].astype(np.float32),
                "x_high": x_high[np.newaxis].astype(np.float32),
            }

            output = self._encoder_session.run(None, inputs)
            patch_features.append(output[0])  # (1, 1096)

        # Stack → (1, L, 1096)
        features = np.concatenate(patch_features, axis=0)  # (L, 1096)
        features = features[np.newaxis]  # (1, L, 1096)

        # Aggregate
        aggr_input_name = self._aggregator_session.get_inputs()[0].name
        logit = self._aggregator_session.run(
            None, {aggr_input_name: features.astype(np.float32)}
        )[0]  # (1, 1)

        # Sigmoid
        score = float(1.0 / (1.0 + np.exp(-np.clip(logit.item(), -500, 500))))
        return float(np.clip(score, 0.0, 1.0))

    @staticmethod
    def _patchify(img: np.ndarray) -> list[np.ndarray]:
        """Split (3, H, W) image into 224x224 non-overlapping patches."""
        _, H, W = img.shape
        patches = []
        for y in range(0, H - _PATCH_SIZE + 1, _PATCH_STRIDE):
            for x in range(0, W - _PATCH_SIZE + 1, _PATCH_STRIDE):
                patches.append(img[:, y:y + _PATCH_SIZE, x:x + _PATCH_SIZE])

        if len(patches) < _MIN_PATCHES:
            # Five-crop fallback for small images
            patches = []
            # Resize to at least 224x224
            if H < _PATCH_SIZE or W < _PATCH_SIZE:
                scale = max(_PATCH_SIZE / H, _PATCH_SIZE / W) * 1.1
                new_h, new_w = int(H * scale), int(W * scale)
                # Use bilinear interpolation via numpy
                from PIL import Image as PILImage
                pil_img = PILImage.fromarray(
                    (img.transpose(1, 2, 0) * 255).astype(np.uint8)
                )
                pil_img = pil_img.resize((new_w, new_h), PILImage.LANCZOS)
                img = np.array(pil_img, dtype=np.float32).transpose(2, 0, 1) / 255.0
                _, H, W = img.shape

            s = _PATCH_SIZE
            patches.append(img[:, :s, :s])                    # top-left
            patches.append(img[:, :s, W - s:])                # top-right
            patches.append(img[:, H - s:, :s])                # bottom-left
            patches.append(img[:, H - s:, W - s:])            # bottom-right
            cy, cx = (H - s) // 2, (W - s) // 2
            patches.append(img[:, cy:cy + s, cx:cx + s])      # center

        return patches

    # ------------------------------------------------------------------
    # Findings
    # ------------------------------------------------------------------

    @staticmethod
    def _emit_findings(score: float, findings: list[AnalyzerFinding]) -> None:
        if score > 0.70:
            findings.append(
                AnalyzerFinding(
                    code="SPAI_AI_DETECTED",
                    title="SPAI spektralna detekcija AI sadrzaja",
                    description=(
                        f"SPAI frekvencijska analiza (CVPR 2025) detektirala je "
                        f"snazne spektralne anomalije tipicne za AI generiranje "
                        f"(rezultat: {score:.0%}). Ova metoda je otporna na "
                        f"kompresiju (WebP, JPEG, AVIF)."
                    ),
                    risk_score=min(0.90, max(0.65, score * 0.90)),
                    confidence=min(0.90, 0.60 + score * 0.25),
                    evidence={"spai_score": round(score, 4), "method": "spai_spectral_vit"},
                )
            )
        elif score > 0.45:
            findings.append(
                AnalyzerFinding(
                    code="SPAI_AI_SUSPECTED",
                    title="SPAI sumnja na AI sadrzaj",
                    description=(
                        f"Spektralna analiza pokazuje umjerenu vjerojatnost "
                        f"({score:.0%}) da je slika umjetno generirana."
                    ),
                    risk_score=max(0.40, score * 0.75),
                    confidence=min(0.80, 0.45 + score * 0.30),
                    evidence={"spai_score": round(score, 4), "method": "spai_spectral_vit"},
                )
            )
        elif score > 0.25:
            findings.append(
                AnalyzerFinding(
                    code="SPAI_AI_LOW",
                    title="SPAI blagi spektralni indikatori",
                    description=(
                        f"Frekvencijska analiza pokazuje blage indikatore "
                        f"({score:.0%}) moguceg AI generiranja."
                    ),
                    risk_score=score * 0.50,
                    confidence=0.40 + score * 0.15,
                    evidence={"spai_score": round(score, 4), "method": "spai_spectral_vit"},
                )
            )
