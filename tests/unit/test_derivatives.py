"""Tests for terrain derivatives — uses real GDAL + WhiteboxTools.

Every test writes a GeoTIFF, runs the native pipeline, reads the result.
Skipped if GDAL/WBT not available. Runs on .111 and in Docker.
"""

import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest
import rasterio

from tests.fixtures.synthetic_dem import (
    make_flat_geotiff,
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


def _run_pipeline(dem_path: Path, tmpdir: Path) -> dict[str, Path]:
    from lost_landscapes.processing.pipeline import ProcessingPipeline
    result = ProcessingPipeline(output_dir=tmpdir / "out").process_dem_file(dem_path, force=True)
    return result.derivative_paths


def _read(path: Path) -> np.ndarray:
    with rasterio.open(path) as src:
        return src.read(1)


# --- Hillshade ---

class TestHillshade:
    def test_flat_terrain_uniform(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            derivs = _run_pipeline(make_flat_geotiff(d), d)
            hs = _read(derivs["hillshade"])
            assert np.std(hs[hs > 0]) < 5.0

    def test_output_range(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            derivs = _run_pipeline(make_sinkhole_geotiff(d), d)
            hs = _read(derivs["hillshade"])
            assert hs.min() >= 0
            assert hs.max() <= 255

    def test_shape_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            derivs = _run_pipeline(make_flat_geotiff(d, size=80), d)
            assert _read(derivs["hillshade"]).shape == (80, 80)


# --- Slope ---

class TestSlope:
    def test_flat_zero_slope(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            derivs = _run_pipeline(make_flat_geotiff(d), d)
            slope = _read(derivs["slope"])
            assert np.mean(slope) < 1.0

    def test_sloped_terrain_nonzero(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            derivs = _run_pipeline(make_slope_geotiff(d, slope_deg=15.0), d)
            slope = _read(derivs["slope"])
            assert np.mean(slope[10:-10, 10:-10]) > 5.0


# --- Curvature ---

class TestCurvature:
    def test_flat_near_zero(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            derivs = _run_pipeline(make_flat_geotiff(d), d)
            curv = _read(derivs["profile_curvature"])
            assert np.mean(np.abs(curv)) < 0.01

    def test_pit_has_curvature(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            derivs = _run_pipeline(make_sinkhole_geotiff(d, depth=5.0, radius=15.0), d)
            curv = _read(derivs["profile_curvature"])
            assert np.max(np.abs(curv)) > 0.001

    def test_plan_curvature_exists(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            derivs = _run_pipeline(make_sinkhole_geotiff(d), d)
            assert "plan_curvature" in derivs
            assert _read(derivs["plan_curvature"]).shape[0] > 0


# --- TPI ---

class TestTPI:
    def test_flat_near_zero(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            derivs = _run_pipeline(make_flat_geotiff(d), d)
            tpi = _read(derivs["tpi"])
            # GDAL TPI outputs nodata (-9999) on edges, mask those
            valid = tpi[(tpi > -9000) & (tpi < 9000)]
            assert np.mean(np.abs(valid)) < 0.1

    def test_pit_negative_tpi(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            derivs = _run_pipeline(make_sinkhole_geotiff(d, depth=5.0, radius=15.0), d)
            tpi = _read(derivs["tpi"])
            assert tpi.min() < -0.5

    def test_mound_positive_tpi(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            dem = np.full((200, 200), 500.0, dtype=np.float32)
            y, x = np.mgrid[0:200, 0:200].astype(np.float32)
            dist = np.sqrt((x - 100) ** 2 + (y - 100) ** 2)
            dem[dist < 15] = 505.0
            dem_path = write_geotiff(d / "mound.tif", dem)
            derivs = _run_pipeline(dem_path, d)
            tpi = _read(derivs["tpi"])
            assert tpi.max() > 0.5


# --- SVF ---

class TestSVF:
    def test_flat_high_svf(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            derivs = _run_pipeline(make_flat_geotiff(d, size=100), d)
            svf = _read(derivs["svf"])
            assert np.mean(svf[20:-20, 20:-20]) > 0.8

    def test_pit_lower_svf(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            derivs = _run_pipeline(make_sinkhole_geotiff(d, depth=8.0, radius=15.0, size=100), d)
            svf = _read(derivs["svf"])
            center = svf[40:60, 40:60].mean()
            edge = svf[5:15, 5:15].mean()
            assert center < edge

    def test_output_range(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            derivs = _run_pipeline(make_sinkhole_geotiff(d, size=100), d)
            svf = _read(derivs["svf"])
            assert svf.min() >= 0
            # WBT output range depends on version/method (0-1 for true SVF, 0-65535 for hillshade proxy)
            assert svf.max() > 0


# --- LRM ---

class TestLRM:
    def test_flat_near_zero(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            derivs = _run_pipeline(make_flat_geotiff(d), d)
            lrm = _read(derivs["lrm_100m"])
            assert np.mean(np.abs(lrm)) < 1.0

    def test_pit_negative_lrm(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            derivs = _run_pipeline(make_sinkhole_geotiff(d, depth=5.0, radius=15.0), d)
            lrm = _read(derivs["lrm_50m"])
            assert lrm.min() < -1.0

    def test_multiscale(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            derivs = _run_pipeline(make_sinkhole_geotiff(d), d)
            assert "lrm_50m" in derivs
            assert "lrm_100m" in derivs
            assert "lrm_200m" in derivs


# --- Fill-Difference ---

class TestFillDifference:
    def test_flat_zero(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            derivs = _run_pipeline(make_flat_geotiff(d), d)
            fd = _read(derivs["fill_difference"])
            assert fd.max() < 0.01

    def test_pit_positive(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            derivs = _run_pipeline(make_sinkhole_geotiff(d, depth=5.0), d)
            fd = _read(derivs["fill_difference"])
            assert fd.max() > 1.0

    def test_slope_zero(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            derivs = _run_pipeline(make_slope_geotiff(d), d)
            fd = _read(derivs["fill_difference"])
            assert fd.max() < 0.5


# --- Fill Depressions Fallback ---

class TestFillDepressionsFallback:
    """Test that fill_depressions falls back to skimage when WBT fails."""

    def test_skimage_fallback_produces_valid_output(self):
        """When all WBT methods fail, skimage reconstruction should produce a filled DEM."""
        from unittest.mock import MagicMock, patch
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            dem_path = make_sinkhole_geotiff(d, depth=5.0, radius=12.0, size=100)
            out_path = d / "filled.tif"
            # Simulate native methods failing to create their output.
            mock_wbt = MagicMock()
            mock_wbt.fill_depressions.return_value = 0  # Native tool can report success without output.
            mock_wbt.breach_depressions_least_cost.return_value = 1
            mock_wbt.fill_depressions_planchon_and_darboux.return_value = 1
            with patch("lost_landscapes.processing.derivatives._get_wbt", return_value=mock_wbt):
                from lost_landscapes.processing.derivatives import fill_depressions
                result_path, elapsed = fill_depressions(str(dem_path), str(out_path))
            mock_wbt.breach_depressions_least_cost.assert_not_called()
            mock_wbt.fill_depressions_planchon_and_darboux.assert_called_once()
            assert Path(result_path).exists(), "Fallback should produce output file"
            # Verify the filled DEM has higher or equal values everywhere (depressions filled up)
            import rasterio
            with rasterio.open(dem_path) as src:
                original = src.read(1)
            with rasterio.open(result_path) as src:
                filled = src.read(1)
            # Filled DEM values should be >= original (depressions raised, not lowered)
            diff = filled - original
            assert diff.min() >= -0.01, f"Filled DEM has values BELOW original by {diff.min():.3f}m — not a valid depression fill"
            # The sinkhole center should have been raised
            center = original.shape[0] // 2
            assert filled[center, center] > original[center, center], "Sinkhole center should be raised by fill"


# --- All Derivatives ---

class TestAllDerivatives:
    def test_all_returned(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            derivs = _run_pipeline(make_sinkhole_geotiff(d, size=100), d)
            expected = ["hillshade", "slope", "tpi", "svf", "fill_difference",
                        "lrm_50m", "lrm_100m", "lrm_200m", "profile_curvature", "plan_curvature"]
            for name in expected:
                assert name in derivs, f"Missing derivative: {name}"
                assert derivs[name].exists(), f"{name} file doesn't exist"
