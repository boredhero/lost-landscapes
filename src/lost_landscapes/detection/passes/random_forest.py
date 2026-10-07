"""Random Forest classifier pass — consumes pre-computed derivatives only."""

import time
from pathlib import Path

import numpy as np
from scipy.ndimage import label as ndimage_label
from shapely.geometry import Point

from lost_landscapes.config import settings
from lost_landscapes.detection.base import Candidate, DetectionPass, FeatureType, PassInput
from lost_landscapes.detection.postprocess.morphometrics import (
    compute_area,
    compute_circularity,
    compute_depth,
    compute_elongation,
    compute_perimeter,
)
from lost_landscapes.detection.registry import register_pass
from lost_landscapes.utils.log_manager import log


def extract_features(
    dem: np.ndarray,
    mask: np.ndarray,
    slope: np.ndarray,
    tpi: np.ndarray,
    svf: np.ndarray,
    resolution: float,
) -> np.ndarray:
    """Extract 10 morphometric features for a single depression region."""
    depth = compute_depth(dem, mask)
    area = compute_area(mask, resolution)
    perimeter = compute_perimeter(mask, resolution)
    circularity = compute_circularity(area, perimeter)
    elongation = compute_elongation(mask)
    depth_area_ratio = depth / area if area > 0 else 0
    mean_slope_val = float(np.mean(slope[mask])) if np.any(mask) else 0
    max_slope_val = float(np.max(slope[mask])) if np.any(mask) else 0

    rows, cols = np.where(mask)
    cy, cx = int(np.mean(rows)), int(np.mean(cols))
    cy = np.clip(cy, 0, tpi.shape[0] - 1)
    cx = np.clip(cx, 0, tpi.shape[1] - 1)
    tpi_centroid = float(tpi[cy, cx])
    svf_centroid = float(svf[cy, cx])

    return np.array([
        depth, area, perimeter, circularity, elongation,
        depth_area_ratio, mean_slope_val, max_slope_val,
        tpi_centroid, svf_centroid,
    ], dtype=np.float64)


FEATURE_NAMES = [
    "depth_m", "area_m2", "perimeter_m", "circularity", "elongation",
    "depth_area_ratio", "mean_slope", "max_slope", "tpi_centroid", "svf_centroid",
]


@register_pass
class RandomForestPass(DetectionPass):

    @property
    def name(self) -> str:
        return "random_forest"

    @property
    def version(self) -> str:
        return "0.2.0"

    @property
    def required_derivatives(self) -> list[str]:
        return ["fill_difference", "slope", "tpi", "svf"]

    def run(self, input_data: PassInput) -> list[Candidate]:
        t0 = time.perf_counter()
        log.info("random_forest_pass_start", version=self.version)
        config = input_data.config
        min_depth_m = config.get("min_depth_m", 0.5)
        min_probability = config.get("min_probability", 0.5)
        model_path = config.get("model_path")
        log.debug("random_forest_pass_config", min_depth_m=min_depth_m, min_probability=min_probability, model_path=str(model_path))
        resolution = abs(input_data.transform[0])
        dem = input_data.dem
        import joblib
        mp = Path(model_path) if model_path else settings.models_dir / "rf_sinkhole_v1.joblib"
        if not mp.exists():
            log.warning("random_forest_pass_model_not_found", model_path=str(mp), reason="returning_empty")
            return []
        t_load = time.perf_counter()
        model = joblib.load(mp)
        load_elapsed = time.perf_counter() - t_load
        log.info("random_forest_model_loaded", model_path=str(mp), load_ms=round(load_elapsed * 1000, 1))
        fill_diff = input_data.derivatives.get("fill_difference")
        slope = input_data.derivatives.get("slope")
        tpi = input_data.derivatives.get("tpi")
        svf = input_data.derivatives.get("svf")
        if any(d is None for d in [fill_diff, slope, tpi, svf]):
            missing = [n for n, d in [("fill_difference", fill_diff), ("slope", slope), ("tpi", tpi), ("svf", svf)] if d is None]
            log.warning("random_forest_pass_missing_derivatives", missing=missing, reason="returning_empty")
            return []
        fill_diff = np.where(np.isfinite(fill_diff) & (fill_diff < 1000), fill_diff, 0)
        depression_mask = fill_diff > min_depth_m
        if not np.any(depression_mask):
            elapsed = time.perf_counter() - t0
            log.info("random_forest_pass_complete", candidates=0, reason="no_depressions", elapsed_s=elapsed)
            return []
        labeled, num_features = ndimage_label(depression_mask)
        log.debug("random_forest_pass_labeling", raw_features=num_features)
        candidates = []
        t_infer_total = 0.0
        for i in range(1, num_features + 1):
            mask = labeled == i
            if np.sum(mask) < 4:
                continue
            features = extract_features(dem, mask, slope, tpi, svf, resolution)
            try:
                t_infer = time.perf_counter()
                proba = model.predict_proba(features.reshape(1, -1))[0]
                t_infer_total += time.perf_counter() - t_infer
                prob_positive = float(proba[1]) if len(proba) > 1 else float(proba[0])
            except Exception as e:
                log.error("rf_predict_failed", region_index=i, error=str(e), exception=True)
                continue
            if prob_positive < min_probability:
                continue
            rows, cols = np.where(mask)
            cy, cx = float(np.mean(rows)), float(np.mean(cols))
            geo_x, geo_y = input_data.transform * (cx, cy)
            candidates.append(
                Candidate(
                    geometry=Point(geo_x, geo_y),
                    score=prob_positive,
                    feature_type=FeatureType.SINKHOLE,
                    morphometrics={name: float(val) for name, val in zip(FEATURE_NAMES, features)},
                    metadata={"classifier": "random_forest"},
                )
            )
        elapsed = time.perf_counter() - t0
        log.info("random_forest_pass_complete", candidates=len(candidates), inference_ms=round(t_infer_total * 1000, 1), elapsed_s=elapsed)
        return candidates
