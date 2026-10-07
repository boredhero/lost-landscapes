"""Global shape + size gate applied to fused candidates before storage.

Extracted from the inline list comprehension formerly at workers/tasks.py:519
so the gate is testable in isolation. Shape thresholds default to literature
values (Wu & Lane 2017): elongation > 0.4 (rejects ~2.5:1 and worse linear
strips), circularity > 0.3 (rejects anthropogenic ribbons).

Codebase elongation convention: minor_axis / major_axis (1.0 = circular,
0.0 = linear). Defaulting missing keys to 1.0 means candidates without shape
data (no-outline ML/point-cloud-only passes) survive — we don't false-reject
those.

Operator semantics: comparisons use <= for rejection, so threshold values
themselves are rejected and just-above survives. Boundary tests in
tests/unit/test_post_fuse_gate.py lock this convention.
"""

from lost_landscapes.detection.base import Candidate
from lost_landscapes.utils.log_manager import log


def apply_post_fuse_gate(
    candidates: list[Candidate],
    *,
    min_score: float = 0.15,
    min_area_m2: float = 20.0,
    min_depth_m: float = 0.3,
    max_depth_m: float = 150.0,
    min_elongation: float = 0.4,
    min_circularity: float = 0.3,
) -> list[Candidate]:
    """Filter fused candidates by score, area, depth, and shape thresholds."""
    kept = []
    rejected_by = {"score": 0, "area": 0, "depth_low": 0, "depth_high": 0, "elongation": 0, "circularity": 0}
    for c in candidates:
        if c.score <= min_score:
            rejected_by["score"] += 1
            continue
        if c.morphometrics.get("area_m2", 0) <= min_area_m2:
            rejected_by["area"] += 1
            continue
        if c.morphometrics.get("depth_m", 0) <= min_depth_m:
            rejected_by["depth_low"] += 1
            continue
        deepest = c.morphometrics.get("depth_m", 0) or c.morphometrics.get("lrm_anomaly_m", 0)
        if deepest >= max_depth_m:
            rejected_by["depth_high"] += 1
            continue
        if c.morphometrics.get("elongation", 1.0) <= min_elongation:
            rejected_by["elongation"] += 1
            continue
        if c.morphometrics.get("circularity", 1.0) <= min_circularity:
            rejected_by["circularity"] += 1
            continue
        kept.append(c)
    log.info("post_fuse_gate", input=len(candidates), kept=len(kept), rejected=rejected_by)
    return kept
