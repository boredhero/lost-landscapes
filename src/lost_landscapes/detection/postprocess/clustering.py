"""Spatial clustering utilities for detection candidates."""

from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import label as ndimage_label
from shapely.geometry import Point

from lost_landscapes.detection.base import Candidate, FeatureType
from lost_landscapes.utils.log_manager import log


def label_depressions(
    depression_raster: NDArray[np.float32],
    min_depth_m: float = 0.5,
    min_area_pixels: int = 4,
) -> tuple[NDArray[np.int32], int]:
    """Label connected depression regions in a fill-difference raster.

    Args:
        depression_raster: fill_dem - original_dem (positive = depression depth)
        min_depth_m: minimum depth threshold
        min_area_pixels: minimum number of pixels to keep

    Returns:
        (labeled_array, num_features)
    """
    log.debug("label_depressions_start", raster_shape=depression_raster.shape, min_depth_m=min_depth_m, min_area_pixels=min_area_pixels)
    binary = depression_raster > min_depth_m
    labeled, num_features = ndimage_label(binary)
    pre_filter_count = num_features
    log.debug("label_depressions_initial", regions_found=num_features, depth_threshold_m=min_depth_m)
    # Filter by minimum area
    area_filtered = 0
    for i in range(1, num_features + 1):
        region = labeled == i
        if np.sum(region) < min_area_pixels:
            labeled[region] = 0
            area_filtered += 1
    # Re-label after filtering
    labeled, num_features = ndimage_label(labeled > 0)
    log.info("label_depressions_complete", pre_filter=pre_filter_count, area_filtered_out=area_filtered, final_features=num_features, min_area_pixels=min_area_pixels)
    return labeled, num_features


def extract_candidates_from_labels(
    labeled: NDArray[np.int32],
    dem: NDArray[np.float32],
    transform: "Any",
    feature_type: FeatureType = FeatureType.UNKNOWN,
) -> list[Candidate]:
    """Convert labeled depression regions to Candidate objects."""
    candidates = []
    num_labels = labeled.max()
    log.debug("extract_candidates_start", num_labels=int(num_labels), feature_type=str(feature_type))
    empty_labels = 0
    for i in range(1, num_labels + 1):
        mask = labeled == i
        if not np.any(mask):
            empty_labels += 1
            continue
        # Centroid in pixel coords
        rows, cols = np.where(mask)
        cy, cx = float(np.mean(rows)), float(np.mean(cols))
        # Convert to geographic coords
        geo_x, geo_y = transform * (cx, cy)
        # Compute basic morphometrics
        rim = float(np.max(dem[mask]))
        floor = float(np.min(dem[mask]))
        depth = rim - floor
        area_pixels = int(np.sum(mask))
        candidates.append(
            Candidate(
                geometry=Point(geo_x, geo_y),
                score=min(depth / 3.0, 1.0),  # simple depth-based score
                feature_type=feature_type,
                morphometrics={
                    "depth_m": depth,
                    "area_pixels": float(area_pixels),
                    "rim_elevation": rim,
                    "floor_elevation": floor,
                },
            )
        )
    if empty_labels:
        log.debug("extract_candidates_empty_labels", empty_labels=empty_labels)
    log.info("extract_candidates_complete", candidates=len(candidates), num_labels=int(num_labels), feature_type=str(feature_type))
    return candidates
