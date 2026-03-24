"""
Mesorch Tampering Detection Module (AAAI 2025)

Dual-backbone CNN+Transformer with DCT frequency decomposition for
pixel-level image manipulation localization.

Best JPEG robustness of any open-source tampering detector:
  F1=0.774 avg across JPEG quality factors (vs TruFor 0.705).

Model vendored from: https://github.com/scu-zjz/Mesorch
Checkpoint: mesorch-98.pth (Google Drive)
License: Academic use

Architecture:
  - ConvNeXt Tiny processes RGB + high-freq DCT features (6 channels)
  - MixVisionTransformer (SegFormer MiT-B3) processes RGB + low-freq DCT
  - 8-stream gated fusion via learned ScoreNetwork
  - Output: (1, 1, H, W) sigmoid mask — pixel-level tampering localization
"""

import base64
import io
import logging
import math
import os
import time
from functools import partial

import numpy as np
from PIL import Image, ImageFilter

from ...config import settings
from ..base import AnalyzerFinding, BaseAnalyzer, ModuleResult

logger = logging.getLogger(__name__)

_TORCH_AVAILABLE = False
_TIMM_AVAILABLE = False

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    _TORCH_AVAILABLE = True
except ImportError:
    logger.info("PyTorch not installed, Mesorch detection disabled")

if _TORCH_AVAILABLE:
    try:
        import timm
        from timm.layers import DropPath, to_2tuple, trunc_normal_
        _TIMM_AVAILABLE = True
    except ImportError:
        logger.info("timm not installed, Mesorch detection disabled")

IMAGE_SIZE = 512

# Jet colormap LUT (shared with cnn_forensics)
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


# ======================================================================
# Vendored Mesorch model classes (from scu-zjz/Mesorch, AAAI 2025)
# ======================================================================

if _TORCH_AVAILABLE and _TIMM_AVAILABLE:

    class HighDctFrequencyExtractor(nn.Module):
        def __init__(self, alpha=0.05):
            super().__init__()
            self.alpha = alpha
            self.dct_matrix_h = None
            self.dct_matrix_w = None

        def create_dct_matrix(self, N):
            n = torch.arange(N, dtype=torch.float32).reshape((1, N))
            k = torch.arange(N, dtype=torch.float32).reshape((N, 1))
            dct = torch.sqrt(torch.tensor(2.0 / N)) * torch.cos(
                math.pi * k * (2 * n + 1) / (2 * N)
            )
            dct[0, :] = 1 / math.sqrt(N)
            return dct

        def dct_2d(self, x):
            H, W = x.size(-2), x.size(-1)
            if self.dct_matrix_h is None or self.dct_matrix_h.size(0) != H:
                self.dct_matrix_h = self.create_dct_matrix(H).to(x.device)
            if self.dct_matrix_w is None or self.dct_matrix_w.size(0) != W:
                self.dct_matrix_w = self.create_dct_matrix(W).to(x.device)
            return torch.matmul(self.dct_matrix_h, torch.matmul(x, self.dct_matrix_w.t()))

        def idct_2d(self, x):
            H, W = x.size(-2), x.size(-1)
            if self.dct_matrix_h is None or self.dct_matrix_h.size(0) != H:
                self.dct_matrix_h = self.create_dct_matrix(H).to(x.device)
            if self.dct_matrix_w is None or self.dct_matrix_w.size(0) != W:
                self.dct_matrix_w = self.create_dct_matrix(W).to(x.device)
            return torch.matmul(self.dct_matrix_h.t(), torch.matmul(x, self.dct_matrix_w))

        def forward(self, x):
            xq = self.dct_2d(x)
            h, w = xq.shape[-2:]
            mask = torch.ones(h, w, device=x.device)
            ah, aw = int(self.alpha * h), int(self.alpha * w)
            mask[:ah, :aw] = 0  # Zero low-freq → keep high-freq
            xq = xq * mask
            xh = self.idct_2d(xq)
            B = xh.shape[0]
            lo = xh.reshape(B, -1).min(dim=1, keepdim=True).values.view(B, 1, 1, 1)
            hi = xh.reshape(B, -1).max(dim=1, keepdim=True).values.view(B, 1, 1, 1)
            return (xh - lo) / (hi - lo + 1e-8)

    class LowDctFrequencyExtractor(nn.Module):
        def __init__(self, alpha=0.95):
            super().__init__()
            self.alpha = alpha
            self.dct_matrix_h = None
            self.dct_matrix_w = None

        def create_dct_matrix(self, N):
            n = torch.arange(N, dtype=torch.float32).reshape((1, N))
            k = torch.arange(N, dtype=torch.float32).reshape((N, 1))
            dct = torch.sqrt(torch.tensor(2.0 / N)) * torch.cos(
                math.pi * k * (2 * n + 1) / (2 * N)
            )
            dct[0, :] = 1 / math.sqrt(N)
            return dct

        def dct_2d(self, x):
            H, W = x.size(-2), x.size(-1)
            if self.dct_matrix_h is None or self.dct_matrix_h.size(0) != H:
                self.dct_matrix_h = self.create_dct_matrix(H).to(x.device)
            if self.dct_matrix_w is None or self.dct_matrix_w.size(0) != W:
                self.dct_matrix_w = self.create_dct_matrix(W).to(x.device)
            return torch.matmul(self.dct_matrix_h, torch.matmul(x, self.dct_matrix_w.t()))

        def idct_2d(self, x):
            H, W = x.size(-2), x.size(-1)
            if self.dct_matrix_h is None or self.dct_matrix_h.size(0) != H:
                self.dct_matrix_h = self.create_dct_matrix(H).to(x.device)
            if self.dct_matrix_w is None or self.dct_matrix_w.size(0) != W:
                self.dct_matrix_w = self.create_dct_matrix(W).to(x.device)
            return torch.matmul(self.dct_matrix_h.t(), torch.matmul(x, self.dct_matrix_w))

        def forward(self, x):
            xq = self.dct_2d(x)
            h, w = xq.shape[-2:]
            mask = torch.ones(h, w, device=x.device)
            ah, aw = int(self.alpha * h), int(self.alpha * w)
            mask[-ah:, -aw:] = 0  # Zero high-freq → keep low-freq
            xq = xq * mask
            xh = self.idct_2d(xq)
            B = xh.shape[0]
            lo = xh.reshape(B, -1).min(dim=1, keepdim=True).values.view(B, 1, 1, 1)
            hi = xh.reshape(B, -1).max(dim=1, keepdim=True).values.view(B, 1, 1, 1)
            return (xh - lo) / (hi - lo + 1e-8)

    class DWConv(nn.Module):
        def __init__(self, dim=768):
            super().__init__()
            self.dwconv = nn.Conv2d(dim, dim, 3, 1, 1, bias=True, groups=dim)

        def forward(self, x, H, W):
            B, N, C = x.shape
            x = x.transpose(1, 2).view(B, C, H, W)
            x = self.dwconv(x)
            return x.flatten(2).transpose(1, 2)

    class _Mlp(nn.Module):
        def __init__(self, in_features, hidden_features=None, out_features=None,
                     act_layer=nn.GELU, drop=0.0):
            super().__init__()
            out_features = out_features or in_features
            hidden_features = hidden_features or in_features
            self.fc1 = nn.Linear(in_features, hidden_features)
            self.dwconv = DWConv(hidden_features)
            self.act = act_layer()
            self.fc2 = nn.Linear(hidden_features, out_features)
            self.drop = nn.Dropout(drop)

        def forward(self, x, H, W):
            x = self.fc1(x)
            x = self.dwconv(x, H, W)
            x = self.act(x)
            x = self.drop(x)
            x = self.fc2(x)
            x = self.drop(x)
            return x

    class _Attention(nn.Module):
        def __init__(self, dim, num_heads=8, qkv_bias=False, qk_scale=None,
                     attn_drop=0.0, proj_drop=0.0, sr_ratio=1):
            super().__init__()
            self.num_heads = num_heads
            head_dim = dim // num_heads
            self.scale = qk_scale or head_dim ** -0.5
            self.q = nn.Linear(dim, dim, bias=qkv_bias)
            self.kv = nn.Linear(dim, dim * 2, bias=qkv_bias)
            self.attn_drop = nn.Dropout(attn_drop)
            self.proj = nn.Linear(dim, dim)
            self.proj_drop = nn.Dropout(proj_drop)
            self.sr_ratio = sr_ratio
            if sr_ratio > 1:
                self.sr = nn.Conv2d(dim, dim, kernel_size=sr_ratio, stride=sr_ratio)
                self.norm = nn.LayerNorm(dim)

        def forward(self, x, H, W):
            B, N, C = x.shape
            q = self.q(x).reshape(B, N, self.num_heads, C // self.num_heads).permute(0, 2, 1, 3)
            if self.sr_ratio > 1:
                x_ = x.permute(0, 2, 1).reshape(B, C, H, W)
                x_ = self.sr(x_).reshape(B, C, -1).permute(0, 2, 1)
                x_ = self.norm(x_)
                kv = self.kv(x_).reshape(B, -1, 2, self.num_heads, C // self.num_heads).permute(2, 0, 3, 1, 4)
            else:
                kv = self.kv(x).reshape(B, -1, 2, self.num_heads, C // self.num_heads).permute(2, 0, 3, 1, 4)
            k, v = kv[0], kv[1]
            attn = (q @ k.transpose(-2, -1)) * self.scale
            attn = attn.float().softmax(dim=-1)
            attn = self.attn_drop(attn)
            x = (attn @ v).transpose(1, 2).reshape(B, N, C)
            x = self.proj(x)
            return self.proj_drop(x)

    class _Block(nn.Module):
        def __init__(self, dim, num_heads, mlp_ratio=4.0, qkv_bias=False,
                     qk_scale=None, drop=0.0, attn_drop=0.0, drop_path=0.0,
                     act_layer=nn.GELU, norm_layer=nn.LayerNorm, sr_ratio=1):
            super().__init__()
            self.norm1 = norm_layer(dim)
            self.attn = _Attention(dim, num_heads=num_heads, qkv_bias=qkv_bias,
                                   qk_scale=qk_scale, attn_drop=attn_drop,
                                   proj_drop=drop, sr_ratio=sr_ratio)
            self.drop_path = DropPath(drop_path) if drop_path > 0.0 else nn.Identity()
            self.norm2 = norm_layer(dim)
            self.mlp = _Mlp(in_features=dim, hidden_features=int(dim * mlp_ratio),
                            act_layer=act_layer, drop=drop)

        def forward(self, x, H, W):
            x = x + self.drop_path(self.attn(self.norm1(x), H, W))
            x = x + self.drop_path(self.mlp(self.norm2(x), H, W))
            return x

    class OverlapPatchEmbed(nn.Module):
        def __init__(self, img_size=224, patch_size=7, stride=4,
                     in_chans=3, embed_dim=768):
            super().__init__()
            img_size = to_2tuple(img_size)
            patch_size = to_2tuple(patch_size)
            self.proj = nn.Conv2d(in_chans, embed_dim, kernel_size=patch_size,
                                  stride=stride,
                                  padding=(patch_size[0] // 2, patch_size[1] // 2))
            self.norm = nn.LayerNorm(embed_dim)

        def forward(self, x):
            x = self.proj(x)
            _, _, H, W = x.shape
            x = x.flatten(2).transpose(1, 2)
            x = self.norm(x)
            return x, H, W

    class _ConvNeXt(timm.models.convnext.ConvNeXt):
        def __init__(self):
            super().__init__(depths=(3, 3, 9, 3), dims=(96, 192, 384, 768))
            # Expand stem from 3 to 6 input channels
            orig = self.stem[0]
            new_conv = nn.Conv2d(6, orig.out_channels,
                                 kernel_size=orig.kernel_size,
                                 stride=orig.stride,
                                 padding=orig.padding, bias=False)
            new_conv.weight.data[:, :3] = orig.weight.data.clone()[:, :3]
            nn.init.kaiming_normal_(new_conv.weight[:, 3:])
            self.stem[0] = new_conv

        def forward_features(self, x):
            x = self.stem(x)
            out = []
            for stage in self.stages:
                x = stage(x)
                out.append(x)
            x = self.norm_pre(x)
            return x, out

        def forward(self, x, *args, **kwargs):
            return self.forward_features(x)

    class MixVisionTransformer(nn.Module):
        def __init__(self, img_size=512, in_chans=3,
                     embed_dims=(64, 128, 320, 512),
                     num_heads=(1, 2, 5, 8), mlp_ratios=(4, 4, 4, 4),
                     qkv_bias=True, drop_rate=0.0, attn_drop_rate=0.0,
                     drop_path_rate=0.1,
                     norm_layer=partial(nn.LayerNorm, eps=1e-6),
                     depths=(3, 4, 18, 3), sr_ratios=(8, 4, 2, 1)):
            super().__init__()
            self.depths = depths
            self.patch_embed1 = OverlapPatchEmbed(img_size, 7, 4, in_chans, embed_dims[0])
            self.patch_embed2 = OverlapPatchEmbed(img_size // 4, 3, 2, embed_dims[0], embed_dims[1])
            self.patch_embed3 = OverlapPatchEmbed(img_size // 8, 3, 2, embed_dims[1], embed_dims[2])
            self.patch_embed4 = OverlapPatchEmbed(img_size // 16, 3, 2, embed_dims[2], embed_dims[3])
            dpr = [x.item() for x in torch.linspace(0, drop_path_rate, sum(depths))]
            cur = 0
            self.block1 = nn.ModuleList([_Block(embed_dims[0], num_heads[0], mlp_ratios[0], qkv_bias, drop=drop_rate, attn_drop=attn_drop_rate, drop_path=dpr[cur + i], norm_layer=norm_layer, sr_ratio=sr_ratios[0]) for i in range(depths[0])])
            self.norm1 = norm_layer(embed_dims[0])
            cur += depths[0]
            self.block2 = nn.ModuleList([_Block(embed_dims[1], num_heads[1], mlp_ratios[1], qkv_bias, drop=drop_rate, attn_drop=attn_drop_rate, drop_path=dpr[cur + i], norm_layer=norm_layer, sr_ratio=sr_ratios[1]) for i in range(depths[1])])
            self.norm2 = norm_layer(embed_dims[1])
            cur += depths[1]
            self.block3 = nn.ModuleList([_Block(embed_dims[2], num_heads[2], mlp_ratios[2], qkv_bias, drop=drop_rate, attn_drop=attn_drop_rate, drop_path=dpr[cur + i], norm_layer=norm_layer, sr_ratio=sr_ratios[2]) for i in range(depths[2])])
            self.norm3 = norm_layer(embed_dims[2])
            cur += depths[2]
            self.block4 = nn.ModuleList([_Block(embed_dims[3], num_heads[3], mlp_ratios[3], qkv_bias, drop=drop_rate, attn_drop=attn_drop_rate, drop_path=dpr[cur + i], norm_layer=norm_layer, sr_ratio=sr_ratios[3]) for i in range(depths[3])])
            self.norm4 = norm_layer(embed_dims[3])
            # Expand first patch embed from 3 to 6 input channels
            orig = self.patch_embed1.proj
            new_conv = nn.Conv2d(6, orig.out_channels,
                                 kernel_size=orig.kernel_size,
                                 stride=orig.stride,
                                 padding=orig.padding, bias=False)
            new_conv.weight.data[:, :3] = orig.weight.data.clone()[:, :3]
            nn.init.kaiming_normal_(new_conv.weight[:, 3:])
            self.patch_embed1.proj = new_conv

        def forward_features(self, x):
            B = x.shape[0]
            outs = []
            x, H, W = self.patch_embed1(x)
            for blk in self.block1:
                x = blk(x, H, W)
            x = self.norm1(x).reshape(B, H, W, -1).permute(0, 3, 1, 2).contiguous()
            outs.append(x)
            x, H, W = self.patch_embed2(x)
            for blk in self.block2:
                x = blk(x, H, W)
            x = self.norm2(x).reshape(B, H, W, -1).permute(0, 3, 1, 2).contiguous()
            outs.append(x)
            x, H, W = self.patch_embed3(x)
            for blk in self.block3:
                x = blk(x, H, W)
            x = self.norm3(x).reshape(B, H, W, -1).permute(0, 3, 1, 2).contiguous()
            outs.append(x)
            x, H, W = self.patch_embed4(x)
            for blk in self.block4:
                x = blk(x, H, W)
            x = self.norm4(x).reshape(B, H, W, -1).permute(0, 3, 1, 2).contiguous()
            outs.append(x)
            return x, outs

        def forward(self, x):
            return self.forward_features(x)

    class _UpsampleConcatConv(nn.Module):
        def __init__(self):
            super().__init__()
            self.upsamplec2 = nn.ConvTranspose2d(192, 96, kernel_size=4, stride=2, padding=1)
            self.upsamples2 = nn.ConvTranspose2d(128, 64, kernel_size=4, stride=2, padding=1)
            self.upsamplec3 = nn.Sequential(
                nn.ConvTranspose2d(384, 192, 4, 2, 1), nn.ConvTranspose2d(192, 96, 4, 2, 1))
            self.upsamples3 = nn.Sequential(
                nn.ConvTranspose2d(320, 128, 4, 2, 1), nn.ConvTranspose2d(128, 64, 4, 2, 1))
            self.upsamplec4 = nn.Sequential(
                nn.ConvTranspose2d(768, 384, 4, 2, 1), nn.ConvTranspose2d(384, 192, 4, 2, 1),
                nn.ConvTranspose2d(192, 96, 4, 2, 1))
            self.upsamples4 = nn.Sequential(
                nn.ConvTranspose2d(512, 320, 4, 2, 1), nn.ConvTranspose2d(320, 128, 4, 2, 1),
                nn.ConvTranspose2d(128, 64, 4, 2, 1))

        def forward(self, inputs):
            c1, c2, c3, c4, s1, s2, s3, s4 = inputs
            c2 = self.upsamplec2(c2)
            c3 = self.upsamplec3(c3)
            c4 = self.upsamplec4(c4)
            s2 = self.upsamples2(s2)
            s3 = self.upsamples3(s3)
            s4 = self.upsamples4(s4)
            features = [c1, c2, c3, c4, s1, s2, s3, s4]
            return torch.cat(features, dim=1), features

    class _LayerNorm2d(nn.LayerNorm):
        def forward(self, x):
            x = x.permute(0, 2, 3, 1)
            x = F.layer_norm(x, self.normalized_shape, self.weight, self.bias, self.eps)
            return x.permute(0, 3, 1, 2)

    class _ScoreNetwork(nn.Module):
        def __init__(self):
            super().__init__()
            self.conv1 = nn.Conv2d(9, 192, kernel_size=7, stride=2, padding=3)
            self.invert = nn.Sequential(
                _LayerNorm2d(192),
                nn.Conv2d(192, 192, 3, 1, 1),
                nn.Conv2d(192, 768, 1),
                nn.Conv2d(768, 192, 1),
                nn.GELU(),
            )
            self.conv2 = nn.Conv2d(192, 8, kernel_size=7, stride=2, padding=3)
            self.softmax = nn.Softmax(dim=1)

        def forward(self, x):
            x = self.conv1(x)
            x = x + self.invert(x)
            x = self.conv2(x)
            return self.softmax(x.float())

    class MesorchModel(nn.Module):
        """MesorchFull — 8-stream gated dual-backbone model."""
        def __init__(self, image_size=512):
            super().__init__()
            self.convnext = _ConvNeXt()
            self.segformer = MixVisionTransformer(img_size=image_size)
            self.upsample = _UpsampleConcatConv()
            self.low_dct = LowDctFrequencyExtractor()
            self.high_dct = HighDctFrequencyExtractor()
            self.inverse = nn.ModuleList(
                [nn.Conv2d(96, 1, 1) for _ in range(4)]
                + [nn.Conv2d(64, 1, 1) for _ in range(4)]
            )
            self.gate = _ScoreNetwork()
            self.resize = nn.Upsample(size=(image_size, image_size),
                                      mode="bilinear", align_corners=True)

        def predict(self, image):
            """Inference-only forward. Returns sigmoid mask [B, 1, H, W]."""
            high_freq = self.high_dct(image)
            low_freq = self.low_dct(image)
            input_high = torch.cat([image, high_freq], dim=1)
            input_low = torch.cat([image, low_freq], dim=1)
            input_all = torch.cat([image, high_freq, low_freq], dim=1)
            _, outs1 = self.convnext(input_high)
            _, outs2 = self.segformer(input_low)
            _, features = self.upsample(outs1 + outs2)
            gate = self.gate(input_all)
            reduced = torch.cat([self.inverse[i](features[i]) for i in range(8)], dim=1)
            pred = torch.sum(gate * reduced, dim=1, keepdim=True)
            pred = self.resize(pred)
            return torch.sigmoid(pred.float())


# ======================================================================
# DENT Analyzer wrapper
# ======================================================================

class MesorchForensicsAnalyzer(BaseAnalyzer):
    """Image manipulation detection using Mesorch (AAAI 2025)."""

    MODULE_NAME = "mesorch_detection"
    MODULE_LABEL = "Mesorch detekcija manipulacije"

    def __init__(self) -> None:
        self._models_loaded = False
        self._model = None

    def _ensure_models(self) -> None:
        if self._models_loaded:
            return

        if not _TORCH_AVAILABLE or not _TIMM_AVAILABLE:
            self._models_loaded = True
            return

        weights_path = os.path.join(
            settings.forensics_model_cache_dir, "cnn", "mesorch", "mesorch-98.pth"
        )

        if not os.path.exists(weights_path):
            logger.warning("Mesorch weights not found at %s", weights_path)
            self._models_loaded = True
            return

        try:
            model = MesorchModel(image_size=IMAGE_SIZE)
            checkpoint = torch.load(weights_path, map_location="cpu", weights_only=False)

            # Handle both raw state_dict and wrapped checkpoint formats:
            # - Raw: {param_name: tensor, ...}
            # - Wrapped: {'model': state_dict, 'optimizer': ..., 'epoch': ...}
            # - IMDLBenCo: {'model_state_dict': state_dict, ...}
            if isinstance(checkpoint, dict):
                if "model" in checkpoint:
                    state_dict = checkpoint["model"]
                    logger.info("Mesorch checkpoint: unwrapped 'model' key")
                elif "model_state_dict" in checkpoint:
                    state_dict = checkpoint["model_state_dict"]
                    logger.info("Mesorch checkpoint: unwrapped 'model_state_dict' key")
                elif "state_dict" in checkpoint:
                    state_dict = checkpoint["state_dict"]
                    logger.info("Mesorch checkpoint: unwrapped 'state_dict' key")
                else:
                    state_dict = checkpoint
            else:
                state_dict = checkpoint

            # Log key info for debugging
            keys = list(state_dict.keys())[:5]
            logger.info("Mesorch state_dict: %d keys, first: %s", len(state_dict), keys)

            missing, unexpected = model.load_state_dict(state_dict, strict=False)
            if missing:
                logger.info("Mesorch missing keys (%d): %s...", len(missing), missing[:3])
            if unexpected:
                logger.info("Mesorch unexpected keys (%d): %s...", len(unexpected), unexpected[:3])

            model.eval()
            self._model = model
            n_params = sum(p.numel() for p in model.parameters()) / 1e6
            logger.info("Mesorch loaded: %s (%.1fM params)", weights_path, n_params)
        except Exception as e:
            logger.warning("Mesorch load failed: %s", e)
            self._model = None

        self._models_loaded = True

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        start = time.monotonic()
        findings: list[AnalyzerFinding] = []

        if not settings.forensics_mesorch_enabled:
            return self._make_result([], int((time.monotonic() - start) * 1000))

        try:
            self._ensure_models()

            if self._model is None:
                return self._make_result(
                    [], int((time.monotonic() - start) * 1000),
                    error="Mesorch model not available",
                )

            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")
            img = img.resize((IMAGE_SIZE, IMAGE_SIZE), Image.BILINEAR)

            # Normalize to [0, 1]
            arr = np.array(img, dtype=np.float32) / 255.0
            tensor = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0)

            with torch.no_grad():
                mask = self._model.predict(tensor)  # [1, 1, 512, 512]

            mask_np = mask.squeeze().cpu().numpy()  # [512, 512] in [0, 1]

            # Score aggregation: mean of top-5% pixels
            flat = mask_np.flatten()
            top_k = max(1, len(flat) // 20)
            top_5_pct = np.sort(flat)[-top_k:]
            top_score = float(np.mean(top_5_pct))
            mean_score = float(np.mean(mask_np))
            risk_score = mean_score * 0.5 + top_score * 0.5

            details = {
                "mesorch_risk": round(risk_score, 4),
                "mean_score": round(mean_score, 4),
                "top_5pct_score": round(top_score, 4),
            }

            if risk_score > 0.45:
                findings.append(AnalyzerFinding(
                    code="MESORCH_TAMPERING",
                    title="Mesorch: otkrivena manipulacija slike",
                    description=(
                        f"Mesorch dual-backbone model (AAAI 2025, JPEG F1=0.774) "
                        f"detektirao je modificirane regije (rizik: {risk_score:.0%}). "
                        f"DCT frekvencijska analiza i transformer model ukazuju na "
                        f"manipulaciju."
                    ),
                    risk_score=min(0.85, risk_score),
                    confidence=0.82,
                    evidence=details,
                ))
            elif risk_score > 0.30:
                findings.append(AnalyzerFinding(
                    code="MESORCH_SUSPICIOUS",
                    title="Mesorch: sumnjiva podrucja u slici",
                    description=(
                        f"Mesorch pokazuje umjeren rizik manipulacije "
                        f"({risk_score:.0%}). Moguca djelomicna modifikacija."
                    ),
                    risk_score=risk_score * 0.7,
                    confidence=0.65,
                    evidence=details,
                ))

        except Exception as e:
            logger.warning("Mesorch detection error: %s", e)
            return self._make_result(
                [], int((time.monotonic() - start) * 1000), error=str(e)
            )

        elapsed = int((time.monotonic() - start) * 1000)
        result = self._make_result(findings, elapsed)
        if self._model is not None and findings:
            result.risk_score = round(risk_score, 4)
            result.risk_score100 = round(risk_score * 100)
        return result

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([], 0)
