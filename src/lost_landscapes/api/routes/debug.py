"""Debug endpoints — performance profiling.

Gated behind LOST_LANDSCAPES_DEBUG=1 env var. Off by default in production
to avoid leaking system info that could help attackers fingerprint the server.
"""

import os
import platform
import shutil
import time
from typing import Any

from fastapi import APIRouter, HTTPException

from lost_landscapes.utils.log_manager import log
from lost_landscapes.utils.perf import get_cpu_count, get_gpu_info, get_memory_mb

router = APIRouter(prefix="/api/debug", tags=["debug"])


def _check_debug_enabled() -> None:
    """Raise 404 if debug mode is not enabled — makes endpoint invisible."""
    if os.environ.get("LOST_LANDSCAPES_DEBUG", "").strip() not in ("1", "true", "yes"):
        log.debug("debug_endpoint_blocked", reason="LOST_LANDSCAPES_DEBUG not set")
        raise HTTPException(status_code=404, detail="Not found")


@router.get("/system-info")
async def system_info() -> dict[str, Any]:
    """Return hardware/software info for diagnosing performance issues.

    Only available when LOST_LANDSCAPES_DEBUG=1 is set. Returns 404 otherwise
    so the endpoint doesn't even show up in scans.
    """
    _check_debug_enabled()
    log.info("debug_system_info_request")
    t0 = time.perf_counter()
    gpu = get_gpu_info()
    info: dict[str, Any] = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu": {
            "count_os": os.cpu_count(),
            "count_available": get_cpu_count(),
            "arch": platform.machine(),
        },
        "memory": {
            "rss_mb": round(get_memory_mb(), 1),
        },
        "gpu": gpu,
    }
    for tool in ["pdal", "gdaldem", "whitebox_tools"]:
        info[f"has_{tool}"] = shutil.which(tool) is not None
    try:
        import cupy
        info["cupy_version"] = cupy.__version__
    except ImportError:
        info["cupy_version"] = None
        log.debug("debug_cupy_not_available")
    try:
        import torch
        info["torch_version"] = torch.__version__
        info["torch_cuda"] = torch.cuda.is_available()
    except ImportError:
        info["torch_version"] = None
        log.debug("debug_torch_not_available")
    try:
        import scipy
        info["scipy_version"] = scipy.__version__
    except ImportError:
        info["scipy_version"] = None
        log.debug("debug_scipy_not_available")
    log.info("debug_system_info_complete", rss_mb=info["memory"]["rss_mb"], cpu_count=info["cpu"]["count_available"], has_gpu=gpu is not None, elapsed_ms=round((time.perf_counter() - t0) * 1000, 1))
    return info


@router.get("/storage")
async def storage_stats() -> dict[str, Any]:
    """Storage usage breakdown — always available (no secrets exposed)."""
    log.info("debug_storage_stats_request")
    t0 = time.perf_counter()
    from lost_landscapes.config import settings
    from lost_landscapes.utils.storage import get_storage_stats
    if not settings.data_dir.exists():
        log.warning("debug_storage_data_dir_missing", data_dir=str(settings.data_dir))
        return {"error": "data_dir not found"}
    stats = get_storage_stats(settings.data_dir)
    log.info("debug_storage_stats_complete", data_dir=str(settings.data_dir), elapsed_ms=round((time.perf_counter() - t0) * 1000, 1))
    return stats
