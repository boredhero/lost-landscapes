"""Reject candidates whose surrounding rim has steep slope (mean OR p90).

Road cut-and-fill banks have steep linear rims, often asymmetric (one side
cut, one side flat). Natural sinks and karst have gentle rims throughout.
Doctor & Young (2013) — annular slope > 20% reject.

Decision rule (dual): reject if mean(ring) > max_mean_deg OR
p90(ring) > max_p90_deg. The p90 leg catches asymmetric road-cut FPs
(e.g. half ring at 25°, half at 5° → mean ≈ 15° passes a mean-only filter,
p90 ≈ 25° rejects).

Slope raster is in degrees (default WBT/GDAL output, verified locally on
/data/lost-landscapes/processed/.../slope.tif: range 0–83.7°, mean 7.6°).

CRS invariant: candidate.outline must be in TILE UTM (same CRS as slope
raster). NEVER use candidate.outline_wgs84 here — that would silently fail
because geometry_mask returns all-False outside the raster's UTM extent,
and the filter would let every candidate through.
"""

import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from shapely.geometry import Point as ShPoint

from lost_landscapes.detection.base import Candidate
from lost_landscapes.utils.log_manager import log


def rim_slope_ok(
    candidate: Candidate,
    slope_raster_path: Path | None,
    *,
    ring_factor: float = 2.0,
    max_mean_deg: float = 11.3,    # = atan(0.20) = 20% rise/run
    max_p90_deg: float = 25.0,
    min_ring_pixels: int = 5,
) -> bool:
    """Return True if the candidate's rim is gentle enough to be a real depression.

    Returns True (keep) when:
      - slope_raster_path is None
      - candidate has no outline / outline is empty / area <= 0
      - ring_factor <= 1.0 (degenerate annulus — log warning, skip)
      - annulus is empty after raster intersection (e.g. centroid off-tile)
      - ring samples fewer than min_ring_pixels
      - mean(ring) <= max_mean_deg AND p90(ring) <= max_p90_deg

    Returns False (reject) only when we successfully computed annular slope
    and EITHER mean OR p90 exceeds its threshold.
    """
    if slope_raster_path is None:
        return True
    outline = candidate.outline
    if outline is None or outline.is_empty:
        return True
    if ring_factor <= 1.0:
        log.warning("rim_slope_filter_invalid_ring_factor", ring_factor=ring_factor)
        return True
    try:
        with rasterio.open(slope_raster_path) as src:
            slope = src.read(1)
            transform = src.transform
            shape = slope.shape
            cx, cy = outline.centroid.x, outline.centroid.y
            area_m2 = outline.area
            if area_m2 <= 0:
                return True
            radius_m = math.sqrt(area_m2 / math.pi)
            outer_m = radius_m * ring_factor
            inner_disk = ShPoint(cx, cy).buffer(radius_m)
            outer_disk = ShPoint(cx, cy).buffer(outer_m)
            annulus = outer_disk.difference(inner_disk)
            if annulus.is_empty:
                return True
            mask = geometry_mask([annulus], out_shape=shape, transform=transform, invert=True)
            ring_pixels = slope[mask]
            ring_pixels = ring_pixels[np.isfinite(ring_pixels)]
            if ring_pixels.size < min_ring_pixels:
                log.debug("rim_slope_filter_insufficient_pixels", n=int(ring_pixels.size), min=min_ring_pixels)
                return True
            mean_deg = float(np.mean(ring_pixels))
            p90_deg = float(np.percentile(ring_pixels, 90))
            log.debug("rim_slope_check", mean_deg=round(mean_deg, 2), p90_deg=round(p90_deg, 2), area_m2=round(area_m2, 1), radius_m=round(radius_m, 2))
            return (mean_deg <= max_mean_deg) and (p90_deg <= max_p90_deg)
    except (rasterio.RasterioIOError, ValueError) as e:
        log.warning("rim_slope_filter_error", error=str(e))
        return True


def filter_candidates_by_rim_slope(
    candidates_with_coords: list[tuple],
    slope_raster_path: Path | None,
    *,
    ring_factor: float = 2.0,
    max_mean_deg: float = 11.3,
    max_p90_deg: float = 25.0,
    min_ring_pixels: int = 5,
) -> list[tuple]:
    """Apply rim slope filter to a list of (candidate, lon, lat) tuples."""
    if slope_raster_path is None:
        log.info("rim_slope_filter_skipped", reason="no_slope_raster")
        return candidates_with_coords
    keep = []
    rejected = 0
    for item in candidates_with_coords:
        c = item[0]
        if rim_slope_ok(
            c, slope_raster_path,
            ring_factor=ring_factor,
            max_mean_deg=max_mean_deg,
            max_p90_deg=max_p90_deg,
            min_ring_pixels=min_ring_pixels,
        ):
            keep.append(item)
        else:
            rejected += 1
    log.info("rim_slope_filter_result", total=len(candidates_with_coords), kept=len(keep), rejected=rejected, max_mean_deg=max_mean_deg, max_p90_deg=max_p90_deg)
    return keep
