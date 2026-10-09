from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from pydantic import ValidationError
from pyproj import Transformer
from rasterio.transform import from_origin

from lost_landscapes.measurements import MeasurementRequest, measure


@pytest.fixture
def dem(tmp_path):
    path = tmp_path / "dem.tif"
    transform = from_origin(500000, 4500100, 1, 1)
    data = np.full((100, 100), 100, dtype="float32")
    data[:, 45:55] = -9999
    with rasterio.open(path, "w", driver="GTiff", width=100, height=100, count=1,
                       dtype="float32", crs="EPSG:32617", transform=transform, nodata=-9999) as dst:
        dst.write(data, 1)
        dst.scales = (2,)
        dst.offsets = (5,)
        dst.set_band_unit(1, "m")
    to_geo = Transformer.from_crs(32617, 4326, always_xy=True)
    west, south = to_geo.transform(500000, 4500000)
    east, north = to_geo.transform(500100, 4500100)
    return SimpleNamespace(path=path, geographic_bounds=(west, south, east, north), resolution_m=1), to_geo


def test_profile_native_scale_mask_and_distances(dem):
    record, geo = dem
    coordinates = [list(geo.transform(500010, 4500050)), list(geo.transform(500090, 4500050))]
    result = measure(MeasurementRequest(type="LineString", coordinates=coordinates), "revision", [record])
    assert result["length_m"] == pytest.approx(80, abs=0.1)
    assert len(result["samples"]) == 201
    assert result["samples"][0]["distance_m"] == 0
    assert result["samples"][-1]["distance_m"] == result["length_m"]
    heights = [s["elevation_m"] for s in result["samples"]]
    assert None in heights
    assert set(heights) == {205, None}
    assert result["sources"][0]["vertical_datum"] is None


def test_point_outside_coverage_is_missing(dem):
    record, _ = dem
    result = measure(MeasurementRequest(type="Point", coordinates=[-80, 40]), "x", [record])
    assert result["samples"][0]["elevation_m"] is None


def test_polygon_ellipsoid_area(dem):
    _, geo = dem
    points = [list(geo.transform(x, y)) for x, y in [(500010, 4500010), (500090, 4500010), (500090, 4500090), (500010, 4500090), (500010, 4500010)]]
    result = measure(MeasurementRequest(type="Polygon", coordinates=[points]), "x", [])
    assert result["area_m2"] == pytest.approx(6400, rel=0.002)
    assert result["length_m"] == pytest.approx(320, rel=0.002)
    assert result["samples"] == []


@pytest.mark.parametrize("kind,coordinates", [
    ("Point", [float("nan"), 0]), ("Point", [181, 0]),
    ("LineString", [[0, 0], [1, 0]]), ("LineString", [[0, 0], [0, 0]]),
    ("Polygon", [[[0, 0], [.01, .01], [0, .01], [.01, 0], [0, 0]]]),
    ("Polygon", []), ("Point", [0, 0, 0]),
])
def test_invalid_or_unbounded_geometry(kind, coordinates):
    with pytest.raises((ValidationError, ValueError)):
        MeasurementRequest(type=kind, coordinates=coordinates)
