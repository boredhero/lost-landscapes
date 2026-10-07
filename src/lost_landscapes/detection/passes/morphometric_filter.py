"""Morphometric filter pass — enriches candidates with full morphometrics.

Consumes pre-computed fill_difference and slope derivatives.
Never computes derivatives itself.

Vectorized: uses batch_morphometrics() to compute all 8 metrics for all
regions in a single set of scipy.ndimage passes, then filters vectorized.
"""

import time

import numpy as np
from rasterio.features import shapes as rasterio_shapes
from scipy import ndimage
from shapely.geometry import Point, shape

from lost_landscapes.detection.base import Candidate, DetectionPass, FeatureType, PassInput
from lost_landscapes.detection.postprocess.classification import classify_candidate
from lost_landscapes.detection.postprocess.morphometrics import batch_morphometrics
from lost_landscapes.detection.registry import register_pass
from lost_landscapes.utils.log_manager import log


@register_pass
class MorphometricFilterPass(DetectionPass):

    @property
    def name(self) -> str:
        return "morphometric_filter"

    @property
    def version(self) -> str:
        return "0.3.0"

    @property
    def required_derivatives(self) -> list[str]:
        return ["fill_difference", "slope"]

    def run(self, input_data: PassInput) -> list[Candidate]:
        t0 = time.perf_counter()
        log.info("morphometric_filter_pass_start", version=self.version)
        config = input_data.config
        min_depth_m = config.get("min_depth_m", 0.3)
        max_area_m2 = config.get("max_area_m2", 4000.0)
        min_area_m2 = config.get("min_area_m2", 25.0)
        min_circularity = config.get("min_circularity", 0.15)
        log.debug("morphometric_filter_pass_thresholds", min_depth_m=min_depth_m, max_area_m2=max_area_m2, min_area_m2=min_area_m2, min_circularity=min_circularity)
        resolution = abs(input_data.transform[0])
        dem = input_data.dem
        fill_diff = input_data.derivatives.get("fill_difference")
        slope = input_data.derivatives.get("slope")
        if fill_diff is None or slope is None:
            missing = [d for d in ("fill_difference", "slope") if input_data.derivatives.get(d) is None]
            log.warning("morphometric_filter_pass_missing_derivative", missing_derivatives=missing)
            return []
        log.debug("morphometric_filter_pass_rasters_loaded", fill_diff_shape_rows=fill_diff.shape[0], fill_diff_shape_cols=fill_diff.shape[1], slope_shape_rows=slope.shape[0], slope_shape_cols=slope.shape[1])
        # Mask nodata
        fill_diff = np.where(np.isfinite(fill_diff) & (fill_diff < 1000), fill_diff, 0)
        depression_mask = fill_diff > min_depth_m
        if not np.any(depression_mask):
            elapsed = time.perf_counter() - t0
            log.info("morphometric_filter_pass_complete", candidates=0, reason="no_depression_pixels", elapsed_s=elapsed)
            return []
        labeled, num_features = ndimage.label(depression_mask)
        if num_features == 0:
            elapsed = time.perf_counter() - t0
            log.info("morphometric_filter_pass_complete", candidates=0, reason="no_labeled_features", elapsed_s=elapsed)
            return []
        log.debug("morphometric_filter_pass_labeling", raw_features=num_features)
        # Batch-compute ALL morphometrics at once
        metrics = batch_morphometrics(dem, fill_diff, slope, labeled, num_features, resolution)
        # Vectorized filtering
        valid = (
            (metrics["area_m2"] >= min_area_m2)
            & (metrics["area_m2"] <= max_area_m2)
            & (metrics["circularity"] >= min_circularity)
            & (metrics["depth_m"] >= min_depth_m)
        )
        valid_count = int(np.sum(valid))
        log.debug("morphometric_filter_pass_filtering", raw_features=num_features, survived_filter=valid_count)
        # Vectorize outlines for valid regions only
        valid_set = set(np.flatnonzero(valid).tolist())
        valid_labels = set(idx + 1 for idx in valid_set)
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
            cy, cx = metrics["centroids"][idx]
            geo_x, geo_y = input_data.transform * (float(cx), float(cy))
            depth = float(metrics["depth_m"][idx])
            circ = float(metrics["circularity"][idx])
            area = float(metrics["area_m2"][idx])
            depth_score = min(depth / 5.0, 1.0)
            score = (depth_score + circ) / 2.0
            candidate = Candidate(
                geometry=Point(geo_x, geo_y),
                outline=outlines.get(idx),
                score=score,
                feature_type=FeatureType.UNKNOWN,
                morphometrics={
                    "depth_m": depth,
                    "area_m2": area,
                    "perimeter_m": float(metrics["perimeter_m"][idx]),
                    "circularity": circ,
                    "volume_m3": float(metrics["volume_m3"][idx]),
                    "k_parameter": float(metrics["k_parameter"][idx]),
                    "elongation": float(metrics["elongation"][idx]),
                    "wall_slope_deg": float(metrics["wall_slope_deg"][idx]),
                    "depth_area_ratio": depth / area if area > 0 else 0,
                },
            )
            candidate.feature_type = classify_candidate(candidate)
            candidates.append(candidate)
        elapsed = time.perf_counter() - t0
        log.info("morphometric_filter_pass_complete", candidates=len(candidates), elapsed_s=elapsed)
        return candidates
