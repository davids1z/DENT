import logging

from fastapi import APIRouter, File, Query, UploadFile

from ..config import settings
from ..forensics.base import ForensicReport
from ..forensics.pipeline import ForensicPipeline

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/forensics", response_model=ForensicReport)
async def analyze_forensics(
    file: UploadFile = File(...),
    skip_modules: str | None = Query(
        None, description="Comma-separated module names to skip"
    ),
):
    """Run forensic fraud detection analysis on an uploaded file."""
    if not settings.forensics_enabled:
        return ForensicReport(
            overall_risk_score=0.0,
            overall_risk_level="Low",
        )

    contents = await file.read()
    filename = file.filename or "unknown"

    max_size = settings.max_image_size_mb * 1024 * 1024
    if len(contents) > max_size:
        return ForensicReport(
            overall_risk_score=0.0,
            overall_risk_level="Low",
            modules=[],
            total_processing_time_ms=0,
        )

    skip = skip_modules.split(",") if skip_modules else None

    pipeline = ForensicPipeline(
        ela_quality=settings.forensics_ela_quality,
        ela_scale=settings.forensics_ela_scale,
        cnn_enabled=settings.forensics_cnn_enabled,
        optical_enabled=settings.forensics_optical_enabled,
        semantic_enabled=settings.forensics_semantic_enabled,
        semantic_face_enabled=settings.forensics_semantic_face_enabled,
        semantic_vlm_enabled=settings.forensics_semantic_vlm_enabled,
        semantic_vlm_model=settings.forensics_semantic_vlm_model,
        openrouter_api_key=settings.openrouter_api_key,
    )
    report = await pipeline.analyze(contents, filename, skip)

    logger.info(
        "Forensic analysis complete: %s risk=%.2f level=%s time=%dms",
        filename,
        report.overall_risk_score,
        report.overall_risk_level,
        report.total_processing_time_ms,
    )

    return report
