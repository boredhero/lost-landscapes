"""Shared test fixtures and factories."""

import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from shapely.geometry import Point, Polygon

from lost_landscapes.detection.base import Candidate, FeatureType

# Resolve project root from this file's location (tests/conftest.py → project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def make_candidate(
    *,
    score: float = 0.5,
    area_m2: float = 50.0,
    depth_m: float = 0.8,
    elongation: float | None = None,
    circularity: float | None = None,
    perimeter_m: float | None = None,
    wall_slope_deg: float | None = None,
    lrm_anomaly_m: float | None = None,
    outline: Polygon | None = None,
    outline_wgs84: Polygon | None = None,
    geometry: Point | None = None,
    feature_type: FeatureType = FeatureType.UNKNOWN,
    morphometrics_extra: dict | None = None,
    metadata_extra: dict | None = None,
) -> Candidate:
    """Unified test factory for Candidate objects.

    Shape keys (elongation, circularity, perimeter_m, wall_slope_deg,
    lrm_anomaly_m) default to None — when None, the key is OMITTED from
    morphometrics, so tests can verify default-fallback behavior in the
    post-fuse gate.

    `outline_wgs84` is set as a dynamic attribute on the returned Candidate
    (the production Candidate dataclass doesn't have this field; sub-plan 03
    in tasks.py attaches it via setattr the same way).
    """
    morph = {"area_m2": area_m2, "depth_m": depth_m}
    if elongation is not None:
        morph["elongation"] = elongation
    if circularity is not None:
        morph["circularity"] = circularity
    if perimeter_m is not None:
        morph["perimeter_m"] = perimeter_m
    if wall_slope_deg is not None:
        morph["wall_slope_deg"] = wall_slope_deg
    if lrm_anomaly_m is not None:
        morph["lrm_anomaly_m"] = lrm_anomaly_m
    if morphometrics_extra:
        morph.update(morphometrics_extra)
    geom = geometry if geometry is not None else Point(0, 0)
    cand = Candidate(
        geometry=geom,
        outline=outline,
        score=score,
        feature_type=feature_type,
        morphometrics=morph,
        metadata=dict(metadata_extra) if metadata_extra else {},
    )
    cand.outline_wgs84 = outline_wgs84
    return cand


def make_candidate_with_outline(
    outline_polygon: Polygon,
    *,
    outline_wgs84: Polygon | None = None,
    score: float = 0.5,
    area_m2: float | None = None,
    depth_m: float = 0.8,
    elongation: float | None = None,
    circularity: float | None = None,
    feature_type: FeatureType = FeatureType.UNKNOWN,
) -> Candidate:
    """Convenience wrapper for polygon-overlap and rim-slope tests.

    If area_m2 is None it's derived from outline_polygon.area (assumes the
    outline's CRS is in meters — fine for tests that build outlines in
    UTM-like or unitless coordinates).
    """
    if area_m2 is None:
        area_m2 = float(outline_polygon.area)
    return make_candidate(
        score=score,
        area_m2=area_m2,
        depth_m=depth_m,
        elongation=elongation,
        circularity=circularity,
        outline=outline_polygon,
        outline_wgs84=outline_wgs84 if outline_wgs84 is not None else outline_polygon,
        geometry=outline_polygon.centroid,
        feature_type=feature_type,
    )


def tmp_slope_tif(slope_arr: np.ndarray, transform, tmp_path: Path, *, crs: str = "EPSG:32617") -> Path:
    """Write a synthetic slope raster to tmp_path/slope.tif for rim filter tests.

    slope_arr: 2D float32 array of slope values in degrees.
    transform: rasterio Affine (build via rasterio.transform.from_origin).
    Returns: Path to the written .tif.
    """
    out = tmp_path / "slope.tif"
    arr = slope_arr.astype(np.float32) if slope_arr.dtype != np.float32 else slope_arr
    with rasterio.open(
        out, "w",
        driver="GTiff",
        height=arr.shape[0],
        width=arr.shape[1],
        count=1,
        dtype=arr.dtype,
        crs=crs,
        transform=transform,
    ) as dst:
        dst.write(arr, 1)
    return out


@pytest.fixture
def configs_dir():
    """Absolute path to configs/ directory — use instead of relative Path('configs/...')."""
    return PROJECT_ROOT / "configs"


@pytest.fixture(autouse=True)
def ensure_passes_registered():
    """Ensure all passes are registered before each test."""
    import importlib

    import lost_landscapes.detection.passes as passes_mod
    from lost_landscapes.detection.passes import (
        curvature,
        discovery,
        fill_difference,
        local_relief_model,
        morphometric_filter,
        multi_return,
        point_density,
        random_forest,
        sky_view_factor,
        tpi,
        unet_segmentation,
        yolo_detector,
    )

    # Force re-registration if registry was cleared
    for mod in [discovery, fill_difference, local_relief_model, curvature, sky_view_factor,
                tpi, point_density, multi_return, morphometric_filter,
                random_forest, unet_segmentation, yolo_detector]:
        importlib.reload(mod)
    importlib.reload(passes_mod)
    yield


@pytest.fixture
def known_sites():
    """Load known validation sites from JSON fixture."""
    path = Path(__file__).parent / "fixtures" / "known_sites.json"
    with open(path) as f:
        data = json.load(f)
    return data["validation_sites"]
