"""Local DEM visualizations, computed before display resampling on native grids.

Only north-up projected metre grids are supported. Complete neighborhood support
is required. Compatible, explicitly identified survey tiles can supply adjacent
neighborhoods; unsupported borders and missing ground remain transparent.
"""

import io
import math

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject, transform_bounds
from rasterio.windows import Window
from rasterio.windows import bounds as window_bounds
from rasterio.windows import from_bounds as window_from_bounds
from scipy.ndimage import minimum_filter, uniform_filter

from lost_landscapes import terrain_horizon as horizon

VERSION = "native-v4-horizon"
LAYERS = ("slope", "local-relief", "hillshade", *horizon.LAYERS)
RADII = (10, 25, 50)
AZIMUTHS = tuple(range(0, 360, 45))
MIN_ZOOM = 14
MAX_SAMPLES = 4_000_000
MAX_TOTAL_SAMPLES = 8_000_000
MAX_NEIGHBOR_SOURCES = 32
METRE_UNITS = ("m", "metre", "meter", "metres", "meters")


def min_zoom(layer):
    return horizon.MIN_ZOOM if layer in horizon.LAYERS else MIN_ZOOM


def source_info(src):
    """Describe eligibility without silently interpreting degrees or feet as metres."""
    units = (src.units[0] or "").strip().lower()
    reason = None
    if not src.crs or not src.crs.is_projected or src.crs.to_epsg() == 3857:
        reason = "A local projected metre CRS is required"
    elif src.crs.linear_units_factor[1] != 1:
        reason = "Horizontal units must be metres"
    elif src.transform.b or src.transform.d or src.transform.a <= 0 or src.transform.e >= 0:
        reason = "A north-up grid is required"
    elif units not in ("", *METRE_UNITS):
        reason = "Elevation units must be metres"
    elif not all(math.isfinite(r) and r > 0 for r in src.res):
        reason = "Finite positive grid spacing is required"
    elif not all(math.isfinite(v) for v in (src.scales[0], src.offsets[0])):
        reason = "Finite elevation scale and offset are required"
    elif max(src.res) > 5:
        reason = "Source spacing exceeds 5 metres"
    tags = src.tags()
    survey = tags.get("LL_SURVEY_ID", "").strip()
    datum = tags.get("LL_VERTICAL_DATUM", "").strip()
    mosaic_reason = reason
    if not mosaic_reason and (not survey or not datum or units not in METRE_UNITS):
        mosaic_reason = (
            "Joining requires a declared survey ID, vertical datum and metre elevation units"
        )
    return {
        "eligible": reason is None,
        "reason": reason,
        "crs": src.crs.to_string() if src.crs else None,
        "resolution_m": list(src.res) if reason is None else None,
        "elevation_units": units if units else "assumed metres (not declared)",
        "elevation_scale": src.scales[0],
        "elevation_offset": src.offsets[0],
        "survey_id": survey or None,
        "vertical_datum": datum or None,
        "mosaic_eligible": mosaic_reason is None,
        "mosaic_reason": mosaic_reason,
        "horizon_radius_presets_m": [r for r in RADII if math.ceil(r / min(src.res)) <= horizon.MAX_RADIUS_CELLS]
        if reason is None else [],
        "effective_half_widths_m": {
            str(r): [math.ceil(r / src.res[0]) * src.res[0], math.ceil(r / src.res[1]) * src.res[1]]
            for r in RADII
        }
        if reason is None
        else {},
    }


def metadata(records):
    sources = []
    for record in records:
        with rasterio.open(record.path) as src:
            sources.append(
                {
                    "id": record.path.name,
                    "geographic_bounds": list(record.geographic_bounds),
                    **source_info(src),
                }
            )
    return {
        "layers": list(LAYERS),
        "min_zoom": MIN_ZOOM,
        "layer_min_zoom": {layer: min_zoom(layer) for layer in LAYERS},
        "horizon": {"directions": horizon.DIRECTIONS, "max_radius_cells": horizon.MAX_RADIUS_CELLS,
                    "max_sample_comparisons": horizon.MAX_WORK,
                    "svf_range": [0, 1], "openness_display_degrees": [60, 120],
                    "sampling": "Physical rays at thirds of the minimum cell spacing, snapped to native cells; full rectangular support required"},
        "radius_presets_m": list(RADII),
        "azimuth_presets": list(AZIMUTHS),
        "altitude_degrees": 45,
        "algorithm_version": VERSION,
        "radius_definition": "Square neighborhood half-width, rounded up to native cells",
        "local_relief_range_m": [-2, 2],
        "slope_range_degrees": [0, 60],
        "sources": sources,
        "limitations": "Local DEMs only. Joining requires the same declared survey and vertical datum, metre elevations, CRS, spacing and pixel alignment. Missing neighborhoods stay transparent. Zoom 14 or closer is required. Oversized windows or mosaics are skipped.",
        "mosaic_limits": {
            "window_samples": MAX_SAMPLES,
            "request_samples": MAX_TOTAL_SAMPLES,
            "sources_per_window": MAX_NEIGHBOR_SOURCES,
        },
    }


def compatible_sources(anchor, other):
    """Accept exact grid joins only; never reproject or harmonize vertical datums."""
    a, b = source_info(anchor), source_info(other)
    if not a["mosaic_eligible"] or not b["mosaic_eligible"]:
        return False
    if (a["survey_id"], a["vertical_datum"], anchor.crs) != (
        b["survey_id"],
        b["vertical_datum"],
        other.crs,
    ):
        return False
    if not all(
        math.isclose(x, y, rel_tol=1e-10, abs_tol=1e-12)
        for x, y in zip(anchor.res, other.res, strict=True)
    ):
        return False
    col = (other.transform.c - anchor.transform.c) / anchor.transform.a
    row = (other.transform.f - anchor.transform.f) / anchor.transform.e
    return all(abs(value - round(value)) <= 1e-6 for value in (col, row))


def intersects(a, b):
    return a[2] > b[0] and a[0] < b[2] and a[3] > b[1] and a[1] < b[3]


def read_neighborhood(anchor, records, window, read_budget):
    """Copy measured cells onto an aligned grid; return None if work exceeds limits.

    Records are ordered globally, so overlap preference is identical on both
    sides of a file boundary. Masked cells never become invented measurements.
    """
    extent = transform_bounds(
        anchor.crs, "EPSG:3857", *window_bounds(window, anchor.transform), densify_pts=21
    )
    elevation = np.full((int(window.height), int(window.width)), np.nan, dtype=np.float64)
    consumed, contributors = 0, 0
    for record in records:
        if not intersects(record.bounds, extent):
            continue
        with rasterio.open(record.path) as other:
            if str(record.path) != anchor.name and not compatible_sources(anchor, other):
                continue
            col = round((other.transform.c - anchor.transform.c) / anchor.transform.a)
            row = round((other.transform.f - anchor.transform.f) / anchor.transform.e)
            left, top = max(int(window.col_off), col), max(int(window.row_off), row)
            right = min(int(window.col_off + window.width), col + other.width)
            bottom = min(int(window.row_off + window.height), row + other.height)
            if right <= left or bottom <= top:
                continue
            count = (right - left) * (bottom - top)
            contributors += 1
            if contributors > MAX_NEIGHBOR_SOURCES or consumed + count > read_budget:
                return None, consumed
            consumed += count
            values = other.read(
                1, window=Window(left - col, top - row, right - left, bottom - top), masked=True
            )
            values = values.astype(np.float64).filled(np.nan)
            values = values * other.scales[0] + other.offsets[0]
            target = elevation[
                top - int(window.row_off) : bottom - int(window.row_off),
                left - int(window.col_off) : right - int(window.col_off),
            ]
            np.copyto(target, values, where=~np.isfinite(target) & np.isfinite(values))
    return elevation, consumed


def derivatives(elevation, spacing_x, spacing_y, layer, radius_m=25, azimuth=315):
    """Return physical scalar values (degrees, metres, or illumination 0..1)."""
    if layer not in LAYERS or radius_m not in RADII or azimuth not in AZIMUTHS:
        raise ValueError("Unsupported visualization option")
    if not all(math.isfinite(v) and v > 0 for v in (spacing_x, spacing_y)):
        raise ValueError("Spacing must be finite and positive")
    if layer in horizon.LAYERS:
        return horizon.horizon_views(elevation, spacing_x, spacing_y, radius_m, (layer,))[layer]
    values = np.asarray(elevation, dtype=np.float64)
    if values.ndim != 2:
        raise ValueError("Elevation must be a two-dimensional grid")
    if min(values.shape) < 3:
        return np.full(values.shape, np.nan, dtype=np.float32)
    valid = np.isfinite(values)
    clean = np.where(valid, values, 0)
    if layer == "local-relief":
        rx, ry = math.ceil(radius_m / spacing_x), math.ceil(radius_m / spacing_y)
        kernel = (2 * ry + 1, 2 * rx + 1)
        if kernel[0] > values.shape[0] or kernel[1] > values.shape[1]:
            return np.full(values.shape, np.nan, dtype=np.float32)
        support = uniform_filter(valid.astype(np.float64), size=kernel, mode="constant", cval=0)
        mean = uniform_filter(clean, size=kernel, mode="constant", cval=0)
        result = clean - mean
        valid = valid & (support >= 1 - 1e-12)
    else:
        valid = minimum_filter(valid, size=3, mode="constant", cval=0).astype(bool)
        dy, dx = np.gradient(clean, spacing_y, spacing_x)
        if layer == "slope":
            result = np.degrees(np.arctan(np.hypot(dx, dy)))
        else:
            az, alt = math.radians(azimuth), math.pi / 4
            result = np.clip(
                (
                    -dx * math.sin(az) * math.cos(alt)
                    + dy * math.cos(az) * math.cos(alt)
                    + math.sin(alt)
                )
                / np.sqrt(1 + dx * dx + dy * dy),
                0,
                1,
            )
    return np.where(valid, result, np.nan).astype(np.float32)


def colorize(values, layer):
    valid = np.isfinite(values)
    clean = np.nan_to_num(values)
    if layer == "local-relief":
        # Fixed diverging scale: blue depressions, ivory zero, orange raised relief.
        t = np.clip(clean / 2, -1, 1)[..., None]
        center = np.array([244, 240, 226])
        endpoint = np.where(t < 0, np.array([44, 112, 168]), np.array([194, 87, 35]))
        rgb = center + np.abs(t) * (endpoint - center)
    else:
        if layer in ("openness-positive", "openness-negative"):
            shade = np.clip((clean - 60) / 60, 0, 1)
        else:
            shade = np.clip(clean / 60, 0, 1) if layer == "slope" else np.clip(clean, 0, 1)
        if layer in ("slope", "openness-negative"):
            shade = 1 - shade
        rgb = np.repeat((shade * 255)[..., None], 3, axis=2)
    rgba = np.dstack((np.clip(rgb, 0, 255).astype(np.uint8), valid.astype(np.uint8) * 255))
    out = io.BytesIO()
    Image.fromarray(rgba).save(out, format="PNG")
    return out.getvalue()


def render(records, bounds, layer, radius_m=25, azimuth=315, size=512):
    """Bound native reads; compute first, warp scalars second, apply colour last."""
    if layer not in LAYERS or radius_m not in RADII or azimuth not in AZIMUTHS:
        raise ValueError("Unsupported visualization option")
    result = np.full((size, size), np.nan, dtype=np.float32)
    target = from_bounds(*bounds, size, size)
    consumed = 0
    horizon_work = 0
    ordered = sorted(records, key=lambda r: (r.resolution_m, str(r.path)))
    for record in ordered:
        if not intersects(record.bounds, bounds):
            continue
        with rasterio.open(record.path) as src:
            if not source_info(src)["eligible"]:
                continue
            native_bounds = transform_bounds("EPSG:3857", src.crs, *bounds, densify_pts=21)
            raw = window_from_bounds(*native_bounds, transform=src.transform)
            # Include interpolation neighbors as well as the complete filter halo.
            rx = math.ceil(radius_m / src.res[0]) if layer == "local-relief" else 1
            ry = math.ceil(radius_m / src.res[1]) if layer == "local-relief" else 1
            plan = None
            if layer in horizon.LAYERS:
                if radius_m not in source_info(src)["horizon_radius_presets_m"]:
                    continue
                plan = horizon.search_plan(src.res[0], src.res[1], radius_m)
                rx, ry = plan[:2]
            hx = rx + max(2, math.ceil(raw.width / size) + 1)
            hy = ry + max(2, math.ceil(raw.height / size) + 1)
            # Extend beyond this source to let compatible neighbors supply the halo.
            left = max(-hx, math.floor(raw.col_off) - hx)
            top = max(-hy, math.floor(raw.row_off) - hy)
            right = min(src.width + hx, math.ceil(raw.col_off + raw.width) + hx)
            bottom = min(src.height + hy, math.ceil(raw.row_off + raw.height) + hy)
            width, height = right - left, bottom - top
            samples = width * height
            comparisons = horizon.work((height, width), plan) if plan else 0
            if (
                width < 2 * rx + 1
                or height < 2 * ry + 1
                or samples > MAX_SAMPLES
                or consumed + samples > MAX_TOTAL_SAMPLES
                or horizon_work + comparisons > horizon.MAX_WORK
            ):
                continue
            window = Window(left, top, width, height)
            elevation, reads = read_neighborhood(src, ordered, window, MAX_TOTAL_SAMPLES - consumed)
            consumed += max(samples, reads)
            horizon_work += comparisons
            if elevation is None:
                continue
            scalar = derivatives(elevation, src.res[0], src.res[1], layer, radius_m, azimuth)
            patch = np.full_like(result, np.nan)
            reproject(
                scalar,
                patch,
                src_transform=src.window_transform(window),
                src_crs=src.crs,
                src_nodata=np.nan,
                dst_transform=target,
                dst_crs="EPSG:3857",
                dst_nodata=np.nan,
                resampling=Resampling.bilinear,
                num_threads=1,
            )
            # Warp the support separately so interpolation cannot bridge invalid cells.
            support = np.zeros_like(result)
            reproject(
                np.isfinite(scalar).astype(np.float32),
                support,
                src_transform=src.window_transform(window),
                src_crs=src.crs,
                dst_transform=target,
                dst_crs="EPSG:3857",
                dst_nodata=0,
                resampling=Resampling.bilinear,
                num_threads=1,
            )
            np.copyto(
                result,
                patch,
                where=np.isfinite(patch) & (support >= 1 - 1e-6) & ~np.isfinite(result),
            )
    return colorize(result, layer)
