"""Filter detections that fall on building footprints using offline OSM data.

Uses locally-stored Geofabrik PBF + osmium CLI to get building polygons,
then excludes any detection whose centroid falls inside a building. Buildings
inside cemeteries are kept (mausoleums/crypts don't produce false LiDAR
anomalies, and real features can exist beneath them).
"""

import time

from shapely.geometry import Point
from shapely.ops import unary_union
from shapely.prepared import prep

from lost_landscapes.utils.log_manager import log
from lost_landscapes.utils.osm_data import get_building_polygons, get_cemetery_polygons


def fetch_building_polygons(west: float, south: float, east: float, north: float) -> list:
    """Fetch OSM building footprints for a bounding box from offline PBF data.
    Returns a list of Shapely Polygons representing building outlines.
    Buildings inside cemeteries/graveyards are excluded.
    """
    log.debug("building_fetch_start", bbox=f"{west},{south},{east},{north}")
    t0 = time.monotonic()
    all_buildings = get_building_polygons(west, south, east, north)
    elapsed = time.monotonic() - t0
    log.info("buildings_raw_fetched", count=len(all_buildings), elapsed_s=round(elapsed, 3), bbox=f"{west},{south},{east},{north}")
    if not all_buildings:
        log.warning("no_buildings_found", bbox=f"{west},{south},{east},{north}")
        return []
    # Exclude buildings that sit inside cemetery/graveyard areas
    cemetery_polys = get_cemetery_polygons(west, south, east, north)
    if cemetery_polys:
        cemetery_mask = prep(unary_union(cemetery_polys))
        filtered = [b for b in all_buildings if not cemetery_mask.contains(b.centroid)]
        excluded = len(all_buildings) - len(filtered)
        if excluded:
            log.info("cemetery_buildings_excluded", excluded=excluded, total_buildings=len(all_buildings))
        all_buildings = filtered
    log.info("buildings_fetched", count=len(all_buildings), bbox=f"{west},{south},{east},{north}")
    return all_buildings


def filter_candidates_by_buildings(
    candidates: list,
    wgs84_coords: list[tuple[float, float]],
    west: float, south: float, east: float, north: float,
) -> list[tuple]:
    """Remove candidates whose centroid falls inside an OSM building footprint.
    Args:
        candidates: list of Candidate objects
        wgs84_coords: list of (lon, lat) tuples matching candidates
        west/south/east/north: WGS84 bounding box
    Returns:
        list of (candidate, lon, lat) tuples that passed the filter
    """
    log.debug("building_filter_start", candidate_count=len(candidates), bbox=f"{west},{south},{east},{north}")
    buildings = fetch_building_polygons(west, south, east, north)
    if not buildings:
        log.info("building_filter_skipped", reason="no_buildings_found", candidate_count=len(candidates))
        return [(c, lon, lat) for c, (lon, lat) in zip(candidates, wgs84_coords)]
    merged = prep(unary_union(buildings))
    keep: list[tuple] = []
    removed = 0
    for c, (lon, lat) in zip(candidates, wgs84_coords):
        if merged.contains(Point(lon, lat)):
            removed += 1
            log.info("building_filtered", lon=round(lon, 5), lat=round(lat, 5), score=round(c.score, 2))
        else:
            keep.append((c, lon, lat))
    log.info("building_filter_result", original=len(candidates), removed=removed, remaining=len(keep), buildings=len(buildings))
    return keep
