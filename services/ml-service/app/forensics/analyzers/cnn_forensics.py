import base64
import io
import logging
import os
import tempfile
import time

import numpy as np
from PIL import Image, ImageFilter

from ...config import settings
from ..base import AnalyzerFinding, BaseAnalyzer, ModuleResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports — PyTorch and PhotoHolmes are heavy, only load when needed
# ---------------------------------------------------------------------------
_TORCH_AVAILABLE = False
_PHOTOHOLMES_AVAILABLE = False

try:
    import torch  # noqa: F401

    _TORCH_AVAILABLE = True
except ImportError:
    logger.info("PyTorch not installed, CNN forensics disabled")

if _TORCH_AVAILABLE:
    try:
        import photoholmes  # noqa: F401

        _PHOTOHOLMES_AVAILABLE = True
    except ImportError:
        logger.info("PhotoHolmes not installed, CNN forensics disabled")

# Jet colormap LUT for CNN heatmap generation
_COLORMAP_LUT = np.zeros((256, 3), dtype=np.uint8)
for _i in range(256):
    _t = _i / 255.0
    if _t < 0.25:
        _r, _g, _b = 0, int(_t / 0.25 * 255), 255
    elif _t < 0.5:
        _r, _g, _b = 0, 255, int((0.5 - _t) / 0.25 * 255)
    elif _t < 0.75:
        _r, _g, _b = int((_t - 0.5) / 0.25 * 255), 255, 0
    else:
        _r, _g, _b = 255, int((1.0 - _t) / 0.25 * 255), 0
    _COLORMAP_LUT[_i] = [_r, _g, _b]


class CnnForensicsAnalyzer(BaseAnalyzer):
    """CNN-based image tampering detection using PhotoHolmes methods."""

    MODULE_NAME = "deep_modification_detection"
    MODULE_LABEL = "Duboka analiza modifikacija"

    def __init__(self) -> None:
        self._models_loaded = False
        self._catnet_method = None
        self._trufor_method = None
        self._cnn_heatmap_b64: str | None = None

    @property
    def cnn_heatmap_b64(self) -> str | None:
        return self._cnn_heatmap_b64

    def _ensure_models(self) -> None:
        """Lazy-load CNN models on first use. Downloads weights if not cached."""
        if self._models_loaded:
            return

        if not _TORCH_AVAILABLE or not _PHOTOHOLMES_AVAILABLE:
            self._models_loaded = True  # Mark as loaded to avoid retrying
            return

        enabled_methods = [
            m.strip().lower()
            for m in settings.forensics_cnn_methods.split(",")
            if m.strip()
        ]

        cache_dir = settings.forensics_model_cache_dir
        os.makedirs(cache_dir, exist_ok=True)

        # Set PhotoHolmes/torch cache dirs
        os.environ.setdefault("TORCH_HOME", cache_dir)

        if "catnet" in enabled_methods:
            try:
                from photoholmes.methods.catnet import CatNet

                weights_path = os.path.join(cache_dir, "cnn", "catnet", "weights.pth")
                if os.path.exists(weights_path):
                    self._catnet_method = CatNet("pretrained", weights=weights_path)
                    self._catnet_method.eval()
                    logger.info("CAT-Net loaded from %s", weights_path)
                else:
                    logger.warning("CatNet weights not found at %s", weights_path)
            except Exception as e:
                logger.warning("Failed to load CAT-Net: %s", e)
                self._catnet_method = None

        if "trufor" in enabled_methods:
            try:
                from photoholmes.methods.trufor import TruFor

                weights_path = os.path.join(cache_dir, "cnn", "trufor", "trufor.pth.tar")
                if os.path.exists(weights_path):
                    self._trufor_method = TruFor(weights=weights_path)
                    self._trufor_method.eval()
                    logger.info("TruFor loaded from %s", weights_path)
                else:
                    logger.warning("TruFor weights not found at %s", weights_path)
            except Exception as e:
                logger.warning("Failed to load TruFor: %s", e)
                self._trufor_method = None

        self._models_loaded = True

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        start = time.monotonic()
        findings: list[AnalyzerFinding] = []
        self._cnn_heatmap_b64 = None

        if not settings.forensics_cnn_enabled:
            elapsed = int((time.monotonic() - start) * 1000)
            return self._make_result([], elapsed)

        try:
            self._ensure_models()

            if not _TORCH_AVAILABLE:
                elapsed = int((time.monotonic() - start) * 1000)
                return self._make_result([], elapsed, error="PyTorch not installed")

            if not _PHOTOHOLMES_AVAILABLE:
                elapsed = int((time.monotonic() - start) * 1000)
                return self._make_result([], elapsed, error="PhotoHolmes not installed")

            if self._catnet_method is None and self._trufor_method is None:
                elapsed = int((time.monotonic() - start) * 1000)
                return self._make_result([], elapsed, error="No CNN models loaded (CAT-Net, TruFor)")

            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")

            # Run CAT-Net (compression artifact tracing)
            if self._catnet_method is not None:
                self._run_catnet(img, findings)

            # Run TruFor (transformer forensics)
            if self._trufor_method is not None:
                self._run_trufor(img, findings)

        except Exception as e:
            logger.warning("CNN forensics error: %s", e)
            elapsed = int((time.monotonic() - start) * 1000)
            return self._make_result([], elapsed, error=str(e))

        elapsed = int((time.monotonic() - start) * 1000)
        return self._make_result(findings, elapsed)

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([], 0)

    # ------------------------------------------------------------------
    # CAT-Net: Compression Artifact Tracing Network
    # ------------------------------------------------------------------

    def _run_catnet(
        self, img: Image.Image, findings: list[AnalyzerFinding]
    ) -> None:
        """Run CAT-Net for JPEG compression artifact inconsistency detection."""
        try:
            import torch
            from photoholmes.preprocessing import default_preprocessing

            # Preprocess image for CAT-Net
            img_arr = np.array(img)

            # Save to temp JPEG for CAT-Net DCT stream (needs JPEG file)
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                img.save(tmp, format="JPEG", quality=95)
                tmp_path = tmp.name

            try:
                # Use PhotoHolmes preprocessing to extract DCT coefficients
                preprocessing = default_preprocessing("catnet")
                image_data = preprocessing(image=img_arr, dct_coefficients=tmp_path)

                with torch.no_grad():
                    output = self._catnet_method.predict(**image_data)
            finally:
                os.unlink(tmp_path)

            # Extract tampering probability map
            if hasattr(output, "heatmap"):
                prob_map = output.heatmap.squeeze().numpy()
            elif isinstance(output, dict) and "heatmap" in output:
                prob_map = output["heatmap"].squeeze().numpy()
            elif isinstance(output, torch.Tensor):
                prob_map = output.squeeze().numpy()
            else:
                logger.debug("CAT-Net output format not recognized: %s", type(output))
                return

            # Normalize to 0-1
            if prob_map.max() > 1.0:
                prob_map = prob_map / max(prob_map.max(), 1e-6)
            prob_map = np.clip(prob_map, 0, 1)

            # Aggregate: mean of top-5% probabilities as risk score
            flat = prob_map.flatten()
            top_5_pct = np.sort(flat)[-max(1, len(flat) // 20) :]
            risk_score = float(np.mean(top_5_pct))

            # Generate heatmap
            if self._cnn_heatmap_b64 is None:
                self._cnn_heatmap_b64 = self._generate_cnn_heatmap(prob_map)

            if risk_score > 0.6:
                findings.append(
                    AnalyzerFinding(
                        code="CNN_CATNET_TAMPERING",
                        title="CAT-Net: otkrivena manipulacija kompresijskim artefaktima",
                        description=(
                            f"CAT-Net neuronska mreza detektirala je nekonzistentne "
                            f"kompresijske artefakte (rizik: {risk_score:.0%}). "
                            "RGB i DCT tokovi podataka ukazuju na montazu regija "
                            "s razlicitom povijesti JPEG kompresije."
                        ),
                        risk_score=min(0.85, risk_score),
                        confidence=0.85,
                        evidence={
                            "catnet_risk": round(risk_score, 4),
                            "top_5pct_mean": round(float(np.mean(top_5_pct)), 4),
                        },
                    )
                )
            elif risk_score > 0.35:
                findings.append(
                    AnalyzerFinding(
                        code="CNN_CATNET_SUSPICIOUS",
                        title="CAT-Net: sumnjive kompresijske nekonzistentnosti",
                        description=(
                            f"CAT-Net detektirao umjerene kompresijske "
                            f"nekonzistentnosti (rizik: {risk_score:.0%}). "
                            "Moguca lokalna modifikacija slike."
                        ),
                        risk_score=risk_score * 0.7,
                        confidence=0.65,
                        evidence={"catnet_risk": round(risk_score, 4)},
                    )
                )

        except Exception as e:
            logger.warning("CAT-Net inference failed: %s", e)

    # ------------------------------------------------------------------
    # TruFor: Transformer-based Forensics
    # ------------------------------------------------------------------

    def _run_trufor(
        self, img: Image.Image, findings: list[AnalyzerFinding]
    ) -> None:
        """Run TruFor for transformer-based tampering localization."""
        try:
            import torch
            from photoholmes.preprocessing import default_preprocessing

            img_arr = np.array(img)

            # Use PhotoHolmes preprocessing for TruFor input format
            preprocessing = default_preprocessing("trufor")
            image_data = preprocessing(image=img_arr)

            with torch.no_grad():
                output = self._trufor_method.predict(**image_data)

            # Extract confidence map and integrity score
            if hasattr(output, "heatmap"):
                confidence_map = output.heatmap.squeeze().numpy()
            elif isinstance(output, dict) and "heatmap" in output:
                confidence_map = output["heatmap"].squeeze().numpy()
            elif isinstance(output, torch.Tensor):
                confidence_map = output.squeeze().numpy()
            else:
                logger.debug("TruFor output format not recognized: %s", type(output))
                return

            # Normalize
            if confidence_map.max() > 1.0:
                confidence_map = confidence_map / max(confidence_map.max(), 1e-6)
            confidence_map = np.clip(confidence_map, 0, 1)

            # Compute integrity score (lower = more likely tampered)
            # Use mean of the map — high values indicate pristine regions
            integrity_score = float(1.0 - np.mean(confidence_map))

            # Top-region analysis
            flat = confidence_map.flatten()
            top_5_pct = np.sort(flat)[-max(1, len(flat) // 20) :]
            top_risk = float(np.mean(top_5_pct))

            # Generate heatmap if not already set by CAT-Net
            if self._cnn_heatmap_b64 is None:
                self._cnn_heatmap_b64 = self._generate_cnn_heatmap(confidence_map)

            if integrity_score < 0.4:
                findings.append(
                    AnalyzerFinding(
                        code="CNN_TRUFOR_TAMPERING",
                        title="TruFor: otkrivena manipulacija transformerskom analizom",
                        description=(
                            f"TruFor transformerska mreza detektirala je modificirane "
                            f"regije s niskim rezultatom integriteta ({integrity_score:.0%}). "
                            "Kombinacija CNN ekstrakcije znacajki i mehanizma paznje "
                            "ukazuje na znacajnu manipulaciju slike."
                        ),
                        risk_score=min(0.80, 1.0 - integrity_score),
                        confidence=0.85,
                        evidence={
                            "integrity_score": round(integrity_score, 4),
                            "top_5pct_risk": round(top_risk, 4),
                        },
                    )
                )
            elif integrity_score < 0.6:
                findings.append(
                    AnalyzerFinding(
                        code="CNN_TRUFOR_SUSPICIOUS",
                        title="TruFor: sumnjiva podrucja u slici",
                        description=(
                            f"TruFor pokazuje umjereno nizak integritet slike "
                            f"({integrity_score:.0%}). Moguca djelomicna "
                            "modifikacija pojedinih regija."
                        ),
                        risk_score=(1.0 - integrity_score) * 0.6,
                        confidence=0.65,
                        evidence={
                            "integrity_score": round(integrity_score, 4),
                            "top_5pct_risk": round(top_risk, 4),
                        },
                    )
                )

        except Exception as e:
            logger.warning("TruFor inference failed: %s", e)

    # ------------------------------------------------------------------
    # Heatmap generation for CNN outputs
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_cnn_heatmap(prob_map: np.ndarray) -> str:
        """Generate a jet-colormap heatmap from a CNN probability map."""
        # Normalize to 0-255
        max_val = max(float(np.max(prob_map)), 1e-6)
        normalized = (prob_map / max_val * 255).astype(np.uint8)

        h, w = normalized.shape[:2]
        heatmap = _COLORMAP_LUT[normalized.ravel()].reshape(h, w, 3)

        heatmap_img = Image.fromarray(heatmap)
        heatmap_img = heatmap_img.filter(ImageFilter.GaussianBlur(radius=2))

        buffer = io.BytesIO()
        heatmap_img.save(buffer, format="PNG", optimize=True)
        return base64.b64encode(buffer.getvalue()).decode("ascii")
