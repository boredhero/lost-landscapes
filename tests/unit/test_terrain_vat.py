"""VAT checks use the official four-layer normalization/blending reference."""

import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from lost_landscapes import terrain_horizon as horizon
from lost_landscapes import terrain_visualization as visualization
from tests.unit import test_terrain_mosaic as mosaic

REFERENCE = Path(__file__).parents[1] / "fixtures" / "terrain-reference"
CASES = json.loads((REFERENCE / "manifest.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["key"] for c in CASES])
def test_vat_matches_reference_components_and_blend(case):
    with np.load(REFERENCE / "horizons.npz", allow_pickle=False) as data, np.load(REFERENCE / "vat.npz", allow_pickle=False) as ref:
        key, spacing, radius = case["key"], case["spacing_m"], case["radius_m"]
        actual = visualization.derivatives(data[key + "/dem"], spacing, spacing, "vat", radius)
        margin = case["margin_cells"]
        np.testing.assert_allclose(actual[margin:-margin, margin:-margin], ref[key], atol=0.00002, rtol=0)
        assert np.isnan(actual[:margin]).all()


def test_vat_opacity_and_fixed_ranges_are_not_tile_normalized():
    # Flat ground has slope=0, HS=sin(35), openness=90, SVF=1.
    hill = np.sin(np.radians(35))
    base = (hill + 1) / 2
    overlay = 1 - 2 * (1 - base) * (1 - (90 - 68) / 25)
    expected = (base + overlay) / 2
    values = horizon.vat(np.zeros((61, 61)), 1, 1, 10)
    np.testing.assert_allclose(values[10:-10, 10:-10], expected, atol=1e-6)
    # An unrelated pixel changing must not rescale the rest of a composite image.
    a = horizon.blend_vat(np.array([0., 25]), np.array([hill, 1]), np.array([1., 0.7]), np.array([90., 68]))
    assert a[0] == pytest.approx(expected, abs=1e-6)


def test_vat_preserves_nodata_and_joined_source_continuity(tmp_path):
    reference, tiles = mosaic.terrain.__wrapped__(tmp_path)
    bounds = (500080, 4499760, 500240, 4499920)
    np.testing.assert_allclose(mosaic.render(tiles, bounds, "vat"), mosaic.render([reference], bounds, "vat"), atol=1)
    values = np.zeros((61, 61))
    values[30, 30] = np.nan
    actual = horizon.vat(values, 1, 1, 10)
    assert np.isnan(actual[20:41, 20:41]).all()
    assert np.isfinite(actual[30, 41])
    image = np.asarray(Image.open(io.BytesIO(visualization.colorize(actual, "vat"))))
    assert not image[20:41, 20:41, 3].any()
    assert visualization.min_zoom("vat") == 16


def test_vat_uses_the_same_horizon_work_limit(monkeypatch):
    monkeypatch.setattr(horizon, "MAX_WORK", 10)
    with pytest.raises(ValueError, match="work exceeds"):
        horizon.vat(np.zeros((61, 61)), 1, 1, 10)
