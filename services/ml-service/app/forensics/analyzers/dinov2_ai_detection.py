"""
DINOv2-larged AI Image Detection Module

Uses frozen DINOv2-large (facebook/dinov2-large) embeddings with a trained
linear probe to distinguish real from AI-generated images.

Key insight: DINOv2 was pre-trained with self-supervised learning on 142M
images, producing rich visual features that capture fine-grained texture
patterns. A simple linear probe on these features achieves 97.2% accuracy
on Flux-generated images (arXiv 2602.07814, Feb 2026).

Detection approach:
1. Extract 1024-dim CLS embedding from frozen DINOv2-large vision encoder.
2. L2-normalize the embedding.
3. Apply a trained logistic regression probe: sigmoid(w . x + b).
4. Threshold the probability to emit findings.
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
_TRANSFORMERS_AVAILABLE = False
_ORT_AVAILABLE = False

try:
    import torch
    _TORCH_AVAILABLE = True
except ImportError:
    pass

if _TORCH_AVAILABLE:
    try:
        import transformers  # noqa: F401
        _TRANSFORMERS_AVAILABLE = True
    except ImportError:
        pass

try:
    import onnxruntime as ort
    _ORT_AVAILABLE = True
except ImportError:
    pass

_DINOV2_MODEL_NAME = "facebook/dinov2-large"


class DINOv2AiDetectionAnalyzer(BaseAnalyzer):
    """DINOv2-large linear probe for AI image detection."""

    MODULE_NAME = "dinov2_ai_detection"
    MODULE_LABEL = "DINOv2 AI detekcija"

    def __init__(self) -> None:
        self._models_loaded = False
        self._processor = None
        self._model = None
        self._probe = None  # {"weights": ndarray(1024,), "bias": float}
        self._onnx_session = None  # ONNX Runtime session (faster than PyTorch)

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _ensure_models(self) -> None:
        if self._models_loaded:
            return

        if not _TORCH_AVAILABLE or not _TRANSFORMERS_AVAILABLE:
            self._models_loaded = True
            return

        if not getattr(settings, "forensics_dinov2_ai_enabled", True):
            self._models_loaded = True
            return

        from transformers import AutoImageProcessor, AutoModel

        model_name = getattr(settings, "forensics_dinov2_ai_model", _DINOV2_MODEL_NAME)
        cache_dir = os.path.join(settings.forensics_model_cache_dir, "dinov2")
        os.makedirs(cache_dir, exist_ok=True)

        try:
            self._processor = AutoImageProcessor.from_pretrained(
                model_name, cache_dir=cache_dir
            )
            self._device = "cuda" if _TORCH_AVAILABLE and torch.cuda.is_available() else "cpu"
            self._model = AutoModel.from_pretrained(
                model_name, cache_dir=cache_dir
            ).to(self._device)
            self._model.eval()
            logger.info("DINOv2 AI detector loaded on %s: %s", self._device, model_name)
        except Exception as e:
            logger.warning("Failed to load DINOv2 model: %s", e)
            self._processor = None
            self._model = None

        # Load linear probe weights
        self._load_probe(cache_dir)

        # Try to load ONNX model (2-3x faster than PyTorch on CPU)
        self._load_onnx(cache_dir)

        self._models_loaded = True

    def _load_onnx(self, cache_dir: str) -> None:
        """Load ONNX Runtime session if exported model exists."""
        if not _ORT_AVAILABLE:
            return
        onnx_path = os.path.join(cache_dir, "dinov2.onnx")
        if not os.path.exists(onnx_path):
            return
        try:
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = int(os.environ.get("OMP_NUM_THREADS", "4"))
            opts.inter_op_num_threads = 1
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self._onnx_session = ort.InferenceSession(
                onnx_path, opts, providers=["CPUExecutionProvider"]
            )
            logger.info("DINOv2 ONNX session loaded from %s", onnx_path)
        except Exception as e:
            logger.warning("Failed to load DINOv2 ONNX: %s (falling back to PyTorch)", e)
            self._onnx_session = None

    def _load_probe(self, cache_dir: str) -> None:
        """Load pre-trained probe (MLP or linear) from disk."""
        probe_path = os.path.join(cache_dir, "dinov2_probe_weights.npz")
        if os.path.exists(probe_path):
            try:
                data = np.load(probe_path, allow_pickle=True)
                probe_type = str(data.get("probe_type", "linear"))
                if probe_type == "mlp" and "w1" in data:
                    self._probe = {
                        "type": "mlp",
                        "w1": data["w1"],
                        "b1": data["b1"],
                        "w2": data["w2"],
                        "b2": data["b2"],
                    }
                    logger.info("DINOv2 MLP probe loaded from %s (hidden=%d)",
                                probe_path, data["w1"].shape[0])
                elif "weights" in data:
                    bias_val = data["bias"]
                    self._probe = {
                        "type": "linear",
                        "weights": data["weights"],
                        "bias": float(bias_val.flat[0]) if hasattr(bias_val, "flat") else float(bias_val),
                    }
                    logger.info("DINOv2 linear probe loaded from %s", probe_path)
                else:
                    self._probe = None
                return
            except Exception as e:
                logger.warning("Failed to load DINOv2 probe: %s", e)

        self._probe = None
        logger.info("DINOv2 probe not found at %s — using heuristic fallback", probe_path)

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        start = time.monotonic()
        findings: list[AnalyzerFinding] = []

        if not getattr(settings, "forensics_dinov2_ai_enabled", True):
            return self._make_result([], int((time.monotonic() - start) * 1000))

        try:
            self._ensure_models()

            if self._model is None or self._processor is None:
                return self._make_result(
                    [], int((time.monotonic() - start) * 1000),
                    error="DINOv2 model not available"
                )

            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")

            score = self._compute_score(img)
            self._emit_findings(score, findings)

        except Exception as e:
            logger.warning("DINOv2 AI detection error: %s", e)
            return self._make_result(
                [], int((time.monotonic() - start) * 1000), error=str(e)
            )

        elapsed = int((time.monotonic() - start) * 1000)
        return self._make_result(findings, elapsed)

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([], 0)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _compute_score(self, img: Image.Image) -> float:
        """Compute AI-generation probability from DINOv2 embedding.
        Uses ONNX Runtime when available (2-3x faster), falls back to PyTorch."""
        embedding = self._extract_embedding(img)

        # L2 normalize
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding_normed = embedding / norm
        else:
            embedding_normed = embedding

        if self._probe is not None and self._probe.get("type") == "mlp":
            h = np.maximum(0, self._probe["w1"] @ embedding_normed + self._probe["b1"])
            logit = float((self._probe["w2"] @ h + self._probe["b2"]).item())
            score = 1.0 / (1.0 + np.exp(-np.clip(logit, -500, 500)))
        elif self._probe is not None and "weights" in self._probe:
            logit = float(
                np.dot(self._probe["weights"], embedding_normed)
                + self._probe["bias"]
            )
            score = 1.0 / (1.0 + np.exp(-np.clip(logit, -500, 500)))
        else:
            score = self._heuristic_score(embedding, embedding_normed, norm)

        return float(np.clip(score, 0.0, 1.0))

    def _extract_embedding(self, img: Image.Image) -> np.ndarray:
        """Extract CLS embedding. Uses ONNX if available."""
        inputs = self._processor(
            images=img,
            return_tensors="pt" if self._onnx_session is None else "np",
        )

        if self._onnx_session is not None:
            pixel_values = inputs["pixel_values"]
            if not isinstance(pixel_values, np.ndarray):
                pixel_values = pixel_values.numpy()
            pixel_values = pixel_values.astype(np.float32)
            result = self._onnx_session.run(None, {"pixel_values": pixel_values})
            return result[0].squeeze(0)

        with torch.no_grad():
            device = getattr(self, "_device", "cpu")
            pixel_values = inputs["pixel_values"].to(device)
            outputs = self._model(pixel_values=pixel_values)
            cls_embedding = outputs.last_hidden_state[:, 0, :]
            return cls_embedding.squeeze(0).cpu().numpy()

    @staticmethod
    def _heuristic_score(
        embedding: np.ndarray,
        embedding_normed: np.ndarray,
        norm: float,
    ) -> float:
        """Heuristic scoring when no trained probe is available.

        Based on empirical observations of DINOv2 embedding statistics:
        AI images tend to have higher kurtosis and different activation
        concentration compared to real photographs.
        """
        signals: list[float] = []

        # Signal 1: Embedding kurtosis
        mean_val = embedding_normed.mean()
        std_val = embedding_normed.std()
        if std_val > 1e-8:
            kurtosis = float(np.mean(((embedding_normed - mean_val) / std_val) ** 4))
            kurt_score = np.clip((kurtosis - 3.0) / 9.0, 0.0, 1.0)
            signals.append(kurt_score)

        # Signal 2: Top-k activation concentration
        top_k = np.sort(np.abs(embedding_normed))[-50:]
        concentration = float(top_k.sum() / (np.abs(embedding_normed).sum() + 1e-8))
        conc_score = np.clip((concentration - 0.15) / 0.25, 0.0, 1.0)
        signals.append(conc_score)

        # Signal 3: Negative-value ratio
        neg_ratio = float((embedding_normed < 0).sum() / len(embedding_normed))
        neg_score = np.clip(abs(neg_ratio - 0.50) / 0.15, 0.0, 1.0)
        signals.append(neg_score * 0.5)

        if not signals:
            return 0.0

        score = sum(signals) / len(signals)
        # Cap heuristic at 0.40 — without trained probe, only flag "maybe suspicious"
        return float(min(score, 0.40))

    # ------------------------------------------------------------------
    # Findings
    # ------------------------------------------------------------------

    @staticmethod
    def _emit_findings(
        score: float, findings: list[AnalyzerFinding]
    ) -> None:
        # DINOv2 probe retrained on diverse data (0% FP on auth)
        if score > 0.70:
            findings.append(
                AnalyzerFinding(
                    code="DINOV2_AI_DETECTED",
                    title="DINOv2 detekcija AI-generiranog sadrzaja",
                    description=(
                        f"DINOv2-large model detektirao je da embedding ove slike "
                        f"snazno indicira AI-generirani sadrzaj (rezultat: {score:.0%})."
                    ),
                    risk_score=min(0.90, max(0.65, score * 0.90)),
                    confidence=min(0.90, 0.60 + score * 0.25),
                    evidence={"dinov2_score": round(score, 4), "method": "dinov2_large_probe"},
                )
            )
        elif score > 0.45:
            findings.append(
                AnalyzerFinding(
                    code="DINOV2_AI_SUSPECTED",
                    title="DINOv2 sumnja na AI sadrzaj",
                    description=(
                        f"DINOv2 embedding analiza pokazuje umjerenu vjerojatnost "
                        f"({score:.0%}) da je slika umjetno generirana."
                    ),
                    risk_score=max(0.40, score * 0.75),
                    confidence=min(0.80, 0.45 + score * 0.30),
                    evidence={"dinov2_score": round(score, 4), "method": "dinov2_large_probe"},
                )
            )
        elif score > 0.25:
            findings.append(
                AnalyzerFinding(
                    code="DINOV2_AI_LOW",
                    title="DINOv2 blagi AI indikatori",
                    description=(
                        f"DINOv2 embedding analiza pokazuje blage indikatore "
                        f"({score:.0%}) moguceg AI generiranja."
                    ),
                    risk_score=score * 0.50,
                    confidence=0.40 + score * 0.15,
                    evidence={"dinov2_score": round(score, 4), "method": "dinov2_large_probe"},
                )
            )
