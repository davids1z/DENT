"""
RINE AI Image Detection Module (ECCV 2024)

Leverages ALL 24 intermediate CLIP encoder blocks instead of just the
final layer. Early/middle blocks capture low-level texture and noise
artifacts that are content-independent — they persist regardless of
whether the image shows a car, face, or landscape.

+10.6% accuracy over standard CLIP probe (91.5% vs 80.9%).
Only 6.32M trainable parameters on top of frozen CLIP ViT-L/14.

Paper: https://arxiv.org/abs/2402.19091
GitHub: https://github.com/mever-team/rine
License: Apache 2.0
"""

import io
import logging
import os
import time

import numpy as np
from PIL import Image

from ..base import AnalyzerFinding, BaseAnalyzer, ModuleResult

logger = logging.getLogger(__name__)

_TORCH_AVAILABLE = False
try:
    import torch
    import torch.nn as nn
    _TORCH_AVAILABLE = True
except ImportError:
    pass


class _Hook:
    """Captures intermediate layer output via register_forward_hook."""
    def __init__(self, module):
        self.output = None
        self.hook = module.register_forward_hook(self._fn)

    def _fn(self, module, input, output):
        self.output = output

    def close(self):
        self.hook.remove()


class _RINEHead(nn.Module):
    """Trainable RINE head: proj1 → alpha weighting → proj2 → classifier."""
    def __init__(self, n_hooks=24, backbone_dim=1024, proj_dim=1024, nproj=1):
        super().__init__()
        self.alpha = nn.Parameter(torch.randn(1, n_hooks, proj_dim))

        proj1_layers = [nn.Dropout()]
        for i in range(nproj):
            proj1_layers.extend([
                nn.Linear(backbone_dim if i == 0 else proj_dim, proj_dim),
                nn.ReLU(),
                nn.Dropout(),
            ])
        self.proj1 = nn.Sequential(*proj1_layers)

        proj2_layers = [nn.Dropout()]
        for _ in range(nproj):
            proj2_layers.extend([
                nn.Linear(proj_dim, proj_dim),
                nn.ReLU(),
                nn.Dropout(),
            ])
        self.proj2 = nn.Sequential(*proj2_layers)

        self.head = nn.Sequential(
            nn.Linear(proj_dim, proj_dim), nn.ReLU(), nn.Dropout(),
            nn.Linear(proj_dim, proj_dim), nn.ReLU(), nn.Dropout(),
            nn.Linear(proj_dim, 1),
        )

    def forward(self, hook_outputs):
        # hook_outputs: list of [batch, seq_len, dim] from each ln_2 layer
        # Take CLS token (index 0) from each layer
        g = torch.stack([h[:, 0, :] for h in hook_outputs], dim=1)  # [B, 24, 1024]
        g = self.proj1(g.float())
        z = torch.softmax(self.alpha, dim=1) * g
        z = torch.sum(z, dim=1)  # [B, 1024]
        z = self.proj2(z)
        p = self.head(z)  # [B, 1]
        return p


class RINEDetectionAnalyzer(BaseAnalyzer):
    """RINE — intermediate CLIP features for content-independent AI detection."""

    MODULE_NAME = "rine_detection"
    MODULE_LABEL = "RINE AI detekcija (ECCV 2024)"

    def __init__(self) -> None:
        self._models_loaded = False
        self._clip_model = None
        self._clip_preprocess = None
        self._rine_head = None
        self._hooks = []
        self._device = "cpu"

    def _ensure_models(self) -> None:
        if self._models_loaded:
            return

        if not _TORCH_AVAILABLE:
            logger.warning("PyTorch not available — RINE disabled")
            self._models_loaded = True
            return

        cache_dir = os.environ.get("DENT_FORENSICS_MODEL_CACHE_DIR", "/app/models")
        ckpt_path = os.path.join(cache_dir, "rine", "model_4class_trainable.pth")

        if not os.path.exists(ckpt_path):
            logger.warning("RINE checkpoint not found at %s", ckpt_path)
            self._models_loaded = True
            return

        try:
            from transformers import CLIPModel, CLIPProcessor

            self._device = "cuda" if torch.cuda.is_available() else "cpu"

            # Load frozen CLIP ViT-L/14 via transformers (already cached on server)
            clip_id = "openai/clip-vit-large-patch14"
            self._clip_model = CLIPModel.from_pretrained(clip_id).to(self._device)
            self._clip_preprocess = CLIPProcessor.from_pretrained(clip_id)
            self._clip_model.eval()
            for p in self._clip_model.parameters():
                p.requires_grad = False

            # Register hooks on all layer_norm2 in vision encoder (24 layers)
            self._hooks = []
            for name, module in self._clip_model.vision_model.encoder.named_modules():
                if name.endswith(".layer_norm2"):
                    self._hooks.append(_Hook(module))

            logger.info("RINE: registered %d hooks on CLIP ViT-L/14", len(self._hooks))

            # Load RINE trainable head
            self._rine_head = _RINEHead(
                n_hooks=len(self._hooks),
                backbone_dim=1024,
                proj_dim=1024,
                nproj=1,
            ).to(self._device)

            state_dict = torch.load(ckpt_path, map_location=self._device, weights_only=True)
            self._rine_head.load_state_dict(state_dict, strict=True)
            self._rine_head.eval()

            param_count = sum(p.numel() for p in self._rine_head.parameters()) / 1e6
            logger.info("RINE head loaded: %.2fM params from %s", param_count, ckpt_path)

        except Exception as e:
            logger.warning("Failed to load RINE: %s", e)
            self._clip_model = None
            self._rine_head = None

        self._models_loaded = True

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        start = time.monotonic()
        findings: list[AnalyzerFinding] = []

        try:
            self._ensure_models()

            if self._clip_model is None or self._rine_head is None:
                return self._make_result(
                    [], int((time.monotonic() - start) * 1000),
                    error="RINE model not available",
                )

            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            score = self._compute_score(img)
            self._emit_findings(score, findings)

        except Exception as e:
            logger.warning("RINE detection error: %s", e)
            return self._make_result(
                [], int((time.monotonic() - start) * 1000), error=str(e),
            )

        elapsed = int((time.monotonic() - start) * 1000)
        result = self._make_result(findings, elapsed)
        result.risk_score = round(score, 4)
        result.risk_score100 = round(score * 100)
        return result

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([], 0)

    def _compute_score(self, img: Image.Image) -> float:
        """Run RINE: CLIP intermediate features → trainable head → sigmoid."""
        inputs = self._clip_preprocess(images=img, return_tensors="pt")
        pixel_values = inputs["pixel_values"].to(self._device)

        with torch.no_grad():
            # Forward through CLIP vision model — hooks capture intermediate outputs
            self._clip_model.vision_model(pixel_values)

            # Collect hook outputs (each is [batch, seq_len, hidden_dim])
            hook_outputs = [h.output for h in self._hooks]

            # RINE head processes all 24 intermediate layer CLS tokens
            logit = self._rine_head(hook_outputs)
            score = float(torch.sigmoid(logit.squeeze()).cpu().item())

        return float(np.clip(score, 0.0, 1.0))

    @staticmethod
    def _emit_findings(score: float, findings: list[AnalyzerFinding]) -> None:
        if score > 0.70:
            findings.append(AnalyzerFinding(
                code="RINE_AI_DETECTED",
                title="RINE: detektiran AI-generiran sadrzaj",
                description=(
                    f"RINE analiza (ECCV 2024) intermedijarnih CLIP slojeva "
                    f"detektirala je artefakte AI generiranja ({score:.0%}). "
                    f"Ova metoda je otporna na razlicite tipove sadrzaja "
                    f"jer koristi teksturne, a ne semanticke signale."
                ),
                risk_score=min(0.95, score),
                confidence=min(0.95, score),
                evidence={"rine_score": round(score, 4), "method": "rine_clip_intermediate"},
            ))
        elif score > 0.45:
            findings.append(AnalyzerFinding(
                code="RINE_AI_SUSPECTED",
                title="RINE: sumnja na AI sadrzaj",
                description=(
                    f"RINE analiza pokazuje umjerenu sumnju ({score:.0%}) "
                    f"da je slika umjetno generirana."
                ),
                risk_score=max(0.40, score * 0.80),
                confidence=min(0.80, 0.50 + score * 0.30),
                evidence={"rine_score": round(score, 4), "method": "rine_clip_intermediate"},
            ))
