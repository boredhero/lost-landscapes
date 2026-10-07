"""Regression coverage for terrain accuracy, missing data, and native reprojection."""

import io

import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.transform import from_bounds

from lost_landscapes.api.routes import landscape as terrain


def test_terrarium_round_trip_keeps_negative_and_fractional_heights():
    source = np.array([[-100.375, 0, 245.123], [1024, 4567.5, -12.999]], dtype=np.float32)
    result = terrain.decode_terrarium(terrain.encode_terrarium(source))
    np.testing.assert_allclose(result, source, atol=1 / 256)


def test_missing_elevations_cannot_be_encoded_as_sea_level():
    with pytest.raises(ValueError):
        terrain.encode_terrarium(np.array([[np.nan]], dtype=np.float32))


def test_partial_coverage_uses_background_without_cliffs():
    local = np.full((40, 40), 350.0, dtype=np.float32)
    local[:, 20:] = np.nan
    background = np.full((40, 40), 340.0, dtype=np.float32)
    result = terrain.composite_elevation(local, background)
    assert result.min() >= 340
    assert result.max() <= 350
    assert np.isfinite(result).all()
    assert np.max(np.abs(np.diff(result, axis=1))) <= 10 / terrain.PAD + 0.001
    np.testing.assert_array_equal(result[:, 20:], background[:, 20:])


def test_padded_composite_agrees_on_shared_pixels():
    local = np.full((60, 60), 350.0, dtype=np.float32)
    local[:, 30:] = np.nan
    base = np.full((44, 44), 340.0)
    result = terrain.composite_elevation(local, base, padding=8)
    expected = terrain.composite_elevation(local, np.full_like(local, 340.0))[8:-8, 8:-8]
    np.testing.assert_allclose(result, expected)


def test_native_reprojection_samples_web_mercator_pixel_centers(tmp_path):
    bounds = terrain.tile_bounds(14, 4551, 6175)
    size = terrain.SIZE
    ramp = np.tile(np.arange(size, dtype=np.float32), (size, 1))
    path = tmp_path / "dem.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=size,
        height=size,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=from_bounds(*bounds, size, size),
        nodata=-9999,
    ) as dst:
        dst.write(ramp, 1)
    dem = terrain.Dem(path, bounds, (0, 0, 1, 1), 1)
    result = terrain.read_elevation(14, 4551, 6175, [dem], pad=0)
    np.testing.assert_allclose(result, ramp, atol=0.001)


def test_relief_keeps_nodata_transparent_and_returns_512_pixels():
    array = np.full((terrain.SIZE + 2 * terrain.PAD,) * 2, np.nan, dtype=np.float32)
    array[:, :200] = 250
    image = np.asarray(Image.open(io.BytesIO(terrain.shaded_relief(array, 15, 12350))))
    assert image.shape == (512, 512, 4)
    assert image[100, 100, 3] == 255
    assert image[100, 400, 3] == 0


def test_cached_tile_is_reused_and_source_revision_invalidates_it(tmp_path, monkeypatch):
    monkeypatch.setattr(terrain.settings, "data_dir", tmp_path)
    revision = ["first"]
    monkeypatch.setattr(terrain, "inventory", lambda: (revision[0], []))
    calls = []

    def read(*args):
        calls.append(1)
        return np.full((terrain.SIZE + 2 * terrain.PAD,) * 2, 123.0, dtype=np.float32)

    monkeypatch.setattr(terrain, "read_elevation", read)
    one = terrain.render_tile("terrain", 15, 0, 0)
    assert terrain.render_tile("terrain", 15, 0, 0) == one
    assert len(calls) == 1
    revision[0] = "second"
    terrain.render_tile("terrain", 15, 0, 0)
    assert len(calls) == 2


def test_inventory_revision_survives_a_timestamp_preserving_move(tmp_path, monkeypatch):
    import shutil

    first = tmp_path / "first"
    second = tmp_path / "second"
    path = first / "processed" / "area" / "area_dem.tif"
    path.parent.mkdir(parents=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=16,
        height=16,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=from_bounds(0, 0, 16, 16, 16, 16),
    ) as dst:
        dst.write(np.full((16, 16), 120.0, dtype=np.float32), 1)
    monkeypatch.setattr(terrain.settings, "data_dir", first)
    monkeypatch.setattr(terrain, "_inventory_time", 0)
    revision, _ = terrain.inventory()
    shutil.copytree(first, second, copy_function=shutil.copy2)
    monkeypatch.setattr(terrain.settings, "data_dir", second)
    monkeypatch.setattr(terrain, "_inventory_time", 0)
    moved_revision, _ = terrain.inventory()
    assert revision == moved_revision
