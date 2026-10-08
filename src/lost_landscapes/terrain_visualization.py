"""Local DEM visualizations, computed before display resampling on native grids.

Only north-up projected metre grids are supported. Complete neighborhood support
is required: source borders and gaps remain transparent rather than inventing
terrain. Different source tiles are not stitched for neighborhood calculations.
"""

import io
import math

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject, transform_bounds
from rasterio.windows import Window
from rasterio.windows import from_bounds as window_from_bounds
from scipy.ndimage import minimum_filter, uniform_filter

VERSION = "native-v2"
LAYERS = ("slope", "local-relief", "hillshade")
RADII = (10, 25, 50)
AZIMUTHS = tuple(range(0, 360, 45))
MIN_ZOOM = 14
MAX_SAMPLES = 4_000_000
MAX_TOTAL_SAMPLES = 8_000_000


def source_info(src):
    """Describe eligibility without silently interpreting degrees or feet as metres."""
    units = (src.units[0] or "").lower()
    reason = None
    if not src.crs or not src.crs.is_projected or src.crs.to_epsg() == 3857:
        reason = "A local projected metre CRS is required"
    elif src.crs.linear_units_factor[1] != 1:
        reason = "Horizontal units must be metres"
    elif src.transform.b or src.transform.d or src.transform.a <= 0 or src.transform.e >= 0:
        reason = "A north-up grid is required"
    elif units not in ("", "m", "metre", "meter", "metres", "meters"):
        reason = "Elevation units must be metres"
    elif not all(math.isfinite(r) and r > 0 for r in src.res):
        reason = "Finite positive grid spacing is required"
    elif not all(math.isfinite(v) for v in (src.scales[0], src.offsets[0])):
        reason = "Finite elevation scale and offset are required"
    elif max(src.res) > 5:
        reason = "Source spacing exceeds 5 metres"
    return {
        "eligible": reason is None,
        "reason": reason,
        "crs": src.crs.to_string() if src.crs else None,
        "resolution_m": list(src.res) if reason is None else None,
        "elevation_units": units if units else "assumed metres (not declared)",
        "elevation_scale": src.scales[0],
        "elevation_offset": src.offsets[0],
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
        "radius_presets_m": list(RADII),
        "azimuth_presets": list(AZIMUTHS),
        "altitude_degrees": 45,
        "algorithm_version": VERSION,
        "radius_definition": "Square neighborhood half-width, rounded up to native cells",
        "local_relief_range_m": [-2, 2],
        "slope_range_degrees": [0, 60],
        "sources": sources,
        "limitations": "Local DEMs only. Complete native neighborhoods are required; source edges and missing data stay transparent. Views below zoom 14 are unavailable. Oversized source windows are skipped.",
    }


def derivatives(elevation, spacing_x, spacing_y, layer, radius_m=25, azimuth=315):
    """Return physical scalar values (degrees, metres, or illumination 0..1)."""
    if layer not in LAYERS or radius_m not in RADII or azimuth not in AZIMUTHS:
        raise ValueError("Unsupported visualization option")
    if not all(math.isfinite(v) and v > 0 for v in (spacing_x, spacing_y)):
        raise ValueError("Spacing must be finite and positive")
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
        shade = np.clip(clean / 60, 0, 1) if layer == "slope" else np.clip(clean, 0, 1)
        if layer == "slope":
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
    for record in sorted(records, key=lambda r: (r.resolution_m, str(r.path))):
        if (
            record.bounds[2] <= bounds[0]
            or record.bounds[0] >= bounds[2]
            or record.bounds[3] <= bounds[1]
            or record.bounds[1] >= bounds[3]
        ):
            continue
        with rasterio.open(record.path) as src:
            if not source_info(src)["eligible"]:
                continue
            native_bounds = transform_bounds("EPSG:3857", src.crs, *bounds, densify_pts=21)
            raw = window_from_bounds(*native_bounds, transform=src.transform)
            # Include interpolation neighbors as well as the complete filter halo.
            rx = math.ceil(radius_m / src.res[0]) if layer == "local-relief" else 1
            ry = math.ceil(radius_m / src.res[1]) if layer == "local-relief" else 1
            hx = rx + max(2, math.ceil(raw.width / size) + 1)
            hy = ry + max(2, math.ceil(raw.height / size) + 1)
            left = max(0, math.floor(raw.col_off) - hx)
            top = max(0, math.floor(raw.row_off) - hy)
            right = min(src.width, math.ceil(raw.col_off + raw.width) + hx)
            bottom = min(src.height, math.ceil(raw.row_off + raw.height) + hy)
            width, height = right - left, bottom - top
            samples = width * height
            if (
                width < 2 * rx + 1
                or height < 2 * ry + 1
                or samples > MAX_SAMPLES
                or consumed + samples > MAX_TOTAL_SAMPLES
            ):
                continue
            consumed += samples
            window = Window(left, top, width, height)
            elevation = src.read(1, window=window, masked=True).astype(np.float64).filled(np.nan)
            elevation *= src.scales[0]
            elevation += src.offsets[0]
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
