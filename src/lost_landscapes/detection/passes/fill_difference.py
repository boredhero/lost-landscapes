"""Fill-difference detection pass — finds depressions from pre-computed fill-difference raster.

Consumes the fill_difference derivative (filled_DEM - original_DEM).
Does NOT compute fill-difference itself — that's done by the processing pipeline
using WhiteboxTools (compiled Rust) and GDAL.

Based on Wall et al. (2016) — 93% detection rate for known sinkholes.

Vectorized: uses scipy.ndimage bulk operations across all labels at once
instead of per-region Python loops. O(H*W) instead of O(N*H*W).
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
class FillDifferencePass(DetectionPass):
    """Detect depressions from pre-computed fill-difference raster."""

    @property
    def name(self) -> str:
        return "fill_difference"

    @property
    def version(self) -> str:
        return "0.3.0"

    @property
    def required_derivatives(self) -> list[str]:
        return ["fill_difference"]

    def run(self, input_data: PassInput) -> list[Candidate]:
        t0 = time.perf_counter()
        log.info("fill_difference_pass_start", version=self.version)
        config = input_data.config
        min_depth_m = config.get("min_depth_m", 0.5)
        max_area_m2 = config.get("max_area_m2", 5000.0)
        min_area_m2 = config.get("min_area_m2", 25.0)
        log.debug("fill_difference_pass_thresholds", min_depth_m=min_depth_m, max_area_m2=max_area_m2, min_area_m2=min_area_m2)
        resolution = abs(input_data.transform[0])
        cell_area = resolution * resolution
        diff = input_data.derivatives.get("fill_difference")
        if diff is None:
            log.warning("fill_difference_pass_missing_derivative", derivative="fill_difference")
            return []
        log.debug("fill_difference_pass_raster_loaded", shape_rows=diff.shape[0], shape_cols=diff.shape[1], dtype=str(diff.dtype))
        # Mask nodata (bogus huge values from DEM edges)
        diff = np.where(np.isfinite(diff) & (diff < 1000), diff, 0)
        depression_mask = diff > min_depth_m
        if not np.any(depression_mask):
            elapsed = time.perf_counter() - t0
            log.info("fill_difference_pass_complete", candidates=0, reason="no_depression_pixels", elapsed_s=elapsed)
            return []
        labeled, num_features = label(depression_mask)
        if num_features == 0:
            elapsed = time.perf_counter() - t0
            log.info("fill_difference_pass_complete", candidates=0, reason="no_labeled_features", elapsed_s=elapsed)
            return []
        log.debug("fill_difference_pass_labeling", raw_features=num_features)
        # Vectorized bulk stats — GPU if available, CPU otherwise
        stats = region_stats(diff, labeled, num_features, mask=depression_mask.astype(np.float32))
        areas_px = stats["areas_px"]
        areas_m2 = areas_px * cell_area
        max_depths = stats["max_vals"]
        centroids = stats["centroids"]
        # Filter by area bounds (vectorized)
        valid = (areas_m2 >= min_area_m2) & (areas_m2 <= max_area_m2)
        valid_count = int(np.sum(valid))
        log.debug("fill_difference_pass_filtering", raw_features=num_features, survived_area_filter=valid_count)
        # Vectorize outlines for valid regions only
        # Create a masked array with only valid labels, then run rasterio_shapes once
        valid_set = set(np.flatnonzero(valid).tolist())
        valid_labels = set(idx + 1 for idx in valid_set)  # label IDs are 1-indexed
        masked_labeled = np.where(np.isin(labeled, list(valid_labels)), labeled, 0).astype(np.int32)
        outlines: dict[int, object] = {}
        for geom_dict, value in rasterio_shapes(
            masked_labeled,
            mask=(masked_labeled > 0),
            transform=input_data.transform,
        ):
            arr_idx = int(value) - 1
            outlines[arr_idx] = shape(geom_dict)
        candidates = []
        for idx in np.flatnonzero(valid):
            cy, cx = centroids[idx]
            geo_x, geo_y = input_data.transform * (float(cx), float(cy))
            depth = float(max_depths[idx])
            candidates.append(
                Candidate(
                    geometry=Point(geo_x, geo_y),
                    outline=outlines.get(idx),
                    score=min(depth / 5.0, 1.0),
                    feature_type=FeatureType.DEPRESSION,
                    morphometrics={
                        "depth_m": depth,
                        "area_m2": float(areas_m2[idx]),
                        "area_pixels": float(areas_px[idx]),
                    },
                )
            )
        elapsed = time.perf_counter() - t0
        log.info("fill_difference_pass_complete", candidates=len(candidates), elapsed_s=elapsed)
        return candidates
