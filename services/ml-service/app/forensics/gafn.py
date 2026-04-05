"""
Gated Attention Fusion Network (GAFN) for forensic score fusion.

Replaces/augments the hand-crafted rules in fusion.py and GBM in stacking_meta.py
with a learned attention-based model that:
  1. Embeds each module's (risk, confidence, findings, availability) → 8-dim
  2. Applies cross-module attention to learn interactions
  3. Fuses via attention-weighted pooling + global context → 3 classes

Key advantages over hand-crafted rules:
  - Learns "CLIP high + everything low = FP" from data
  - Handles missing modules via attention masking (no zero = authentic confusion)
  - Per-module contribution scores for interpretability
  - Adding new detectors = adding 1 attention slot (no rule rewriting)

Key advantages over GBM:
  - Smooth, continuous interaction surfaces (vs axis-aligned GBM splits)
  - Native missing-module handling
  - Differentiable end-to-end (future: fine-tune through probes)

Parameters: ~1,800 — fits comfortably with 14K training samples.
"""

import logging
import os

import numpy as np

logger = logging.getLogger(__name__)

_TORCH_AVAILABLE = False
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    _TORCH_AVAILABLE = True
except ImportError:
    pass

# Feature layout
FEATURES_PER_MODULE = 4  # risk_score, confidence, n_findings_norm, is_available
N_GLOBAL_FEATURES = 6  # has_c2pa, has_ai_tool, has_ai_filename, n_active, n_high, n_low
N_CLASSES = 3
CLASS_NAMES = ["authentic", "ai_generated", "tampered"]


def extract_gafn_features(
    modules: list,
    module_order: list[str],
    metadata_flags: dict | None = None,
) -> np.ndarray:
    """Extract GAFN feature vector from module results.

    Returns: (N_modules * 4 + 6,) flat vector.

    Feature layout per module: [risk_score, avg_confidence, n_findings_norm, is_available]
    Global features: [has_c2pa, has_ai_tool, has_ai_filename, n_active, n_high, n_low]
    """
    n_modules = len(module_order)

    # Build lookup
    mod_lookup = {}
    for m in modules:
        if not m.error:
            mod_lookup[m.module_name] = m

    # Per-module features
    features = np.zeros(n_modules * FEATURES_PER_MODULE, dtype=np.float32)

    n_active = 0
    n_high = 0
    n_low = 0

    for i, mod_name in enumerate(module_order):
        m = mod_lookup.get(mod_name)
        base = i * FEATURES_PER_MODULE

        if m is None:
            # Module not available — all zeros, is_available = 0
            features[base + 3] = 0.0
            continue

        risk = float(m.risk_score)
        features[base + 0] = risk
        features[base + 3] = 1.0  # is_available

        if m.findings:
            avg_conf = sum(f.confidence for f in m.findings) / len(m.findings)
            n_findings = min(len(m.findings), 10) / 10.0
        else:
            avg_conf = 0.0
            n_findings = 0.0

        features[base + 1] = avg_conf
        features[base + 2] = n_findings

        n_active += 1
        if risk >= 0.50:
            n_high += 1
        if risk < 0.15:
            n_low += 1

    # Global features
    flags = metadata_flags or {}
    global_feats = np.array(
        [
            float(flags.get("has_c2pa", False)),
            float(flags.get("has_ai_tool", False)),
            float(flags.get("has_ai_filename", False)),
            n_active / max(n_modules, 1),
            n_high / max(n_modules, 1),
            n_low / max(n_modules, 1),
        ],
        dtype=np.float32,
    )

    return np.concatenate([features, global_feats])


if _TORCH_AVAILABLE:

    class ModuleEmbedding(nn.Module):
        """Per-module gated embedding: (4 features) → (d_model)."""

        def __init__(self, d_in: int = FEATURES_PER_MODULE, d_model: int = 8):
            super().__init__()
            self.fc = nn.Linear(d_in, d_model)
            self.gate = nn.Linear(d_in, d_model)
            self.norm = nn.LayerNorm(d_model)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            h = F.gelu(self.fc(x))
            g = torch.sigmoid(self.gate(x))
            return self.norm(h * g)

    class CrossModuleAttention(nn.Module):
        """Multi-head attention over module embeddings."""

        def __init__(self, d_model: int = 8, n_heads: int = 2, dropout: float = 0.1):
            super().__init__()
            self.attention = nn.MultiheadAttention(
                embed_dim=d_model,
                num_heads=n_heads,
                dropout=dropout,
                batch_first=True,
            )
            self.norm = nn.LayerNorm(d_model)
            self.dropout = nn.Dropout(dropout)

        def forward(self, x, mask=None):
            attn_out, attn_weights = self.attention(
                x, x, x,
                key_padding_mask=mask,
                need_weights=True,
                average_attn_weights=True,
            )
            out = self.norm(x + self.dropout(attn_out))
            return out, attn_weights

    class GatedAttentionFusionNetwork(nn.Module):
        """GAFN: attention-based forensic score fusion.

        Input:  (batch, N_modules * 4 + 6)
        Output: logits (batch, 3), probs (batch, 3), contributions (batch, N_modules)
        """

        def __init__(
            self,
            n_modules: int = 30,
            features_per_module: int = FEATURES_PER_MODULE,
            n_global: int = N_GLOBAL_FEATURES,
            d_model: int = 8,
            n_heads: int = 2,
            d_fusion: int = 32,
            n_classes: int = N_CLASSES,
            dropout: float = 0.2,
        ):
            super().__init__()
            self.n_modules = n_modules
            self.features_per_module = features_per_module
            self.d_model = d_model

            self.module_embed = ModuleEmbedding(features_per_module, d_model)
            self.module_type_embed = nn.Embedding(n_modules, d_model)
            self.attention = CrossModuleAttention(d_model, n_heads, dropout)
            self.global_proj = nn.Linear(n_global, d_model)

            self.fusion = nn.Sequential(
                nn.Linear(d_model * 2, d_fusion),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(d_fusion, d_fusion // 2),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(d_fusion // 2, n_classes),
            )

            self.importance_head = nn.Linear(d_model, 1)
            self.temperature = nn.Parameter(torch.ones(1) * 1.5)

            self._init_weights()

        def _init_weights(self):
            for m in self.modules():
                if isinstance(m, nn.Linear):
                    nn.init.xavier_uniform_(m.weight)
                    if m.bias is not None:
                        nn.init.zeros_(m.bias)

        def forward(self, x: torch.Tensor) -> dict[str, torch.Tensor]:
            batch_size = x.shape[0]
            n_mod_features = self.n_modules * self.features_per_module

            module_features = x[:, :n_mod_features].view(
                batch_size, self.n_modules, self.features_per_module
            )
            global_features = x[:, n_mod_features:]

            # Availability mask: True where unavailable
            mask = module_features[:, :, 3] < 0.5

            # Per-module embeddings + type embeddings
            embeds = []
            for i in range(self.n_modules):
                e = self.module_embed(module_features[:, i, :])
                t = self.module_type_embed(
                    torch.tensor([i], device=x.device).expand(batch_size)
                )
                embeds.append(e + t)
            embeds = torch.stack(embeds, dim=1)

            # Cross-module attention
            embeds, _ = self.attention(embeds, mask)

            # Module importance (interpretability)
            importance = self.importance_head(embeds).squeeze(-1)
            importance = importance.masked_fill(mask, float("-inf"))
            contributions = F.softmax(importance, dim=-1)

            # Pooling + global context
            pooled = (embeds * contributions.unsqueeze(-1)).sum(dim=1)
            global_embed = F.gelu(self.global_proj(global_features))
            fused = torch.cat([pooled, global_embed], dim=-1)

            logits = self.fusion(fused)
            probs = F.softmax(logits / self.temperature, dim=-1)

            return {
                "logits": logits,
                "probs": probs,
                "contributions": contributions,
            }


class GAFNPredictor:
    """Production wrapper for GAFN model.

    Loads trained weights and provides predict() interface matching
    StackingMetaLearner for drop-in replacement.
    """

    def __init__(self, weights_path: str = ""):
        self._weights_path = weights_path
        self._model = None
        self._loaded = False
        self._load_attempted = False
        self._module_order = None

    def predict_proba(
        self,
        modules: list,
        module_order: list[str],
        metadata_flags: dict | None = None,
    ) -> dict[str, float] | None:
        """Predict 3-class probabilities.

        Returns {"authentic": 0.65, "ai_generated": 0.25, "tampered": 0.10}
        or None if no trained weights available.
        """
        if not self._loaded and not self._load_attempted:
            self._try_load(module_order)

        if not self._loaded or self._model is None:
            return None

        features = extract_gafn_features(modules, module_order, metadata_flags)
        features_t = torch.from_numpy(features).unsqueeze(0)

        with torch.no_grad():
            result = self._model(features_t)
            probs = result["probs"][0].numpy()

        return {
            "authentic": round(float(probs[0]), 4),
            "ai_generated": round(float(probs[1]), 4),
            "tampered": round(float(probs[2]), 4),
        }

    def get_contributions(
        self,
        modules: list,
        module_order: list[str],
        metadata_flags: dict | None = None,
    ) -> dict[str, float] | None:
        """Get per-module contribution scores (interpretability)."""
        if not self._loaded or self._model is None:
            return None

        features = extract_gafn_features(modules, module_order, metadata_flags)
        features_t = torch.from_numpy(features).unsqueeze(0)

        with torch.no_grad():
            result = self._model(features_t)
            contributions = result["contributions"][0].numpy()

        return {
            name: round(float(contributions[i]), 4)
            for i, name in enumerate(module_order)
            if contributions[i] > 0.01
        }

    def _try_load(self, module_order: list[str]) -> None:
        self._load_attempted = True

        if not _TORCH_AVAILABLE:
            return

        base_dir = os.environ.get("DENT_FORENSICS_MODEL_CACHE_DIR", "/app/models")
        weights_path = self._weights_path or os.path.join(
            base_dir, "gafn", "gafn_weights.pt"
        )

        if not os.path.isfile(weights_path):
            logger.debug("GAFN weights not found at %s", weights_path)
            return

        try:
            checkpoint = torch.load(weights_path, map_location="cpu", weights_only=False)

            n_modules = checkpoint.get("n_modules", len(module_order))
            saved_order = checkpoint.get("module_order", [])

            if saved_order and saved_order != module_order:
                logger.warning(
                    "GAFN module_order mismatch: trained=%d, current=%d",
                    len(saved_order),
                    len(module_order),
                )
                return

            self._model = GatedAttentionFusionNetwork(n_modules=n_modules)
            self._model.load_state_dict(checkpoint["model_state_dict"])
            self._model.eval()
            self._module_order = module_order
            self._loaded = True

            n_params = sum(p.numel() for p in self._model.parameters())
            logger.info(
                "GAFN loaded from %s (%d params, %d modules)",
                weights_path,
                n_params,
                n_modules,
            )
        except Exception as e:
            logger.warning("Failed to load GAFN: %s", e)


# Singleton
_gafn_predictor: GAFNPredictor | None = None


def get_gafn_predictor(weights_path: str = "") -> GAFNPredictor:
    global _gafn_predictor
    if _gafn_predictor is None:
        _gafn_predictor = GAFNPredictor(weights_path)
    return _gafn_predictor
