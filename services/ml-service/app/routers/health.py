import os
from datetime import datetime, timezone

from fastapi import APIRouter

from ..config import settings

router = APIRouter()


@router.get("/health")
async def health():
    from .forensics import _pipeline

    # Report concurrency status for monitoring
    pipeline_info = {}
    if _pipeline is not None:
        sem = _pipeline._analysis_semaphore
        # Semaphore._value gives remaining slots (not a public API, but safe for monitoring)
        max_concurrent = int(os.environ.get("DENT_MAX_CONCURRENT_ANALYSES", "3"))
        active = max_concurrent - sem._value
        pipeline_info = {
            "active_analyses": active,
            "max_concurrent": max_concurrent,
            "thread_pool_size": _pipeline._executor._max_workers,
        }

    return {
        "status": "healthy",
        "service": "DENT ML Service",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "concurrency": pipeline_info,
    }


@router.get("/health/models")
async def model_status():
    """Diagnostic: check which model weight files exist on disk."""
    cache = settings.forensics_model_cache_dir
    checks = {
        "catnet_weights": os.path.join(cache, "cnn", "catnet", "weights.pth"),
        "trufor_weights": os.path.join(cache, "cnn", "trufor", "trufor.pth.tar"),
        "clip_probe": os.path.join(cache, "clip_ai", "probe_weights.npz"),
    }
    result = {}
    for name, path in checks.items():
        exists = os.path.exists(path)
        size = os.path.getsize(path) if exists else 0
        result[name] = {"path": path, "exists": exists, "size_mb": round(size / 1048576, 1)}

    # Check HF cache dirs
    for subdir in ["clip_ai", "vae_recon", "text_ai"]:
        d = os.path.join(cache, subdir)
        hf_dirs = [f for f in os.listdir(d) if f.startswith("models--")] if os.path.isdir(d) else []
        result[f"{subdir}_hf_cache"] = {"path": d, "cached_models": hf_dirs}

    # List cnn directory contents
    cnn_dir = os.path.join(cache, "cnn")
    if os.path.isdir(cnn_dir):
        cnn_contents = {}
        for root, dirs, files in os.walk(cnn_dir):
            for f in files:
                fp = os.path.join(root, f)
                cnn_contents[os.path.relpath(fp, cnn_dir)] = os.path.getsize(fp)
        result["cnn_dir_contents"] = cnn_contents
    else:
        result["cnn_dir_contents"] = "directory does not exist"

    return result
