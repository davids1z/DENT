import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import agent, analyze, forensics, health

logging.basicConfig(level=settings.log_level)

app = FastAPI(
    title="DENT ML Service",
    description="AI-powered vehicle damage analysis",
    version="1.0.0",
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
