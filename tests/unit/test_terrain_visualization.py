"""Analytic terrain fixtures test scientific values, support, and map rendering."""

import io
import math

import numpy as np
import pytest
import rasterio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds

from lost_landscapes import terrain_visualization as visualization
from lost_landscapes.api.routes import landscape


def pixels(data):
    return np.asarray(Image.open(io.BytesIO(data)))


@pytest.mark.parametrize("spacing_x,spacing_y", [(1.0, 1.0), (2.0, 3.0)])
def test_slope_matches_analytic_plane_in_ground_metres(spacing_x, spacing_y):
    rows, cols = np.indices((91, 91), dtype=np.float64)
    elevation = 100 + 0.3 * cols * spacing_x - 0.4 * rows * spacing_y
    actual = visualization.derivatives(elevation, spacing_x, spacing_y, "slope")
    expected = math.degrees(math.atan(0.5))
    np.testing.assert_allclose(actual[3:-3, 3:-3], expected, atol=0.001)


def test_signed_relief_removes_plane_and_preserves_offset_invariance():
    rows, cols = np.indices((121, 121), dtype=np.float64)
    plane = 100 + 0.125 * cols - 0.0625 * rows
    flat_residual = visualization.derivatives(plane, 2, 3, "local-relief", radius_m=10)
    np.testing.assert_allclose(flat_residual[10:-10, 10:-10], 0, atol=0.0001)
    surface = plane.copy()
    surface[35, 35] += 4
    surface[85, 85] -= 4
    actual = visualization.derivatives(surface, 2, 3, "local-relief", radius_m=10)
    shifted = visualization.derivatives(surface + 1000, 2, 3, "local-relief", radius_m=10)
    assert actual[35, 35] > 3.9
    assert actual[85, 85] < -3.9
    np.testing.assert_allclose(actual, shifted, atol=0.0002, equal_nan=True)


@pytest.mark.parametrize("spacing_x,spacing_y", [(1.0, 1.0), (2.0, 3.0)])
def test_relief_radius_is_metres_not_pixels(spacing_x, spacing_y):
    elevation = np.zeros((101, 101), dtype=np.float64)
    elevation[50, 50] = 1
    radius = 10
    actual = visualization.derivatives(
        elevation, spacing_x, spacing_y, "local-relief", radius_m=radius
    )
    rx = math.ceil(radius / spacing_x)
    ry = math.ceil(radius / spacing_y)
    mean = 1 / ((2 * rx + 1) * (2 * ry + 1))
    assert actual[50, 50] == pytest.approx(1 - mean, abs=1e-6)
    assert actual[50, 50 + rx] == pytest.approx(-mean, abs=1e-6)
    assert actual[50, 51 + rx] == pytest.approx(0, abs=1e-6)


def test_relief_requires_full_support_around_missing_ground():
    rows, cols = np.indices((101, 101), dtype=np.float64)
    elevation = 200 + 0.125 * cols + 0.25 * rows
    elevation[50, 50] = np.nan
    actual = visualization.derivatives(elevation, 2, 2, "local-relief", radius_m=10)
    assert np.isnan(actual[45:56, 45:56]).all()
    assert np.isnan(actual[:5]).all()
    assert np.isnan(actual[:, -5:]).all()
    assert actual[50, 56] == pytest.approx(0, abs=0.0001)
    np.testing.assert_allclose(actual[np.isfinite(actual)], 0, atol=0.0001)


@pytest.mark.parametrize("layer", ["slope", "local-relief", "hillshade"])
def test_all_missing_input_has_no_valid_derivative(layer):
    actual = visualization.derivatives(np.full((81, 81), np.nan), 2, 2, layer)
    assert not np.isfinite(actual).any()


@pytest.mark.parametrize("layer", ["slope", "local-relief"])
def test_source_windows_with_halo_match_whole_surface(layer):
    rows, cols = np.indices((180, 240), dtype=np.float64)
    elevation = 100 + np.sin(cols / 11) * 2 + np.cos(rows / 17)
    whole = visualization.derivatives(elevation, 2, 2, layer, radius_m=25)
    # More than the old display padding of eight pixels is needed here.
    halo = 15
    left = visualization.derivatives(
        elevation[:, :120 + halo], 2, 2, layer, radius_m=25
    )
    right = visualization.derivatives(
        elevation[:, 120 - halo:], 2, 2, layer, radius_m=25
    )
    stitched = np.concatenate((left[:, :120], right[:, halo:]), axis=1)
    np.testing.assert_allclose(stitched, whole, atol=0.0001, equal_nan=True)


@pytest.fixture
def local_dem(tmp_path):
    size, spacing = 512, 2.0
    rows, cols = np.indices((size, size), dtype=np.float64)
    surface = 100 + 0.1 * cols + 0.04 * rows
    surface += 3 * np.exp(-((cols - 260) ** 2 + (rows - 250) ** 2) / 300)
    transform = from_origin(500000, 4500000, spacing, spacing)
    path = tmp_path / "synthetic_dem.tif"
    source_bounds = (500000, 4500000 - size * spacing, 500000 + size * spacing, 4500000)
    with rasterio.open(
        path, "w", driver="GTiff", width=size, height=size, count=1,
        dtype="float32", crs="EPSG:32617", transform=transform, nodata=-9999,
    ) as dst:
        dst.write(surface.astype(np.float32), 1)
    mercator = transform_bounds("EPSG:32617", "EPSG:3857", *source_bounds)
    geographic = transform_bounds("EPSG:32617", "EPSG:4326", *source_bounds)
    return landscape.Dem(path, mercator, geographic, spacing)


@pytest.mark.parametrize("layer", ["slope", "local-relief"])
def test_four_display_tiles_agree_with_one_render(local_dem, layer):
    west, south, east, north = local_dem.bounds
    cx, cy = (west + east) / 2, (south + north) / 2
    extent = 200
    bounds = (cx - extent, cy - extent, cx + extent, cy + extent)
    whole = pixels(visualization.render([local_dem], bounds, layer, radius_m=10, size=128))
    quadrants = [
        (cx - extent, cy, cx, cy + extent),
        (cx, cy, cx + extent, cy + extent),
        (cx - extent, cy - extent, cx, cy),
        (cx, cy - extent, cx + extent, cy),
    ]
    images = [pixels(visualization.render([local_dem], b, layer, radius_m=10, size=64)) for b in quadrants]
    stitched = np.concatenate(
        (np.concatenate(images[:2], axis=1), np.concatenate(images[2:], axis=1)), axis=0
    )
    assert whole.shape == (128, 128, 4)
    assert np.all(whole[..., 3] == 255)
    np.testing.assert_allclose(stitched, whole, atol=1)


def test_no_coverage_renders_transparency():
    actual = pixels(visualization.render([], (0, 0, 256, 256), "local-relief", size=64))
    assert actual.shape == (64, 64, 4)
    assert np.all(actual[..., 3] == 0)


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(landscape.settings, "data_dir", tmp_path)
    monkeypatch.setattr(landscape, "inventory", lambda: ("test-revision", []))
    app = FastAPI()
    app.include_router(landscape.router)
    return TestClient(app)


@pytest.mark.parametrize("parameters", ["radius_m=-1", "radius_m=11", "radius_m=nan", "azimuth=12", "azimuth=360"])
def test_api_rejects_unsupported_scientific_parameters(client, parameters):
    response = client.get(f"/landscape/tiles/local-relief/15/10000/12000.png?{parameters}")
    assert response.status_code == 422


def test_derivative_endpoint_does_not_fetch_background(client, monkeypatch):
    def fail_if_called(*args, **kwargs):
        pytest.fail("Scientific derivative must not fall back to regional terrain")

    monkeypatch.setattr(landscape, "background", fail_if_called)
    response = client.get("/landscape/tiles/local-relief/15/10000/12000.png?radius_m=10")
    assert response.status_code == 200
    assert pixels(response.content).shape == (512, 512, 4)
    assert not pixels(response.content)[..., 3].any()


def test_parameter_changes_separate_cached_tiles(client, monkeypatch):
    calls = []
    original = visualization.render

    def counted(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(visualization, "render", counted)
    base = "/landscape/tiles/local-relief/15/10000/12000.png"
    assert client.get(base + "?radius_m=10").status_code == 200
    assert client.get(base + "?radius_m=10").status_code == 200
    assert len(calls) == 1
    assert client.get(base + "?radius_m=25").status_code == 200
    assert len(calls) == 2
    hillshade = "/landscape/tiles/hillshade/15/10000/12000.png"
    assert client.get(hillshade + "?azimuth=315").status_code == 200
    assert client.get(hillshade + "?azimuth=45").status_code == 200
    assert len(calls) == 4
