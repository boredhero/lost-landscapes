"""Tests for the robust CRS resolver — validates fixes for the infinity bug.

The core issue: compound CRS (UTM + NAVD88 vertical) caused to_epsg() to return
None, falling back to hardcoded EPSG:32617 regardless of actual zone. This test
suite ensures resolve_epsg() handles every CRS variant we encounter in production.
"""

import math
from pathlib import Path

import numpy as np
import pytest
import rasterio
from pyproj import CRS as PyprojCRS
from rasterio.transform import from_bounds

from lost_landscapes.utils.crs import resolve_epsg

# ---------- resolve_epsg: happy path ----------

class TestResolveEpsgSimple:
    """Direct EPSG codes — the happy path that must always work."""

    @pytest.mark.parametrize("epsg", [32617, 32610, 26917, 26910, 6346, 6350, 4326])
    def test_simple_epsg_codes(self, epsg):
        crs = PyprojCRS.from_epsg(epsg)
        assert resolve_epsg(crs) == epsg

    def test_rasterio_crs_object(self):
        crs = rasterio.crs.CRS.from_epsg(26917)
        assert resolve_epsg(crs) == 26917


# ---------- resolve_epsg: compound CRS (the actual production bug) ----------

class TestResolveEpsgCompound:
    """Compound CRS (UTM + vertical datum) — the exact scenario that caused infinity."""

    @pytest.mark.parametrize("zone", [10, 15, 17, 19])
    def test_compound_nad83_utm_plus_navd88(self, zone):
        """Build a real compound CRS like PDAL outputs and verify horizontal extraction."""
        compound = PyprojCRS.from_proj4(f"+proj=utm +zone={zone} +datum=NAD83 +vunits=m +no_defs")
        result = resolve_epsg(compound)
        assert result is not None
        assert result % 100 == zone

    def test_compound_wkt_from_pdal(self):
        """Test with a WKT string similar to what PDAL actually writes for PA tiles."""
        wkt = 'COMPD_CS["NAD83 / UTM zone 17N + NAVD88 height",PROJCS["NAD83 / UTM zone 17N",GEOGCS["NAD83",DATUM["North_American_Datum_1983",SPHEROID["GRS 1980",6378137,298.257222101]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",-81],PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],PARAMETER["false_northing",0],UNIT["metre",1]],VERT_CS["NAVD88 height",VERT_DATUM["North American Vertical Datum 1988",2005],UNIT["metre",1]]]'
        result = resolve_epsg(wkt)
        assert result is not None
        assert result % 100 == 17

    def test_compound_wkt_zone_10(self):
        """CA tiles: UTM zone 10N + NAVD88."""
        wkt = 'COMPD_CS["NAD83 / UTM zone 10N + NAVD88 height",PROJCS["NAD83 / UTM zone 10N",GEOGCS["NAD83",DATUM["North_American_Datum_1983",SPHEROID["GRS 1980",6378137,298.257222101]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",-123],PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],PARAMETER["false_northing",0],UNIT["metre",1]],VERT_CS["NAVD88 height",VERT_DATUM["North American Vertical Datum 1988",2005],UNIT["metre",1]]]'
        result = resolve_epsg(wkt)
        assert result is not None
        assert result % 100 == 10


# ---------- resolve_epsg: GeoTIFF file input ----------

class TestResolveEpsgFromFile:
    """File path input — reads CRS directly from GeoTIFF."""

    @pytest.mark.parametrize("epsg", [26917, 26910, 32617])
    def test_from_geotiff_path(self, tmp_path, epsg):
        dem = np.ones((50, 50), dtype=np.float32) * 500.0
        path = tmp_path / "test_dem.tif"
        transform = from_bounds(500000, 4400000, 501000, 4401000, 50, 50)
        with rasterio.open(path, "w", driver="GTiff", height=50, width=50, count=1, dtype="float32", crs=f"EPSG:{epsg}", transform=transform) as dst:
            dst.write(dem, 1)
        assert resolve_epsg(path) == epsg

    def test_nonexistent_file_raises(self):
        with pytest.raises((ValueError, Exception)):
            resolve_epsg(Path("/nonexistent/dem.tif"))


# ---------- resolve_epsg: error cases ----------

class TestResolveEpsgErrors:
    """Error cases — must fail loud, never silently return wrong zone."""

    def test_none_raises_valueerror(self):
        with pytest.raises(ValueError, match="CRS is None"):
            resolve_epsg(None)

    def test_garbage_string_raises_valueerror(self):
        with pytest.raises(ValueError):
            resolve_epsg("not a crs at all")


# ---------- End-to-end: CRS transform produces finite coordinates ----------

class TestCrsTransformNotInfinity:
    """Verify that the CRS codes resolve_epsg returns actually produce finite WGS84 coords.
    This is the end-to-end validation that the infinity bug is fixed.
    """

    @pytest.mark.parametrize("epsg,easting,northing,expected_lon_range,expected_lat_range", [
        (26917, 576000.0, 4552500.0, (-83, -79), (40, 42)),    # Western PA
        (26910, 550000.0, 4200000.0, (-124, -120), (37, 39)),  # NorCal
        (32617, 576000.0, 4552500.0, (-83, -79), (40, 42)),    # WGS84 UTM 17N
        (32610, 550000.0, 4200000.0, (-124, -120), (37, 39)),  # WGS84 UTM 10N
        (6346, 500000.0, 3500000.0, (-94, -78), (31, 33)),     # NAD83(2011) UTM 15N
    ])
    def test_transform_produces_finite_wgs84(self, epsg, easting, northing, expected_lon_range, expected_lat_range):
        from pyproj import Transformer
        t = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
        lon, lat = t.transform(easting, northing)
        assert math.isfinite(lon), f"Longitude is {lon} for EPSG:{epsg}"
        assert math.isfinite(lat), f"Latitude is {lat} for EPSG:{epsg}"
        assert expected_lon_range[0] <= lon <= expected_lon_range[1], f"Lon {lon} not in {expected_lon_range}"
        assert expected_lat_range[0] <= lat <= expected_lat_range[1], f"Lat {lat} not in {expected_lat_range}"

    def test_compound_crs_resolves_and_transforms(self, tmp_path):
        """Full pipeline test: write GeoTIFF with compound CRS WKT, resolve, transform."""
        # Write a DEM as if PDAL created it with compound CRS
        dem = np.ones((50, 50), dtype=np.float32) * 500.0
        path = tmp_path / "compound_dem.tif"
        wkt = 'COMPD_CS["NAD83 / UTM zone 17N + NAVD88 height",PROJCS["NAD83 / UTM zone 17N",GEOGCS["NAD83",DATUM["North_American_Datum_1983",SPHEROID["GRS 1980",6378137,298.257222101]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",-81],PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],PARAMETER["false_northing",0],UNIT["metre",1]],VERT_CS["NAVD88 height",VERT_DATUM["North American Vertical Datum 1988",2005],UNIT["metre",1]]]'
        transform = from_bounds(576000, 4552000, 577000, 4553000, 50, 50)
        with rasterio.open(path, "w", driver="GTiff", height=50, width=50, count=1, dtype="float32", crs=wkt, transform=transform) as dst:
            dst.write(dem, 1)
        # Resolve CRS from the file
        epsg = resolve_epsg(path)
        assert epsg % 100 == 17
        # Transform the DEM bounds — this is exactly what tasks.py does
        from pyproj import Transformer
        t = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
        lon, lat = t.transform(576000.0, 4552500.0)
        assert math.isfinite(lon) and math.isfinite(lat), f"Got ({lon}, {lat}) — still infinity!"
        assert -83 <= lon <= -79
        assert 40 <= lat <= 42
