"""Sky-View Factor detection pass — consumes pre-computed SVF raster.

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
class SkyViewFactorPass(DetectionPass):

    @property
    def name(self) -> str:
        return "sky_view_factor"

    @property
    def version(self) -> str:
        return "0.3.0"

    @property
    def required_derivatives(self) -> list[str]:
        return ["svf"]

    def run(self, input_data: PassInput) -> list[Candidate]:
        t0 = time.perf_counter()
        log.info("svf_pass_start", version=self.version)
        config = input_data.config
        threshold = config.get("threshold", 0.75)
        min_area_pixels = config.get("min_area_pixels", 4)
        max_area_pixels = config.get("max_area_pixels", 0)
        log.debug("svf_pass_config", threshold=threshold, min_area_pixels=min_area_pixels, max_area_pixels=max_area_pixels)
        resolution = abs(input_data.transform[0])
        cell_area = resolution * resolution
        svf = input_data.derivatives.get("svf")
        if svf is None:
            log.warning("svf_pass_missing_derivative", derivative="svf", reason="returning_empty")
            return []
        log.debug("svf_pass_raster_loaded", shape_rows=svf.shape[0], shape_cols=svf.shape[1], dtype=str(svf.dtype))
        # Normalize SVF to 0-1 range — WBT outputs raw integer counts (0-32000+)
        # depending on version, not a 0-1 fraction. Normalize so threshold works.
        svf_max = np.nanmax(svf[svf < 1e10])  # exclude nodata
        if svf_max > 1.5:  # raw integers, needs normalization
            log.debug("svf_pass_normalizing", svf_max=float(svf_max))
            svf = svf / svf_max
        enclosed_mask = svf < threshold
        if not np.any(enclosed_mask):
            elapsed = time.perf_counter() - t0
            log.info("svf_pass_complete", candidates=0, reason="no_enclosed_pixels", elapsed_s=elapsed)
            return []
        labeled, num_features = label(enclosed_mask)
        if num_features == 0:
            elapsed = time.perf_counter() - t0
            log.info("svf_pass_complete", candidates=0, reason="no_labeled_features", elapsed_s=elapsed)
            return []
        log.debug("svf_pass_labeling", raw_features=num_features)
        # Vectorized bulk stats — GPU if available
        stats = region_stats(svf, labeled, num_features, mask=enclosed_mask.astype(np.float32))
        areas_px = stats["areas_px"]
        min_svfs = stats["min_vals"]
        centroids = stats["centroids"]
        valid = areas_px >= min_area_pixels
        if max_area_pixels > 0:
            valid = valid & (areas_px <= max_area_pixels)
        valid_count = int(np.sum(valid))
        log.debug("svf_pass_filtering", raw_features=num_features, survived_area_filter=valid_count)
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
            min_svf_val = float(min_svfs[idx])
            score = min(max(0.0, 1.0 - min_svf_val), 1.0)
            area_m2 = float(areas_px[idx]) * cell_area
            candidates.append(
                Candidate(
                    geometry=Point(geo_x, geo_y),
                    outline=outlines.get(idx),
                    score=score,
                    feature_type=FeatureType.DEPRESSION,
                    morphometrics={"min_svf": min_svf_val, "area_m2": area_m2},
                )
            )
        elapsed = time.perf_counter() - t0
        log.info("svf_pass_complete", candidates=len(candidates), elapsed_s=elapsed)
        return candidates
