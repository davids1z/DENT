"""Integration test for the full forensic pipeline.

Runs a lightweight pipeline (heavy modules disabled) on a test image
and verifies the response structure.

NOTE: Requires torch + transformers (Python 3.10+). Skipped otherwise.
"""
import pytest

torch = pytest.importorskip("torch", reason="torch not available")

from app.forensics.base import ForensicReport, RiskLevel
from app.forensics.pipeline import ForensicPipeline


@pytest.fixture(scope="module")
def lightweight_pipeline():
    """Pipeline with heavy/slow modules disabled for fast testing."""
    return ForensicPipeline(
        cnn_enabled=False,
        mesorch_enabled=False,
        optical_enabled=False,
        semantic_enabled=False,
        aigen_enabled=False,
        vae_recon_enabled=False,
        spectral_enabled=False,
        # Keep lightweight modules
        safe_ai_enabled=True,
        dinov2_ai_enabled=True,
        clip_ai_enabled=True,
        efficientnet_ai_enabled=True,
        community_forensics_enabled=True,
        npr_enabled=True,
        prnu_enabled=True,
    )


@pytest.mark.asyncio
async def test_pipeline_returns_report(lightweight_pipeline, photo_image_bytes):
    report = await lightweight_pipeline.analyze(photo_image_bytes, "test.jpg")
    assert isinstance(report, ForensicReport)
    assert 0.0 <= report.overall_risk_score <= 1.0
    assert report.overall_risk_level in list(RiskLevel)
    assert report.total_processing_time_ms >= 0


@pytest.mark.asyncio
async def test_pipeline_has_modules(lightweight_pipeline, photo_image_bytes):
    report = await lightweight_pipeline.analyze(photo_image_bytes, "test.jpg")
    assert len(report.modules) > 0
    module_names = {m.module_name for m in report.modules}
    # At minimum, these lightweight modules should be present
    assert "safe_ai_detection" in module_names
    assert "metadata_analysis" in module_names
    assert "modification_detection" in module_names


@pytest.mark.asyncio
async def test_pipeline_skip_modules(lightweight_pipeline, photo_image_bytes):
    report = await lightweight_pipeline.analyze(
        photo_image_bytes, "test.jpg",
        skip_modules=["safe_ai_detection", "clip_ai_detection"],
    )
    module_names = {m.module_name for m in report.modules}
    assert "safe_ai_detection" not in module_names
    assert "clip_ai_detection" not in module_names


@pytest.mark.asyncio
async def test_pipeline_handles_png(lightweight_pipeline, png_image_bytes):
    report = await lightweight_pipeline.analyze(png_image_bytes, "test.png")
    assert isinstance(report, ForensicReport)
    assert report.overall_risk_score >= 0.0
