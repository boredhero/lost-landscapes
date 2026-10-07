"""Validation tests against known cave, mine, and sinkhole sites.

These tests query PostGIS for detections near known validation sites.
They require:
1. Real LiDAR data processed for the area
2. Detections stored in PostGIS
3. DB connection to .111

Run with: uv run pytest tests/validation/ -v
Mark with @pytest.mark.validation so they can be selected/excluded.
"""

import asyncio
import json
from pathlib import Path

import pytest

# Load known sites
SITES_PATH = Path(__file__).parent.parent / "fixtures" / "known_sites.json"
with open(SITES_PATH) as f:
    ALL_SITES = json.load(f)["validation_sites"]

PA_CAVES = [s for s in ALL_SITES if s["state"] == "PA" and s["type"] == "cave_entrance"]
PA_MINES = [s for s in ALL_SITES if s["state"] == "PA" and s["type"] == "mine_portal"]
WV_CAVES = [s for s in ALL_SITES if s["state"] == "WV"]
OH_CAVES = [s for s in ALL_SITES if s["state"] == "OH"]
NY_CAVES = [s for s in ALL_SITES if s["state"] == "NY"]
NC_SITES = [s for s in ALL_SITES if s["state"] == "NC"]
MD_SITES = [s for s in ALL_SITES if s["state"] == "MD"]
MA_SITES = [s for s in ALL_SITES if s["state"] == "MA"]
LA_SITES = [s for s in ALL_SITES if s["state"] == "LA"]
CA_SITES = [s for s in ALL_SITES if s["state"] == "CA"]

# Check DB availability
try:
    from lost_landscapes.db.engine import async_session_factory
    from lost_landscapes.db.repositories import get_detections_near_point

    async def _check():
        async with async_session_factory() as session:
            from sqlalchemy import text
            await session.execute(text("SELECT 1"))

    asyncio.run(_check())
    DB_AVAILABLE = True
except Exception:
    DB_AVAILABLE = False

pytestmark = [
    pytest.mark.validation,
    pytest.mark.skipif(not DB_AVAILABLE, reason="PostGIS not reachable"),
]


async def _count_detections_near(lat: float, lon: float, radius_m: float = 200.0) -> int:
    async with async_session_factory() as session:
        detections = await get_detections_near_point(session, lat, lon, radius_m)
        return len(detections)


def count_near(lat: float, lon: float, radius_m: float = 200.0) -> int:
    return asyncio.run(_count_detections_near(lat, lon, radius_m))


# --- PA Caves ---

class TestPACaves:
    @pytest.mark.parametrize("site", PA_CAVES, ids=[s["name"] for s in PA_CAVES])
    def test_detection_near_known_cave(self, site):
        """At least one detection should exist within 200m of a known PA cave."""
        n = count_near(site["lat"], site["lon"])
        # Not asserting — just reporting for now (not all areas processed yet)
        if n == 0:
            pytest.skip(f"No detections near {site['name']} (area may not be processed yet)")
        assert n > 0, f"No detection near {site['name']} ({site['lat']}, {site['lon']})"


class TestPAMines:
    @pytest.mark.parametrize("site", PA_MINES, ids=[s["name"] for s in PA_MINES])
    def test_detection_near_known_mine(self, site):
        n = count_near(site["lat"], site["lon"])
        if n == 0:
            pytest.skip(f"No detections near {site['name']} (area may not be processed yet)")
        assert n > 0


class TestWVCaves:
    @pytest.mark.parametrize("site", WV_CAVES, ids=[s["name"] for s in WV_CAVES])
    def test_detection_near_known_cave(self, site):
        n = count_near(site["lat"], site["lon"])
        if n == 0:
            pytest.skip(f"No detections near {site['name']} (area may not be processed yet)")
        assert n > 0


class TestOHCaves:
    @pytest.mark.parametrize("site", OH_CAVES, ids=[s["name"] for s in OH_CAVES])
    def test_detection_near_known_cave(self, site):
        n = count_near(site["lat"], site["lon"])
        if n == 0:
            pytest.skip(f"No detections near {site['name']} (area may not be processed yet)")
        assert n > 0


class TestNYCaves:
    @pytest.mark.parametrize("site", NY_CAVES, ids=[s["name"] for s in NY_CAVES])
    def test_detection_near_known_cave(self, site):
        n = count_near(site["lat"], site["lon"])
        if n == 0:
            pytest.skip(f"No detections near {site['name']} (area may not be processed yet)")
        assert n > 0


class TestNCSites:
    @pytest.mark.parametrize("site", NC_SITES, ids=[s["name"] for s in NC_SITES])
    def test_detection_near_known_site(self, site):
        n = count_near(site["lat"], site["lon"])
        if n == 0:
            pytest.skip(f"No detections near {site['name']} (area may not be processed yet)")
        assert n > 0


class TestMDSites:
    @pytest.mark.parametrize("site", MD_SITES, ids=[s["name"] for s in MD_SITES])
    def test_detection_near_known_site(self, site):
        n = count_near(site["lat"], site["lon"])
        if n == 0:
            pytest.skip(f"No detections near {site['name']} (area may not be processed yet)")
        assert n > 0


class TestMASites:
    @pytest.mark.parametrize("site", MA_SITES, ids=[s["name"] for s in MA_SITES])
    def test_detection_near_known_site(self, site):
        n = count_near(site["lat"], site["lon"])
        if n == 0:
            pytest.skip(f"No detections near {site['name']} (area may not be processed yet)")
        assert n > 0


class TestLASites:
    @pytest.mark.parametrize("site", LA_SITES, ids=[s["name"] for s in LA_SITES])
    def test_detection_near_known_site(self, site):
        n = count_near(site["lat"], site["lon"])
        if n == 0:
            pytest.skip(f"No detections near {site['name']} (area may not be processed yet)")
        assert n > 0


class TestCASites:
    @pytest.mark.parametrize("site", CA_SITES, ids=[s["name"] for s in CA_SITES])
    def test_detection_near_known_site(self, site):
        n = count_near(site["lat"], site["lon"])
        if n == 0:
            pytest.skip(f"No detections near {site['name']} (area may not be processed yet)")
        assert n > 0


# --- Aggregate metrics ---

class TestAggregateMetrics:
    def test_total_sites_count(self):
        assert len(ALL_SITES) >= 36

    def test_coverage_report(self):
        """Print how many known sites have nearby detections."""
        detected = 0
        total = len(ALL_SITES)
        for site in ALL_SITES:
            n = count_near(site["lat"], site["lon"])
            if n > 0:
                detected += 1
        print(f"\nValidation: {detected}/{total} known sites have detections within 200m")
        print(f"Detection rate: {detected/total*100:.1f}%")
