"""Curvature detection pass — consumes pre-computed curvature rasters.

Vectorized: uses scipy.ndimage bulk operations across all labels at once.
"""

import time

import numpy as np
from rasterio.features import shapes as rasterio_shapes
from shapely.geometry import Point, shape

from lost_landscapes.detection.array_backend import label, region_stats
from lost_landscapes.detection.base import Candidate, DetectionPass, FeatureType, PassInput
from lost_landscapes.detection.registry import register_pass
from lost_landscapes.utils.log_manager import log


@register_pass
class CurvaturePass(DetectionPass):

    @property
    def name(self) -> str:
        return "curvature"

    @property
    def version(self) -> str:
        return "0.3.0"

    @property
    def required_derivatives(self) -> list[str]:
        return ["profile_curvature"]

    def run(self, input_data: PassInput) -> list[Candidate]:
        t0 = time.perf_counter()
        log.info("curvature_pass_start", version=self.version)
        config = input_data.config
        threshold = config.get("threshold", -0.02)
        min_area_pixels = config.get("min_area_pixels", 4)
        max_area_pixels = config.get("max_area_pixels", 0)
        log.debug("curvature_pass_thresholds", threshold=threshold, min_area_pixels=min_area_pixels, max_area_pixels=max_area_pixels)
        resolution = abs(input_data.transform[0])
        cell_area = resolution * resolution
        curv = input_data.derivatives.get("profile_curvature")
        if curv is None:
            log.warning("curvature_pass_missing_derivative", derivative="profile_curvature")
            return []
        log.debug("curvature_pass_raster_loaded", shape_rows=curv.shape[0], shape_cols=curv.shape[1], dtype=str(curv.dtype))
        concave_mask = curv < threshold
        if not np.any(concave_mask):
            elapsed = time.perf_counter() - t0
            log.info("curvature_pass_complete", candidates=0, reason="no_concave_pixels", elapsed_s=elapsed)
            return []
        labeled, num_features = label(concave_mask)
        if num_features == 0:
            elapsed = time.perf_counter() - t0
            log.info("curvature_pass_complete", candidates=0, reason="no_labeled_features", elapsed_s=elapsed)
            return []
        log.debug("curvature_pass_labeling", raw_features=num_features)
        stats = region_stats(curv, labeled, num_features, mask=concave_mask.astype(np.float32))
        areas_px = stats["areas_px"]
        min_curvs = stats["min_vals"]
        centroids = stats["centroids"]
        valid = areas_px >= min_area_pixels
        if max_area_pixels > 0:
            valid = valid & (areas_px <= max_area_pixels)
        valid_count = int(np.sum(valid))
        log.debug("curvature_pass_filtering", raw_features=num_features, survived_area_filter=valid_count)
        valid_set = set(np.flatnonzero(valid).tolist())
        valid_labels = set(idx + 1 for idx in valid_set)
        masked_labeled = np.where(np.isin(labeled, list(valid_labels)), labeled, 0).astype(np.int32)
        outlines: dict[int, object] = {}
        for geom_dict, value in rasterio_shapes(masked_labeled, mask=(masked_labeled > 0), transform=input_data.transform):
            arr_idx = int(value) - 1
            outlines[arr_idx] = shape(geom_dict)
        candidates = []
        for idx in np.flatnonzero(valid):
            cy, cx = centroids[idx]
            geo_x, geo_y = input_data.transform * (float(cx), float(cy))
            min_curv_val = float(min_curvs[idx])
            strength = min(abs(min_curv_val) / 0.1, 1.0)
            area_m2 = float(areas_px[idx]) * cell_area
            candidates.append(
                Candidate(
                    geometry=Point(geo_x, geo_y),
                    outline=outlines.get(idx),
                    score=strength,
                    feature_type=FeatureType.DEPRESSION,
                    morphometrics={"min_curvature": min_curv_val, "area_m2": area_m2},
                )
            )
        elapsed = time.perf_counter() - t0
        log.info("curvature_pass_complete", candidates=len(candidates), elapsed_s=elapsed)
        return candidates
