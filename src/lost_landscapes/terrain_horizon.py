"""Bounded native-grid horizon views, using the RVT visible-sky convention.

Reference: EarthObservation/RVT_py, rvt.vis.sky_view_factor (16 directions,
noise removal disabled). Unlike RVT's edge padding, missing support stays NaN.
"""

import math
from functools import lru_cache

import numpy as np
from scipy.ndimage import minimum_filter

LAYERS = ("svf", "openness-positive", "openness-negative")
ADVANCED_LAYERS = (*LAYERS, "vat")
DIRECTIONS = 16
MAX_RADIUS_CELLS = 128
MAX_WORK = 240_000_000  # sampled cell comparisons per request, not elapsed time
MIN_ZOOM = 16
VAT_RECIPE = {
    "name": "RVT general-terrain VAT with shared metre search radius",
    "hillshade": {"azimuth": 315, "altitude": 35, "range": [0, 1]},
    "slope": {"range_degrees": [0, 50], "inverted": True, "blend": "luminosity", "opacity": 0.5},
    "openness_positive": {"range_degrees": [68, 93], "blend": "overlay", "opacity": 0.5},
    "svf": {"range": [0.7, 1], "blend": "multiply", "opacity": 0.25},
    "order_bottom_to_top": ["hillshade", "slope", "openness_positive", "svf"],
}


def blend_vat(slope_degrees, hillshade, svf, openness_degrees):
    """Fixed RVT general-terrain ranges and standard grayscale blend semantics."""
    slope = 1 - np.clip(slope_degrees / 50, 0, 1)
    openness = np.clip((openness_degrees - 68) / 25, 0, 1)
    sky = np.clip((svf - 0.7) / 0.3, 0, 1)
    # For grayscale inputs, luminosity blend gives the active grayscale value.
    base = 0.5 * np.clip(hillshade, 0, 1) + 0.5 * slope
    overlay = np.where(base <= 0.5, 2 * base * openness,
                       1 - 2 * (1 - base) * (1 - openness))
    base = 0.5 * base + 0.5 * overlay
    return (base * (0.75 + 0.25 * sky)).astype(np.float32)


def vat(elevation, spacing_x, spacing_y, radius_m):
    """Blend four physical native-grid views, preserving shared missing support."""
    views = horizon_views(elevation, spacing_x, spacing_y, radius_m, ("svf", "openness-positive"))
    values = np.asarray(elevation, dtype=np.float64)
    if min(values.shape) < 3:
        return views["svf"]
    dy, dx = np.gradient(values, spacing_y, spacing_x)
    slope = np.degrees(np.arctan(np.hypot(dx, dy)))
    az, alt = math.radians(315), math.radians(35)
    shade = np.clip((-dx * math.sin(az) * math.cos(alt) + dy * math.cos(az) * math.cos(alt)
                     + math.sin(alt)) / np.sqrt(1 + dx * dx + dy * dy), 0, 1)
    return blend_vat(slope, shade, views["svf"], views["openness-positive"])


@lru_cache(maxsize=128)
def search_plan(spacing_x, spacing_y, radius_m):
    """Physical rays snapped to cells; square-grid sampling agrees with RVT.

    Samples start at one minimum cell spacing, at thirds of that spacing. The
    nominal radius rounds up to that spacing; snapped endpoints can lie up to
    half a cell diagonal beyond it. Actual physical distances determine angles.
    """
    if not all(math.isfinite(v) and v > 0 for v in (spacing_x, spacing_y, radius_m)):
        raise ValueError("Grid spacing and search radius must be finite and positive")
    step = min(spacing_x, spacing_y)
    cells = math.ceil(radius_m / step)
    if cells > MAX_RADIUS_CELLS:
        raise ValueError("Horizon radius exceeds 128 native cells")
    distances = (np.arange((cells - 1) * 3 + 1) / 3 + 1) * step
    rays = []
    for angle in np.arange(DIRECTIONS) * (2 * np.pi / DIRECTIONS):
        rows = np.rint(np.cos(angle) * distances / spacing_y).astype(int)
        cols = np.rint(np.sin(angle) * distances / spacing_x).astype(int)
        offsets = sorted(set(zip(rows.tolist(), cols.tolist())) - {(0, 0)})
        if not offsets:
            raise ValueError("Search radius does not reach a native cell in every direction")
        rays.append(tuple((row, col, math.hypot(row * spacing_y, col * spacing_x))
                          for row, col in offsets))
    ry = max(abs(row) for ray in rays for row, _, _ in ray)
    rx = max(abs(col) for ray in rays for _, col, _ in ray)
    return rx, ry, tuple(rays)


def work(shape, plan):
    rx, ry, rays = plan
    return max(0, shape[0] - 2 * ry) * max(0, shape[1] - 2 * rx) * sum(map(len, rays))


def horizon_views(elevation, spacing_x, spacing_y, radius_m, products=LAYERS):
    """Return dimensionless SVF and/or positive/negative openness in degrees."""
    if not products or any(p not in LAYERS for p in products):
        raise ValueError("Unknown horizon product")
    values = np.asarray(elevation, dtype=np.float64)
    if values.ndim != 2:
        raise ValueError("Elevation must be a two-dimensional grid")
    plan = search_plan(spacing_x, spacing_y, radius_m)
    rx, ry, rays = plan
    result = {p: np.full(values.shape, np.nan, dtype=np.float32) for p in products}
    if values.shape[0] <= 2 * ry or values.shape[1] <= 2 * rx:
        return result
    positive = "svf" in products or "openness-positive" in products
    negative = "openness-negative" in products
    if work(values.shape, plan) * (2 if positive and negative else 1) > MAX_WORK:
        raise ValueError("Horizon work exceeds the bounded calculation limit")
    support = minimum_filter(np.isfinite(values), size=(2 * ry + 1, 2 * rx + 1),
                             mode="constant", cval=0)[ry:-ry, rx:-rx]
    center = values[ry:-ry, rx:-rx]
    if not support.any():
        return result
    totals = {p: np.zeros(center.shape, dtype=np.float64) for p in products}
    height, width = center.shape
    for ray in rays:
        high = np.full(center.shape, -np.inf) if positive else None
        low = np.full(center.shape, -np.inf) if negative else None
        for row, col, distance in ray:
            slope = (values[ry+row:ry+row+height, rx+col:rx+col+width] - center) / distance
            if positive:
                np.maximum(high, slope, out=high)
            if negative:
                np.maximum(low, -slope, out=low)
        if positive:
            angle = np.arctan(high)
            if "svf" in totals:
                totals["svf"] += 1 - np.sin(np.maximum(angle, 0))
            if "openness-positive" in totals:
                totals["openness-positive"] += angle
        if negative:
            totals["openness-negative"] += np.arctan(low)
    for product, total in totals.items():
        scalar = total / DIRECTIONS
        if product != "svf":
            scalar = 90 - np.degrees(scalar)
        result[product][ry:-ry, rx:-rx] = np.where(support, scalar, np.nan)
    return result
