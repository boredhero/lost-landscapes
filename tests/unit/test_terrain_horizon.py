"""Physical invariants and independently generated RVT reference comparisons."""

import io
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from lost_landscapes import terrain_horizon as horizon
from lost_landscapes import terrain_visualization as visualization
from lost_landscapes.api.routes import landscape
from tests.unit import test_terrain_mosaic as mosaic

REFERENCE = Path(__file__).parents[1] / "fixtures" / "terrain-reference"
CASES = json.loads((REFERENCE / "manifest.json").read_text())["cases"]


@pytest.fixture
def terrain(tmp_path):
    return mosaic.terrain.__wrapped__(tmp_path)


@pytest.mark.parametrize("case", CASES, ids=[c["key"] for c in CASES])
def test_matches_official_rvt_finite_interior(case):
    with np.load(REFERENCE / "horizons.npz", allow_pickle=False) as data:
        key, spacing, radius = case["key"], case["spacing_m"], case["radius_m"]
        actual = horizon.horizon_views(data[key + "/dem"], spacing, spacing, radius)
        margin = case["margin_cells"]
        for layer in horizon.LAYERS:
            expected = data[key + "/" + layer]
            tolerance = 2e-6 if layer == "svf" else 0.0002
            np.testing.assert_allclose(actual[layer][margin:-margin, margin:-margin], expected,
                                       atol=tolerance, rtol=0)
            assert np.isnan(actual[layer][:margin]).all()


def test_flat_ground_has_open_sky_and_ninety_degree_openness():
    actual = horizon.horizon_views(np.full((61, 61), 300.0), 1, 1, 10)
    for layer in horizon.LAYERS:
        np.testing.assert_allclose(actual[layer][10:-10, 10:-10], 1 if layer == "svf" else 90)


def test_mound_and_pit_have_distinct_positive_and_negative_openness():
    mound = np.zeros((61, 61))
    mound[30, 30] = 5
    positive = horizon.horizon_views(mound, 1, 1, 10)
    negative = horizon.horizon_views(-mound, 1, 1, 10)
    assert positive["svf"][30, 30] == 1
    assert negative["svf"][30, 30] < 1
    assert positive["openness-positive"][30, 30] > 90
    assert positive["openness-negative"][30, 30] < 90
    np.testing.assert_allclose(negative["openness-negative"], positive["openness-positive"], equal_nan=True)
    assert not np.isclose(positive["openness-negative"][30, 30], 180 - positive["openness-positive"][30, 30])


def test_rectangular_grid_uses_ground_distance_for_horizon_angles():
    rows, cols = np.indices((61, 61), dtype=float)
    values = 0.4 * cols * 2 - 0.3 * rows * 3
    actual = horizon.horizon_views(values, 2, 3, 25)
    _, _, rays = horizon.search_plan(2, 3, 25)
    # Independent scalar calculation at one point using physical plane gradients.
    angles = [max(np.arctan((0.4 * col * 2 - 0.3 * row * 3) / np.hypot(col * 2, row * 3))
                  for row, col, _ in ray) for ray in rays]
    expected = np.mean(1 - np.sin(np.maximum(angles, 0)))
    assert actual["svf"][30, 30] == pytest.approx(expected, abs=1e-6)
    assert actual["openness-positive"][30, 30] == pytest.approx(90 - np.degrees(np.mean(angles)), abs=1e-5)


def test_nodata_requires_complete_neighborhood_and_is_not_open_sky():
    values = np.zeros((61, 61))
    values[30, 30] = np.nan
    actual = horizon.horizon_views(values, 1, 1, 10)
    for layer in horizon.LAYERS:
        assert np.isnan(actual[layer][20:41, 20:41]).all()
        assert np.isfinite(actual[layer][30, 41])
        assert not np.isfinite(horizon.horizon_views(np.full((31, 31), np.nan), 1, 1, 10)[layer]).any()


@pytest.mark.parametrize("layer", horizon.LAYERS)
def test_horizon_tiles_join_without_changing_reference_surface(terrain, layer):
    reference, tiles = terrain
    bounds = (500080, 4499760, 500240, 4499920)
    expected = mosaic.render([reference], bounds, layer, 25)
    actual = mosaic.render(tiles, bounds, layer, 25)
    assert np.all(actual[..., 3] == 255)
    np.testing.assert_allclose(actual, expected, atol=1)


def test_work_budget_and_radius_cell_limit_are_enforced(terrain, monkeypatch):
    with pytest.raises(ValueError, match="128 native cells"):
        horizon.search_plan(0.01, 0.01, 50)
    monkeypatch.setattr(horizon, "MAX_WORK", 10)
    with pytest.raises(ValueError, match="work exceeds"):
        horizon.horizon_views(np.zeros((61, 61)), 1, 1, 10)
    _, tiles = terrain
    assert not mosaic.render(tiles, (500080, 4499760, 500240, 4499920), "svf")[..., 3].any()


def test_horizon_api_low_zoom_is_transparent_and_does_not_compute(monkeypatch, tmp_path):
    monkeypatch.setattr(landscape.settings, "data_dir", tmp_path)
    monkeypatch.setattr(landscape, "inventory", lambda: ("test-horizon", []))
    monkeypatch.setattr(visualization, "render", lambda *args: pytest.fail("Low zoom must not render horizons"))
    app = FastAPI()
    app.include_router(landscape.router)
    with TestClient(app) as client:
        for layer in horizon.LAYERS:
            response = client.get(f"/landscape/tiles/{layer}/15/10000/12000.png")
            assert response.status_code == 200
            assert not np.asarray(Image.open(io.BytesIO(response.content)))[..., 3].any()


def test_openness_grayscale_is_inverted_only_for_negative():
    values = np.array([[60, 90, 120, np.nan]])
    positive = np.asarray(Image.open(io.BytesIO(visualization.colorize(values, "openness-positive"))))
    negative = np.asarray(Image.open(io.BytesIO(visualization.colorize(values, "openness-negative"))))
    assert positive[0, 0, 0] == 0 and positive[0, 2, 0] == 255
    assert negative[0, 0, 0] == 255 and negative[0, 2, 0] == 0
    assert not positive[0, 3, 3] and not negative[0, 3, 3]
