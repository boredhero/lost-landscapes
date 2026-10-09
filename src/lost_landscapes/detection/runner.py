"""Pass runner: orchestrates detection pass chains on tiles."""

import time
from pathlib import Path
from typing import Any

import numpy as np
import rasterio

from lost_landscapes.config import settings
from lost_landscapes.detection.base import Candidate, DetectionPass, PassInput
from lost_landscapes.detection.fusion import ResultFuser
from lost_landscapes.detection.geometry_support import PASSES as GEOMETRY_PASSES
from lost_landscapes.detection.geometry_support import prepare
from lost_landscapes.detection.postprocess.classification import classify_candidate
from lost_landscapes.detection.postprocess.morphometrics import compute_morphometrics_for_candidate
from lost_landscapes.detection.registry import PassRegistry
from lost_landscapes.utils.crs import resolve_epsg
from lost_landscapes.utils.log_manager import log
from lost_landscapes.utils.perf import get_profiler


class PassRunner:
    """Executes a configured chain of detection passes on a tile."""

    def __init__(
        self,
        pass_names: list[str],
        config: dict[str, Any] | None = None,
        weights: dict[str, float] | None = None,
        min_confidence: float = 0.3,
    ):
        log.info("pass_runner_init", pass_names=pass_names, min_confidence=min_confidence, weights=weights)
        self.passes = PassRegistry.get_pass_chain(pass_names)
        self.config = config or {}
        self.fuser = ResultFuser(weights=weights, min_confidence=min_confidence)

    @classmethod
    def from_toml(cls, toml_path: Path) -> "PassRunner":
        """Create a PassRunner from a TOML configuration file."""
        import tomllib
        log.info("config_load_start", toml_path=str(toml_path))
        try:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
        except Exception as e:
            log.error("config_load_failed", toml_path=str(toml_path), error=str(e), exception=True)
            raise
        pipeline = data.get("pipeline", {})
        pass_names = pipeline.get("passes", [])
        min_confidence = pipeline.get("min_confidence", 0.3)
        weights = data.get("weights", {})
        # Flatten pass configs: {"passes": {"fill_difference": {...}}} → {"passes.fill_difference": {...}}
        config = {}
        for pass_name, pass_config in data.get("passes", {}).items():
            config[f"passes.{pass_name}"] = pass_config
        log.info("config_loaded", toml_path=str(toml_path), passes=pass_names, min_confidence=min_confidence, weights=weights, num_pass_configs=len(config))
        return cls(
            pass_names=pass_names,
            config=config,
            weights=weights,
            min_confidence=min_confidence,
        )

    def run_on_dem(
        self,
        dem_path: Path,
        derivatives: dict[str, Path] | None = None,
        point_cloud: Any | None = None,
    ) -> list[Candidate]:
        """Run all passes on a DEM file and return fused candidates."""
        profiler = get_profiler()

        t0 = time.perf_counter()
        with rasterio.open(dem_path) as src:
            elevation_unit = src.units[0] or src.tags(1).get("UNITTYPE") or src.tags().get("elevation_units")
            if any(p.name in GEOMETRY_PASSES for p in self.passes) and elevation_unit and elevation_unit.lower() not in {"m", "metre", "metres", "meter", "meters"}:
                raise ValueError("Discovery requires metre elevations; reproject/convert the source first")
            dem = src.read(1, masked=True).astype(np.float32).filled(np.nan)
            dem = dem * src.scales[0] + src.offsets[0]
            transform = src.transform
            crs = resolve_epsg(src.crs)
        dem_io_elapsed = time.perf_counter() - t0

        log.info(
            "raster_io_dem",
            elapsed_s=round(dem_io_elapsed, 3),
            shape=list(dem.shape),
            size_mb=round(dem.nbytes / 1e6, 1),
        )
        if profiler:
            profiler.record("load_dem", dem_io_elapsed, parent="detection_io")

        # Load derivative rasters
        loaded_derivatives: dict[str, np.ndarray] = {}
        if derivatives:
            t0 = time.perf_counter()
            total_bytes = 0
            for name, path in derivatives.items():
                with rasterio.open(path) as src:
                    arr = src.read(1).astype(np.float32)
                    loaded_derivatives[name] = arr
                    total_bytes += arr.nbytes
            deriv_io_elapsed = time.perf_counter() - t0
            log.info(
                "raster_io_derivatives",
                elapsed_s=round(deriv_io_elapsed, 3),
                count=len(loaded_derivatives),
                total_mb=round(total_bytes / 1e6, 1),
            )
            if profiler:
                profiler.record(
                    "load_derivatives", deriv_io_elapsed, parent="detection_io",
                    count=len(loaded_derivatives), total_mb=round(total_bytes / 1e6, 1),
                )

        result = self.run_on_array(dem, transform, crs, loaded_derivatives, point_cloud)
        for c in result:
            if c.metadata.get("experimental"):
                stat = dem_path.stat()
                c.metadata.update(source_dem=dem_path.name, source_size_bytes=stat.st_size, source_modified_ns=stat.st_mtime_ns,
                                  elevation_units="metres (assumed when undeclared)")
        return result

    def run_on_array(
        self,
        dem: np.ndarray,
        transform: Any,
        crs: int,
        derivatives: dict[str, np.ndarray] | None = None,
        point_cloud: Any | None = None,
        parallel: bool = True,
    ) -> list[Candidate]:
        """Run all passes on in-memory arrays and return fused candidates.

        When parallel=True (default), runs independent passes concurrently
        using a thread pool. Each pass is numpy/scipy-bound which releases
        the GIL, so threads give real parallelism for C-level operations.

        Thread safety: Each pass gets its own read-only view of the shared
        numpy arrays (numpy arrays are thread-safe for read operations).
        No pass mutates the input arrays. The profiler uses a threading.Lock
        internally for safe concurrent writes.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        if derivatives is None:
            derivatives = {}

        if any(p.name in GEOMETRY_PASSES for p in self.passes):
            derivatives = {**derivatives, **prepare(dem, transform, crs)}

        profiler = get_profiler()
        detection_wall_start = time.perf_counter()

        log.info(
            "detection_start",
            passes=[p.name for p in self.passes],
            num_passes=len(self.passes),
            dem_shape=list(dem.shape),
            derivatives=list(derivatives.keys()),
            parallel=parallel,
        )

        def _run_single_pass(detection_pass: DetectionPass) -> list[tuple[str, Candidate]]:
            pass_config = self.config.get(f"passes.{detection_pass.name}", {})
            pass_input = PassInput(
                dem=dem,
                transform=transform,
                crs=crs,
                derivatives=derivatives,
                point_cloud=point_cloud if detection_pass.requires_point_cloud else None,
                config=pass_config,
            )
            try:
                t0 = time.perf_counter()
                candidates = detection_pass.run(pass_input)
                elapsed = time.perf_counter() - t0
                log.info(
                    "pass_complete",
                    pass_name=detection_pass.name,
                    candidates=len(candidates),
                    elapsed_s=round(elapsed, 3),
                    elapsed_ms=round(elapsed * 1000, 1),
                )
                if profiler:
                    profiler.record(
                        detection_pass.name, elapsed,
                        parent="detection_passes",
                        candidates=len(candidates),
                    )
                for c in candidates:
                    if detection_pass.name in GEOMETRY_PASSES:
                        c.metadata.update(crs=f"EPSG:{crs}", resolution_m=[abs(transform.a), abs(transform.e)],
                                          relief_half_widths_m=[10, 25])
                return [(detection_pass.name, c) for c in candidates]
            except Exception as e:
                if detection_pass.name in GEOMETRY_PASSES:
                    raise
                elapsed = time.perf_counter() - t0
                log.error("pass_failed", pass_name=detection_pass.name, error=str(e), elapsed_s=round(elapsed, 3), exception=True)
                return []

        all_candidates: list[tuple[str, Candidate]] = []

        if parallel and len(self.passes) > 1:
            pool_size = min(len(self.passes), settings.detection_workers)
            log.info("parallel_execution_start", thread_pool_size=pool_size, num_passes=len(self.passes))
            with ThreadPoolExecutor(max_workers=pool_size) as executor:
                futures = {executor.submit(_run_single_pass, p): p for p in self.passes}
                for future in as_completed(futures):
                    all_candidates.extend(future.result())
        else:
            log.info("sequential_execution_start", num_passes=len(self.passes))
            for detection_pass in self.passes:
                all_candidates.extend(_run_single_pass(detection_pass))

        passes_elapsed = time.perf_counter() - detection_wall_start
        log.info(
            "all_passes_complete",
            wall_time_s=round(passes_elapsed, 3),
            total_raw_candidates=len(all_candidates),
        )

        # Pre-filter before DBSCAN: remove obvious junk that can't survive post-fusion
        # quality filters. Use looser thresholds than post-fusion (score 0.15 vs 0.3)
        # because multi-pass fusion bonus (1.2x) can boost borderline candidates.
        # Shape families never enter depression-specific fusion or classification.
        geometry_candidates = [c for name, c in all_candidates if name in GEOMETRY_PASSES
                               and c.score >= self.fuser.min_confidence]
        all_candidates = [(name, c) for name, c in all_candidates if name not in GEOMETRY_PASSES]
        pre_count = len(all_candidates)
        all_candidates = [(pn, c) for pn, c in all_candidates if c.score > 0.15 and c.morphometrics.get("area_m2", 0) > 20 and c.morphometrics.get("depth_m", c.morphometrics.get("lrm_anomaly_m", 0)) < 200]
        log.info("pre_fusion_filter", before=pre_count, after=len(all_candidates), removed=pre_count - len(all_candidates))

        # Fusion timing
        t0 = time.perf_counter()
        fused = self.fuser.fuse(all_candidates)
        fusion_elapsed = time.perf_counter() - t0

        # Post-fusion morphometrics: compute full metrics for each fused candidate
        # using the merged outline + original DEM. This ensures every candidate has
        # depth, area, circularity, etc. regardless of which passes detected it.
        resolution_m = abs(transform[0])
        morph_computed = 0
        for candidate in fused:
            if candidate.outline is not None:
                full_morph = compute_morphometrics_for_candidate(dem, candidate.outline, transform, resolution_m)
                if full_morph:
                    candidate.morphometrics.update(full_morph)
                    morph_computed += 1
        if morph_computed:
            log.info("post_fusion_morphometrics", total=len(fused), computed=morph_computed)
        # Post-fusion classification: classify using complete morphometrics
        type_changes = 0
        for candidate in fused:
            old_type = candidate.feature_type
            candidate.feature_type = classify_candidate(candidate)
            if candidate.feature_type != old_type:
                type_changes += 1
        if type_changes:
            log.info("post_fusion_reclassification", total=len(fused), reclassified=type_changes)

        total_elapsed = time.perf_counter() - detection_wall_start
        log.info(
            "detection_complete",
            total_s=round(total_elapsed, 3),
            passes_s=round(passes_elapsed, 3),
            fusion_s=round(fusion_elapsed, 3),
            raw_candidates=len(all_candidates),
            fused_candidates=len(fused),
        )
        if profiler:
            profiler.record("fusion", fusion_elapsed, parent="detection",
                            raw=len(all_candidates), fused=len(fused))
            profiler.record("detection_total", total_elapsed, parent=None,
                            passes=len(self.passes), fused=len(fused))

        return sorted(fused + geometry_candidates, key=lambda c: c.score, reverse=True)
