"""Unit tests for ingest module — source discovery, manager."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from lost_landscapes.ingest.manager import (
    SOURCE_REGISTRY,
    STATE_SOURCES,
    get_source,
    get_sources_for_location,
)
from lost_landscapes.ingest.sources.usgs_3dep import USGS3DEPSource


class TestSourceRegistry:
    def test_all_sources_registered(self):
        assert "usgs_3dep" in SOURCE_REGISTRY
        assert "tnm" in SOURCE_REGISTRY
        assert "pasda" in SOURCE_REGISTRY
        assert "wv" in SOURCE_REGISTRY
        assert "ny" in SOURCE_REGISTRY
        assert "oh" in SOURCE_REGISTRY
        assert "nc" in SOURCE_REGISTRY
        assert "md" in SOURCE_REGISTRY
        assert "va" in SOURCE_REGISTRY
        assert "ky" in SOURCE_REGISTRY
        assert "nj" in SOURCE_REGISTRY
        assert "ct" in SOURCE_REGISTRY

    def test_get_source(self):
        source = get_source("usgs_3dep")
        assert source.name == "usgs_3dep"

    def test_unknown_source_raises(self):
        with pytest.raises(KeyError, match="nonexistent"):
            get_source("nonexistent")


class TestStateSources:
    def test_pa_has_pasda(self):
        assert "pasda" in STATE_SOURCES["PA"]

    def test_nc_has_nc(self):
        assert "nc" in STATE_SOURCES["NC"]

    def test_va_has_va(self):
        assert "va" in STATE_SOURCES["VA"]

    def test_ky_has_ky(self):
        assert "ky" in STATE_SOURCES["KY"]

    def test_sources_for_location_always_starts_with_3dep(self):
        with patch("lost_landscapes.ingest.manager.resolve_state", return_value="PA"):
            sources = get_sources_for_location(40.0, -80.0)
            assert sources[0] == "usgs_3dep"
            assert "pasda" in sources
            assert sources[-1] == "tnm"

    def test_sources_for_location_unknown_state(self):
        with patch("lost_landscapes.ingest.manager.resolve_state", return_value=None):
            sources = get_sources_for_location(0.0, 0.0)
            assert sources == ["usgs_3dep", "tnm"]

    def test_sources_for_location_state_without_specific_source(self):
        with patch("lost_landscapes.ingest.manager.resolve_state", return_value="AK"):
            sources = get_sources_for_location(64.0, -150.0)
            assert sources == ["usgs_3dep", "tnm"]


class TestUSGS3DEPSource:
    def test_source_name(self):
        source = USGS3DEPSource()
        assert source.name == "usgs_3dep"

    def test_parse_stac_item(self):
        source = USGS3DEPSource()
        item = {
            "id": "USGS_LPC_PA_SouthCentral_2018_D19_4288000e_9318000n",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[-79.7, 39.8], [-79.6, 39.8], [-79.6, 39.9], [-79.7, 39.9], [-79.7, 39.8]]],
            },
            "properties": {
                "datetime": "2018-06-15T00:00:00Z",
                "proj:epsg": 6344,
            },
            "assets": {
                "data": {
                    "href": "https://example.com/tile.copc.laz",
                    "file:size": 52428800,
                },
            },
        }
        tile = source._parse_stac_item(item)
        assert tile is not None
        assert tile.format == "copc"
        assert tile.acquisition_year == 2018
        assert tile.file_size_bytes == 52428800
        assert "copc.laz" in tile.filename

    def test_parse_invalid_item_returns_none(self):
        source = USGS3DEPSource()
        tile = source._parse_stac_item({"id": "broken", "properties": {}})
        assert tile is None


class TestKnownSites:
    def test_sites_json_valid(self):
        sites_path = Path(__file__).parent.parent / "fixtures" / "known_sites.json"
        with open(sites_path) as f:
            data = json.load(f)
        sites = data["validation_sites"]
        assert len(sites) >= 10, f"Expected >=10 validation sites, got {len(sites)}"
        for site in sites:
            assert "name" in site
            assert "lat" in site
            assert "lon" in site
            assert "type" in site
            assert -90 <= site["lat"] <= 90
            assert -180 <= site["lon"] <= 180
            assert site["type"] in ("cave_entrance", "mine_portal", "sinkhole", "depression")

    def test_sites_cover_all_states(self):
        sites_path = Path(__file__).parent.parent / "fixtures" / "known_sites.json"
        with open(sites_path) as f:
            data = json.load(f)
        states = {s["state"] for s in data["validation_sites"]}
        # Only states with LiDAR-visible (non-commercialized) validation sites
        assert "PA" in states
        assert "WV" in states
        assert "NC" in states
        assert "MA" in states
        assert "LA" in states
        assert "CA" in states
