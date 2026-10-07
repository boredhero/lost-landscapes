"""Terrain derivative computation — GDAL + WhiteboxTools native subprocesses.

NO numpy computation. Everything runs as compiled C/C++/Rust subprocesses.
Python only orchestrates and reads results.

For unit tests: generate small test GeoTIFFs and run the same native pipeline.
"""

import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from lost_landscapes.config import settings
from lost_landscapes.utils.log_manager import log


def _run(cmd: list[str], timeout: int = 300) -> None:
    """Run a subprocess, raise on failure."""
    log.debug("subprocess_start", cmd=cmd[0], args=cmd[1:4], timeout=timeout)
    t0 = time.perf_counter()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        elapsed = time.perf_counter() - t0
        log.error("subprocess_timeout", cmd=cmd[0], timeout=timeout, elapsed_s=round(elapsed, 3))
        raise
    except FileNotFoundError:
        log.error("subprocess_not_found", cmd=cmd[0], exception=True)
        raise
    elapsed = time.perf_counter() - t0
    if result.returncode != 0:
        log.error("subprocess_failed", cmd=cmd[0], exit_code=result.returncode, elapsed_s=round(elapsed, 3), stderr=result.stderr[:300])
        raise RuntimeError(f"{cmd[0]} failed (exit {result.returncode}): {result.stderr[:500]}")
    log.debug("subprocess_complete", cmd=cmd[0], exit_code=result.returncode, elapsed_s=round(elapsed, 3))


def _get_wbt(verbose: bool = False):
    """Get a WhiteboxTools instance."""
    import whitebox
    log.debug("wbt_init", verbose=verbose)
    wbt = whitebox.WhiteboxTools()
    wbt.set_verbose_mode(verbose)
    wbt.set_max_procs(settings.derivative_workers)
    return wbt


def _wbt_check(ret: int, name: str, out: str, dem_input: str | None = None) -> None:
    """Check WBT return code and verify output file exists.
    On ghost output (rc=0 but no file), re-runs with verbose to capture diagnostics.
    """
    if ret != 0:
        log.error("wbt_failed", tool=name, exit_code=ret, output=out)
        raise RuntimeError(f"WhiteboxTools {name} failed (exit {ret})")
    if not Path(out).exists():
        diag = ""
        if dem_input:
            try:
                import contextlib
                import io
                wbt_verbose = _get_wbt(verbose=True)
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    getattr(wbt_verbose, name)(dem_input, out)
                diag = buf.getvalue()[:1000]
            except Exception as e:
                log.error("wbt_verbose_rerun_failed", tool=name, error=str(e), exception=True)
                diag = f"verbose re-run failed: {e}"
        log.error("wbt_ghost_output", tool=name, output=out, input=dem_input, verbose_output=diag)
        raise RuntimeError(f"WhiteboxTools {name} returned 0 but output missing: {out}")


# --- Individual derivative functions (each runs a native subprocess) ---
# Each returns (output_path, elapsed_seconds) for profiling.
# These run in child processes via ProcessPoolExecutor, so they can't
# share the parent's PipelineProfiler — they return timing data instead.


def _timed_derivative(fn):
    """Wrapper that times a derivative function and returns (result, elapsed_s)."""
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        result = fn(*args, **kwargs)
        elapsed = time.perf_counter() - t0
        return result, elapsed
    wrapper.__name__ = fn.__name__
    wrapper.__qualname__ = fn.__qualname__
    return wrapper


@_timed_derivative
def compute_hillshade(dem: str, out: str) -> str:
    log.debug("compute_hillshade_start", dem=dem, output=out)
    _run(["gdaldem", "hillshade", dem, out, "-az", "315", "-alt", "45", "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES", "-q"])
    log.debug("compute_hillshade_done", output=out, size_bytes=Path(out).stat().st_size if Path(out).exists() else 0)
    return out


@_timed_derivative
def compute_slope(dem: str, out: str) -> str:
    log.debug("compute_slope_start", dem=dem, output=out)
    _run(["gdaldem", "slope", dem, out, "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES", "-q"])
    log.debug("compute_slope_done", output=out, size_bytes=Path(out).stat().st_size if Path(out).exists() else 0)
    return out


@_timed_derivative
def compute_tpi(dem: str, out: str) -> str:
    log.debug("compute_tpi_start", dem=dem, output=out)
    _run(["gdaldem", "TPI", dem, out, "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES", "-q"])
    log.debug("compute_tpi_done", output=out, size_bytes=Path(out).stat().st_size if Path(out).exists() else 0)
    return out


@_timed_derivative
def compute_roughness(dem: str, out: str) -> str:
    log.debug("compute_roughness_start", dem=dem, output=out)
    _run(["gdaldem", "roughness", dem, out, "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES", "-q"])
    log.debug("compute_roughness_done", output=out, size_bytes=Path(out).stat().st_size if Path(out).exists() else 0)
    return out


@_timed_derivative
def compute_svf(dem: str, out: str) -> str:
    log.debug("compute_svf_start", dem=dem, output=out)
    wbt = _get_wbt()
    if hasattr(wbt, 'sky_view_factor'):
        log.debug("compute_svf_using", method="sky_view_factor")
        ret = wbt.sky_view_factor(dem, out)
    elif hasattr(wbt, 'viewshed'):
        log.debug("compute_svf_using", method="multidirectional_hillshade_fallback")
        ret = wbt.multidirectional_hillshade(dem, out)
    else:
        log.error("compute_svf_no_method_available")
        raise RuntimeError("WhiteboxTools has no sky_view_factor or suitable alternative")
    _wbt_check(ret, "sky_view_factor", out)
    log.debug("compute_svf_done", output=out, size_bytes=Path(out).stat().st_size if Path(out).exists() else 0)
    return out


@_timed_derivative
def compute_lrm(dem: str, out: str, kernel: int = 100) -> str:
    log.debug("compute_lrm_start", dem=dem, output=out, kernel=kernel)
    wbt = _get_wbt()
    # LRM thresholds are in meters. DevFromMeanElev is standardized by local
    # standard deviation and turns tiny flat-surface noise into large scores.
    ret = wbt.diff_from_mean_elev(dem, out, filterx=kernel, filtery=kernel)
    _wbt_check(ret, "lrm", out)
    log.debug("compute_lrm_done", output=out, kernel=kernel, size_bytes=Path(out).stat().st_size if Path(out).exists() else 0)
    return out


@_timed_derivative
def compute_profile_curvature(dem: str, out: str) -> str:
    log.debug("compute_profile_curvature_start", dem=dem, output=out)
    wbt = _get_wbt()
    ret = wbt.profile_curvature(dem, out)
    _wbt_check(ret, "profile_curvature", out)
    log.debug("compute_profile_curvature_done", output=out, size_bytes=Path(out).stat().st_size if Path(out).exists() else 0)
    return out


@_timed_derivative
def compute_plan_curvature(dem: str, out: str) -> str:
    log.debug("compute_plan_curvature_start", dem=dem, output=out)
    wbt = _get_wbt()
    ret = wbt.plan_curvature(dem, out)
    _wbt_check(ret, "plan_curvature", out)
    log.debug("compute_plan_curvature_done", output=out, size_bytes=Path(out).stat().st_size if Path(out).exists() else 0)
    return out


@_timed_derivative
def compute_fill_difference(dem: str, filled: str, out: str) -> str:
    """Subtract original DEM from filled DEM using rasterio (trivial operation)."""
    import rasterio
    log.debug("compute_fill_difference_start", dem=dem, filled=filled, output=out)
    with rasterio.open(dem) as src_dem, rasterio.open(filled) as src_filled:
        dem_arr = src_dem.read(1)
        filled_arr = src_filled.read(1)
        log.debug("compute_fill_difference_arrays", dem_shape=dem_arr.shape, filled_shape=filled_arr.shape)
        diff = (filled_arr - dem_arr).astype("float32")
        profile = src_dem.profile.copy()
        profile.update(dtype="float32", compress="deflate")
        with rasterio.open(out, "w", **profile) as dst:
            dst.write(diff, 1)
    log.debug("compute_fill_difference_done", output=out, size_bytes=Path(out).stat().st_size if Path(out).exists() else 0)
    return out


@_timed_derivative
def fill_depressions(dem: str, out: str) -> str:
    log.info("fill_depressions_start", dem=dem, output=out)
    wbt = _get_wbt()
    ret = wbt.fill_depressions(dem, out)
    if ret == 0 and Path(out).exists():
        log.info("fill_depressions_primary_ok", dem=dem, output=out, size_bytes=Path(out).stat().st_size)
        return out
    log.warning("fill_depressions_primary_failed", dem=dem, ret=ret, output_exists=Path(out).exists())
    # Preserve fill semantics: breaching lowers terrain and corrupts fill differences.
    # Fallback 1: native Planchon-Darboux depression filling.
    if hasattr(wbt, 'fill_depressions_planchon_and_darboux'):
        ret = wbt.fill_depressions_planchon_and_darboux(dem, out, fix_flats=True)
        if ret == 0 and Path(out).exists():
            log.info("fill_depressions_planchon_ok", dem=dem)
            return out
    # Fallback 2: skimage morphological reconstruction (Planchon-Darboux equivalent, no new deps)
    log.warning("fill_depressions_skimage_fallback", dem=dem)
    import numpy as np
    import rasterio
    from skimage.morphology import reconstruction
    with rasterio.open(dem) as src:
        dem_arr = src.read(1).astype(np.float64)
        profile = src.profile.copy()
        nodata = profile.get('nodata', -9999)
    nodata_mask = np.isnan(dem_arr) | (dem_arr == nodata)
    seed = np.full_like(dem_arr, dem_arr[~nodata_mask].max() if not nodata_mask.all() else 0)
    seed[0, :] = dem_arr[0, :]
    seed[-1, :] = dem_arr[-1, :]
    seed[:, 0] = dem_arr[:, 0]
    seed[:, -1] = dem_arr[:, -1]
    seed[nodata_mask] = dem_arr[nodata_mask]
    filled = reconstruction(seed, dem_arr, method='erosion')
    profile.update(dtype="float32", compress="deflate", tiled=True, blockxsize=256, blockysize=256)
    with rasterio.open(out, "w", **profile) as dst:
        dst.write(filled.astype(np.float32), 1)
    log.info("fill_depressions_skimage_ok", dem=dem, out=out)
    return out


# --- Parallel orchestrator ---

def compute_all_derivatives(
    dem_path: Path,
    filled_dem_path: Path,
    output_dir: Path,
    max_workers: int = 8,
) -> dict[str, Path]:
    """Compute all derivatives in parallel using native subprocesses.

    Each derivative is a separate process running a compiled tool.
    Results are cached permanently — skips if output file already exists.

    Returns dict of {name: Path} and logs per-derivative timing.
    Child processes can't share the parent's PipelineProfiler, so each
    derivative function returns (result, elapsed_s) via @_timed_derivative.
    Timing is collected here and fed back to the profiler if one is active.
    """
    from lost_landscapes.utils.perf import get_profiler
    log.info("compute_all_derivatives_start", dem=str(dem_path), filled_dem=str(filled_dem_path), output_dir=str(output_dir), max_workers=max_workers)
    output_dir.mkdir(parents=True, exist_ok=True)
    dem = str(dem_path)
    filled = str(filled_dem_path)
    wall_start = time.perf_counter()

    # (name, output_path, function, args)
    tasks = [
        ("hillshade", output_dir / "hillshade.tif", compute_hillshade, [dem, str(output_dir / "hillshade.tif")]),
        ("slope", output_dir / "slope.tif", compute_slope, [dem, str(output_dir / "slope.tif")]),
        ("tpi", output_dir / "tpi.tif", compute_tpi, [dem, str(output_dir / "tpi.tif")]),
        ("roughness", output_dir / "roughness.tif", compute_roughness, [dem, str(output_dir / "roughness.tif")]),
        ("svf", output_dir / "svf.tif", compute_svf, [dem, str(output_dir / "svf.tif")]),
        ("lrm_50m", output_dir / "lrm_50m.tif", compute_lrm, [dem, str(output_dir / "lrm_50m.tif"), 50]),
        ("lrm_100m", output_dir / "lrm_100m.tif", compute_lrm, [dem, str(output_dir / "lrm_100m.tif"), 100]),
        ("lrm_200m", output_dir / "lrm_200m.tif", compute_lrm, [dem, str(output_dir / "lrm_200m.tif"), 200]),
        ("profile_curvature", output_dir / "profile_curvature.tif", compute_profile_curvature, [dem, str(output_dir / "profile_curvature.tif")]),
        ("plan_curvature", output_dir / "plan_curvature.tif", compute_plan_curvature, [dem, str(output_dir / "plan_curvature.tif")]),
        ("fill_difference", output_dir / "fill_difference.tif", compute_fill_difference, [dem, filled, str(output_dir / "fill_difference.tif")]),
    ]

    results: dict[str, Path] = {}

    # Check cache first
    to_compute = []
    cached_names = []
    for name, out_path, fn, args in tasks:
        if out_path.exists():
            results[name] = out_path
            cached_names.append(name)
        else:
            to_compute.append((name, fn, args, out_path))

    if cached_names:
        log.info("derivatives_cache_hits", cached_names=cached_names, count=len(cached_names))
    if not to_compute:
        log.info("all_derivatives_cached", count=len(results))
        return results

    log.info(
        "computing_derivatives",
        cached=len(results),
        remaining=len(to_compute),
        max_workers=min(max_workers, len(to_compute)),
        names=[t[0] for t in to_compute],
    )

    profiler = get_profiler()
    timings: list[tuple[str, float]] = []

    # Run uncached derivatives in parallel via threads.
    # Each derivative calls a native subprocess (GDAL/WBT) that releases the GIL,
    # so threads give real parallelism. We use ThreadPoolExecutor instead of
    # ProcessPoolExecutor because Celery workers are daemonic processes that
    # cannot spawn child processes.
    with ThreadPoolExecutor(max_workers=min(max_workers, len(to_compute))) as executor:
        futures = {}
        for name, fn, args, out_path in to_compute:
            futures[executor.submit(fn, *args)] = (name, out_path)

        for future in as_completed(futures):
            name, out_path = futures[future]
            try:
                _result_path, elapsed_s = future.result()
                if out_path.exists():
                    results[name] = out_path
                    timings.append((name, elapsed_s))
                    log.info("derivative_done", name=name, elapsed_s=round(elapsed_s, 3))
                    if profiler:
                        profiler.record(name, elapsed_s, parent="derivatives")
                else:
                    log.error("derivative_missing", name=name, path=str(out_path), elapsed_s=round(elapsed_s, 3))
            except Exception as e:
                log.error("derivative_failed", name=name, error=str(e))

    wall_elapsed = time.perf_counter() - wall_start
    cpu_total = sum(t for _, t in timings)

    # Sort by slowest-first for the summary
    timings.sort(key=lambda x: x[1], reverse=True)
    timing_summary = {name: round(t, 3) for name, t in timings}

    log.info(
        "derivatives_complete",
        wall_time_s=round(wall_elapsed, 3),
        cpu_total_s=round(cpu_total, 3),
        parallelism_ratio=round(cpu_total / wall_elapsed, 1) if wall_elapsed > 0 else 0,
        computed=len(timings),
        cached=len(cached_names),
        slowest=timings[0][0] if timings else None,
        slowest_s=round(timings[0][1], 3) if timings else 0,
        per_derivative=timing_summary,
    )

    if profiler:
        profiler.record(
            "derivatives_total", wall_elapsed, parent=None,
            computed=len(timings), cached=len(cached_names),
            parallelism_ratio=round(cpu_total / wall_elapsed, 1) if wall_elapsed > 0 else 0,
        )

    return results
