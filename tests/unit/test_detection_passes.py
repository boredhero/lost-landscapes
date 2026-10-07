"""Tests for all detection passes — uses real GDAL + WhiteboxTools pipeline.

Every test generates a GeoTIFF, runs the native derivative pipeline,
then runs detection passes against the real derivatives.
"""

import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest

from lost_landscapes.detection.base import PassInput
from tests.conftest import PROJECT_ROOT
from tests.fixtures.synthetic_dem import (
    make_flat_geotiff,
    make_pass_input_from_geotiff,
    make_sinkhole_geotiff,
    make_slope_geotiff,
    write_geotiff,
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


def _process_and_load(dem_path: Path, tmpdir: Path):
    """Run native pipeline and return PassInput."""
    from lost_landscapes.processing.pipeline import ProcessingPipeline
    result = ProcessingPipeline(output_dir=tmpdir / "out").process_dem_file(dem_path, force=True)
    return make_pass_input_from_geotiff(dem_path, result.derivative_paths)


# --- FillDifferencePass ---

class TestFillDifferencePass:
    def test_detects_pit(self):
        from lost_landscapes.detection.passes.fill_difference import FillDifferencePass
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_sinkhole_geotiff(d, depth=5.0, radius=15.0), d)
            assert len(FillDifferencePass().run(inp)) >= 1

    def test_no_false_pos_flat(self):
        from lost_landscapes.detection.passes.fill_difference import FillDifferencePass
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_flat_geotiff(d), d)
            assert len(FillDifferencePass().run(inp)) == 0

    def test_no_false_pos_slope(self):
        from lost_landscapes.detection.passes.fill_difference import FillDifferencePass
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_slope_geotiff(d), d)
            assert len(FillDifferencePass().run(inp)) == 0

    def test_rejects_shallow(self):
        from lost_landscapes.detection.passes.fill_difference import FillDifferencePass
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_sinkhole_geotiff(d, depth=0.2), d)
            inp.config = {"min_depth_m": 1.0}
            assert len(FillDifferencePass().run(inp)) == 0

    def test_multiple_depressions(self):
        from lost_landscapes.detection.passes.fill_difference import FillDifferencePass
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            yg = np.arange(400, dtype=np.float32) * 0.01
            dem = np.tile(yg[:, np.newaxis], (1, 400)) + 500.0
            y, x = np.mgrid[0:400, 0:400].astype(np.float32)
            for cy, cx, depth, radius in [(100, 100, 3.0, 12), (300, 300, 4.0, 15)]:
                dist = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
                mask = dist < radius
                dem[mask] = 500.0 - depth * (1 - dist[mask] / radius)
            dem_path = write_geotiff(d / "multi.tif", dem)
            inp = _process_and_load(dem_path, d)
            assert len(FillDifferencePass().run(inp)) >= 2

    def test_respects_max_area(self):
        from lost_landscapes.detection.passes.fill_difference import FillDifferencePass
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_sinkhole_geotiff(d, depth=3.0, radius=50.0), d)
            inp.config = {"max_area_m2": 100.0}
            for c in FillDifferencePass().run(inp):
                assert c.morphometrics["area_m2"] <= 100.0


# --- LocalReliefModelPass ---

class TestLocalReliefModelPass:
    def test_detects_pit(self):
        from lost_landscapes.detection.passes.local_relief_model import LocalReliefModelPass
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_sinkhole_geotiff(d, depth=5.0, radius=15.0), d)
            candidates = LocalReliefModelPass().run(inp)
            assert len(candidates) >= 1

    def test_no_false_pos_flat(self):
        from lost_landscapes.detection.passes.local_relief_model import LocalReliefModelPass
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_flat_geotiff(d), d)
            inp.config = {"threshold_m": 1.0}  # high threshold for flat terrain
            assert len(LocalReliefModelPass().run(inp)) == 0

    def test_feature_type_is_cave(self):
        from lost_landscapes.detection.base import FeatureType
        from lost_landscapes.detection.passes.local_relief_model import LocalReliefModelPass
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_sinkhole_geotiff(d, depth=5.0, radius=15.0), d)
            candidates = LocalReliefModelPass().run(inp)
            if candidates:
                assert candidates[0].feature_type == FeatureType.CAVE_ENTRANCE


# --- CurvaturePass ---

class TestCurvaturePass:
    def test_detects_depression(self):
        from lost_landscapes.detection.passes.curvature import CurvaturePass
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_sinkhole_geotiff(d, depth=5.0, radius=15.0), d)
            inp.config = {"threshold": -0.001}
            assert len(CurvaturePass().run(inp)) >= 1

    def test_no_false_pos_flat(self):
        from lost_landscapes.detection.passes.curvature import CurvaturePass
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_flat_geotiff(d), d)
            assert len(CurvaturePass().run(inp)) == 0


# --- SkyViewFactorPass ---

class TestSkyViewFactorPass:
    def test_detects_pit(self):
        from lost_landscapes.detection.passes.sky_view_factor import SkyViewFactorPass
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_sinkhole_geotiff(d, depth=8.0, radius=15.0, size=100), d)
            # WBT output range varies by version: 0-1 (true SVF) or 0-65535 (hillshade proxy)
            svf = inp.derivatives.get("svf")
            if svf is not None and svf.max() > 10:
                inp.config = {"threshold": svf.max() * 0.8}  # 80% of max
            else:
                inp.config = {"threshold": 0.9}
            assert len(SkyViewFactorPass().run(inp)) >= 1

    def test_no_false_pos_flat(self):
        from lost_landscapes.detection.passes.sky_view_factor import SkyViewFactorPass
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_flat_geotiff(d, size=100), d)
            assert len(SkyViewFactorPass().run(inp)) == 0


# --- TPIPass ---

class TestTPIPass:
    def test_detects_depression(self):
        from lost_landscapes.detection.passes.tpi import TPIPass
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_sinkhole_geotiff(d, depth=5.0, radius=15.0), d)
            inp.config = {"threshold": -0.05, "min_area_pixels": 1}
            assert len(TPIPass().run(inp)) >= 1

    def test_no_false_pos_flat(self):
        from lost_landscapes.detection.passes.tpi import TPIPass
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_flat_geotiff(d), d)
            assert len(TPIPass().run(inp)) == 0


# --- MorphometricFilterPass ---

class TestMorphometricFilterPass:
    def test_computes_morphometrics(self):
        from lost_landscapes.detection.passes.morphometric_filter import MorphometricFilterPass
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_sinkhole_geotiff(d, depth=5.0, radius=20.0), d)
            inp.config = {"min_depth_m": 0.3, "min_area_m2": 5.0, "min_circularity": 0.1}
            candidates = MorphometricFilterPass().run(inp)
            assert len(candidates) >= 1
            m = candidates[0].morphometrics
            assert "depth_m" in m
            assert "area_m2" in m
            assert "circularity" in m
            assert "volume_m3" in m
            assert "k_parameter" in m
            assert "elongation" in m
            assert "wall_slope_deg" in m

    def test_no_false_pos_flat(self):
        from lost_landscapes.detection.passes.morphometric_filter import MorphometricFilterPass
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_flat_geotiff(d), d)
            assert len(MorphometricFilterPass().run(inp)) == 0

    def test_classifies_feature_type(self):
        from lost_landscapes.detection.base import FeatureType
        from lost_landscapes.detection.passes.morphometric_filter import MorphometricFilterPass
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_sinkhole_geotiff(d, depth=5.0, radius=20.0), d)
            inp.config = {"min_depth_m": 0.3, "min_area_m2": 5.0, "min_circularity": 0.1}
            candidates = MorphometricFilterPass().run(inp)
            if candidates:
                assert candidates[0].feature_type != FeatureType.UNKNOWN


# --- PointDensityPass ---

class TestPointDensityPass:
    def test_empty_without_point_cloud(self):
        from lost_landscapes.detection.passes.point_density import PointDensityPass
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_flat_geotiff(d), d)
            assert len(PointDensityPass().run(inp)) == 0

    def test_detects_void(self):
        from lost_landscapes.detection.passes.point_density import PointDensityPass
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_flat_geotiff(d, size=100), d)
            rng = np.random.default_rng(42)
            n = 5000
            x, y, z = rng.uniform(0, 100, n), rng.uniform(0, 100, n), rng.uniform(0, 10, n)
            void = (x > 40) & (x < 60) & (y > 40) & (y < 60)
            inp.point_cloud = {"X": x[~void], "Y": y[~void], "Z": z[~void]}
            inp.config = {"cell_size_m": 5.0, "z_score_threshold": -1.5}
            assert len(PointDensityPass().run(inp)) >= 1


# --- MultiReturnPass ---

class TestMultiReturnPass:
    def test_empty_without_point_cloud(self):
        from lost_landscapes.detection.passes.multi_return import MultiReturnPass
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_flat_geotiff(d), d)
            assert len(MultiReturnPass().run(inp)) == 0

    def test_detects_anomalous_returns(self):
        from lost_landscapes.detection.passes.multi_return import MultiReturnPass
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_flat_geotiff(d, size=100), d)
            rng = np.random.default_rng(42)
            n = 5000
            x, y = rng.uniform(0, 100, n), rng.uniform(0, 100, n)
            rn, nr = np.ones(n, dtype=np.int32), np.ones(n, dtype=np.int32)
            cluster = (x > 40) & (x < 60) & (y > 40) & (y < 60)
            nr[cluster] = 4
            inp.point_cloud = {"X": x, "Y": y, "ReturnNumber": rn, "NumberOfReturns": nr}
            inp.config = {"search_radius_m": 10.0, "min_multi_return_ratio": 0.3}
            assert len(MultiReturnPass().run(inp)) >= 1


# --- PassRunner with TOML configs ---

class TestPassRunnerToml:
    def test_load_cave_config(self):
        from lost_landscapes.detection.runner import PassRunner
        runner = PassRunner.from_toml(PROJECT_ROOT / "configs/passes/cave_hunting.toml")
        assert len(runner.passes) >= 4

    def test_load_sinkhole_config(self):
        from lost_landscapes.detection.runner import PassRunner
        runner = PassRunner.from_toml(PROJECT_ROOT / "configs/passes/sinkhole_survey.toml")
        assert len(runner.passes) >= 4

    def test_cave_config_detects_pit(self):
        from lost_landscapes.detection.runner import PassRunner
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_sinkhole_geotiff(d, depth=5.0, radius=15.0), d)
            runner = PassRunner.from_toml(PROJECT_ROOT / "configs/passes/cave_hunting.toml")
            assert len(runner.run_on_array(inp.dem, inp.transform, inp.crs, inp.derivatives)) >= 1

    def test_sinkhole_config_detects_pit(self):
        from lost_landscapes.detection.runner import PassRunner
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_sinkhole_geotiff(d, depth=5.0, radius=15.0), d)
            runner = PassRunner.from_toml(PROJECT_ROOT / "configs/passes/sinkhole_survey.toml")
            assert len(runner.run_on_array(inp.dem, inp.transform, inp.crs, inp.derivatives)) >= 1

    def test_no_false_pos_flat(self):
        from lost_landscapes.detection.runner import PassRunner
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            inp = _process_and_load(make_flat_geotiff(d), d)
            runner = PassRunner.from_toml(PROJECT_ROOT / "configs/passes/sinkhole_survey.toml")
            runner.fuser.min_confidence = 0.5  # higher threshold for near-flat terrain
            assert len(runner.run_on_array(inp.dem, inp.transform, inp.crs, inp.derivatives)) == 0


class TestSVFNormalization:
    """Regression tests for SVF pass — WBT outputs raw integers, not 0-1 fractions."""

    def test_svf_pass_normalizes_raw_integer_output(self):
        """SVF values in 0-32000 range must be normalized to 0-1 before thresholding."""
        from rasterio.transform import from_bounds

        from lost_landscapes.detection.passes.sky_view_factor import SkyViewFactorPass
        # Create a 50x50 SVF raster with raw integer values (simulating WBT output)
        # Most pixels at ~25000 (open sky), a 10x10 bowl at ~15000 (enclosed)
        svf = np.full((50, 50), 25000.0, dtype=np.float32)
        svf[20:30, 20:30] = 15000.0  # enclosed region: 15000/25000 = 0.6 normalized, below 0.75 threshold
        dem = np.full((50, 50), 300.0, dtype=np.float32)
        transform = from_bounds(0, 0, 50, 50, 50, 50)
        inp = PassInput(dem=dem, transform=transform, crs=32617, derivatives={"svf": svf})
        p = SkyViewFactorPass()
        candidates = p.run(inp)
        # Without normalization, svf < 0.75 matches zero pixels (all > 10000)
        # With normalization, the bowl at 0.6 should be detected
        assert len(candidates) > 0, "SVF pass should detect enclosed region in raw integer data"
        assert candidates[0].morphometrics["area_m2"] > 50

    def test_svf_pass_already_normalized_input(self):
        """SVF values already in 0-1 range should work without double-normalization."""
        from rasterio.transform import from_bounds

        from lost_landscapes.detection.passes.sky_view_factor import SkyViewFactorPass
        svf = np.full((50, 50), 0.95, dtype=np.float32)
        svf[20:30, 20:30] = 0.5  # enclosed region below 0.75 threshold
        dem = np.full((50, 50), 300.0, dtype=np.float32)
        transform = from_bounds(0, 0, 50, 50, 50, 50)
        inp = PassInput(dem=dem, transform=transform, crs=32617, derivatives={"svf": svf})
        p = SkyViewFactorPass()
        candidates = p.run(inp)
        assert len(candidates) > 0, "SVF pass should detect enclosed region in 0-1 data"

    def test_svf_high_values_not_detected(self):
        """Uniformly high SVF (open terrain) should produce zero detections."""
        from rasterio.transform import from_bounds

        from lost_landscapes.detection.passes.sky_view_factor import SkyViewFactorPass
        svf = np.full((50, 50), 24000.0, dtype=np.float32)  # uniformly open sky
        dem = np.full((50, 50), 300.0, dtype=np.float32)
        transform = from_bounds(0, 0, 50, 50, 50, 50)
        inp = PassInput(dem=dem, transform=transform, crs=32617, derivatives={"svf": svf})
        p = SkyViewFactorPass()
        candidates = p.run(inp)
        assert len(candidates) == 0, "Uniformly high SVF should not detect anything"


class TestOutlineExtraction:
    """Standalone tests for outline vectorization — no GDAL/WBT required."""

    def test_rasterio_shapes_produces_valid_polygons(self):
        """rasterio.features.shapes correctly vectorizes labeled regions into Shapely Polygons."""
        from rasterio.features import shapes as rasterio_shapes
        from rasterio.transform import from_bounds
        from shapely.geometry import shape as shapely_shape

        # Simulate a labeled array with two depression regions
        labeled = np.zeros((100, 100), dtype=np.int32)
        labeled[20:40, 20:40] = 1  # square region
        labeled[60:80, 50:90] = 2  # rectangular region

        transform = from_bounds(-79.80, 40.40, -79.70, 40.50, 100, 100)

        outlines = {}
        for geom_dict, value in rasterio_shapes(labeled, mask=(labeled > 0), transform=transform):
            outlines[int(value)] = shapely_shape(geom_dict)

        assert len(outlines) == 2
        assert outlines[1].geom_type == "Polygon"
        assert outlines[2].geom_type == "Polygon"

        # Square region should be roughly square
        bounds1 = outlines[1].bounds
        width1 = bounds1[2] - bounds1[0]
        height1 = bounds1[3] - bounds1[1]
        assert abs(width1 - height1) < 0.005  # approximately square

        # Rectangular region should be wider than tall
        bounds2 = outlines[2].bounds
        width2 = bounds2[2] - bounds2[0]
        height2 = bounds2[3] - bounds2[1]
        assert width2 > height2

        # Both should have valid area
        assert outlines[1].area > 0
        assert outlines[2].area > 0

    def test_outline_crs_transform_utm_to_wgs84(self):
        """Outline polygons correctly transform from UTM to WGS84 coordinates."""
        from pyproj import Transformer
        from shapely.geometry import Polygon
        from shapely.ops import transform as shapely_transform

        # A 100m x 100m square in UTM zone 17N (typical for western PA)
        poly_utm = Polygon([
            (580000, 4475000),
            (580100, 4475000),
            (580100, 4475100),
            (580000, 4475100),
        ])

        transformer = Transformer.from_crs("EPSG:32617", "EPSG:4326", always_xy=True)
        poly_wgs = shapely_transform(lambda x, y: transformer.transform(x, y), poly_utm)

        assert poly_wgs.geom_type == "Polygon"
        assert poly_wgs.is_valid

        # Should be in WGS84 range (western PA is around -80, 40)
        bounds = poly_wgs.bounds
        assert -81 < bounds[0] < -79  # lon
        assert 40 < bounds[1] < 41    # lat
        assert -81 < bounds[2] < -79
        assert 40 < bounds[3] < 41

        # Area should be tiny in degrees (100m square ≈ 0.000001 deg²)
        assert poly_wgs.area < 0.0001
        assert poly_wgs.area > 0
