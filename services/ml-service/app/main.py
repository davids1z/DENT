import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import analyze, evidence, forensics, health

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle — pre-load ML models into memory."""
    if settings.forensics_enabled:
        logger.info("Pre-loading forensic models at startup...")
        pipeline = forensics.get_pipeline()
        pipeline.warmup_models()
        logger.info("All forensic models loaded and ready to serve.")
    yield
    # Graceful shutdown — release thread pool and resources
    logger.info("Shutting down ML service...")
    if settings.forensics_enabled:
        try:
            pipeline = forensics.get_pipeline()
            if hasattr(pipeline, "_executor") and pipeline._executor is not None:
                pipeline._executor.shutdown(wait=True, cancel_futures=False)
                logger.info("ThreadPoolExecutor shut down cleanly.")
        except Exception as e:
            logger.warning("Error during executor shutdown: %s", e)
    logger.info("ML service shutdown complete.")


app = FastAPI(
    title="DENT ML Service",
    description="AI-powered vehicle damage analysis",
    version="1.0.0",
    lifespan=lifespan,
)

from .middleware import RequestIdMiddleware

app.add_middleware(RequestIdMiddleware)
# ML service is only called by the C# API on the internal Docker network.
# Restrict CORS to internal callers only (not exposed to browsers).
import os

_ml_cors_origins = os.environ.get(
    "DENT_CORS_ORIGINS", "http://api:8080,http://localhost:8080"
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ml_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["Health"])
app.include_router(analyze.router, tags=["Analysis"])
app.include_router(forensics.router, tags=["Forensics"])
app.include_router(evidence.router, tags=["Evidence"])
