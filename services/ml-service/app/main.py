import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import agent, analyze, evidence, forensics, health

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle — pre-load ML models into memory."""
    # ── Startup: warm up forensic pipeline ─────────────────────
    if settings.forensics_enabled:
        logger.info("Pre-loading forensic models at startup...")
        pipeline = forensics.get_pipeline()
        pipeline.warmup_models()
        logger.info("All forensic models loaded and ready to serve.")
    yield
    # ── Shutdown: nothing to clean up ──────────────────────────


app = FastAPI(
    title="DENT ML Service",
    description="AI-powered vehicle damage analysis",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["Health"])
app.include_router(analyze.router, tags=["Analysis"])
app.include_router(forensics.router, tags=["Forensics"])
app.include_router(agent.router, tags=["Agent"])
app.include_router(evidence.router, tags=["Evidence"])
