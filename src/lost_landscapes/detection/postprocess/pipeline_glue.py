"""Glue function that runs the post-fuse filter chain in the correct order.

Exists so the chain (shape gate → buildings → infra → sort+cap) is testable
in isolation. The headline cap-reorder bug was that the cap previously ran
BEFORE buildings/infra filters, so road FPs (with high multi-pass-bonus
scores) crowded out real candidates from the top-200 cut. Moving the cap to
AFTER the filters means the cap evaluates over the genuinely-survived set.

Filters are injected as callables so tests can stub them; production
callers pass `filter_candidates_by_buildings` and
`filter_candidates_by_infrastructure` directly.
"""

from collections.abc import Callable

from lost_landscapes.detection.base import Candidate
from lost_landscapes.detection.postprocess.post_fuse_gate import apply_post_fuse_gate


def run_post_fuse_chain(
    candidates: list[Candidate],
    wgs84_coords: list[tuple[float, float]],
    bbox: tuple[float, float, float, float],
    *,
    cap: int = 200,
    gate_kwargs: dict | None = None,
    buildings_filter_func: Callable | None = None,
    infra_filter_func: Callable | None = None,
    rim_filter_func: Callable | None = None,
) -> list[tuple[Candidate, float, float]]:
    """Run shape gate → buildings → infra → rim_slope → sort+cap. Returns (c, lon, lat) tuples.

    Args:
        candidates: list of fused Candidate objects.
        wgs84_coords: list of (lon, lat) tuples paired by index with candidates.
        bbox: (west, south, east, north) for the OSM-fetching filters.
        cap: max number of survivors after all filters. Cap runs LAST.
        gate_kwargs: passed to apply_post_fuse_gate (thresholds).
        buildings_filter_func: callable matching filter_candidates_by_buildings;
            None to skip the building filter.
        infra_filter_func: callable matching filter_candidates_by_infrastructure;
            None to skip.
        rim_filter_func: callable accepting list[(c, lon, lat)] and returning
            same; production binds slope_raster_path via functools.partial.
            None to skip.
    """
    assert len(candidates) == len(wgs84_coords), (
        f"candidates ({len(candidates)}) and wgs84_coords ({len(wgs84_coords)}) length mismatch"
    )
    if not candidates:
        return []
    survivors = apply_post_fuse_gate(candidates, **(gate_kwargs or {}))
    survivor_ids = {id(c) for c in survivors}
    paired = [
        (c, lon, lat)
        for c, (lon, lat) in zip(candidates, wgs84_coords)
        if id(c) in survivor_ids
    ]
    if not paired:
        return []
    west, south, east, north = bbox
    if buildings_filter_func is not None:
        cands = [item[0] for item in paired]
        coords = [(item[1], item[2]) for item in paired]
        paired = buildings_filter_func(cands, coords, west, south, east, north)
        if not paired:
            return []
    if infra_filter_func is not None:
        cands = [item[0] for item in paired]
        coords = [(item[1], item[2]) for item in paired]
        paired = infra_filter_func(cands, coords, west, south, east, north)
        if not paired:
            return []
    if rim_filter_func is not None:
        paired = rim_filter_func(paired)
    paired.sort(key=lambda item: item[0].score, reverse=True)
    return paired[:cap]
