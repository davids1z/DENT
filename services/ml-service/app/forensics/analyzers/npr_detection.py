"""
NPR AI Detection Module (CVPR 2024)

Detects AI-generated images by analyzing Neighboring Pixel Relationships —
upsampling artifacts present in virtually all CNN-based and many diffusion
generators.

Model: Modified ResNet50 with only layer1+layer2 (1.44M params, ~6MB).
The core insight: AI generators use learned upsampling that leaves a
characteristic pixel-level pattern detectable by NPR = x - interpolate(x, 0.5).

Performance: 92.2% mean accuracy across 28 generators despite being trained
ONLY on ProGAN. Generalizes because upsampling artifacts are universal.

Reference: https://github.com/chuangchuangtan/NPR-DeepfakeDetection
Paper: "Rethinking the Up-Sampling Operations in CNN-based Generative
Network for Generalizable Deepfake Detection" (CVPR 2024)
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

_TORCH_AVAILABLE = False
try:
    import torch
    import torch.nn as nn
    from torch.nn import functional as F
    _TORCH_AVAILABLE = True
except ImportError:
    logger.info("PyTorch not installed, NPR detection disabled")

# ImageNet normalization
NORM_MEAN = [0.485, 0.456, 0.406]
NORM_STD = [0.229, 0.224, 0.225]
INPUT_SIZE = 224

# Weights URL — directly from GitHub repo (~6MB)
NPR_WEIGHTS_URL = "https://github.com/chuangchuangtan/NPR-DeepfakeDetection/raw/main/NPR.pth"


# ======================================================================
# Vendored NPR model (from chuangchuangtan/NPR-DeepfakeDetection)
# Modified ResNet50 with only layer1+layer2 and NPR in forward()
# ======================================================================

if _TORCH_AVAILABLE:

    def _conv3x3(in_planes, out_planes, stride=1):
        return nn.Conv2d(in_planes, out_planes, kernel_size=3, stride=stride,
                         padding=1, bias=False)

    def _conv1x1(in_planes, out_planes, stride=1):
        return nn.Conv2d(in_planes, out_planes, kernel_size=1, stride=stride,
                         bias=False)

    class _Bottleneck(nn.Module):
        expansion = 4

        def __init__(self, inplanes, planes, stride=1, downsample=None):
            super().__init__()
            self.conv1 = _conv1x1(inplanes, planes)
            self.bn1 = nn.BatchNorm2d(planes)
            self.conv2 = _conv3x3(planes, planes, stride)
            self.bn2 = nn.BatchNorm2d(planes)
            self.conv3 = _conv1x1(planes, planes * self.expansion)
            self.bn3 = nn.BatchNorm2d(planes * self.expansion)
            self.relu = nn.ReLU(inplace=True)
            self.downsample = downsample

        def forward(self, x):
            identity = x
            out = self.relu(self.bn1(self.conv1(x)))
            out = self.relu(self.bn2(self.conv2(out)))
            out = self.bn3(self.conv3(out))
            if self.downsample is not None:
                identity = self.downsample(x)
            return self.relu(out + identity)

    class NPRResNet(nn.Module):
        """ResNet50 truncated to layer1+layer2 with NPR preprocessing."""

        def __init__(self, num_classes=1):
            super().__init__()
            self.inplanes = 64
            self.conv1 = nn.Conv2d(3, 64, kernel_size=3, stride=2, padding=1, bias=False)
            self.bn1 = nn.BatchNorm2d(64)
            self.relu = nn.ReLU(inplace=True)
            self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=1)
            self.layer1 = self._make_layer(_Bottleneck, 64, 3)
            self.layer2 = self._make_layer(_Bottleneck, 128, 4, stride=2)
            self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
            self.fc1 = nn.Linear(512, num_classes)

            for m in self.modules():
                if isinstance(m, nn.Conv2d):
                    nn.init.kaiming_normal_(m.weight, mode="fan_out", nonlinearity="relu")
                elif isinstance(m, nn.BatchNorm2d):
                    nn.init.constant_(m.weight, 1)
                    nn.init.constant_(m.bias, 0)

        def _make_layer(self, block, planes, blocks, stride=1):
            downsample = None
            if stride != 1 or self.inplanes != planes * block.expansion:
                downsample = nn.Sequential(
                    _conv1x1(self.inplanes, planes * block.expansion, stride),
                    nn.BatchNorm2d(planes * block.expansion),
                )
            layers = [block(self.inplanes, planes, stride, downsample)]
            self.inplanes = planes * block.expansion
            for _ in range(1, blocks):
                layers.append(block(self.inplanes, planes))
            return nn.Sequential(*layers)

        @staticmethod
        def _interpolate(img, factor):
            return F.interpolate(
                F.interpolate(img, scale_factor=factor, mode="nearest",
                              recompute_scale_factor=True),
                scale_factor=1 / factor, mode="nearest",
                recompute_scale_factor=True,
            )

        def forward(self, x):
            # NPR: Neighboring Pixel Relationship
            # x - downsample(x, 0.5) → upsampled back reveals upsampling artifacts
            npr = x - self._interpolate(x, 0.5)
            x = self.conv1(npr * 2.0 / 3.0)
            x = self.relu(self.bn1(x))
            x = self.maxpool(x)
            x = self.layer1(x)
            x = self.layer2(x)
            x = self.avgpool(x)
            x = x.view(x.size(0), -1)
            return self.fc1(x)


# ======================================================================
# DENT Analyzer wrapper
# ======================================================================

class NprDetectionAnalyzer(BaseAnalyzer):
    """AI-generated image detection using NPR upsampling artifact analysis."""

    MODULE_NAME = "npr_ai_detection"
    MODULE_LABEL = "NPR AI detekcija (upsampling artefakti)"

    def __init__(self) -> None:
        self._models_loaded = False
        self._model = None
        self._transform = None

    def _ensure_models(self) -> None:
        if self._models_loaded:
            return

        if not _TORCH_AVAILABLE:
            self._models_loaded = True
            return

        from torchvision import transforms

        self._transform = transforms.Compose([
            transforms.Resize((INPUT_SIZE, INPUT_SIZE)),
            transforms.CenterCrop(INPUT_SIZE),
            transforms.ToTensor(),
            transforms.Normalize(mean=NORM_MEAN, std=NORM_STD),
        ])

        weights_dir = os.path.join(settings.forensics_model_cache_dir, "npr")
        weights_path = os.path.join(weights_dir, "NPR.pth")

        if not os.path.exists(weights_path):
            logger.warning("NPR weights not found at %s", weights_path)
            self._models_loaded = True
            return

        try:
            model = NPRResNet(num_classes=1)
            state_dict = torch.load(weights_path, map_location="cpu", weights_only=False)

            # Handle wrapped checkpoint
            if isinstance(state_dict, dict):
                if "model" in state_dict:
                    state_dict = state_dict["model"]
                elif "state_dict" in state_dict:
                    state_dict = state_dict["state_dict"]

            # Strip DataParallel 'module.' prefix if present
            if any(k.startswith("module.") for k in state_dict):
                state_dict = {k.replace("module.", "", 1): v for k, v in state_dict.items()}

            missing, unexpected = model.load_state_dict(state_dict, strict=False)
            if missing:
                logger.info("NPR missing keys (%d): %s", len(missing), missing[:3])
            if unexpected:
                logger.info("NPR unexpected keys (%d): %s", len(unexpected), unexpected[:3])

            model.eval()
            self._model = model
            n_params = sum(p.numel() for p in model.parameters()) / 1e6
            logger.info("NPR loaded: %s (%.2fM params, %.1f MB)",
                        weights_path, n_params,
                        os.path.getsize(weights_path) / 1e6)
        except Exception as e:
            logger.warning("NPR load failed: %s", e)
            self._model = None

        self._models_loaded = True

    async def analyze_image(self, image_bytes: bytes, filename: str) -> ModuleResult:
        start = time.monotonic()
        findings: list[AnalyzerFinding] = []

        if not settings.forensics_npr_enabled:
            return self._make_result([], int((time.monotonic() - start) * 1000))

        try:
            self._ensure_models()

            if self._model is None or self._transform is None:
                return self._make_result(
                    [], int((time.monotonic() - start) * 1000),
                    error="NPR model not available",
                )

            img = Image.open(io.BytesIO(image_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")

            tensor = self._transform(img).unsqueeze(0)

            with torch.no_grad():
                logit = self._model(tensor)
                prob = torch.sigmoid(logit).item()

            details = {
                "npr_score": round(prob, 4),
                "model": "NPR-ResNet50-truncated",
                "params": "1.44M",
                "detects": "upsampling artifacts",
            }

            if prob > 0.75:
                findings.append(AnalyzerFinding(
                    code="NPR_AI_DETECTED",
                    title="NPR: detektirani AI upsampling artefakti",
                    description=(
                        f"NPR model (CVPR 2024, 92.2% accuracy) detektirao je "
                        f"karakteristicne upsampling artefakte u pikselima "
                        f"(rezultat: {prob:.0%}). Ovi artefakti nastaju pri "
                        f"generiranju slika pomocu neuronskih mreza."
                    ),
                    risk_score=min(0.95, max(0.80, prob)),
                    confidence=min(0.95, 0.75 + prob * 0.15),
                    evidence=details,
                ))
            elif prob > 0.50:
                findings.append(AnalyzerFinding(
                    code="NPR_AI_SUSPECTED",
                    title="NPR: sumnja na AI upsampling artefakte",
                    description=(
                        f"NPR model pokazuje umjerenu vjerojatnost ({prob:.0%}) "
                        f"prisutnosti AI upsampling artefakata u slici."
                    ),
                    risk_score=max(0.50, prob * 0.90),
                    confidence=0.70 + prob * 0.10,
                    evidence=details,
                ))
            elif prob > 0.30:
                findings.append(AnalyzerFinding(
                    code="NPR_AI_LOW",
                    title="NPR: blagi upsampling indikatori",
                    description=(
                        f"NPR model pokazuje niske indikatore ({prob:.0%}) "
                        f"mogucih AI upsampling artefakata."
                    ),
                    risk_score=prob * 0.60,
                    confidence=0.55,
                    evidence=details,
                ))

        except Exception as e:
            logger.warning("NPR detection error: %s", e)
            return self._make_result(
                [], int((time.monotonic() - start) * 1000), error=str(e)
            )

        elapsed = int((time.monotonic() - start) * 1000)
        result = self._make_result(findings, elapsed)
        if self._model is not None:
            result.risk_score = round(prob, 4)
            result.risk_score100 = round(prob * 100)
        return result

    async def analyze_document(self, doc_bytes: bytes, filename: str) -> ModuleResult:
        return self._make_result([], 0)
