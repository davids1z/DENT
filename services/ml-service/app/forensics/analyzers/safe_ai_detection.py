"""
SAFE (KDD 2025) -- Synthetic Artifact-Free Enhancement AI Detector

Detects AI-generated images by analyzing high-frequency wavelet artifacts that
ALL generators leave behind, regardless of architecture (GAN, diffusion,
autoregressive).

CRITICAL: The model applies a Discrete Wavelet Transform (DWT) preprocessing
step *before* the convolutional layers. The DWT extracts the HH (diagonal
detail) subband using a biorthogonal 1.3 wavelet, which isolates the
high-frequency pixel correlations that distinguish real from AI-generated
images. Without this step, the model receives raw RGB pixels and produces
inverted/meaningless results.

Model: Truncated ResNet (DWT -> conv1 3x3 + layer1 + layer2 + fc), 1.44M params, ~6MB.
Accuracy: 98.92% on GenEval including Flux, SD3, PixArt, GPT-4o.
CPU inference: < 1 second.

Reference: https://github.com/Ouxiang-Li/SAFE
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

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False

# Check for pytorch_wavelets (preferred, GPU-compatible, exact match to official SAFE)
_PYTORCH_WAVELETS_AVAILABLE = False
try:
    from pytorch_wavelets import DWTForward
    _PYTORCH_WAVELETS_AVAILABLE = True
    logger.debug("pytorch_wavelets available for SAFE DWT preprocessing")
except ImportError:
    logger.debug("pytorch_wavelets not available, will try PyWavelets fallback")

# Check for PyWavelets as fallback (already in requirements for optical forensics)
_PYWT_AVAILABLE = False
try:
    import pywt
    _PYWT_AVAILABLE = True
    logger.debug("PyWavelets available as DWT fallback")
except ImportError:
    logger.debug("PyWavelets not available either")

# Input size for SAFE (NO ImageNet normalization)
SAFE_INPUT_SIZE = 256


class Bottleneck(nn.Module):
    """Standard ResNet bottleneck block."""
    expansion = 4

    def __init__(self, in_ch, out_ch, stride=1, downsample=None):
        super().__init__()
        self.conv1 = nn.Conv2d(in_ch, out_ch, 1, bias=False)
        self.bn1 = nn.BatchNorm2d(out_ch)
        self.conv2 = nn.Conv2d(out_ch, out_ch, 3, stride=stride, padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(out_ch)
        self.conv3 = nn.Conv2d(out_ch, out_ch * self.expansion, 1, bias=False)
        self.bn3 = nn.BatchNorm2d(out_ch * self.expansion)
        self.downsample = downsample

    def forward(self, x):
        identity = x
        out = F.relu(self.bn1(self.conv1(x)))
        out = F.relu(self.bn2(self.conv2(out)))
        out = self.bn3(self.conv3(out))
        if self.downsample is not None:
            identity = self.downsample(x)
        return F.relu(out + identity)


class SAFENet(nn.Module):
    """Truncated ResNet for SAFE: DWT -> conv1(3x3) + layer1 + layer2 + fc.

    The DWT preprocessing step extracts the HH (diagonal detail) subband using
    a biorthogonal 1.3 wavelet at J=1 decomposition level. This isolates
    high-frequency artifacts that distinguish real from AI-generated images.

    The HH subband preserves the channel count (3 for RGB), so conv1 input
    channels remain 3. The spatial dimensions are halved by DWT then resized
    back to the original input size.
    """

    def __init__(self, num_classes=2):
        super().__init__()
        # conv1 takes 3 channels: the DWT HH subband has same channel count as input RGB
        self.conv1 = nn.Conv2d(3, 64, 3, stride=2, padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(64)
        self.maxpool = nn.MaxPool2d(3, stride=2, padding=1)

        # Layer 1: 3 bottleneck blocks, 64 -> 256
        self.layer1 = self._make_layer(64, 64, 3)
        # Layer 2: 4 bottleneck blocks, 256 -> 512
        self.layer2 = self._make_layer(256, 128, 4, stride=2)

        self.avgpool = nn.AdaptiveAvgPool2d(1)
        self.fc1 = nn.Linear(512, num_classes)

        # Lazy-init DWT filter on first forward pass (needs to match device)
        self._dwt_filter = None

    def _make_layer(self, in_ch, out_ch, blocks, stride=1):
        downsample = None
        if stride != 1 or in_ch != out_ch * Bottleneck.expansion:
            downsample = nn.Sequential(
                nn.Conv2d(in_ch, out_ch * Bottleneck.expansion, 1, stride=stride, bias=False),
                nn.BatchNorm2d(out_ch * Bottleneck.expansion),
            )
        layers = [Bottleneck(in_ch, out_ch, stride, downsample)]
        for _ in range(1, blocks):
            layers.append(Bottleneck(out_ch * Bottleneck.expansion, out_ch))
        return nn.Sequential(*layers)

    def _preprocess_dwt(self, x):
        """Apply DWT to extract HH (diagonal detail) subband.

        Matches the official SAFE implementation:
            DWTForward(J=1, mode='symmetric', wave='bior1.3')
            -> extract Yh[0][:, :, 2, :, :]  (HH subband)
            -> resize back to original spatial dimensions

        The HH subband captures diagonal high-frequency details which reveal
        the pixel correlation artifacts left by AI generators.

        Input:  [B, 3, H, W]  (RGB image tensor)
        Output: [B, 3, H, W]  (HH detail coefficients, resized to original size)
        """
        orig_h, orig_w = x.shape[-2], x.shape[-1]

        if _PYTORCH_WAVELETS_AVAILABLE:
            # Primary path: pytorch_wavelets (exact match to official SAFE code)
            if self._dwt_filter is None or next(self._dwt_filter.parameters(), torch.tensor(0)).device != x.device:
                self._dwt_filter = DWTForward(J=1, mode='symmetric', wave='bior1.3').to(x.device)
            Yl, Yh = self._dwt_filter(x)
            # Yh[0] shape: [B, C, 3, H/2, W/2] where dim=2 indexes LH(0), HL(1), HH(2)
            hh = Yh[0][:, :, 2, :, :]  # [B, 3, H/2, W/2]

        elif _PYWT_AVAILABLE:
            # Fallback: PyWavelets (CPU-only, per-channel, slightly slower)
            hh = self._dwt_pywt_fallback(x)

        else:
            # No wavelet library available -- return input unchanged (will give bad results)
            logger.warning("No DWT library available! SAFE results will be unreliable.")
            return x

        # Resize HH subband back to original spatial dimensions
        hh = F.interpolate(hh, size=(orig_h, orig_w), mode='bilinear', align_corners=False)
        return hh

    def _dwt_pywt_fallback(self, x):
        """PyWavelets-based DWT fallback for when pytorch_wavelets is not installed.

        Processes each image in the batch and each channel separately using pywt.dwt2,
        then stacks results back into a tensor. Less efficient but produces equivalent
        HH subband output.
        """
        batch_size, channels, h, w = x.shape
        # pywt needs numpy, process on CPU
        x_np = x.detach().cpu().numpy()

        hh_list = []
        for b in range(batch_size):
            channel_hh = []
            for c in range(channels):
                # pywt.dwt2 returns (cA, (cH, cV, cD)) where cD = HH diagonal detail
                coeffs = pywt.dwt2(x_np[b, c], wavelet='bior1.3', mode='symmetric')
                _, (cH, cV, cD) = coeffs
                channel_hh.append(cD)
            hh_list.append(np.stack(channel_hh, axis=0))

        hh_np = np.stack(hh_list, axis=0)  # [B, C, H/2, W/2]
        return torch.tensor(hh_np, dtype=x.dtype, device=x.device)

    def forward(self, x):
        # CRITICAL: Apply DWT preprocessing before conv layers
        # This extracts high-frequency wavelet artifacts that distinguish AI from real
        x = 1 * self._preprocess_dwt(x)
        x = F.relu(self.bn1(self.conv1(x)))
        x = self.maxpool(x)
        x = self.layer1(x)
        x = self.layer2(x)
        x = self.avgpool(x)
        x = torch.flatten(x, 1)
        return self.fc1(x)


class SAFEAiDetectionAnalyzer(BaseAnalyzer):
    """SAFE AI detection -- pixel correlation analysis for ALL generators."""

    MODULE_NAME = "safe_ai_detection"
    MODULE_LABEL = "SAFE AI detekcija (KDD 2025)"

    def __init__(self) -> None:
        self._models_loaded = False
        self._model = None
        self._transform = None

    def _ensure_models(self) -> None:
        if self._models_loaded:
            return

        if not _TORCH_AVAILABLE:
            logger.warning("PyTorch not available, SAFE disabled")
            self._models_loaded = True
            return

        if not _PYTORCH_WAVELETS_AVAILABLE and not _PYWT_AVAILABLE:
            logger.warning(
                "Neither pytorch_wavelets nor PyWavelets installed. "
                "SAFE requires DWT preprocessing and cannot function without it. "
                "Install: pip install pytorch-wavelets"
            )
            self._models_loaded = True
            return

        from torchvision import transforms

        try:
            from ..config import settings
        except Exception as e:
            logger.debug("Settings import fallback: %s", e)
            from types import SimpleNamespace
            settings = SimpleNamespace(forensics_model_cache_dir="/app/models")

        cache_dir = os.path.join(
            getattr(settings, "forensics_model_cache_dir", "/app/models"),
            "safe_ai",
        )
        os.makedirs(cache_dir, exist_ok=True)

        weights_path = os.path.join(cache_dir, "checkpoint-best.pth")

        # Download if not cached
        if not os.path.exists(weights_path):
            logger.info("Downloading SAFE checkpoint (~6MB)...")
            try:
                import urllib.request
                urllib.request.urlretrieve(
                    "https://raw.githubusercontent.com/Ouxiang-Li/SAFE/main/checkpoint/checkpoint-best.pth",
                    weights_path,
                )
                logger.info("SAFE checkpoint downloaded")
            except Exception as e:
                logger.warning("SAFE download failed: %s", e)
                self._models_loaded = True
                return

        try:
            self._model = SAFENet(num_classes=2)
            checkpoint = torch.load(weights_path, map_location="cpu", weights_only=False)
            state_dict = checkpoint.get("model", checkpoint)
            self._model.load_state_dict(state_dict)
            self._model.eval()

            total_params = sum(p.numel() for p in self._model.parameters())
            dwt_backend = "pytorch_wavelets" if _PYTORCH_WAVELETS_AVAILABLE else "PyWavelets (fallback)"
            logger.info("SAFE loaded: %.2fM params, DWT=%s, %s", total_params / 1e6, dwt_backend, weights_path)
        except Exception as e:
            logger.warning("Failed to load SAFE: %s", e)
            self._model = None

        # SAFE uses NO ImageNet normalization -- raw [0,1] tensor
        self._transform = transforms.Compose([
            transforms.Resize(SAFE_INPUT_SIZE + 20),
            transforms.CenterCrop(SAFE_INPUT_SIZE),
            transforms.ToTensor(),
        ])

        self._models_loaded = True

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        start = time.monotonic()
        findings: list[AnalyzerFinding] = []

        try:
            self._ensure_models()

            if self._model is None:
                elapsed = int((time.monotonic() - start) * 1000)
                return self._make_result([], elapsed, error="SAFE not loaded")

            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")

            tensor = self._transform(img).unsqueeze(0)

            with torch.no_grad():
                logits = self._model(tensor)
                probs = torch.softmax(logits, dim=1)
                # SAFE labels: class 0 = real, class 1 = synthetic
                synthetic_prob = float(probs[0, 1])

            # JPEG compression creates pixel correlation patterns similar to
            # AI generator artifacts. Light dampening for JPEG inputs.
            # 0.85 dampening: a SAFE raw score of 0.60 becomes 0.51 (still detectable).
            # Was 0.60 which destroyed the signal entirely on all insurance photos.
            is_jpeg = image_bytes[:2] == b'\xff\xd8'
            if is_jpeg:
                synthetic_prob *= 0.85

            if synthetic_prob > 0.75:
                findings.append(AnalyzerFinding(
                    code="SAFE_AI_DETECTED",
                    title="SAFE: detektiran AI-generiran sadrzaj",
                    description=(
                        f"SAFE detektor (KDD 2025) otkrio je lokalne pixel korelacije "
                        f"tipicne za AI-generirane slike ({synthetic_prob:.0%}). "
                        f"Ova metoda detektira artefakte zajednicke svim generatorima "
                        f"ukljucujuci Flux, DALL-E 3, Midjourney i Stable Diffusion."
                    ),
                    risk_score=min(0.90, synthetic_prob),
                    confidence=min(0.95, synthetic_prob),
                    evidence={
                        "synthetic_probability": round(synthetic_prob, 4),
                        "authentic_probability": round(1.0 - synthetic_prob, 4),
                        "model": "SAFE (KDD 2025)",
                        "dwt_backend": "pytorch_wavelets" if _PYTORCH_WAVELETS_AVAILABLE else "pywt",
                    },
                ))
            elif synthetic_prob > 0.50:
                findings.append(AnalyzerFinding(
                    code="SAFE_AI_SUSPECTED",
                    title="SAFE: sumnja na AI sadrzaj",
                    description=(
                        f"SAFE detektor pokazuje umjerenu sumnju na AI-generirani "
                        f"sadrzaj ({synthetic_prob:.0%})."
                    ),
                    risk_score=synthetic_prob * 0.80,
                    confidence=0.60 + synthetic_prob * 0.20,
                    evidence={
                        "synthetic_probability": round(synthetic_prob, 4),
                        "dwt_backend": "pytorch_wavelets" if _PYTORCH_WAVELETS_AVAILABLE else "pywt",
                    },
                ))

        except Exception as e:
            logger.warning("SAFE inference failed: %s", e)
            elapsed = int((time.monotonic() - start) * 1000)
            return self._make_result([], elapsed, error=str(e))

        elapsed = int((time.monotonic() - start) * 1000)
        result = self._make_result(findings, elapsed)
        result.risk_score = round(synthetic_prob, 4)
        result.risk_score100 = round(synthetic_prob * 100)
        return result

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([], 0)
