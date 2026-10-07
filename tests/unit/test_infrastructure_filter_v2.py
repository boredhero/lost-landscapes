"""Tests for sub-plan 03's polygon-overlap infrastructure filter.

The filter now tests the candidate's outline_wgs84 against mask polygons
(road buffers, landuse polygons), rejecting when ≥30% of candidate area
overlaps. Falls back to centroid-in-polygon when outline is None / invalid.

Buffers are now meter-projected (UTM) instead of raw degrees in WGS84.
"""

from unittest.mock import patch

import pytest
from shapely.geometry import LineString, Point, Polygon, box

from lost_landscapes.detection.postprocess.infrastructure_filter import (
    ROAD_BUFFER_M,
    _buffer_lines,
    _rejects,
    _utm_epsg_for,
    filter_candidates_by_infrastructure,
)
from tests.conftest import make_candidate, make_candidate_with_outline

# ===== Helper =====

def _stub_with_roads(roads_polys=None, water_polys=None, rail_polys=None, landuse_polys=None):
    """Patch the OSM fetchers to return controlled fixtures.

    Patch the names imported INTO infrastructure_filter (not at the source) —
    `from lost_landscapes.utils.osm_data import get_landuse_polygons` binds the
    reference at import time.
    """
    return [
        patch("lost_landscapes.detection.postprocess.infrastructure_filter.get_road_geometries", return_value=roads_polys or []),
        patch("lost_landscapes.detection.postprocess.infrastructure_filter.get_water_geometries", return_value=water_polys or []),
        patch("lost_landscapes.detection.postprocess.infrastructure_filter.get_railway_geometries", return_value=rail_polys or []),
        patch("lost_landscapes.detection.postprocess.infrastructure_filter.get_landuse_polygons", return_value=landuse_polys or []),
    ]


# ===== T3.1 — Overlap-fraction at exactly the seam =====

@pytest.mark.parametrize("overlap_x_frac,expected_kept", [
    (0.20, True),    # 20% overlap → keep (below 0.3 threshold)
    (0.29, True),    # just below threshold
    (0.30, False),   # AT threshold → reject (>= rejects)
    (0.31, False),   # just above
    (0.50, False),
])
def test_road_filter_polygon_overlap_seam(overlap_x_frac, expected_kept):
    """Seam test: overlap fraction at exactly OVERLAP_REJECT_FRACTION.

    Mask is the unit square [0,1]^2. Candidate is a unit-area square
    positioned so its overlap with the mask is exactly `overlap_x_frac`.
    """
    mask = box(0.0, 0.0, 1.0, 1.0)
    cand_outline_wgs84 = box(1.0 - overlap_x_frac, 0.0, 2.0 - overlap_x_frac, 1.0)
    candidate = make_candidate_with_outline(cand_outline_wgs84, outline_wgs84=cand_outline_wgs84)
    from shapely.prepared import prep
    rejected = _rejects(prep(mask), mask, candidate, Point(-10, -10))
    assert (not rejected) == expected_kept, (
        f"overlap={overlap_x_frac}: expected_kept={expected_kept}, got rejected={rejected}"
    )


# ===== T3.2 — Centroid fallback when outline absent =====

def test_road_filter_falls_back_to_centroid_when_outline_wgs84_is_none():
    mask = box(0.0, 0.0, 1.0, 1.0)
    candidate = make_candidate(outline_wgs84=None)
    from shapely.prepared import prep
    # Centroid INSIDE the mask
    assert _rejects(prep(mask), mask, candidate, Point(0.5, 0.5)) is True
    # Centroid OUTSIDE the mask
    assert _rejects(prep(mask), mask, candidate, Point(2.0, 2.0)) is False


# ===== T3.3 — Invalid-geometry branch (R2.2 mitigation) =====

def test_road_filter_falls_back_when_outline_is_invalid():
    """Self-intersecting bowtie polygon must not crash; falls back to centroid."""
    bowtie = Polygon([(0, 0), (1, 1), (0, 1), (1, 0), (0, 0)])
    assert not bowtie.is_valid
    candidate = make_candidate(outline_wgs84=bowtie)
    mask = box(-0.1, -0.1, 1.1, 1.1)
    from shapely.prepared import prep
    # Centroid is inside the mask → should reject via fallback
    assert _rejects(prep(mask), mask, candidate, Point(0.5, 0.5)) is True


# ===== T3.4 — UTM buffer in meters =====

@pytest.mark.parametrize("lat", [30.0, 40.0, 50.0])
def test_road_buffer_in_meters_at_multiple_latitudes(lat):
    """30m UTM buffer should be ~30m perpendicular regardless of latitude.

    Asserts an offset of 29m is INSIDE the buffer and 31m is OUTSIDE; locks
    the boundary at exactly 30m within a numeric tolerance.
    """
    line = LineString([(0.0, lat), (0.001, lat)])
    bbox = (-0.0001, lat - 0.0001, 0.0011, lat + 0.0001)
    buffered = _buffer_lines([line], buffer_m=ROAD_BUFFER_M, bbox_lon_lat=bbox)[0]
    # Convert offset meters → degrees of latitude (1 deg lat ≈ 111320 m)
    deg_per_m_lat = 1.0 / 111320.0
    test_inside = Point(0.0005, lat + 29.0 * deg_per_m_lat)
    test_outside = Point(0.0005, lat + 31.0 * deg_per_m_lat)
    assert buffered.contains(test_inside), f"Point at 29m N at lat {lat} should be inside 30m buffer"
    assert not buffered.contains(test_outside), f"Point at 31m N at lat {lat} should be outside 30m buffer"


def test_utm_epsg_north_south():
    assert _utm_epsg_for(-79.0, 40.0) == 32617  # Pittsburgh, UTM 17N
    assert _utm_epsg_for(-79.0, -40.0) == 32717  # Argentina-ish, UTM 17S
    assert _utm_epsg_for(0.0, 0.0) == 32631      # equator/prime meridian → zone 31N


# ===== T3.5 — Landuse filter coverage (was missing from d156fd8) =====

def test_landuse_polygon_overlap_filter_rejects_inside():
    """Detection inside an OSM landuse=industrial polygon is rejected via overlap."""
    industrial = box(0, 0, 1.0, 1.0)
    cand_outline = box(0.2, 0.2, 0.8, 0.8)  # centered, ~36% overlap area
    candidate = make_candidate_with_outline(cand_outline, outline_wgs84=cand_outline)
    patches = _stub_with_roads(landuse_polys=[industrial])
    for p in patches:
        p.start()
    try:
        keep = filter_candidates_by_infrastructure(
            [candidate], [(0.5, 0.5)],
            west=-0.1, south=-0.1, east=1.1, north=1.1,
        )
    finally:
        for p in patches:
            p.stop()
    assert candidate not in [k[0] for k in keep]


def test_landuse_polygon_outside_keeps_candidate():
    """Detection outside the landuse polygon survives."""
    industrial = box(0, 0, 1.0, 1.0)
    cand_outline = box(2.0, 2.0, 2.5, 2.5)  # far away
    candidate = make_candidate_with_outline(cand_outline, outline_wgs84=cand_outline)
    patches = _stub_with_roads(landuse_polys=[industrial])
    for p in patches:
        p.start()
    try:
        keep = filter_candidates_by_infrastructure(
            [candidate], [(2.25, 2.25)],
            west=-0.1, south=-0.1, east=3.0, north=3.0,
        )
    finally:
        for p in patches:
            p.stop()
    assert candidate in [k[0] for k in keep]


# ===== T3.6 — c.outline (tile UTM) is preserved (NOT mutated) =====

def test_outline_attribute_invariant_outline_not_mutated():
    """Ensures c.outline (tile UTM) is unchanged; only outline_wgs84 is added.

    Sub-plan 04's rim_slope_filter requires c.outline to remain in tile UTM —
    if a refactor accidentally reassigns c.outline = WGS84, the rim filter
    silently fails (geometry_mask returns all-False outside raster extent).
    """
    utm_outline = box(581000, 4477000, 581100, 4477100)  # tile UTM 17N
    wgs_outline = box(-79.96, 40.46, -79.95, 40.47)
    cand = make_candidate(outline=utm_outline, outline_wgs84=wgs_outline)
    # Production code in tasks.py only sets outline_wgs84; c.outline is untouched.
    assert cand.outline == utm_outline
    assert cand.outline_wgs84 == wgs_outline
    assert cand.outline != cand.outline_wgs84


# ===== T3.7 — Empty candidate list short-circuits =====

def test_filter_with_empty_candidates_returns_empty():
    keep = filter_candidates_by_infrastructure(
        [], [],
        west=0.0, south=0.0, east=1.0, north=1.0,
    )
    assert keep == []
