import asyncio
import json
import logging

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import StreamingResponse

from ..config import settings
from ..forensics.base import ForensicReport
from ..forensics.pipeline import ForensicPipeline
from ..forensics.thresholds import get_registry

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Singleton pipeline ────────────────────────────────────────
# Created once at module import time. Models are lazy-loaded
# on first request, then stay in memory for all subsequent calls.
# This avoids re-loading model weights on every single request.
_pipeline: ForensicPipeline | None = None


def get_pipeline() -> ForensicPipeline:
    """Return the singleton ForensicPipeline, creating it once if needed."""
    global _pipeline
    if _pipeline is None:
        # Initialize threshold registry (loads calibration file if configured)
        get_registry(settings.forensics_calibration_file)
        _pipeline = ForensicPipeline(
            ela_quality=settings.forensics_ela_quality,
            ela_scale=settings.forensics_ela_scale,
            cnn_enabled=settings.forensics_cnn_enabled,
            optical_enabled=settings.forensics_optical_enabled,
            semantic_enabled=settings.forensics_semantic_enabled,
            semantic_face_enabled=settings.forensics_semantic_face_enabled,
            semantic_vlm_enabled=settings.forensics_semantic_vlm_enabled,
            semantic_vlm_model=settings.forensics_semantic_vlm_model,
            openrouter_api_key=settings.openrouter_api_key,
            document_enabled=settings.forensics_document_enabled,
            document_signature_verification=settings.forensics_document_signature_verification,
            aigen_enabled=settings.forensics_aigen_enabled,
            spectral_enabled=settings.forensics_spectral_enabled,
            office_enabled=settings.forensics_office_enabled,
            clip_ai_enabled=settings.forensics_clip_ai_enabled,
            vae_recon_enabled=settings.forensics_vae_recon_enabled,
            text_ai_enabled=settings.forensics_text_ai_enabled,
            prnu_enabled=settings.forensics_prnu_enabled,
            content_validation_enabled=settings.forensics_content_validation_enabled,
            content_validation_ocr_lang=settings.forensics_content_validation_ocr_lang,
            embedded_image_forensics_enabled=settings.forensics_document_embedded_image_forensics,
        )
    return _pipeline


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
        from fastapi import HTTPException
        raise HTTPException(
            status_code=413,
            detail=f"Datoteka prevelika ({len(contents) / 1024 / 1024:.1f} MB). "
                   f"Maksimalna veličina: {settings.max_image_size_mb} MB.",
        )

    skip = skip_modules.split(",") if skip_modules else None

    pipeline = get_pipeline()
    report = await pipeline.analyze(contents, filename, skip)

    logger.info(
        "Forensic analysis complete: %s risk=%.2f level=%s time=%dms",
        filename,
        report.overall_risk_score,
        report.overall_risk_level,
        report.total_processing_time_ms,
    )

    return report


@router.post("/forensics/stream")
async def analyze_forensics_stream(
    file: UploadFile = File(...),
    skip_modules: str | None = Query(
        None, description="Comma-separated module names to skip"
    ),
):
    """SSE streaming forensic analysis — sends progress events per module."""
    if not settings.forensics_enabled:
        async def _disabled():
            report = ForensicReport(
                overall_risk_score=0.0,
                overall_risk_level="Low",
            )
            yield f"data: {json.dumps({'type': 'complete', 'report': report.model_dump()})}\n\n"

        return StreamingResponse(_disabled(), media_type="text/event-stream")

    contents = await file.read()
    filename = file.filename or "unknown"

    max_size = settings.max_image_size_mb * 1024 * 1024
    if len(contents) > max_size:
        async def _too_large():
            report = ForensicReport(
                overall_risk_score=0.0,
                overall_risk_level="Low",
                modules=[],
                total_processing_time_ms=0,
            )
            yield f"data: {json.dumps({'type': 'complete', 'report': report.model_dump()})}\n\n"

        return StreamingResponse(_too_large(), media_type="text/event-stream")

    skip = skip_modules.split(",") if skip_modules else None

    # Queue for progress events from the pipeline callback
    progress_queue: asyncio.Queue = asyncio.Queue()

    def on_progress(module_name: str, pct: float) -> None:
        progress_queue.put_nowait({
            "type": "progress",
            "module": module_name,
            "progress": pct,
        })

    async def _stream():
        pipeline = get_pipeline()

        # Run pipeline in a task so we can yield progress events as they arrive
        analysis_task = asyncio.ensure_future(
            pipeline.analyze(contents, filename, skip, progress_callback=on_progress)
        )

        # Yield progress events while pipeline runs
        while not analysis_task.done():
            try:
                event = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                # Send keepalive to prevent connection drop
                yield ": keepalive\n\n"

        # Drain any remaining progress events
        while not progress_queue.empty():
            event = progress_queue.get_nowait()
            yield f"data: {json.dumps(event)}\n\n"

        # Get the final report
        report = analysis_task.result()

        logger.info(
            "Forensic stream complete: %s risk=%.2f level=%s time=%dms",
            filename,
            report.overall_risk_score,
            report.overall_risk_level,
            report.total_processing_time_ms,
        )

        yield f"data: {json.dumps({'type': 'complete', 'report': report.model_dump()})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")
