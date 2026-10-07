"""Tests for ML detection passes and training pipeline.

Feature extraction tests use the native GDAL/WBT pipeline.
ML model tests (RF training, U-Net arch, YOLO) work without GDAL.
"""

import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest
from rasterio.transform import from_bounds

from lost_landscapes.detection.base import PassInput
from lost_landscapes.detection.passes.random_forest import (
    FEATURE_NAMES,
    RandomForestPass,
    extract_features,
)
from lost_landscapes.detection.passes.unet_segmentation import (
    UNetSegmentationPass,
    _prepare_input_tensor,
)
from lost_landscapes.detection.passes.yolo_detector import YOLODetectorPass
from lost_landscapes.detection.registry import PassRegistry
from lost_landscapes.ml.training import (
    extract_rf_training_data,
    extract_unet_patches,
    train_random_forest,
)

NATIVE_AVAILABLE = shutil.which("gdaldem") is not None


# --- Helpers ---

def _make_test_dem(size=100):
    dem = np.full((size, size), 500.0, dtype=np.float32)
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    dist = np.sqrt((x - size / 2) ** 2 + (y - size / 2) ** 2)
    dem[dist < 12] = 500.0 - 5.0 * (1 - dist[dist < 12] / 12.0)
    return dem


def _make_test_mask(size=100):
    mask = np.zeros((size, size), dtype=bool)
    y, x = np.mgrid[0:size, 0:size]
    mask[np.sqrt((x - 50) ** 2 + (y - 50) ** 2) < 12] = True
    return mask


def _get_native_derivatives(dem_path: Path, tmpdir: Path) -> dict[str, np.ndarray]:
    """Run native pipeline and return derivative arrays."""
    from lost_landscapes.processing.pipeline import ProcessingPipeline
    from tests.fixtures.synthetic_dem import make_pass_input_from_geotiff
    result = ProcessingPipeline(output_dir=tmpdir / "out").process_dem_file(dem_path, force=True)
    inp = make_pass_input_from_geotiff(dem_path, result.derivative_paths)
    return inp.derivatives


# --- Registry ---

class TestMLPassesRegistered:
    def test_all_11_passes_registered(self):
        passes = PassRegistry.list_passes()
        assert "random_forest" in passes
        assert "unet_segmentation" in passes
        assert "yolo_detector" in passes
        assert len(passes) == 11


# --- Feature Extraction (requires GDAL+WBT for derivatives) ---

@pytest.mark.skipif(not NATIVE_AVAILABLE, reason="Requires GDAL + WhiteboxTools")
class TestFeatureExtraction:
    def test_extract_10_features(self):
        from lost_landscapes.processing.pipeline import ProcessingPipeline
        from tests.fixtures.synthetic_dem import make_pass_input_from_geotiff, make_sinkhole_geotiff
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            dem_path = make_sinkhole_geotiff(d)
            result = ProcessingPipeline(output_dir=d / "out").process_dem_file(dem_path, force=True)
            inp = make_pass_input_from_geotiff(dem_path, result.derivative_paths)
            mask = _make_test_mask(size=200)
            features = extract_features(inp.dem, mask, inp.derivatives["slope"], inp.derivatives["tpi"], inp.derivatives["svf"], 1.0)
            assert features.shape == (10,)
            assert len(FEATURE_NAMES) == 10

    def test_features_are_finite(self):
        from lost_landscapes.processing.pipeline import ProcessingPipeline
        from tests.fixtures.synthetic_dem import make_pass_input_from_geotiff, make_sinkhole_geotiff
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            dem_path = make_sinkhole_geotiff(d)
            result = ProcessingPipeline(output_dir=d / "out").process_dem_file(dem_path, force=True)
            inp = make_pass_input_from_geotiff(dem_path, result.derivative_paths)
            mask = _make_test_mask(size=200)
            features = extract_features(inp.dem, mask, inp.derivatives["slope"], inp.derivatives["tpi"], inp.derivatives["svf"], 1.0)
            assert np.all(np.isfinite(features))

    def test_depth_feature_positive(self):
        from lost_landscapes.processing.pipeline import ProcessingPipeline
        from tests.fixtures.synthetic_dem import make_pass_input_from_geotiff, make_sinkhole_geotiff
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            dem_path = make_sinkhole_geotiff(d)
            result = ProcessingPipeline(output_dir=d / "out").process_dem_file(dem_path, force=True)
            inp = make_pass_input_from_geotiff(dem_path, result.derivative_paths)
            mask = _make_test_mask(size=200)
            features = extract_features(inp.dem, mask, inp.derivatives["slope"], inp.derivatives["tpi"], inp.derivatives["svf"], 1.0)
            assert features[0] > 0


# --- Random Forest Pass ---

class TestRandomForestPass:
    def test_returns_empty_without_model(self):
        dem = _make_test_dem()
        transform = from_bounds(0, 0, 100, 100, 100, 100)
        inp = PassInput(dem=dem, transform=transform, crs=32617, derivatives={})
        assert len(RandomForestPass().run(inp)) == 0

    @pytest.mark.skipif(not NATIVE_AVAILABLE, reason="Requires GDAL + WhiteboxTools")
    def test_works_with_trained_model(self):
        from lost_landscapes.processing.pipeline import ProcessingPipeline
        from tests.fixtures.synthetic_dem import make_pass_input_from_geotiff, make_sinkhole_geotiff
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            dem_path = make_sinkhole_geotiff(d)
            result = ProcessingPipeline(output_dir=d / "out").process_dem_file(dem_path, force=True)
            inp = make_pass_input_from_geotiff(dem_path, result.derivative_paths)

            X, y = extract_rf_training_data(inp.dem, 1.0, [_make_test_mask(size=200)], inp.derivatives, n_negatives=20)
            assert X.shape[0] > 0

            model_path = d / "model.joblib"
            metrics = train_random_forest(X, y, model_path)
            assert model_path.exists()
            assert metrics["n_samples"] > 0


# --- Training Pipeline ---

@pytest.mark.skipif(not NATIVE_AVAILABLE, reason="Requires GDAL + WhiteboxTools")
class TestTrainingPipeline:
    def test_rf_training_data_extraction(self):
        from lost_landscapes.processing.pipeline import ProcessingPipeline
        from tests.fixtures.synthetic_dem import make_pass_input_from_geotiff, make_sinkhole_geotiff
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            dem_path = make_sinkhole_geotiff(d)
            result = ProcessingPipeline(output_dir=d / "out").process_dem_file(dem_path, force=True)
            inp = make_pass_input_from_geotiff(dem_path, result.derivative_paths)
            X, y = extract_rf_training_data(inp.dem, 1.0, [_make_test_mask(size=200)], inp.derivatives, n_negatives=10)
            assert X.ndim == 2
            assert X.shape[1] == 10
            assert np.sum(y == 1) >= 1
            assert np.sum(y == 0) >= 1

    def test_rf_training_produces_model(self):
        from lost_landscapes.processing.pipeline import ProcessingPipeline
        from tests.fixtures.synthetic_dem import make_pass_input_from_geotiff, make_sinkhole_geotiff
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            dem_path = make_sinkhole_geotiff(d)
            result = ProcessingPipeline(output_dir=d / "out").process_dem_file(dem_path, force=True)
            inp = make_pass_input_from_geotiff(dem_path, result.derivative_paths)
            X, y = extract_rf_training_data(inp.dem, 1.0, [_make_test_mask(size=200)], inp.derivatives, n_negatives=15)
            model_path = d / "model.joblib"
            metrics = train_random_forest(X, y, model_path, n_estimators=10)
            assert model_path.exists()
            assert "feature_importances" in metrics
            assert len(metrics["feature_importances"]) == 10

    def test_unet_patch_extraction(self):
        from lost_landscapes.processing.pipeline import ProcessingPipeline
        from tests.fixtures.synthetic_dem import make_pass_input_from_geotiff, make_sinkhole_geotiff
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            dem_path = make_sinkhole_geotiff(d, size=300)
            result = ProcessingPipeline(output_dir=d / "out").process_dem_file(dem_path, force=True)
            inp = make_pass_input_from_geotiff(dem_path, result.derivative_paths)
            patches_in, patches_out = extract_unet_patches(
                inp.dem, inp.derivatives, positive_centers=[(150, 150)], patch_size=128, n_negatives=2,
            )
            assert patches_in.shape[0] == 3
            assert patches_in.shape[1] == 5
            assert patches_in.shape[2] == 128


# --- U-Net Architecture ---

class TestUNetArchitecture:
    def test_input_tensor_preparation(self):
        dem = np.random.rand(64, 64).astype(np.float32) * 100
        # With no derivatives, should return zeros
        channels = _prepare_input_tensor(dem, {}, 1.0)
        assert channels.shape == (5, 64, 64)
        assert channels.dtype == np.float32

    def test_unet_model_builds(self):
        try:
            import torch

            from lost_landscapes.detection.passes.unet_segmentation import _build_unet
            UNet = _build_unet()
            model = UNet(in_channels=5, out_channels=1)
            x = torch.randn(1, 5, 256, 256)
            with torch.no_grad():
                out = model(x)
            assert out.shape == (1, 1, 256, 256)
            assert out.min() >= 0
            assert out.max() <= 1
        except ImportError:
            pytest.skip("PyTorch not installed")

    def test_unet_pass_returns_empty_without_model(self):
        dem = np.random.rand(64, 64).astype(np.float32) * 100
        transform = from_bounds(0, 0, 64, 64, 64, 64)
        inp = PassInput(dem=dem, transform=transform, crs=32617, derivatives={})
        assert len(UNetSegmentationPass().run(inp)) == 0


# --- YOLO ---

class TestYOLODetectorPass:
    def test_returns_empty_without_model(self):
        dem = np.random.rand(100, 100).astype(np.float32) * 100
        transform = from_bounds(0, 0, 100, 100, 100, 100)
        inp = PassInput(dem=dem, transform=transform, crs=32617, derivatives={})
        assert len(YOLODetectorPass().run(inp)) == 0

    def test_requires_gpu_flag(self):
        assert YOLODetectorPass().requires_gpu is True
        assert YOLODetectorPass().name == "yolo_detector"
