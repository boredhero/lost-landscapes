"""Multi-return analysis detection pass — anomalous return patterns near openings.

Near cave/mine openings, LiDAR pulses penetrate, creating unusual multi-return
patterns. High ratio of multi-return points in non-vegetated areas signals
openings. Requires raw point cloud data.
"""

import time

import numpy as np
from scipy.ndimage import label as ndimage_label
from shapely.geometry import Point

from lost_landscapes.detection.base import Candidate, DetectionPass, FeatureType, PassInput
from lost_landscapes.detection.registry import register_pass
from lost_landscapes.processing.point_cloud import compute_multi_return_ratio
from lost_landscapes.utils.log_manager import log


@register_pass
class MultiReturnPass(DetectionPass):
    """Detect openings via anomalous multi-return patterns."""

    @property
    def name(self) -> str:
        return "multi_return"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def required_derivatives(self) -> list[str]:
        return []

    @property
    def requires_point_cloud(self) -> bool:
        return True

    def run(self, input_data: PassInput) -> list[Candidate]:
        t0 = time.perf_counter()
        log.info("multi_return_pass_start", version=self.version)
        if input_data.point_cloud is None:
            log.warning("multi_return_pass_missing_input", reason="point_cloud_is_none")
            return []
        config = input_data.config
        cell_size = config.get("search_radius_m", 5.0)
        min_ratio = config.get("min_multi_return_ratio", 0.4)
        log.debug("multi_return_pass_thresholds", cell_size=cell_size, min_ratio=min_ratio)
        pc = input_data.point_cloud
        try:
            x = pc["X"].astype(np.float64)
            y = pc["Y"].astype(np.float64)
            rn = pc["ReturnNumber"].astype(np.int32)
            nr = pc["NumberOfReturns"].astype(np.int32)
            classification = pc.get("Classification")
            if classification is not None:
                classification = classification.astype(np.int32)
        except (KeyError, TypeError) as e:
            log.error("multi_return_pass_point_cloud_parse_error", error=str(e), exception=True)
            return []
        log.debug("multi_return_pass_point_cloud_loaded", num_points=len(x))
        ratio, bounds = compute_multi_return_ratio(
            x, y, rn, nr, classification, cell_size
        )
        log.debug("multi_return_pass_ratio_grid", shape_rows=ratio.shape[0], shape_cols=ratio.shape[1])
        # Find cells with high multi-return ratio (anomalous in non-veg areas)
        anomaly_mask = ratio > min_ratio
        if not np.any(anomaly_mask):
            elapsed = time.perf_counter() - t0
            log.info("multi_return_pass_complete", candidates=0, reason="no_anomalous_cells", elapsed_s=elapsed)
            return []
        labeled, num_features = ndimage_label(anomaly_mask)
        log.debug("multi_return_pass_labeling", raw_features=num_features)
        xmin, ymin, xmax, ymax = bounds
        candidates = []
        skipped_small = 0
        for i in range(1, num_features + 1):
            region = labeled == i
            if np.sum(region) < 2:
                skipped_small += 1
                continue
            rows, cols = np.where(region)
            cy, cx = float(np.mean(rows)), float(np.mean(cols))
            geo_x = xmin + cx * cell_size
            geo_y = ymax - cy * cell_size
            max_ratio = float(np.max(ratio[region]))
            score = min(max_ratio, 1.0)
            area_m2 = float(np.sum(region)) * cell_size * cell_size
            candidates.append(
                Candidate(
                    geometry=Point(geo_x, geo_y),
                    score=score,
                    feature_type=FeatureType.CAVE_ENTRANCE,
                    morphometrics={
                        "max_multi_return_ratio": max_ratio,
                        "anomaly_area_m2": area_m2,
                    },
                )
            )
        elapsed = time.perf_counter() - t0
        log.info("multi_return_pass_complete", candidates=len(candidates), raw_features=num_features, skipped_too_small=skipped_small, elapsed_s=elapsed)
        return candidates
