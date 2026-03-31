import asyncio
import json
import logging

from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from ..config import settings
from ..forensics.analyzers.cross_image import analyze_cross_image
from ..forensics.base import BatchGroupResponse, ForensicReport
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
            mesorch_enabled=settings.forensics_mesorch_enabled,
            optical_enabled=settings.forensics_optical_enabled,
            semantic_enabled=settings.forensics_semantic_enabled,
            semantic_face_enabled=settings.forensics_semantic_face_enabled,
            document_enabled=settings.forensics_document_enabled,
            document_signature_verification=settings.forensics_document_signature_verification,
            aigen_enabled=settings.forensics_aigen_enabled,
            efficientnet_ai_enabled=settings.forensics_efficientnet_ai_enabled,
            safe_ai_enabled=settings.forensics_safe_ai_enabled,
            dinov2_ai_enabled=settings.forensics_dinov2_ai_enabled,
            bfree_enabled=settings.forensics_bfree_enabled,
            spai_enabled=settings.forensics_spai_enabled,
            spectral_enabled=settings.forensics_spectral_enabled,
            office_enabled=settings.forensics_office_enabled,
            community_forensics_enabled=settings.forensics_community_forensics_enabled,
            npr_enabled=settings.forensics_npr_enabled,
            clip_ai_enabled=settings.forensics_clip_ai_enabled,
            vae_recon_enabled=settings.forensics_vae_recon_enabled,
            text_ai_enabled=settings.forensics_text_ai_enabled,
            prnu_enabled=settings.forensics_prnu_enabled,
            content_validation_enabled=settings.forensics_content_validation_enabled,
            content_validation_ocr_lang=settings.forensics_content_validation_ocr_lang,
            embedded_image_forensics_enabled=settings.forensics_document_embedded_image_forensics,
        )
    return _pipeline


# Modules skipped in "quick" scan mode to reduce analysis to ~40s
_QUICK_SKIP = {
    "mesorch_detection",         # ~100s on CPU
    "semantic_forensics",        # ~20s (face + statistical)
    "deep_modification_detection",  # ~40s (TruFor)
    "vae_reconstruction",        # ~15s (VAE decode)
}


@router.post("/forensics", response_model=ForensicReport)
async def analyze_forensics(
    request: Request,
    file: UploadFile = File(...),
    skip_modules: str | None = Query(
        None, description="Comma-separated module names to skip"
    ),
    scan_mode: str | None = Query(
        None, description="'quick' (~40s, core modules) or 'full' (~180s, all modules). Default: full"
    ),
):
    """Run forensic fraud detection analysis on an uploaded file."""
    request_id = getattr(request.state, "request_id", None)

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

    skip = set(skip_modules.split(",")) if skip_modules else set()
    if scan_mode == "quick":
        skip |= _QUICK_SKIP
    skip = list(skip) if skip else None

    pipeline = get_pipeline()
    report = await pipeline.analyze(contents, filename, skip, request_id=request_id)

    logger.info(
        "[%s] Forensic analysis complete: %s risk=%.2f level=%s time=%dms",
        request_id,
        filename,
        report.overall_risk_score,
        report.overall_risk_level,
        report.total_processing_time_ms,
    )

    return report


@router.post("/forensics/batch")
async def analyze_forensics_batch(
    files: list[UploadFile] = File(...),
    skip_modules: str | None = Query(None),
    scan_mode: str | None = Query(None),
):
    """Batch forensic analysis — process multiple files in one request.

    All files are analyzed concurrently using the same pipeline. This is
    significantly faster than N separate /forensics calls because:
    1. Single HTTP round-trip instead of N
    2. ONNX models can batch multiple images in one forward pass
    3. No queue/scheduling overhead between files
    """
    if not settings.forensics_enabled:
        return [ForensicReport(overall_risk_score=0.0, overall_risk_level="Low")
                for _ in files]

    max_size = settings.max_image_size_mb * 1024 * 1024
    skip = set(skip_modules.split(",")) if skip_modules else set()
    if scan_mode == "quick":
        skip |= _QUICK_SKIP
    skip_list = list(skip) if skip else None

    pipeline = get_pipeline()

    # Read all files and fire analyses concurrently
    async def analyze_one(f: UploadFile) -> ForensicReport:
        contents = await f.read()
        filename = f.filename or "unknown"
        if len(contents) > max_size:
            return ForensicReport(
                overall_risk_score=0.0, overall_risk_level="Low",
                modules=[], total_processing_time_ms=0,
            )
        return await pipeline.analyze(contents, filename, skip_list)

    reports = await asyncio.gather(*[analyze_one(f) for f in files])

    logger.info(
        "Batch forensic analysis complete: %d files, avg_time=%dms",
        len(reports),
        sum(r.total_processing_time_ms for r in reports) // max(len(reports), 1),
    )

    return list(reports)


@router.post("/forensics/batch-group", response_model=BatchGroupResponse)
async def analyze_forensics_batch_group(
    files: list[UploadFile] = File(...),
    skip_modules: str | None = Query(None, description="Comma-separated module names to skip"),
    scan_mode: str | None = Query(None, description="quick or full"),
):
    """Group forensic analysis with cross-image comparison."""
    if not settings.forensics_enabled:
        return BatchGroupResponse(
            per_file_reports=[
                ForensicReport(overall_risk_score=0.0, overall_risk_level="Low")
                for _ in files
            ],
        )

    max_size = settings.max_image_size_mb * 1024 * 1024
    skip = set(skip_modules.split(",")) if skip_modules else set()
    if scan_mode == "quick":
        skip |= _QUICK_SKIP
    skip_list = list(skip) if skip else None

    pipeline = get_pipeline()

    # Read all files upfront (we need the bytes for cross-image analysis too)
    file_data: list[tuple[bytes, str]] = []
    for f in files:
        data = await f.read()
        name = f.filename or "unknown"
        file_data.append((data, name))

    # Run per-file analysis concurrently (same as batch)
    async def analyze_one(data: bytes, name: str) -> ForensicReport:
        if len(data) > max_size:
            return ForensicReport(
                overall_risk_score=0.0, overall_risk_level="Low",
                modules=[], total_processing_time_ms=0,
            )
        return await pipeline.analyze(data, name, skip_list)

    per_file_reports = list(await asyncio.gather(
        *(analyze_one(data, name) for data, name in file_data)
    ))

    # Run cross-image analysis
    cross_report = analyze_cross_image(
        [d for d, _ in file_data],
        [n for _, n in file_data],
        per_file_reports,
    )

    logger.info(
        "Batch-group forensic analysis complete: %d files, %d cross-findings, modifier=%.4f",
        len(per_file_reports),
        len(cross_report.findings),
        cross_report.group_risk_modifier,
    )

    return BatchGroupResponse(
        per_file_reports=per_file_reports,
        cross_image_report=cross_report,
    )


@router.post("/forensics/stream")
async def analyze_forensics_stream(
    file: UploadFile = File(...),
    skip_modules: str | None = Query(
        None, description="Comma-separated module names to skip"
    ),
    scan_mode: str | None = Query(
        None, description="'quick' (~40s, core modules) or 'full' (~180s, all modules). Default: full"
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

    skip = set(skip_modules.split(",")) if skip_modules else set()
    if scan_mode == "quick":
        skip |= _QUICK_SKIP
    skip = list(skip) if skip else None

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
