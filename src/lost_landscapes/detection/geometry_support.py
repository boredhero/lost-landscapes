"""Bounded native-grid inputs and shape measurements for experimental discovery."""

import numpy as np
from pyproj import CRS
from rasterio.features import shapes
from scipy import ndimage
from shapely.geometry import Point, shape

from lost_landscapes.detection.base import Candidate

VERSION = "0.1.0"
MAX_CELLS = 4_000_000
PASSES = {"raised_features", "linear_features", "enclosures", "repeated_patterns", "geological_forms"}


def spacing(transform, crs):
    reference = CRS.from_user_input(crs)
    if (not reference.is_projected or any(abs(axis.unit_conversion_factor - 1) > 1e-9 for axis in reference.axis_info[:2])
            or transform.b != 0 or transform.d != 0 or transform.a <= 0 or transform.e >= 0):
        raise ValueError("Discovery requires a north-up projected metre grid")
    dx, dy = transform.a, abs(transform.e)
    if not (0.25 <= dx <= 5 and 0.25 <= dy <= 5):
        raise ValueError("Discovery supports 0.25–5 metre cells")
    return dx, dy


def prepare(dem, transform, crs):
    """Compute physical 10/25m residuals once, before passes; never fill missing ground."""
    dx, dy = spacing(transform, crs)
    if dem.ndim != 2 or dem.size > MAX_CELLS or min(dem.shape) < 3:
        raise ValueError("Discovery requires a 2D DEM of at most 4 million cells; split larger tiles")
    valid = np.isfinite(dem)
    clean = np.where(valid, dem, 0).astype(np.float32)
    result = {}
    for radius in (10, 25):
        window = (2 * int(np.ceil(radius / dy)) + 1, 2 * int(np.ceil(radius / dx)) + 1)
        support = ndimage.minimum_filter(valid.astype(np.uint8), size=window, mode="constant", cval=0).astype(bool)
        residual = clean - ndimage.uniform_filter(clean, size=window, mode="constant")
        result[f"discovery_lrm_{radius}"] = np.where(support, residual, np.nan)
    gy, gx = np.gradient(clean, dy, dx)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    support = ndimage.minimum_filter(valid.astype(np.uint8), size=3, mode="constant", cval=0).astype(bool)
    result["discovery_slope"] = np.where(support, slope, np.nan)
    return result


def regions(mask, transform, min_area, max_area, limit=200):
    """Bound polygon work; enumerate largest connected regions deterministically."""
    labels, count = ndimage.label(mask)  # Four-connected: diagonal contacts are not continuous banks.
    if count > 20000:
        raise ValueError("Discovery mask exceeds 20,000 components; inspect noise or raise the relief threshold")
    areas = np.bincount(labels.ravel()) * abs(transform.a * transform.e)
    eligible = np.flatnonzero((areas >= min_area) & (areas <= max_area))
    eligible = eligible[eligible != 0]
    chosen = sorted(eligible, key=lambda i: (-areas[i], int(i)))[:limit]
    slices = ndimage.find_objects(labels)
    for index in chosen:
        window = slices[index - 1]
        component = labels[window] == index
        # Do not turn clipped features into complete geometry.
        if window[0].start == 0 or window[1].start == 0 or window[0].stop == mask.shape[0] or window[1].stop == mask.shape[1]:
            continue
        local_transform = transform * type(transform).translation(window[1].start, window[0].start)
        polygons = [shape(g) for g, value in shapes(component.astype(np.uint8), mask=component, transform=local_transform) if value]
        polygon = max(polygons, key=lambda p: p.area)
        if polygon.is_valid and polygon.area > 0:
            yield polygon, window, component


def metrics(polygon):
    corners = list(polygon.minimum_rotated_rectangle.exterior.coords)
    lengths = [Point(corners[i]).distance(Point(corners[i + 1])) for i in range(4)]
    length, width = max(lengths), min(lengths)
    return {"area_m2": polygon.area, "length_m": length, "width_m": width,
            "aspect_ratio": length / max(width, 1e-9), "rectangularity": polygon.area / max(length * width, 1e-9),
            "circularity": min(1.0, 4 * np.pi * polygon.area / max(polygon.length**2, 1e-9))}


def candidate(pass_name, feature_type, polygon, measurements, parameters, explanation, score=None):
    if score is None:
        if "spacing_cv" in measurements:
            strength = max(0., 1 - measurements["spacing_cv"])
        elif "interior_area_m2" in measurements:
            strength = min(1., measurements["interior_area_m2"] / (4 * parameters.get("min_interior_m2", 50)))
        elif "mean_slope_deg" in measurements:
            strength = min(1., measurements["mean_slope_deg"] / 90)
        else:
            contrast = abs(measurements.get("signed_relief_m", measurements.get("height_residual_m", 0)))
            strength = 1 - np.exp(-contrast / (3 * parameters.get("threshold_m", 0.5)))
        score = 0.4 + 0.4 * strength
    # Keep exported geometry compatible with investigations' 500-vertex limit.
    tolerance = 0.1
    while sum(len(r.coords) for r in [polygon.exterior, *polygon.interiors]) > 480:
        polygon = polygon.simplify(tolerance, preserve_topology=True)
        tolerance *= 2
        if tolerance > 10000:
            raise ValueError("Candidate geometry exceeds export limit")
    return Candidate(geometry=polygon.representative_point(), outline=polygon, score=float(score), feature_type=feature_type,
                     morphometrics={k: float(v) for k, v in measurements.items()}, metadata={
                         "experimental": True, "algorithm": pass_name, "algorithm_version": VERSION,
                         "source_passes": [pass_name], "parameters": parameters, "explanation": explanation,
                         "score_kind": "heuristic ranking, not probability", "evaluation": "synthetic only; regional review required",
                         "alternatives": ["natural landform", "modern land use", "survey or processing artifact"],
                         "per_pass": [{"pass_name": pass_name, "score": float(score), "morphometrics": measurements}],
                     })


def bounded_parameters(config, defaults):
    unknown = set(config) - set(defaults)
    if unknown:
        raise ValueError(f"Unknown discovery parameters: {sorted(unknown)}")
    result = {**defaults, **config}
    for key, value in result.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or not 0 < value <= 100000:
            raise ValueError(f"Invalid discovery parameter: {key}")
    if result.get("min_area_m2", 0) > result.get("max_area_m2", float("inf")):
        raise ValueError("Minimum area exceeds maximum")
    if "min_members" in result and (int(result["min_members"]) != result["min_members"] or not 3 <= result["min_members"] <= 200):
        raise ValueError("Repeated patterns require 3–200 members")
    if "max_spacing_cv" in result and result["max_spacing_cv"] > 1:
        raise ValueError("Spacing coefficient of variation must be at most 1")
    if any(key.endswith("slope_deg") and value > 90 for key, value in result.items()):
        raise ValueError("Slope thresholds must be at most 90 degrees")
    return result


def supported_mask(values, threshold, sign=1):
    valid = np.isfinite(values)
    # An extra pixel prevents threshold components touching incomplete neighborhoods.
    interior = ndimage.binary_erosion(valid)
    mask = interior & (np.nan_to_num(values) * sign >= threshold)
    labels, _ = ndimage.label(mask)
    touching = np.unique(labels[ndimage.binary_dilation(~interior)])
    return mask & ~np.isin(labels, touching[touching != 0])
