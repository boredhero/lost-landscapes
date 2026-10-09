"""Compare measured tiled terrain with a continuous reference raster."""

import io
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds
from rasterio.windows import Window

from lost_landscapes import terrain_visualization as visualization
from lost_landscapes.api.routes import landscape

CRS = "EPSG:32617"
TAGS = {"LL_SURVEY_ID": "synthetic-survey", "LL_VERTICAL_DATUM": "synthetic-datum"}


def record(path):
    with rasterio.open(path) as src:
        return landscape.Dem(
            path,
            transform_bounds(src.crs, "EPSG:3857", *src.bounds),
            transform_bounds(src.crs, "EPSG:4326", *src.bounds),
            src.res[0],
        )


def write_dem(path, values, transform, *, tags=TAGS, units="m", scale=1, offset=0, crs=CRS):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype="float32",
        crs=crs,
        transform=transform,
        nodata=-9999,
    ) as dst:
        dst.write(np.where(np.isfinite(values), values, -9999).astype(np.float32), 1)
        dst.update_tags(**tags)
        if units:
            dst.set_band_unit(1, units)
        dst.scales = [scale]
        dst.offsets = [offset]
    return record(path)


@pytest.fixture
def terrain(tmp_path):
    rows, cols = np.indices((160, 160), dtype=float)
    values = 100 + cols * 0.03 - rows * 0.07
    values += 2 * np.exp(-((cols - 80) ** 2 + (rows - 80) ** 2) / 90)
    values -= 3 * np.exp(-((cols - 70) ** 2 + (rows - 90) ** 2) / 40)
    reference = write_dem(tmp_path / "reference.tif", values, from_origin(500000, 4500000, 2, 2))
    tiles = []
    for r in range(2):
        for c in range(2):
            tiles.append(
                write_dem(
                    tmp_path / f"tile-{r}-{c}.tif",
                    values[r * 80 : (r + 1) * 80, c * 80 : (c + 1) * 80],
                    from_origin(500000 + c * 160, 4500000 - r * 160, 2, 2),
                )
            )
    return reference, tiles


def render(records, native_bounds, layer="local-relief", radius=25):
    bounds = transform_bounds(CRS, "EPSG:3857", *native_bounds)
    data = visualization.render(records, bounds, layer, radius_m=radius, size=128)
    return np.asarray(Image.open(io.BytesIO(data)))


@pytest.mark.parametrize(
    "layer,radius",
    [
        ("slope", 25),
        ("hillshade", 25),
        ("local-relief", 10),
        ("local-relief", 25),
        ("local-relief", 50),
    ],
)
def test_four_tile_corner_matches_continuous_surface(terrain, layer, radius):
    reference, tiles = terrain
    bounds = (500080, 4499760, 500240, 4499920)
    expected = render([reference], bounds, layer, radius)
    actual = render(tiles, bounds, layer, radius)
    assert np.all(actual[..., 3] == 255)
    np.testing.assert_allclose(actual, expected, atol=1)
    np.testing.assert_array_equal(actual, render(list(reversed(tiles)), bounds, layer, radius))


def test_neighbor_outside_display_extent_supplies_required_halo(terrain):
    reference, tiles = terrain
    bounds = (500130, 4499860, 500150, 4499900)
    display = transform_bounds(CRS, "EPSG:3857", *bounds)
    assert not visualization.intersects(tiles[1].bounds, display)
    actual = render(tiles, bounds, radius=50)
    assert np.all(actual[..., 3] == 255)
    np.testing.assert_allclose(actual, render([reference], bounds, radius=50), atol=1)


def test_real_nodata_at_join_stays_missing_and_matches_reference(terrain):
    reference, tiles = terrain
    # The same measured-data hole spans both sides of the vertical tile seam.
    for path, window in [
        (reference.path, Window(78, 50, 4, 10)),
        (tiles[0].path, Window(78, 50, 2, 10)),
        (tiles[1].path, Window(0, 50, 2, 10)),
    ]:
        with rasterio.open(path, "r+") as dst:
            dst.write(
                np.full((int(window.height), int(window.width)), -9999, dtype="float32"),
                1,
                window=window,
            )
    bounds = (500100, 4499800, 500220, 4499940)
    expected = render([reference], bounds)
    actual = render(tiles, bounds)
    assert np.any(actual[..., 3] == 0)
    assert np.any(actual[..., 3] == 255)
    np.testing.assert_array_equal(actual[..., 3], expected[..., 3])
    np.testing.assert_allclose(actual, expected, atol=1)


@pytest.mark.parametrize(
    "mismatch",
    ["survey", "datum", "units", "unknown_units", "unknown_datum", "spacing", "alignment", "crs"],
)
def test_incompatible_sources_cannot_supply_neighborhoods(terrain, mismatch):
    _, tiles = terrain
    with rasterio.open(tiles[1].path, "r+") as dst:
        if mismatch == "survey":
            dst.update_tags(LL_SURVEY_ID="different-survey")
        elif mismatch == "datum":
            dst.update_tags(LL_VERTICAL_DATUM="different-datum")
        elif mismatch == "unknown_datum":
            dst.update_tags(LL_VERTICAL_DATUM="")
        elif mismatch == "units":
            dst.set_band_unit(1, "ft")
        elif mismatch == "unknown_units":
            dst.set_band_unit(1, "")
        elif mismatch == "spacing":
            dst.transform = from_origin(500160, 4500000, 3, 2)
        elif mismatch == "alignment":
            dst.transform = from_origin(500161, 4500000, 2, 2)
        elif mismatch == "crs":
            dst.crs = "EPSG:32618"
    with rasterio.open(tiles[0].path) as anchor, rasterio.open(tiles[1].path) as other:
        assert not visualization.compatible_sources(anchor, other)
    # Isolate the western viewport: an incompatible eastern file must not fill its halo.
    actual = render(
        [tiles[0], record(tiles[1].path)], (500130, 4499860, 500150, 4499900), radius=50
    )
    assert not actual[..., 3].any()


def test_scaled_elevation_values_join_in_physical_metres(terrain):
    reference, tiles = terrain
    with rasterio.open(tiles[1].path, "r+") as dst:
        values = dst.read(1)
        dst.write((values - 10) / 2, 1)
        dst.scales = [2]
        dst.offsets = [10]
    bounds = (500100, 4499800, 500220, 4499940)
    np.testing.assert_allclose(render(tiles, bounds), render([reference], bounds), atol=1)


def test_missing_provenance_retains_individual_source_rendering(terrain):
    _, tiles = terrain
    for tile in tiles:
        with rasterio.open(tile.path, "r+") as dst:
            dst.update_tags(LL_SURVEY_ID="")
    with rasterio.open(tiles[0].path) as src:
        info = visualization.source_info(src)
    assert info["eligible"] and not info["mosaic_eligible"]
    actual = render(tiles, (500080, 4499760, 500240, 4499920))
    assert np.any(actual[..., 3] == 255)
    assert np.any(actual[..., 3] == 0)


def test_overlap_precedence_is_consistent_between_anchor_files(terrain, tmp_path):
    reference, _ = terrain
    with rasterio.open(reference.path) as src:
        values, transform = src.read(1), src.transform
    alternate = write_dem(tmp_path / "z-alternate.tif", values + 10, transform)
    bounds = (500080, 4499760, 500240, 4499920)
    np.testing.assert_array_equal(
        render([alternate, reference], bounds), render([reference], bounds)
    )


@pytest.mark.parametrize(
    "limit,value", [("MAX_SAMPLES", 100), ("MAX_TOTAL_SAMPLES", 100), ("MAX_NEIGHBOR_SOURCES", 1)]
)
def test_oversized_neighborhoods_are_not_partially_rendered(terrain, monkeypatch, limit, value):
    _, tiles = terrain
    monkeypatch.setattr(visualization, limit, value)
    assert not render(tiles, (500080, 4499760, 500240, 4499920))[..., 3].any()


def test_neighbor_metadata_changes_catalog_revision(terrain, monkeypatch):
    _, tiles = terrain
    # Use one imported-layout path, with the same inventory code used by the API.
    folder = tiles[0].path.parent / "processed" / "a"
    folder.mkdir(parents=True)
    path = folder / "a_dem.tif"
    path.write_bytes(tiles[0].path.read_bytes())
    monkeypatch.setattr(landscape.settings, "data_dir", folder.parent.parent)
    monkeypatch.setattr(landscape, "_inventory_time", 0)
    monkeypatch.setattr(landscape, "_inventory", ("empty", []))
    first, _ = landscape.inventory()
    with rasterio.open(path, "r+") as dst:
        dst.update_tags(LL_VERTICAL_DATUM="changed-datum")
    monkeypatch.setattr(landscape, "_inventory_time", 0)
    second, _ = landscape.inventory()
    assert second != first


def test_import_records_declared_provenance_and_preserves_external_mask(tmp_path):
    source = tmp_path / "input.tif"
    write_dem(source, np.ones((32, 32)), from_origin(500000, 4500000, 2, 2), tags={}, units=None)
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=False):
        with rasterio.open(source, "r+") as dst:
            mask = np.full((32, 32), 255, dtype="uint8")
            mask[12:16, 12:16] = 0
            dst.write_mask(mask)
    assert Path(str(source) + ".msk").exists()
    destination = tmp_path / "imported"
    command = [
        sys.executable,
        "scripts/import_study_area.py",
        str(source),
        "--name",
        "Fixture",
        "--source",
        "Synthetic",
        "--data-dir",
        str(destination),
        "--survey-id",
        "fixture",
        "--vertical-datum",
        "synthetic",
        "--elevation-units",
        "m",
    ]
    completed = subprocess.run(
        command, cwd=Path(__file__).parents[2], capture_output=True, text=True, timeout=30
    )
    assert completed.returncode == 0, completed.stderr
    with rasterio.open(destination / "processed" / "fixture-000" / "fixture-000_dem.tif") as src:
        assert visualization.source_info(src)["mosaic_eligible"]
        assert src.tags()["LL_SURVEY_ID"] == "fixture"
        np.testing.assert_array_equal(src.dataset_mask(), mask)


def test_import_refuses_conflicting_datum_before_writing(terrain, tmp_path):
    _, tiles = terrain
    destination = tmp_path / "imported"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/import_study_area.py",
            str(tiles[0].path),
            "--name",
            "Fixture",
            "--source",
            "Synthetic",
            "--data-dir",
            str(destination),
            "--survey-id",
            "synthetic-survey",
            "--vertical-datum",
            "different",
        ],
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode != 0 and "conflicts" in completed.stderr
    assert not destination.exists()
