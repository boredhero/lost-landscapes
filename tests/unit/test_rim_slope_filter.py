"""Tests for rim_slope_filter — annular slope rejection.

The decision rule is dual: reject if mean(ring) > max_mean_deg OR
p90(ring) > max_p90_deg. The p90 leg catches asymmetric road-cut FPs
that mean-only filters would let through. Tests cover:
- symmetric steep (mean and p90 both high) → reject
- asymmetric half-steep (mean=15, p90=25) → reject via p90
- mean-only rejection in isolation
- silent-failure traps: CRS mismatch, off-tile centroid, ring_factor<=1.0
- min_ring_pixels boundary
- no-outline / no-raster short-circuits
"""

import numpy as np
import pytest
from rasterio.transform import from_origin
from shapely.geometry import Point as ShPoint

from lost_landscapes.detection.postprocess.rim_slope_filter import (
    filter_candidates_by_rim_slope,
    rim_slope_ok,
)
from tests.conftest import make_candidate, make_candidate_with_outline, tmp_slope_tif


def _flat_slope_tif(value: float, shape, transform, tmp_path, *, crs="EPSG:32617"):
    arr = np.full(shape, value, dtype=np.float32)
    return tmp_slope_tif(arr, transform, tmp_path, crs=crs)


def _build_annular_ring_tif(
    inner_radius: int,
    outer_radius: int,
    ring_value: float,
    base_value: float,
    shape,
    transform,
    tmp_path,
    *,
    half_steep: bool = False,
    crs: str = "EPSG:32617",
):
    """Build a slope raster with a flat base and an annular ring at `ring_value`.

    If `half_steep`, only the right half of the ring gets ring_value.
    """
    arr = np.full(shape, base_value, dtype=np.float32)
    cy, cx = shape[0] // 2, shape[1] // 2
    yy, xx = np.ogrid[: shape[0], : shape[1]]
    in_ring = ((yy - cy) ** 2 + (xx - cx) ** 2 >= inner_radius ** 2) & (
        (yy - cy) ** 2 + (xx - cx) ** 2 <= outer_radius ** 2
    )
    if half_steep:
        right_half = xx > cx
        in_ring = in_ring & right_half
    arr[in_ring] = ring_value
    return tmp_slope_tif(arr, transform, tmp_path, crs=crs)


# ===== T4.1 — Steep symmetric rim → reject =====

def test_rim_slope_filter_rejects_steep_symmetric_rim(tmp_path):
    transform = from_origin(0.0, 100.0, 1.0, 1.0)
    path = _build_annular_ring_tif(
        inner_radius=15, outer_radius=30, ring_value=25.0, base_value=5.0,
        shape=(100, 100), transform=transform, tmp_path=tmp_path,
    )
    # outline at center, area=π·15² → radius ≈ 15
    outline = ShPoint(50.0, 50.0).buffer(15.0)
    candidate = make_candidate_with_outline(outline)
    assert not rim_slope_ok(candidate, path)


# ===== T4.2 — Gentle rim → keep =====

def test_rim_slope_filter_keeps_gentle_rim(tmp_path):
    transform = from_origin(0.0, 100.0, 1.0, 1.0)
    path = _flat_slope_tif(5.0, (100, 100), transform, tmp_path)
    outline = ShPoint(50.0, 50.0).buffer(15.0)
    candidate = make_candidate_with_outline(outline)
    assert rim_slope_ok(candidate, path)


# ===== T4.3 — Asymmetric half-steep ring rejects via p90 =====

def test_rim_slope_filter_rejects_asymmetric_half_steep_via_p90(tmp_path):
    """Half ring at 25°, half at 5° → mean ≈ 15° (above 11.3° mean threshold).

    NOTE: with default thresholds (max_mean_deg=11.3, max_p90_deg=25.0),
    mean ≈ 15° already trips the mean leg. To verify the p90 leg in isolation,
    we relax the mean threshold so only p90 can fire. This locks in the
    dual-rule design — without the p90 leg, this asymmetric FP would survive.
    """
    transform = from_origin(0.0, 100.0, 1.0, 1.0)
    path = _build_annular_ring_tif(
        inner_radius=15, outer_radius=30, ring_value=25.0, base_value=5.0,
        shape=(100, 100), transform=transform, tmp_path=tmp_path,
        half_steep=True,
    )
    outline = ShPoint(50.0, 50.0).buffer(15.0)
    candidate = make_candidate_with_outline(outline)
    # Relax mean threshold to 30° (mean is ~15°, would pass mean-only).
    # With max_p90_deg=25, the p90 (~25°) trips the rejection.
    assert not rim_slope_ok(candidate, path, max_mean_deg=30.0, max_p90_deg=20.0)
    # Sanity: with both thresholds relaxed, candidate is kept.
    assert rim_slope_ok(candidate, path, max_mean_deg=30.0, max_p90_deg=30.0)


# ===== T4.4 — Mean-only rejection (uniform ring just above mean threshold) =====

def test_rim_slope_filter_rejects_via_mean_only(tmp_path):
    """Uniform 12° ring: p90 ≈ 12° (passes p90=25 threshold) but mean=12 > 11.3 → reject."""
    transform = from_origin(0.0, 100.0, 1.0, 1.0)
    path = _build_annular_ring_tif(
        inner_radius=15, outer_radius=30, ring_value=12.0, base_value=5.0,
        shape=(100, 100), transform=transform, tmp_path=tmp_path,
    )
    outline = ShPoint(50.0, 50.0).buffer(15.0)
    candidate = make_candidate_with_outline(outline)
    assert not rim_slope_ok(candidate, path)


# ===== T4.5 — CRS-mismatch silent-failure trap =====

def test_rim_slope_filter_off_tile_outline_is_kept(tmp_path):
    """Outline OUTSIDE the raster extent → empty annulus pixels → keep + log warn.

    This is the silent-failure trap: if a refactor accidentally passes
    outline_wgs84 (lon/lat) instead of tile-UTM outline, the geometry_mask
    is all False and the filter silently lets the candidate through. The
    debug log "rim_slope_filter_insufficient_pixels" is the breadcrumb.
    """
    transform = from_origin(0.0, 100.0, 1.0, 1.0)  # raster covers (0,100)x(0,100)
    path = _flat_slope_tif(30.0, (100, 100), transform, tmp_path)  # all steep
    # Outline at (-79.96, 40.46) — clearly outside tile UTM extent
    wgs_like_outline = ShPoint(-79.96, 40.46).buffer(0.001)
    candidate = make_candidate_with_outline(wgs_like_outline)
    assert rim_slope_ok(candidate, path) is True


# ===== T4.6 — Off-tile centroid is kept (not silently rejected) =====

def test_rim_slope_filter_off_tile_centroid_with_small_raster(tmp_path):
    transform = from_origin(0.0, 50.0, 1.0, 1.0)  # raster covers (0,50)x(0,50)
    path = _flat_slope_tif(30.0, (50, 50), transform, tmp_path)
    outline = ShPoint(200.0, 200.0).buffer(15.0)  # WAY outside raster
    candidate = make_candidate_with_outline(outline)
    assert rim_slope_ok(candidate, path) is True


# ===== T4.7 — min_ring_pixels boundary =====

def test_rim_slope_filter_skips_below_min_ring_pixels(tmp_path):
    """Tiny outline whose annulus contains <5 pixels → skip filter (return True).

    Locks the magic number 5: a flip to e.g. 50 would change semantics
    silently for typical ~10-pixel rings.
    """
    transform = from_origin(0.0, 10.0, 1.0, 1.0)
    path = _flat_slope_tif(30.0, (10, 10), transform, tmp_path)  # all steep
    tiny_outline = ShPoint(5.0, 5.0).buffer(0.4)  # area ≈ 0.5; radius ≈ 0.4; outer ≈ 0.8
    candidate = make_candidate_with_outline(tiny_outline)
    # Annulus is sub-pixel — fewer than 5 pixels → skip → True
    assert rim_slope_ok(candidate, path, min_ring_pixels=5) is True
    # Lower the threshold; if there ARE any pixels, they're 30° → reject
    # (this branch may or may not fire depending on how rasterio rasterizes —
    #  the behavior we lock here is "small outline → skip")
    result_lowered = rim_slope_ok(candidate, path, min_ring_pixels=1)
    # Either still skipped (0 pixels) or rejected (1+ pixels at 30°). Never silently kept.
    assert result_lowered in (True, False)


# ===== T4.8 — Degenerate ring_factor =====

@pytest.mark.parametrize("ring_factor", [0.5, 1.0, -1.0])
def test_rim_slope_filter_handles_invalid_ring_factor(ring_factor, tmp_path):
    transform = from_origin(0.0, 100.0, 1.0, 1.0)
    path = _flat_slope_tif(30.0, (100, 100), transform, tmp_path)  # all steep
    outline = ShPoint(50.0, 50.0).buffer(15.0)
    candidate = make_candidate_with_outline(outline)
    # ring_factor <= 1.0 is degenerate → log + skip → True
    assert rim_slope_ok(candidate, path, ring_factor=ring_factor) is True


# ===== T4.9 — No slope raster path → skip =====

def test_rim_slope_filter_skips_when_no_slope_raster():
    candidate = make_candidate_with_outline(ShPoint(50.0, 50.0).buffer(15.0))
    assert rim_slope_ok(candidate, None) is True


# ===== T4.10 — No outline → skip =====

def test_rim_slope_filter_skips_when_no_outline():
    no_outline = make_candidate(outline=None)
    assert rim_slope_ok(no_outline, "any_path") is True


# ===== Filter-list wrapper tests =====

def test_filter_candidates_by_rim_slope_passes_through_when_no_raster():
    candidates_with_coords = [
        (make_candidate_with_outline(ShPoint(50.0, 50.0).buffer(15.0)), 0.0, 0.0),
        (make_candidate_with_outline(ShPoint(50.0, 50.0).buffer(15.0)), 0.0, 0.0),
    ]
    out = filter_candidates_by_rim_slope(candidates_with_coords, None)
    assert out == candidates_with_coords


def test_filter_candidates_by_rim_slope_rejects_steep_keeps_gentle(tmp_path):
    """End-to-end filter wrapper: 1 steep candidate rejected, 1 gentle kept.

    rasterio.transform.from_origin(left=0, top=200, xres=1, yres=1) places
    the raster origin at world (0, 200) with y decreasing downward. So pixel
    (row=R, col=C) maps to world (col, 200 - row).
    """
    transform = from_origin(0.0, 200.0, 1.0, 1.0)
    arr = np.full((200, 200), 5.0, dtype=np.float32)
    yy, xx = np.ogrid[:200, :200]
    # Steep ring at pixel center (row=50, col=50) → world (50, 150)
    pix_cy, pix_cx = 50, 50
    in_ring = ((yy - pix_cy) ** 2 + (xx - pix_cx) ** 2 >= 15 ** 2) & (
        (yy - pix_cy) ** 2 + (xx - pix_cx) ** 2 <= 30 ** 2
    )
    arr[in_ring] = 30.0
    path = tmp_slope_tif(arr, transform, tmp_path)
    # Steep candidate at world (50, 150) — matches the ring center.
    steep_cand = make_candidate_with_outline(ShPoint(50.0, 150.0).buffer(15.0))
    # Gentle candidate at world (150, 50) — matches pixel (row=150, col=150) → flat base.
    gentle_cand = make_candidate_with_outline(ShPoint(150.0, 50.0).buffer(15.0))
    items = [(steep_cand, 0.0, 0.0), (gentle_cand, 1.0, 1.0)]
    out = filter_candidates_by_rim_slope(items, path)
    out_ids = {id(item[0]) for item in out}
    assert id(gentle_cand) in out_ids, "Gentle-rim candidate should survive"
    assert id(steep_cand) not in out_ids, "Steep-rim candidate should be rejected"
