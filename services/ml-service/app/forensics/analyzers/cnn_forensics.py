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

        self._load_errors: list[str] = []

        # PyTorch 2.6+ defaults to weights_only=True in torch.load().
        # PhotoHolmes model checkpoints contain numpy globals that aren't
        # in the safe list, so we need to temporarily patch torch.load
        # to use weights_only=False for these trusted academic weights.
        import torch
        _original_torch_load = torch.load

        def _patched_load(*args, **kwargs):
            kwargs.setdefault("weights_only", False)
            return _original_torch_load(*args, **kwargs)

        # PyTorch 2.6+ safe globals for numpy types in model checkpoints
        try:
            import numpy as _np
            torch.serialization.add_safe_globals([_np.core.multiarray.scalar, _np.dtype, _np.ndarray])
        except Exception:
            pass

        if "catnet" in enabled_methods:
            try:
                from photoholmes.methods.catnet import CatNet

                weights_path = os.path.join(cache_dir, "cnn", "catnet", "weights.pth")
                if os.path.exists(weights_path):
                    sz = os.path.getsize(weights_path)
                    logger.info("CatNet weights found: %s (%d bytes)", weights_path, sz)
                    torch.load = _patched_load
                    self._catnet_method = CatNet("pretrained", weights=weights_path)
                    torch.load = _original_torch_load
                    self._catnet_method.eval()
                    logger.info("CAT-Net loaded successfully")
                else:
                    msg = f"CatNet weights not found at {weights_path}"
                    logger.warning(msg)
                    self._load_errors.append(msg)
            except Exception as e:
                torch.load = _original_torch_load
                msg = f"CatNet constructor failed: {e}"
                logger.warning(msg)
                self._load_errors.append(msg)
                self._catnet_method = None

        if "trufor" in enabled_methods:
            try:
                from photoholmes.methods.trufor import TruFor

                weights_path = os.path.join(cache_dir, "cnn", "trufor", "trufor.pth.tar")
                if os.path.exists(weights_path):
                    sz = os.path.getsize(weights_path)
                    logger.info("TruFor weights found: %s (%d bytes)", weights_path, sz)
                    torch.load = _patched_load
                    self._trufor_method = TruFor(weights=weights_path)
                    torch.load = _original_torch_load
                    self._trufor_method.eval()
                    logger.info("TruFor loaded successfully")
                else:
                    msg = f"TruFor weights not found at {weights_path}"
                    logger.warning(msg)
                    self._load_errors.append(msg)
            except Exception as e:
                torch.load = _original_torch_load
                msg = f"TruFor constructor failed: {e}"
                logger.warning(msg)
                self._load_errors.append(msg)
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
                details = "; ".join(getattr(self, "_load_errors", []) or ["unknown"])
                return self._make_result([], elapsed, error=f"No CNN models loaded: {details}")

            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")

            # CAT-Net DISABLED AGAIN (March 2025 eval showed 0.85 score on
            # ALL images including authentic). Even with JPEG-aware DCT, higher
            # thresholds (0.80/0.65), and min area check, CatNet still gives
            # false positives. deep_modification_detection avg=0.850 for auth.
            # if self._catnet_method is not None:
            #     self._run_catnet(img, image_bytes, findings)

            # Run TruFor (transformer forensics) — works on RGB, no JPEG issues
            if self._trufor_method is not None:
                self._run_trufor(img, findings)

        except Exception as e:
            logger.warning("CNN forensics error: %s", e)
            elapsed = int((time.monotonic() - start) * 1000)
            return self._make_result([], elapsed, error=str(e))

        # Raw score passthrough for meta-learner calibration.
        # Even when no findings emit (below threshold), pass the raw
        # TruFor signal so the meta-learner can learn from it.
        result = self._make_result(findings, int((time.monotonic() - start) * 1000))
        if hasattr(self, "_last_trufor_combined_risk"):
            result.risk_score = round(self._last_trufor_combined_risk, 4)
        return result

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([], 0)

    # ------------------------------------------------------------------
    # CAT-Net: Compression Artifact Tracing Network
    # ------------------------------------------------------------------

    def _run_catnet(
        self, img: Image.Image, image_bytes: bytes, findings: list[AnalyzerFinding]
    ) -> None:
        """Run CAT-Net for JPEG compression artifact inconsistency detection."""
        try:
            import torch
            import jpegio
            from photoholmes.methods.catnet.preprocessing import catnet_preprocessing

            img_arr = np.array(img)
            img_tensor = torch.from_numpy(img_arr).permute(2, 0, 1).float()

            # JPEG-aware DCT extraction:
            # If input is JPEG, use ORIGINAL bytes to preserve original DCT/Q-tables.
            # Re-compressing a JPEG introduces "double compression" artifacts that
            # CatNet interprets as splice evidence — causing massive false positives.
            is_jpeg = image_bytes[:2] == b'\xff\xd8'

            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                if is_jpeg:
                    tmp.write(image_bytes)  # Original JPEG bytes — no re-compression
                else:
                    img.save(tmp, format="JPEG", quality=95)  # PNG/RAW → must compress
                tmp_path = tmp.name

            try:
                jpeg = jpegio.read(tmp_path)
                # Use luma (Y) channel only — Cb/Cr are subsampled
                dct_coefs = torch.from_numpy(
                    jpeg.coef_arrays[0][np.newaxis]
                ).float()
                qtables = torch.from_numpy(
                    jpeg.quant_tables[0][np.newaxis]
                ).float()

                image_data = catnet_preprocessing(
                    image=img_tensor,
                    dct_coefficients=dct_coefs,
                    qtables=qtables,
                )

                with torch.no_grad():
                    output = self._catnet_method.predict(**image_data)
            finally:
                os.unlink(tmp_path)

            # Extract tampering probability map
            # photoholmes CatNet returns tuple: (authentic_map, tampered_map)
            if isinstance(output, tuple) and len(output) >= 2:
                prob_map = output[1].squeeze().cpu().numpy()  # index 1 = tampered probability
            elif hasattr(output, "heatmap"):
                prob_map = output.heatmap.squeeze().cpu().numpy()
            elif isinstance(output, dict) and "heatmap" in output:
                prob_map = output["heatmap"].squeeze().cpu().numpy()
            elif isinstance(output, torch.Tensor):
                prob_map = output.squeeze().cpu().numpy()
            else:
                logger.debug("CAT-Net output format not recognized: %s", type(output))
                return

            # Normalize to 0-1
            if prob_map.max() > 1.0:
                prob_map = prob_map / max(prob_map.max(), 1e-6)
            prob_map = np.clip(prob_map, 0, 1)

            # Aggregate risk score from probability map.
            # Use MEAN of entire map (not top-5%) to avoid false positives
            # from JPEG block boundaries at object edges which naturally
            # have higher tampered probability in re-compressed images.
            mean_score = float(np.mean(prob_map))
            # Also check if there's a concentrated region (real splicing
            # creates a localized high-probability area, not diffuse noise)
            flat = prob_map.flatten()
            top_5_pct = np.sort(flat)[-max(1, len(flat) // 20):]
            top_score = float(np.mean(top_5_pct))
            # Combine: mean provides baseline, top provides localization signal
            # Only flag if BOTH mean is elevated AND top region is very high
            risk_score = mean_score * 0.6 + top_score * 0.4

            # Generate heatmap
            if self._cnn_heatmap_b64 is None:
                self._cnn_heatmap_b64 = self._generate_cnn_heatmap(prob_map)

            # Minimum tampered area check: skip if <5% of pixels above 0.5.
            # Real splices create a localized region, not scattered noise.
            tampered_area_pct = float(np.mean(prob_map > 0.5))
            if tampered_area_pct < 0.05:
                logger.debug(
                    "CAT-Net: tampered area too small (%.1f%%), skipping",
                    tampered_area_pct * 100,
                )
                return

            if risk_score > 0.80:
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
                            "tampered_area_pct": round(tampered_area_pct, 4),
                        },
                    )
                )
            elif risk_score > 0.65:
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
                        evidence={
                            "catnet_risk": round(risk_score, 4),
                            "tampered_area_pct": round(tampered_area_pct, 4),
                        },
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
            from photoholmes.methods.trufor.preprocessing import trufor_preprocessing

            img_arr = np.array(img)
            img_tensor = torch.from_numpy(img_arr).permute(2, 0, 1).float()

            # Use PhotoHolmes preprocessing for TruFor input format
            image_data = trufor_preprocessing(image=img_tensor)

            with torch.no_grad():
                output = self._trufor_method.predict(**image_data)

            # photoholmes TruFor returns tuple of 4 tensors:
            # [0]: tampered probability map (H,W) — higher = more likely tampered
            # [1]: authentic confidence map (H,W) — higher = more likely authentic
            # [2]: integrity score (scalar) — higher = more likely tampered
            # [3]: noise fingerprint map (H,W)
            if isinstance(output, tuple) and len(output) >= 3:
                tamper_map = output[0].squeeze().cpu().numpy()
                integrity_score = float(output[2].item())
                confidence_map = tamper_map  # For heatmap generation
            elif isinstance(output, tuple) and len(output) >= 1:
                tamper_map = output[0].squeeze().cpu().numpy()
                confidence_map = tamper_map
                integrity_score = float(np.mean(tamper_map))
            else:
                logger.debug("TruFor output format not recognized: %s", type(output))
                return

            # Normalize
            if confidence_map.max() > 1.0:
                confidence_map = confidence_map / max(confidence_map.max(), 1e-6)
            confidence_map = np.clip(confidence_map, 0, 1)

            # Top-region analysis (top 5% of tamper map pixels)
            flat = confidence_map.flatten()
            top_5_pct = np.sort(flat)[-max(1, len(flat) // 20) :]
            top_risk = float(np.mean(top_5_pct))

            # Store raw combined risk for meta-learner passthrough
            tamper_mean_raw = float(np.mean(tamper_map))
            self._last_trufor_combined_risk = max(top_risk * 0.6, integrity_score) * 0.5 + tamper_mean_raw * 0.5

            # Generate heatmap if not already set by CAT-Net
            if self._cnn_heatmap_b64 is None:
                self._cnn_heatmap_b64 = self._generate_cnn_heatmap(confidence_map)

            # TruFor output ranges (PhotoHolmes, CPU):
            #   integrity_score: 0.05-0.20 (higher = more tampered)
            #   tamper_map mean: 0.01-0.20
            #   top_risk (top 5% pixels): 0.10-0.80
            # Use top-region analysis as primary signal — tampered regions
            # show high localized values even when mean is low.
            tamper_mean = float(np.mean(tamper_map))
            combined_risk = max(top_risk * 0.6, integrity_score) * 0.5 + tamper_mean * 0.5

            if top_risk > 0.40:
                findings.append(
                    AnalyzerFinding(
                        code="CNN_TRUFOR_TAMPERING",
                        title="TruFor: otkrivena manipulacija transformerskom analizom",
                        description=(
                            f"TruFor transformerska mreza detektirala je modificirane "
                            f"regije (top 5%: {top_risk:.0%}, mean: {tamper_mean:.0%}). "
                            "Lokalizirana manipulacija detektirana u specificnim "
                            "dijelovima slike."
                        ),
                        risk_score=min(0.85, top_risk),
                        confidence=0.75,
                        evidence={
                            "integrity_score": round(integrity_score, 4),
                            "tamper_map_mean": round(tamper_mean, 4),
                            "top_risk": round(top_risk, 4),
                        },
                    )
                )
            elif top_risk > 0.25:
                findings.append(
                    AnalyzerFinding(
                        code="CNN_TRUFOR_SUSPICIOUS",
                        title="TruFor: sumnjiva podrucja u slici",
                        description=(
                            f"TruFor pokazuje umjeren rizik manipulacije "
                            f"(top 5%: {top_risk:.0%}). Moguca djelomicna "
                            "modifikacija pojedinih regija."
                        ),
                        risk_score=top_risk * 0.7,
                        confidence=0.60,
                        evidence={
                            "integrity_score": round(integrity_score, 4),
                            "tamper_map_mean": round(tamper_mean, 4),
                            "top_risk": round(top_risk, 4),
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
