"""Processing pipeline — orchestrates PDAL + GDAL + WhiteboxTools.

Python only orchestrates subprocesses and reads results.
All derivative computation is in derivatives.py.
"""

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from lost_landscapes.config import settings
from lost_landscapes.processing.derivatives import compute_all_derivatives, fill_depressions
from lost_landscapes.utils.crs import resolve_epsg
from lost_landscapes.utils.log_manager import log
from lost_landscapes.utils.perf import get_profiler, new_profiler


@dataclass
class ProcessedTile:
    """Immutable result of processing a tile. Stored permanently."""

    tile_dir: Path
    dem_path: Path
    filled_dem_path: Path | None = None
    derivative_paths: dict[str, Path] = field(default_factory=dict)
    resolution_m: float = 1.0
    crs: int = 32617


def _ensure_geotiff_keys(dem_path: Path) -> None:
    """Re-encode DEM with proper GeoTIFF keys if it only has WKT CRS.
    WhiteboxTools panics on 'TIFF file does not contain geokeys' when PDAL
    writes compound CRS (UTM + NAVD88) as WKT-only. Extract horizontal EPSG
    and re-write via gdal_translate to embed GeoKeys."""
    import re

    import rasterio
    log.debug("ensure_geotiff_keys_check", path=str(dem_path))
    with rasterio.open(dem_path) as src:
        crs = src.crs
        if not crs:
            log.debug("ensure_geotiff_keys_no_crs", path=str(dem_path))
            return
        epsg = crs.to_epsg()
        if epsg:
            log.debug("ensure_geotiff_keys_already_ok", path=str(dem_path), epsg=epsg)
            return  # Already has a clean EPSG → GeoKeys are fine
    # Extract horizontal EPSG from compound CRS
    from pyproj import CRS as PyprojCRS
    pcrs = PyprojCRS(crs)
    horiz = pcrs.sub_crs_list[0] if pcrs.is_compound and pcrs.sub_crs_list else pcrs
    h_epsg = horiz.to_epsg()
    if not h_epsg:
        m = re.search(r'UTM zone (\d+)([NS])', str(crs))
        if m:
            h_epsg = 26900 + int(m.group(1)) if m.group(2) == 'N' else 32700 + int(m.group(1))
    if not h_epsg:
        log.warning("geotiff_keys_unknown_crs", path=str(dem_path))
        return
    tmp = dem_path.with_suffix('.tmp.tif')
    result = subprocess.run(["gdal_translate", "-a_srs", f"EPSG:{h_epsg}", "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES", str(dem_path), str(tmp)], capture_output=True, text=True, timeout=120)
    if result.returncode == 0 and tmp.exists():
        tmp.rename(dem_path)
        log.info("geotiff_keys_fixed", path=str(dem_path), epsg=h_epsg)
    else:
        tmp.unlink(missing_ok=True)
        log.warning("geotiff_keys_fix_failed", path=str(dem_path), error=result.stderr[:200])


def generate_dem_pdal(
    input_path: Path,
    output_dir: Path,
    resolution: float = 1.0,
    target_srs: str | None = None,
) -> tuple[Path, Path]:
    """Generate ground DEM and filled DEM from point cloud using PDAL."""
    profiler = get_profiler()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = input_path.stem.replace(".copc", "")
    dem_path = output_dir / f"{stem}_dem.tif"
    filled_path = output_dir / f"{stem}_filled.tif"
    input_size_mb = round(input_path.stat().st_size / 1e6, 2) if input_path.exists() else None
    log.info("generate_dem_pdal_start", input=str(input_path), input_size_mb=input_size_mb, resolution=resolution, target_srs=target_srs, stem=stem)

    if not dem_path.exists():
        reader_type = "readers.copc" if str(input_path).endswith(".copc.laz") else "readers.las"
        # Auto-detect if data is pre-classified — skip SMRF if >50% of points have Class 2 (ground)
        pre_classified = False
        t0_class = time.perf_counter()
        try:
            log.debug("classification_check_start", input=str(input_path))
            info_proc = subprocess.run(["pdal", "info", "--stats", "--dimensions", "Classification", str(input_path)], capture_output=True, text=True, timeout=60)
            if info_proc.returncode == 0:
                import re as _re
                # Look for count of Classification=2 in stats
                _info = info_proc.stdout
                # Check if Classification dimension has values > 0 (not all unclassified)
                _class2_match = _re.search(r'"statistic"[^}]*"name":\s*"Classification"[^}]*"count":\s*(\d+)', _info)
                _total_match = _re.search(r'"num_points":\s*(\d+)', _info)
                if _total_match:
                    total_pts = int(_total_match.group(1))
                    # Check if Classification=2 points exist by running a quick count pipeline
                    count_proc = subprocess.run(["pdal", "pipeline", "--stdin"], input=json.dumps({"pipeline": [{"type": reader_type, "filename": str(input_path)}, {"type": "filters.range", "limits": "Classification[2:2]"}, {"type": "filters.stats"}]}), capture_output=True, text=True, timeout=120)
                    if count_proc.returncode == 0:
                        _cnt_match = _re.search(r'"count":\s*(\d+)', count_proc.stdout)
                        if _cnt_match:
                            ground_pts = int(_cnt_match.group(1))
                            ground_pct = ground_pts / total_pts * 100 if total_pts > 0 else 0
                            pre_classified = ground_pct > 10  # >10% ground points = already classified
                            log.info("classification_check", total=total_pts, ground=ground_pts, ground_pct=round(ground_pct, 1), pre_classified=pre_classified)
        except Exception as e:
            log.warning("classification_check_failed", error=str(e), exception=True)
        class_check_elapsed = time.perf_counter() - t0_class
        log.debug("classification_check_complete", elapsed_s=round(class_check_elapsed, 3), pre_classified=pre_classified)
        pipeline = [{"type": reader_type, "filename": str(input_path)}]
        if target_srs:
            pipeline.append({"type": "filters.reprojection", "out_srs": target_srs})
        if pre_classified:
            # Data already has ground classification — skip SMRF, use mean interpolation (4-7x faster)
            pipeline.extend([
                {"type": "filters.range", "limits": "Classification[2:2]"},
                {"type": "writers.gdal", "filename": str(dem_path), "resolution": resolution, "output_type": "mean", "radius": 1.5, "window_size": 1, "gdalopts": "COMPRESS=DEFLATE,TILED=YES,BLOCKXSIZE=256,BLOCKYSIZE=256", "data_type": "float32"},
            ])
            log.info("pdal_dem_start", input=str(input_path), file_size_mb=round(input_path.stat().st_size / 1e6, 1), mode="pre_classified_fast")
        else:
            # No classification — run full SMRF ground classification
            pipeline.append({"type": "filters.assign", "value": ["ReturnNumber = 1 WHERE ReturnNumber == 0", "NumberOfReturns = 1 WHERE NumberOfReturns == 0"]})
            pipeline.extend([
                {"type": "filters.smrf", "slope": 0.15, "window": 18, "threshold": 0.5},
                {"type": "filters.range", "limits": "Classification[2:2]"},
                {"type": "writers.gdal", "filename": str(dem_path), "resolution": resolution, "output_type": "mean", "radius": 1.5, "window_size": 1, "gdalopts": "COMPRESS=DEFLATE,TILED=YES,BLOCKXSIZE=256,BLOCKYSIZE=256", "data_type": "float32"},
            ])
            log.info("pdal_dem_start", input=str(input_path), file_size_mb=round(input_path.stat().st_size / 1e6, 1), mode="smrf_classify")
        t0 = time.perf_counter()
        proc = subprocess.run(
            ["pdal", "pipeline", "--stdin"],
            input=json.dumps({"pipeline": pipeline}),
            capture_output=True, text=True, timeout=900,
        )
        pdal_elapsed = time.perf_counter() - t0
        if proc.returncode != 0:
            log.error("pdal_dem_failed", exit_code=proc.returncode, elapsed_s=round(pdal_elapsed, 3), stderr=proc.stderr[:500])
            raise RuntimeError(f"PDAL DEM failed: {proc.stderr[:500]}")
        # Ensure DEM has GeoTIFF keys (not just WKT) — WhiteboxTools panics without them.
        # Compound CRS from PDAL (UTM + NAVD88) writes WKT only. Re-encode with horizontal EPSG.
        _ensure_geotiff_keys(dem_path)
        dem_size_mb = round(dem_path.stat().st_size / 1e6, 2) if dem_path.exists() else None
        log.info("pdal_dem_complete", elapsed_s=round(pdal_elapsed, 2), output=str(dem_path), size_mb=dem_size_mb)
        # Log DEM properties
        try:
            import rasterio
            with rasterio.open(dem_path) as src:
                log.info("dem_properties", path=str(dem_path), crs=str(src.crs), width=src.width, height=src.height, resolution=src.res, nodata=src.nodata, dtype=str(src.dtypes[0]), bounds=src.bounds)
        except Exception as e:
            log.warning("dem_properties_read_failed", path=str(dem_path), error=str(e), exception=True)
        if profiler:
            profiler.record("pdal_dem_generation", pdal_elapsed, parent="processing")
    else:
        dem_size_mb = round(dem_path.stat().st_size / 1e6, 2) if dem_path.exists() else None
        log.info("pdal_dem_cached", path=str(dem_path), size_mb=dem_size_mb)

    if not filled_path.exists():
        t0 = time.perf_counter()
        _result, fill_elapsed = fill_depressions(str(dem_path), str(filled_path))
        filled_size_mb = round(filled_path.stat().st_size / 1e6, 2) if filled_path.exists() else None
        log.info("fill_depressions_complete", elapsed_s=round(fill_elapsed, 2), output=str(filled_path), size_mb=filled_size_mb)
        if profiler:
            profiler.record("fill_depressions", fill_elapsed, parent="processing")
    else:
        filled_size_mb = round(filled_path.stat().st_size / 1e6, 2) if filled_path.exists() else None
        log.info("fill_depressions_cached", path=str(filled_path), size_mb=filled_size_mb)
    log.info("generate_dem_pdal_complete", dem=str(dem_path), filled=str(filled_path))
    return dem_path, filled_path


class ProcessingPipeline:
    """Full tile processing — PDAL + GDAL + WhiteboxTools.

    All outputs are written to persistent storage. Once computed,
    derivatives are cached permanently and never recomputed unless
    explicitly requested via force=True.
    """

    def __init__(
        self,
        output_dir: Path,
        resolution: float = 1.0,
        target_srs: str | None = None,
    ):
        self.output_dir = output_dir
        self.resolution = resolution
        self.target_srs = target_srs

    def process_point_cloud(self, input_path: Path, force: bool = False) -> ProcessedTile:
        """Process a LAZ/COPC point cloud through the full pipeline."""
        stem = input_path.stem.replace(".copc", "")
        tile_dir = self.output_dir / stem
        tile_dir.mkdir(parents=True, exist_ok=True)
        deriv_dir = tile_dir / "derivatives"
        input_size_mb = round(input_path.stat().st_size / 1e6, 2) if input_path.exists() else None
        log.info("process_point_cloud_start", input=str(input_path), input_size_mb=input_size_mb, stem=stem, force=force, resolution=self.resolution, target_srs=self.target_srs)
        t0_pipeline = time.perf_counter()
        marker = tile_dir / ".processed"
        if marker.exists() and not force and settings.enable_processing_cache:
            cached = self._load_existing(tile_dir, deriv_dir)
            if cached.dem_path.exists() and len(cached.derivative_paths) >= 8:
                log.info("process_point_cloud_fully_cached", stem=stem, derivatives=len(cached.derivative_paths))
                return cached
            log.warning("stale_cache_reprocessing", tile_dir=str(tile_dir), derivatives=len(cached.derivative_paths))
            marker.unlink(missing_ok=True)
        profiler = new_profiler(f"process_point_cloud:{stem}")
        with profiler.stage("dem_generation", parent="processing", input=str(input_path)):
            dem_path, filled_path = generate_dem_pdal(input_path, tile_dir, self.resolution, self.target_srs)
        with profiler.stage("derivatives_all", parent="processing"):
            derivative_paths = compute_all_derivatives(dem_path, filled_path, deriv_dir, max_workers=settings.derivative_workers)
        marker.write_text(f"processed\nderivatives: {len(derivative_paths)}\n")
        profiler.log_summary()
        pipeline_elapsed = time.perf_counter() - t0_pipeline
        log.info("process_point_cloud_complete", stem=stem, elapsed_s=round(pipeline_elapsed, 3), derivative_count=len(derivative_paths), tile_dir=str(tile_dir))
        return ProcessedTile(
            tile_dir=tile_dir, dem_path=dem_path, filled_dem_path=filled_path,
            derivative_paths=derivative_paths, resolution_m=self.resolution,
            crs=self._read_crs(dem_path),
        )

    def process_dem_file(self, dem_path: Path, force: bool = False) -> ProcessedTile:
        """Process from an existing DEM file (no PDAL needed)."""
        stem = dem_path.stem
        tile_dir = self.output_dir / stem
        tile_dir.mkdir(parents=True, exist_ok=True)
        deriv_dir = tile_dir / "derivatives"
        dem_size_mb = round(dem_path.stat().st_size / 1e6, 2) if dem_path.exists() else None
        log.info("process_dem_file_start", dem=str(dem_path), dem_size_mb=dem_size_mb, stem=stem, force=force, resolution=self.resolution)
        t0_pipeline = time.perf_counter()
        marker = tile_dir / ".processed"
        if marker.exists() and not force and settings.enable_processing_cache:
            cached = self._load_existing(tile_dir, deriv_dir)
            if cached.dem_path.exists() and len(cached.derivative_paths) >= 8:
                log.info("process_dem_file_fully_cached", stem=stem, derivatives=len(cached.derivative_paths))
                return cached
            log.warning("stale_cache_reprocessing", tile_dir=str(tile_dir), derivatives=len(cached.derivative_paths))
            marker.unlink(missing_ok=True)
        profiler = new_profiler(f"process_dem:{stem}")
        filled_path = tile_dir / f"{stem}_filled.tif"
        if not filled_path.exists():
            with profiler.stage("fill_depressions", parent="processing"):
                _result, elapsed = fill_depressions(str(dem_path), str(filled_path))
                log.info("process_dem_fill_complete", elapsed_s=round(elapsed, 3), output=str(filled_path))
        else:
            log.info("process_dem_filled_cached", path=str(filled_path))
        with profiler.stage("derivatives_all", parent="processing"):
            derivative_paths = compute_all_derivatives(dem_path, filled_path, deriv_dir, max_workers=settings.derivative_workers)
        marker.write_text(f"processed\nderivatives: {len(derivative_paths)}\n")
        profiler.log_summary()
        pipeline_elapsed = time.perf_counter() - t0_pipeline
        log.info("process_dem_file_complete", stem=stem, elapsed_s=round(pipeline_elapsed, 3), derivative_count=len(derivative_paths), tile_dir=str(tile_dir))
        return ProcessedTile(
            tile_dir=tile_dir, dem_path=dem_path, filled_dem_path=filled_path,
            derivative_paths=derivative_paths, resolution_m=self.resolution,
            crs=self._read_crs(dem_path),
        )

    @staticmethod
    def _read_crs(dem_path: Path) -> int:
        """Read EPSG code from a DEM file via robust compound CRS resolver."""
        try:
            return resolve_epsg(dem_path)
        except ValueError as e:
            log.error("pipeline_crs_unresolvable", path=str(dem_path), error=str(e))
            raise

    def _load_existing(self, tile_dir: Path, deriv_dir: Path) -> ProcessedTile:
        """Load an already-processed tile from disk."""
        log.debug("load_existing_start", tile_dir=str(tile_dir), deriv_dir=str(deriv_dir))
        dem_files = list(tile_dir.glob("*_dem.tif")) + list(tile_dir.glob("dem_*.tif"))
        dem_path = dem_files[0] if dem_files else tile_dir / "dem.tif"
        filled_files = list(tile_dir.glob("*_filled.tif"))
        filled_path = filled_files[0] if filled_files else None
        derivative_paths = {}
        if deriv_dir.exists():
            for f in deriv_dir.glob("*.tif"):
                derivative_paths[f.stem] = f
        log.info("pipeline_cached", tile_dir=str(tile_dir), derivatives=len(derivative_paths), dem_exists=dem_path.exists() if dem_path else False, filled_exists=filled_path is not None and filled_path.exists() if filled_path else False, derivative_names=list(derivative_paths.keys()))
        return ProcessedTile(
            tile_dir=tile_dir, dem_path=dem_path, filled_dem_path=filled_path,
            derivative_paths=derivative_paths, resolution_m=self.resolution,
            crs=self._read_crs(dem_path) if dem_path.exists() else 32617,
        )
