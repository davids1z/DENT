"""Shared test fixtures for DENT ML service tests."""
import io
import os
import sys

import numpy as np
import pytest
from PIL import Image

# Ensure app modules are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_test_image(width: int = 256, height: int = 256, pattern: str = "photo") -> bytes:
    """Generate a small test image as bytes.

    Patterns:
      - "photo": simulated camera-like noise (browns, greens, blues)
      - "gradient": smooth gradient (simulates AI-generated content)
    """
    rng = np.random.RandomState(42)

    if pattern == "gradient":
        # Smooth gradient — typical of AI-generated images
        arr = np.zeros((height, width, 3), dtype=np.uint8)
        for c in range(3):
            base = rng.randint(50, 200)
            grad = np.linspace(base, base + 55, width).astype(np.uint8)
            arr[:, :, c] = np.tile(grad, (height, 1))
    else:
        # Noisy texture — simulates real camera photo
        arr = rng.randint(40, 200, (height, width, 3), dtype=np.uint8)

    img = Image.fromarray(arr, "RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


@pytest.fixture(scope="session")
def photo_image_bytes() -> bytes:
    """Small JPEG that simulates a real camera photo."""
    return _make_test_image(pattern="photo")


@pytest.fixture(scope="session")
def gradient_image_bytes() -> bytes:
    """Small JPEG with smooth gradient (simulates AI-generated)."""
    return _make_test_image(pattern="gradient")


@pytest.fixture(scope="session")
def png_image_bytes() -> bytes:
    """Small PNG (no JPEG artifacts)."""
    arr = np.random.RandomState(99).randint(0, 255, (128, 128, 3), dtype=np.uint8)
    img = Image.fromarray(arr, "RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
