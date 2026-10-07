"""Tests for the processing pipeline — uses real GDAL/WhiteboxTools.

Requires: gdal-bin, whitebox. Skipped if not available.
"""

import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
import rasterio
from shapely.geometry import box

from tests.conftest import PROJECT_ROOT
from tests.fixtures.synthetic_dem import (
    make_flat_geotiff,
    make_pass_input_from_geotiff,
    make_sinkhole_geotiff,
)

GDAL_AVAILABLE = shutil.which("gdaldem") is not None
WBT_AVAILABLE = True
try:
    import whitebox  # noqa: F401 — availability check
except Exception:
    WBT_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not GDAL_AVAILABLE or not WBT_AVAILABLE,
    reason="Requires GDAL + WhiteboxTools",
)


class TestNativePipeline:
    def test_process_dem_produces_derivatives(self):
        from lost_landscapes.processing.pipeline import ProcessingPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            dem_path = make_sinkhole_geotiff(tmpdir, depth=5.0)
            result = ProcessingPipeline(output_dir=tmpdir / "out").process_dem_file(dem_path, force=True)
            assert len(result.derivative_paths) >= 8

    def test_fill_difference_detects_pit(self):
        from lost_landscapes.processing.pipeline import ProcessingPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            dem_path = make_sinkhole_geotiff(tmpdir, depth=5.0, radius=15.0)
            result = ProcessingPipeline(output_dir=tmpdir / "out").process_dem_file(dem_path, force=True)
            with rasterio.open(result.derivative_paths["fill_difference"]) as src:
                fd = src.read(1)
            assert fd.max() > 1.0

    def test_cached_not_recomputed(self):
        from lost_landscapes.processing.pipeline import ProcessingPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            dem_path = make_sinkhole_geotiff(tmpdir)
            pipeline = ProcessingPipeline(output_dir=tmpdir / "out")
            r1 = pipeline.process_dem_file(dem_path, force=True)
            r2 = pipeline.process_dem_file(dem_path, force=False)
            assert len(r1.derivative_paths) == len(r2.derivative_paths)


class TestDetectionOnNativeDerivatives:
    def test_fill_difference_pass(self):
        from lost_landscapes.detection.passes.fill_difference import FillDifferencePass
        from lost_landscapes.processing.pipeline import ProcessingPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            dem_path = make_sinkhole_geotiff(tmpdir, depth=5.0, radius=15.0)
            result = ProcessingPipeline(output_dir=tmpdir / "out").process_dem_file(dem_path, force=True)
            inp = make_pass_input_from_geotiff(dem_path, result.derivative_paths)
            assert len(FillDifferencePass().run(inp)) >= 1

    def test_full_config_detects(self):
        from lost_landscapes.detection.runner import PassRunner
        from lost_landscapes.processing.pipeline import ProcessingPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            dem_path = make_sinkhole_geotiff(tmpdir, depth=5.0, radius=15.0)
            result = ProcessingPipeline(output_dir=tmpdir / "out").process_dem_file(dem_path, force=True)
            runner = PassRunner.from_toml(PROJECT_ROOT / "configs/passes/cave_hunting.toml")
            inp = make_pass_input_from_geotiff(dem_path, result.derivative_paths)
            assert len(runner.run_on_array(inp.dem, inp.transform, inp.crs, inp.derivatives)) >= 1

    def test_flat_no_detections(self):
        from lost_landscapes.detection.runner import PassRunner
        from lost_landscapes.processing.pipeline import ProcessingPipeline

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            dem_path = make_flat_geotiff(tmpdir)
            result = ProcessingPipeline(output_dir=tmpdir / "out").process_dem_file(dem_path, force=True)
            runner = PassRunner.from_toml(PROJECT_ROOT / "configs/passes/sinkhole_survey.toml")
            inp = make_pass_input_from_geotiff(dem_path, result.derivative_paths)
            assert len(runner.run_on_array(inp.dem, inp.transform, inp.crs, inp.derivatives)) == 0


class TestTileManager:
    def test_add_and_query(self):
        from lost_landscapes.processing.tile_manager import ManagedTile, TileManager
        tm = TileManager()
        tm.add_tile(ManagedTile(tile_id=uuid4(), bbox=box(-79.8, 39.7, -79.7, 39.8)))
        assert len(tm.query_bbox(-80.0, 39.5, -79.5, 40.0)) == 1

    def test_no_results_outside(self):
        from lost_landscapes.processing.tile_manager import ManagedTile, TileManager
        tm = TileManager()
        tm.add_tile(ManagedTile(tile_id=uuid4(), bbox=box(-79.8, 39.7, -79.7, 39.8)))
        assert len(tm.query_bbox(-75.0, 40.0, -74.0, 41.0)) == 0


class TestPointCloud:
    def test_density_void(self):
        from lost_landscapes.processing.point_cloud import compute_point_density
        rng = np.random.default_rng(42)
        n = 10000
        x, y, z = rng.uniform(0, 100, n), rng.uniform(0, 100, n), rng.uniform(0, 10, n)
        void = (x > 45) & (x < 55) & (y > 45) & (y < 55)
        density, _, _ = compute_point_density(x[~void], y[~void], z[~void], cell_size=5.0)
        assert density.min() < density.mean() * 0.3

    def test_multi_return_ratio(self):
        from lost_landscapes.processing.point_cloud import compute_multi_return_ratio
        n = 1000
        x, y = np.random.uniform(0, 100, n), np.random.uniform(0, 100, n)
        ratio, _ = compute_multi_return_ratio(x, y, np.ones(n, dtype=np.int32), np.full(n, 3, dtype=np.int32), cell_size=10.0)
        assert np.mean(ratio[ratio > 0]) > 0.9
