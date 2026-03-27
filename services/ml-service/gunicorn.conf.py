"""Gunicorn configuration for DENT ML Service.

Uses --preload to load ML models once in the master process before forking
workers. Workers inherit model memory via Linux COW (copy-on-write), so
2 workers only use ~5.5GB total instead of ~9GB without sharing.

Key settings:
- preload_app: Load app + models in master before fork
- worker_class: UvicornWorker for async FastAPI compatibility
- workers: Configurable via DENT_UVICORN_WORKERS env var (default: 2)
- timeout: 300s to handle long-running forensic analyses
"""
import os

# Worker configuration
workers = int(os.environ.get("DENT_UVICORN_WORKERS", "2"))
worker_class = "uvicorn.workers.UvicornWorker"
preload_app = True

# Binding
bind = "0.0.0.0:8000"

# Timeouts — forensic analysis can take up to 3 minutes per image
timeout = 300
graceful_timeout = 120
keepalive = 5

# Logging
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("DENT_LOG_LEVEL", "info").lower()

# Performance
worker_tmp_dir = "/dev/shm"  # Use shared memory for heartbeat (faster than disk)


def on_starting(server):
    """Load ML models in the master process BEFORE forking workers.

    This is the key to memory efficiency: models loaded here are shared
    across all workers via COW (copy-on-write). Since model weights are
    read-only during inference, the physical memory pages stay shared.
    """
    server.log.info("Master: pre-loading forensic models before fork...")

    from app.routers.forensics import get_pipeline

    pipeline = get_pipeline()
    pipeline.warmup_models()

    server.log.info("Master: all models loaded, forking %d workers", workers)


def post_fork(server, worker):
    """Per-worker initialization after fork.

    Reset PyTorch thread settings for the forked worker process.
    Each worker gets its own thread pool for inference.
    """
    import torch

    num_threads = int(os.environ.get("OMP_NUM_THREADS", "4"))
    torch.set_num_threads(num_threads)

    server.log.info(
        "Worker %s: initialized with %d torch threads", worker.pid, num_threads
    )
