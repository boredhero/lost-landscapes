"""Array backend abstraction — GPU (CuPy) + CPU (scipy) hybrid.

Benchmark results on RX 6900 XT (gfx1030) with 1500x1500 DEM:
  - label():        GPU 1.4ms vs CPU 14.3ms  → 10x GPU win
  - sum(per-label): GPU 1776ms vs CPU 17.6ms → 100x CPU win

Strategy: GPU for connected-component labeling (single large parallel
operation), CPU for per-label region stats (many tiny operations where
GPU kernel launch overhead dominates).

Thread safety: Backend state is determined once at import time and is
immutable — safe for concurrent ThreadPoolExecutor access.

Process safety: Each worker process imports independently and detects
its own GPU state.
"""

import time

import numpy as np
from scipy import ndimage as scipy_ndimage

from lost_landscapes.utils.log_manager import log

# Detect CuPy at import time (once per process)
_HAS_CUPY = False
_CUPY_REASON = ""

try:
    import cupy
    import cupyx.scipy.ndimage as cupy_ndimage

    # Verify we can actually allocate on the GPU
    _test = cupy.zeros(10)
    del _test
    _HAS_CUPY = True
    log.info("cupy_available", device=str(cupy.cuda.Device(0)))
except ImportError:
    _CUPY_REASON = "cupy not installed"
    log.debug("cupy_import_failed", reason="cupy not installed")
except Exception as e:
    _CUPY_REASON = f"cupy init failed: {e}"
    log.warning("cupy_init_failed", error=str(e), exception=True)

if not _HAS_CUPY and _CUPY_REASON:
    log.info("cupy_unavailable", reason=_CUPY_REASON)


def has_gpu() -> bool:
    """Check if GPU acceleration is available."""
    return _HAS_CUPY


def label(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """Connected component labeling — GPU accelerated (10x speedup).

    Uses CuPy on GPU when available. Returns numpy arrays because
    downstream code (Shapely, region_stats) uses numpy/scipy.
    """
    backend = "gpu" if _HAS_CUPY else "cpu"
    t0 = time.perf_counter()
    if _HAS_CUPY:
        gpu_mask = cupy.asarray(mask)
        gpu_labeled, num = cupy_ndimage.label(gpu_mask)
        labeled, num_features = cupy.asnumpy(gpu_labeled), int(num)
    else:
        labeled, num_features = scipy_ndimage.label(mask)
    elapsed = time.perf_counter() - t0
    log.debug("label_complete", backend=backend, mask_shape=list(mask.shape), num_features=num_features, elapsed_ms=round(elapsed * 1000, 2), memory_mb=round(mask.nbytes / 1e6, 2))
    return labeled, num_features


def region_stats(
    data: np.ndarray,
    labeled: np.ndarray,
    num_features: int,
    mask: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """Compute bulk region statistics — ALWAYS on CPU.

    Per-label stats (sum, min, max, mean across thousands of small regions)
    are 100x faster on CPU than GPU due to kernel launch overhead per label.
    scipy.ndimage implements these as optimized C loops that process all
    labels in a single pass over the array.

    Returns dict with numpy arrays:
        areas_px, centroids, max_vals, min_vals, sum_vals, mean_vals
    """
    t0 = time.perf_counter()
    labels = np.arange(1, num_features + 1)
    use_mask = mask if mask is not None else (labeled > 0).astype(np.float32)
    areas = scipy_ndimage.sum(use_mask, labeled, labels).astype(np.float64)
    max_vals = np.asarray(scipy_ndimage.maximum(data, labeled, labels))
    min_vals = np.asarray(scipy_ndimage.minimum(data, labeled, labels))
    sum_vals = np.asarray(scipy_ndimage.sum(data, labeled, labels))
    mean_vals = np.asarray(scipy_ndimage.mean(data, labeled, labels))
    centroids = scipy_ndimage.center_of_mass(use_mask, labeled, labels)
    elapsed = time.perf_counter() - t0
    total_memory_mb = round((data.nbytes + labeled.nbytes) / 1e6, 2)
    log.debug("region_stats_complete", backend="cpu", num_features=num_features, data_shape=list(data.shape), elapsed_ms=round(elapsed * 1000, 2), memory_mb=total_memory_mb)
    return {
        "areas_px": np.asarray(areas, dtype=np.float64),
        "max_vals": np.asarray(max_vals, dtype=np.float64),
        "min_vals": np.asarray(min_vals, dtype=np.float64),
        "sum_vals": np.asarray(sum_vals, dtype=np.float64),
        "mean_vals": np.asarray(mean_vals, dtype=np.float64),
        "centroids": centroids,
    }
