"""
SAFE (KDD 2025) — Synthetic Artifact-Free Enhancement AI Detector

Detects AI-generated images by analyzing local pixel correlations that
ALL generators leave behind, regardless of architecture (GAN, diffusion,
autoregressive). Uses 3 image transformations (crop, color jitter, rotation)
to expose these correlations.

Model: Truncated ResNet (conv1 3x3 + layer1 + layer2 + fc), 1.44M params, ~6MB.
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
    """Truncated ResNet for SAFE: conv1(3x3) + layer1(3 blocks) + layer2(4 blocks) + fc."""

    def __init__(self, num_classes=2):
        super().__init__()
        self.conv1 = nn.Conv2d(3, 64, 3, stride=2, padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(64)
        self.maxpool = nn.MaxPool2d(3, stride=2, padding=1)

        # Layer 1: 3 bottleneck blocks, 64 → 256
        self.layer1 = self._make_layer(64, 64, 3)
        # Layer 2: 4 bottleneck blocks, 256 → 512
        self.layer2 = self._make_layer(256, 128, 4, stride=2)

        self.avgpool = nn.AdaptiveAvgPool2d(1)
        self.fc1 = nn.Linear(512, num_classes)

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

    def forward(self, x):
        x = F.relu(self.bn1(self.conv1(x)))
        x = self.maxpool(x)
        x = self.layer1(x)
        x = self.layer2(x)
        x = self.avgpool(x)
        x = torch.flatten(x, 1)
        return self.fc1(x)


class SAFEAiDetectionAnalyzer(BaseAnalyzer):
    """SAFE AI detection — pixel correlation analysis for ALL generators."""

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

        from torchvision import transforms

        try:
            from ..config import settings
        except Exception:
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
            logger.info("SAFE loaded: %.2fM params, %s", total_params / 1e6, weights_path)
        except Exception as e:
            logger.warning("Failed to load SAFE: %s", e)
            self._model = None

        # SAFE uses NO ImageNet normalization — raw tensor
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
                # Class 1 = synthetic
                synthetic_prob = float(probs[0, 1])

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
