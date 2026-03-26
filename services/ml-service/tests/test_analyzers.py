"""Unit tests for individual forensic analyzer modules.

Each test verifies that the analyzer:
1. Returns a valid ModuleResult
2. Has the correct module_name
3. Returns risk_score in [0, 1]
4. Does not error on valid input

NOTE: These tests require torch + transformers (Python 3.10+).
Run inside Docker or a venv with all ML deps installed.
Skipped automatically when torch is not available.
"""
import pytest

torch = pytest.importorskip("torch", reason="torch not available")

from app.forensics.base import ModuleResult


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _assert_valid_result(result: ModuleResult, expected_name: str) -> None:
    assert isinstance(result, ModuleResult)
    assert result.module_name == expected_name
    assert 0.0 <= result.risk_score <= 1.0
    assert result.risk_score100 == round(result.risk_score * 100)
    assert result.error is None


# ---------------------------------------------------------------------------
# SAFE AI Detection (KDD 2025)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safe_returns_valid_result(photo_image_bytes):
    from app.forensics.analyzers.safe_ai_detection import SAFEAiDetectionAnalyzer
    analyzer = SAFEAiDetectionAnalyzer()
    result = await analyzer.analyze_image(photo_image_bytes, "test.jpg")
    _assert_valid_result(result, "safe_ai_detection")


# ---------------------------------------------------------------------------
# DINOv2 AI Detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dinov2_returns_valid_result(photo_image_bytes):
    from app.forensics.analyzers.dinov2_ai_detection import DINOv2AiDetectionAnalyzer
    analyzer = DINOv2AiDetectionAnalyzer()
    result = await analyzer.analyze_image(photo_image_bytes, "test.jpg")
    _assert_valid_result(result, "dinov2_ai_detection")


@pytest.mark.asyncio
async def test_dinov2_document_returns_empty():
    from app.forensics.analyzers.dinov2_ai_detection import DINOv2AiDetectionAnalyzer
    analyzer = DINOv2AiDetectionAnalyzer()
    result = await analyzer.analyze_document(b"fake doc", "test.pdf")
    assert isinstance(result, ModuleResult)
    assert result.module_name == "dinov2_ai_detection"
    assert result.risk_score == 0.0
    assert len(result.findings) == 0


# ---------------------------------------------------------------------------
# CLIP AI Detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clip_returns_valid_result(photo_image_bytes):
    from app.forensics.analyzers.clip_ai_detection import ClipAiDetectionAnalyzer
    analyzer = ClipAiDetectionAnalyzer()
    result = await analyzer.analyze_image(photo_image_bytes, "test.jpg")
    _assert_valid_result(result, "clip_ai_detection")


# ---------------------------------------------------------------------------
# Metadata Analyzer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_metadata_returns_valid_result(photo_image_bytes):
    from app.forensics.analyzers.metadata import MetadataAnalyzer
    analyzer = MetadataAnalyzer()
    result = await analyzer.analyze_image(photo_image_bytes, "test.jpg")
    _assert_valid_result(result, "metadata_analysis")


# ---------------------------------------------------------------------------
# ELA / Modification Detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_modification_returns_valid_result(photo_image_bytes):
    from app.forensics.analyzers.modification import ModificationAnalyzer
    analyzer = ModificationAnalyzer()
    result = await analyzer.analyze_image(photo_image_bytes, "test.jpg")
    _assert_valid_result(result, "modification_detection")


# ---------------------------------------------------------------------------
# PRNU Detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_prnu_returns_valid_result(photo_image_bytes):
    from app.forensics.analyzers.prnu_detection import PrnuDetectionAnalyzer
    analyzer = PrnuDetectionAnalyzer()
    result = await analyzer.analyze_image(photo_image_bytes, "test.jpg")
    _assert_valid_result(result, "prnu_detection")


# ---------------------------------------------------------------------------
# NPR Detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_npr_returns_valid_result(photo_image_bytes):
    from app.forensics.analyzers.npr_detection import NprDetectionAnalyzer
    analyzer = NprDetectionAnalyzer()
    result = await analyzer.analyze_image(photo_image_bytes, "test.jpg")
    _assert_valid_result(result, "npr_ai_detection")


# ---------------------------------------------------------------------------
# PNG image (no JPEG artifacts)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safe_handles_png(png_image_bytes):
    from app.forensics.analyzers.safe_ai_detection import SAFEAiDetectionAnalyzer
    analyzer = SAFEAiDetectionAnalyzer()
    result = await analyzer.analyze_image(png_image_bytes, "test.png")
    _assert_valid_result(result, "safe_ai_detection")


@pytest.mark.asyncio
async def test_dinov2_handles_png(png_image_bytes):
    from app.forensics.analyzers.dinov2_ai_detection import DINOv2AiDetectionAnalyzer
    analyzer = DINOv2AiDetectionAnalyzer()
    result = await analyzer.analyze_image(png_image_bytes, "test.png")
    _assert_valid_result(result, "dinov2_ai_detection")
