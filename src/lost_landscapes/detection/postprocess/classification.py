"""Feature type classification based on morphometric properties."""

from lost_landscapes.detection.base import Candidate, FeatureType
from lost_landscapes.utils.log_manager import log


def classify_candidate(candidate: Candidate) -> FeatureType:
    """Assign a feature type based on morphometric properties.

    Uses simple heuristic rules. ML-based classification comes later.
    """
    m = candidate.morphometrics
    depth = m.get("depth_m", 0)
    area = m.get("area_m2", 0)
    circularity = m.get("circularity", 0)
    log.debug("classify_candidate_input", depth_m=depth, area_m2=area, circularity=circularity)
    # Very large, shallow, irregular = salt dome collapse (LA)
    if area > 10000 and depth < 5.0 and circularity < 0.3:
        log.info("candidate_classified", feature_type=FeatureType.SALT_DOME_COLLAPSE, depth_m=depth, area_m2=area, circularity=circularity, rule="large_shallow_irregular")
        return FeatureType.SALT_DOME_COLLAPSE
    # Elongated, moderate depth, large = lava tube collapse (CA)
    if circularity < 0.2 and depth > 0.5 and area > 500:
        log.info("candidate_classified", feature_type=FeatureType.LAVA_TUBE, depth_m=depth, area_m2=area, circularity=circularity, rule="elongated_moderate_large")
        return FeatureType.LAVA_TUBE
    # Very deep, small, circular = likely cave entrance or pit
    if depth > 3.0 and area < 500 and circularity > 0.4:
        log.info("candidate_classified", feature_type=FeatureType.CAVE_ENTRANCE, depth_m=depth, area_m2=area, circularity=circularity, rule="deep_small_circular")
        return FeatureType.CAVE_ENTRANCE
    # Rectangular/low circularity with moderate depth = mine portal
    if circularity < 0.3 and depth > 1.0 and area < 1000:
        log.info("candidate_classified", feature_type=FeatureType.MINE_PORTAL, depth_m=depth, area_m2=area, circularity=circularity, rule="rectangular_moderate_depth")
        return FeatureType.MINE_PORTAL
    # Large, shallow, circular = sinkhole
    if area > 200 and depth > 0.5 and circularity > 0.5:
        log.info("candidate_classified", feature_type=FeatureType.SINKHOLE, depth_m=depth, area_m2=area, circularity=circularity, rule="large_shallow_circular")
        return FeatureType.SINKHOLE
    # Moderate features = generic depression
    if depth > 0.5:
        log.info("candidate_classified", feature_type=FeatureType.DEPRESSION, depth_m=depth, area_m2=area, circularity=circularity, rule="moderate_depth_fallback")
        return FeatureType.DEPRESSION
    log.info("candidate_classified", feature_type=FeatureType.UNKNOWN, depth_m=depth, area_m2=area, circularity=circularity, rule="no_match")
    return FeatureType.UNKNOWN
