"""
RINE AI Image Detection Module (ECCV 2024)

Leverages ALL 24 intermediate CLIP encoder blocks instead of just the
final layer. Early/middle blocks capture low-level texture and noise
artifacts that are content-independent — they persist regardless of
whether the image shows a car, face, or landscape.

+10.6% accuracy over standard CLIP probe (91.5% vs 80.9%).
Only 6.32M trainable parameters on top of frozen CLIP ViT-L/14.

CRITICAL: This module requires the OpenAI CLIP package (not HuggingFace
transformers CLIP). The checkpoint was trained with `import clip;
clip.load("ViT-L/14")` which produces numerically different intermediate
representations than HuggingFace's CLIPModel.

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
_OPENAI_CLIP_AVAILABLE = False

try:
    import torch
    import torch.nn as nn
    _TORCH_AVAILABLE = True
except ImportError:
    pass

if _TORCH_AVAILABLE:
    try:
        import clip as openai_clip
        _OPENAI_CLIP_AVAILABLE = True
    except ImportError:
        logger.warning(
            "OpenAI CLIP package not installed — RINE module disabled. "
            "Install with: pip install git+https://github.com/openai/CLIP.git"
        )


class _Hook:
    """Captures intermediate layer output via register_forward_hook."""
    def __init__(self, name, module):
        self.name = name
        self.output = None
        self.hook = module.register_forward_hook(self._fn)

    def _fn(self, module, input, output):
        self.output = output

    def close(self):
        self.hook.remove()


class _RINEHead(nn.Module):
    """Trainable RINE head: proj1 -> alpha weighting -> proj2 -> classifier.

    Architecture matches the original RINE paper (mever-team/rine) exactly:
    - proj1: Dropout + nproj x (Linear -> ReLU -> Dropout)
    - alpha: learnable [1, n_hooks, proj_dim] softmax-weighted aggregation
    - proj2: Dropout + nproj x (Linear -> ReLU -> Dropout)
    - head: Linear -> ReLU -> Dropout -> Linear -> ReLU -> Dropout -> Linear(1)
    """
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
        """Process intermediate CLIP hook outputs.

        In OpenAI CLIP, intermediate representations are in LND format
        (Length/seq_len, Batch, Dim). The original RINE code does:
            g = torch.stack([h.output for h in hooks], dim=2)[0, :, :, :]
        which stacks [L,N,D] tensors along dim=2 -> [L, N, n_hooks, D],
        then takes index 0 on the L dimension (CLS token) -> [N, n_hooks, D].
        """
        # hook_outputs: list of [seq_len, batch, dim] from each ln_2 (LND format)
        # Stack along dim=2: [seq_len, batch, n_hooks, dim]
        g = torch.stack(hook_outputs, dim=2)
        # Take CLS token (index 0 in sequence dimension): [batch, n_hooks, dim]
        g = g[0, :, :, :]

        g = self.proj1(g.float())
        z = torch.softmax(self.alpha, dim=1) * g
        z = torch.sum(z, dim=1)  # [batch, proj_dim]
        z = self.proj2(z)
        p = self.head(z)  # [batch, 1]
        return p


class RINEDetectionAnalyzer(BaseAnalyzer):
    """RINE -- intermediate CLIP features for content-independent AI detection.

    Uses OpenAI CLIP package (not HuggingFace transformers) because the
    checkpoint was trained with the OpenAI implementation. The two CLIP
    implementations produce numerically different intermediate representations
    even for the same ViT-L/14 weights, causing the RINE head to output
    ~0.0 when fed HuggingFace features.
    """

    MODULE_NAME = "rine_detection"
    MODULE_LABEL = "RINE AI detekcija (ECCV 2024)"

    def __init__(self) -> None:
        self._models_loaded = False
        self._clip_model = None
        self._clip_preprocess = None
        self._rine_head = None
        self._hooks: list[_Hook] = []
        self._device = "cpu"

    def _ensure_models(self) -> None:
        if self._models_loaded:
            return

        if not _TORCH_AVAILABLE:
            logger.warning("PyTorch not available -- RINE disabled")
            self._models_loaded = True
            return

        if not _OPENAI_CLIP_AVAILABLE:
            logger.warning("OpenAI CLIP not installed -- RINE disabled")
            self._models_loaded = True
            return

        cache_dir = os.environ.get("DENT_FORENSICS_MODEL_CACHE_DIR", "/app/models")
        ckpt_path = os.path.join(cache_dir, "rine", "model_4class_trainable.pth")

        if not os.path.exists(ckpt_path):
            logger.warning("RINE checkpoint not found at %s", ckpt_path)
            self._models_loaded = True
            return

        try:
            self._device = "cuda" if torch.cuda.is_available() else "cpu"

            # ---- Load frozen CLIP ViT-L/14 via OpenAI CLIP package ----
            # clip.load() downloads the model on first run. We use a
            # persistent download_root inside the models volume so the
            # entrypoint.sh pre-download is reused.
            clip_download_root = os.path.join(cache_dir, "clip_openai")
            os.makedirs(clip_download_root, exist_ok=True)
            self._clip_model, self._clip_preprocess = openai_clip.load(
                "ViT-L/14", device=self._device, jit=False,
                download_root=clip_download_root,
            )
            self._clip_model.eval()
            for p in self._clip_model.parameters():
                p.requires_grad = False

            # ---- Register hooks on all ln_2 in visual transformer ----
            # OpenAI CLIP structure: model.visual.transformer.resblocks[i].ln_2
            # The RINE paper hooks into ln_2 of every ResidualAttentionBlock.
            # named_modules() with "ln_2" filter matches the original RINE code:
            #   [Hook(name, module) for name, module in
            #    self.clip.visual.named_modules() if "ln_2" in name]
            self._hooks = []
            for name, module in self._clip_model.visual.named_modules():
                if "ln_2" in name:
                    self._hooks.append(_Hook(name, module))

            logger.info(
                "RINE: registered %d hooks on OpenAI CLIP ViT-L/14",
                len(self._hooks),
            )

            if len(self._hooks) != 24:
                logger.warning(
                    "RINE: expected 24 hooks but got %d -- "
                    "checkpoint may not match this CLIP architecture",
                    len(self._hooks),
                )

            # ---- Load RINE trainable head ----
            # 4-class checkpoint config: nproj=2, proj_dim=1024, backbone_dim=1024
            self._rine_head = _RINEHead(
                n_hooks=len(self._hooks),
                backbone_dim=1024,
                proj_dim=1024,
                nproj=2,
            ).to(self._device)

            state_dict = torch.load(
                ckpt_path, map_location=self._device, weights_only=True,
            )
            self._rine_head.load_state_dict(state_dict, strict=True)
            self._rine_head.eval()

            param_count = sum(p.numel() for p in self._rine_head.parameters()) / 1e6
            logger.info(
                "RINE head loaded: %.2fM params from %s", param_count, ckpt_path,
            )

        except Exception as e:
            logger.warning("Failed to load RINE: %s", e, exc_info=True)
            self._clip_model = None
            self._rine_head = None
            self._hooks = []

        self._models_loaded = True

    # Logit threshold for treating the RINE output as "saturated / no signal".
    # The shipped 4-class checkpoint was trained on ProGAN/StyleGAN/BigGAN and
    # outputs logits in the range -30 to -55 on every modern car-damage image
    # regardless of whether it's real or AI-generated. Both saturate to ~0
    # via sigmoid and the score has zero discriminative value. Treat any
    # |logit| > this threshold as "model has no opinion" → return error so
    # fusion does not consume the bogus 0%.
    _LOGIT_SATURATION_THRESHOLD = 20.0

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
            score, raw_logit = self._compute_score(img)

            # Saturation guard: 4-class checkpoint fails to generalize to
            # modern AI distributions and produces logits like -51 on AI and
            # -33 on authentic — both round to sigmoid 0.000 and the result
            # is meaningless. Treat as model error rather than emitting a
            # misleading "0% AI" verdict that the meta-learner would consume.
            if abs(raw_logit) > self._LOGIT_SATURATION_THRESHOLD:
                logger.debug(
                    "RINE saturated logit %.2f on %s — treating as no signal",
                    raw_logit, filename,
                )
                return self._make_result(
                    [], int((time.monotonic() - start) * 1000),
                    error=f"RINE checkpoint saturated (logit={raw_logit:.1f}, model not calibrated for modern AI)",
                )

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

    def _compute_score(self, img: Image.Image) -> tuple[float, float]:
        """Run RINE: OpenAI CLIP intermediate features -> trainable head -> sigmoid.

        Returns (score, raw_logit). Raw logit is used by the caller to detect
        saturated outputs (the existing 4-class checkpoint produces extreme
        negative logits like -50 on every modern car-damage image regardless
        of whether the image is real or AI — meaning the model has failed to
        generalize from its ProGAN/StyleGAN/BigGAN training distribution and
        the score is meaningless).
        """
        # Preprocess using OpenAI CLIP's transform (Resize+CenterCrop+Normalize)
        pixel_values = self._clip_preprocess(img).unsqueeze(0).to(self._device)

        with torch.no_grad():
            # Forward through CLIP vision encoder -- hooks capture ln_2 outputs.
            self._clip_model.encode_image(pixel_values)

            # Collect hook outputs.
            hook_outputs = [h.output for h in self._hooks]

            # RINE head: stack, extract CLS, project, weight, classify
            logit_t = self._rine_head(hook_outputs)
            raw_logit = float(logit_t.squeeze().cpu().item())
            score = float(torch.sigmoid(logit_t.squeeze()).cpu().item())

        return float(np.clip(score, 0.0, 1.0)), raw_logit

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
