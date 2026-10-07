"""Point density detection pass — finds voids where LiDAR enters openings.

Areas with anomalously low point density indicate where LiDAR pulses
penetrated into cave/mine openings rather than reflecting off terrain.
Requires raw point cloud data.
"""

import time

import numpy as np
from scipy.ndimage import label as ndimage_label
from shapely.geometry import Point

from lost_landscapes.detection.base import Candidate, DetectionPass, FeatureType, PassInput
from lost_landscapes.detection.registry import register_pass
from lost_landscapes.processing.point_cloud import compute_point_density
from lost_landscapes.utils.log_manager import log


@register_pass
class PointDensityPass(DetectionPass):
    """Detect voids via point density anomalies in point cloud."""

    @property
    def name(self) -> str:
        return "point_density"

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
        log.info("point_density_pass_start", version=self.version)
        if input_data.point_cloud is None:
            log.warning("point_density_pass_no_point_cloud", reason="point_cloud_is_none")
            return []
        config = input_data.config
        cell_size = config.get("cell_size_m", 2.0)
        z_threshold = config.get("z_score_threshold", -2.5)
        log.debug("point_density_pass_config", cell_size_m=cell_size, z_score_threshold=z_threshold)
        pc = input_data.point_cloud
        try:
            x = pc["X"].astype(np.float64)
            y = pc["Y"].astype(np.float64)
            z = pc["Z"].astype(np.float64)
        except (KeyError, TypeError) as e:
            log.error("point_density_pass_xyz_extract_failed", error=str(e), exception=True)
            return []
        log.debug("point_density_pass_points_loaded", num_points=len(x))
        density, z_scores, bounds = compute_point_density(x, y, z, cell_size)
        void_mask = z_scores < z_threshold
        if not np.any(void_mask):
            elapsed = time.perf_counter() - t0
            log.info("point_density_pass_complete", candidates=0, reason="no_void_cells", elapsed_s=elapsed)
            return []
        labeled, num_features = ndimage_label(void_mask)
        log.debug("point_density_pass_labeling", raw_features=num_features)
        xmin, ymin, xmax, ymax = bounds
        candidates = []
        for i in range(1, num_features + 1):
            region = labeled == i
            if np.sum(region) < 2:
                continue
            rows, cols = np.where(region)
            cy, cx = float(np.mean(rows)), float(np.mean(cols))
            # Convert grid coords to geographic
            geo_x = xmin + cx * cell_size
            geo_y = ymax - cy * cell_size
            min_zscore = float(np.min(z_scores[region]))
            score = min(abs(min_zscore) / 5.0, 1.0)
            area_m2 = float(np.sum(region)) * cell_size * cell_size
            candidates.append(
                Candidate(
                    geometry=Point(geo_x, geo_y),
                    score=score,
                    feature_type=FeatureType.CAVE_ENTRANCE,
                    morphometrics={
                        "density_z_score": min_zscore,
                        "void_area_m2": area_m2,
                    },
                )
            )
        elapsed = time.perf_counter() - t0
        log.info("point_density_pass_complete", candidates=len(candidates), elapsed_s=elapsed)
        return candidates
