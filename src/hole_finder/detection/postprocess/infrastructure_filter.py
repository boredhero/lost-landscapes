"""Filter detections that fall on roads, waterways, or railways using offline OSM data.

Uses locally-stored Geofabrik PBF + osmium CLI to get infrastructure features,
then excludes detections whose outline overlaps a buffered feature by ≥30%
(falling back to centroid-in-polygon when the candidate has no outline).
Springs are exempt from water filtering.

Buffer distances are projected meters: line geometries are transformed to a
local UTM zone (picked from the bbox center), buffered by the meter constant,
then transformed back to WGS84. Avoids the prior degree-buffer asymmetry
(0.0003° was ~33 m N-S but cos(lat)*33 m E-W).
"""

import time
from typing import Callable

from pyproj import Transformer
from shapely.geometry import Point
from shapely.ops import transform as shapely_transform
from shapely.ops import unary_union
from shapely.prepared import prep

from hole_finder.utils.log_manager import log
from hole_finder.utils.osm_data import get_landuse_polygons, get_railway_geometries, get_road_geometries, get_water_geometries

# Buffer distances in METERS (projected; previously in degrees in WGS84)
ROAD_BUFFER_M = 30.0   # highway cuts are wide
WATER_BUFFER_M = 30.0  # creek/river banks
RAIL_BUFFER_M = 40.0   # rail cuts through hills are wide

OVERLAP_REJECT_FRACTION = 0.3  # candidate is rejected if ≥30% of its area overlaps mask polygon


def _utm_epsg_for(lon: float, lat: float) -> int:
    zone = int((lon + 180) / 6) + 1
    return 32600 + zone if lat >= 0 else 32700 + zone


def _buffer_lines(geometries: list, buffer_m: float, bbox_lon_lat: tuple[float, float, float, float]) -> list:
    """Buffer line/point geometries by `buffer_m` meters using a local UTM CRS.

    Polygons pass through unchanged (already enclosing — no buffering needed).
    """
    if not geometries:
        return []
    west, south, east, north = bbox_lon_lat
    center_lon = (west + east) / 2.0
    center_lat = (south + north) / 2.0
    utm_epsg = _utm_epsg_for(center_lon, center_lat)
    to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{utm_epsg}", always_xy=True).transform
    to_wgs = Transformer.from_crs(f"EPSG:{utm_epsg}", "EPSG:4326", always_xy=True).transform
    result = []
    for geom in geometries:
        if geom.geom_type in ("Polygon", "MultiPolygon"):
            result.append(geom)
            continue
        utm_geom = shapely_transform(to_utm, geom)
        buffered_utm = utm_geom.buffer(buffer_m)
        result.append(shapely_transform(to_wgs, buffered_utm))
    return result


def fetch_infrastructure_polygons(west: float, south: float, east: float, north: float) -> dict[str, list]:
    """Fetch OSM roads, waterways, railways, and landuse from offline PBF data.

    Returns dict with keys 'roads', 'water', 'railways', 'landuse' -> lists of
    Shapely Polygons (in WGS84, after meter-buffer for line features).
    """
    log.debug("infrastructure_fetch_start", bbox=f"{west},{south},{east},{north}")
    t0 = time.monotonic()
    bbox = (west, south, east, north)
    raw_roads = get_road_geometries(west, south, east, north)
    raw_water = get_water_geometries(west, south, east, north)
    raw_railways = get_railway_geometries(west, south, east, north)
    raw_landuse = get_landuse_polygons(west, south, east, north)
    elapsed = time.monotonic() - t0
    roads = _buffer_lines(raw_roads, ROAD_BUFFER_M, bbox) if raw_roads else []
    water = _buffer_lines(raw_water, WATER_BUFFER_M, bbox) if raw_water else []
    railways = _buffer_lines(raw_railways, RAIL_BUFFER_M, bbox) if raw_railways else []
    landuse = [g for g in raw_landuse if g.is_valid] if raw_landuse else []
    log.info("infrastructure_fetched", roads=len(roads), water=len(water), railways=len(railways), landuse=len(landuse), bbox=f"{west},{south},{east},{north}", elapsed_s=round(elapsed, 3))
    return {"roads": roads, "water": water, "railways": railways, "landuse": landuse}


def _rejects(prep_geom, full_geom, candidate, fallback_point: Point) -> bool:
    """Return True if `candidate` should be rejected by the given mask geometry.

    Uses outline-overlap-fraction (≥OVERLAP_REJECT_FRACTION rejects) when the
    candidate has a valid `outline_wgs84`; falls back to centroid-in-polygon
    for ML / point-cloud / no-outline candidates.
    """
    outline = getattr(candidate, "outline_wgs84", None)
    if outline is not None and not outline.is_empty:
        if not outline.is_valid:
            log.warning("infrastructure_filter_invalid_outline_fallback_to_centroid")
            return prep_geom.contains(fallback_point)
        if not prep_geom.intersects(outline):
            return False
        try:
            overlap_area = outline.intersection(full_geom).area
            if outline.area <= 0:
                return prep_geom.contains(fallback_point)
            return (overlap_area / outline.area) >= OVERLAP_REJECT_FRACTION
        except Exception as e:
            log.warning("infrastructure_filter_overlap_failed_fallback_to_centroid", error=str(e))
            return prep_geom.contains(fallback_point)
    return prep_geom.contains(fallback_point)


def filter_candidates_by_infrastructure(
    candidates: list,
    wgs84_coords: list[tuple[float, float]],
    west: float, south: float, east: float, north: float,
) -> list[tuple]:
    """Remove candidates that overlap roads, water, or railways.

    Springs are exempt from water filtering only (still rejected by road/rail/landuse).
    """
    log.debug("infrastructure_filter_start", candidate_count=len(candidates), bbox=f"{west},{south},{east},{north}")
    if not candidates:
        return []
    infra = fetch_infrastructure_polygons(west, south, east, north)
    all_road = infra["roads"]
    all_water = infra["water"]
    all_railway = infra["railways"]
    all_landuse = infra["landuse"]
    if not all_road and not all_water and not all_railway and not all_landuse:
        log.info("infrastructure_filter_skipped", reason="no_infrastructure_found", candidate_count=len(candidates))
        return [(c, lon, lat) for c, (lon, lat) in zip(candidates, wgs84_coords)]
    road_full = unary_union(all_road) if all_road else None
    water_full = unary_union(all_water) if all_water else None
    rail_full = unary_union(all_railway) if all_railway else None
    landuse_full = unary_union(all_landuse) if all_landuse else None
    road_geom = prep(road_full) if road_full else None
    water_geom = prep(water_full) if water_full else None
    rail_geom = prep(rail_full) if rail_full else None
    landuse_geom = prep(landuse_full) if landuse_full else None
    original = len(candidates)
    road_removed = 0
    water_removed = 0
    rail_removed = 0
    landuse_removed = 0
    spring_exemptions = 0
    keep: list[tuple] = []
    for c, (lon, lat) in zip(candidates, wgs84_coords):
        pt = Point(lon, lat)
        is_spring = getattr(c, 'feature_type', None) and str(c.feature_type) == 'spring'
        if road_geom and _rejects(road_geom, road_full, c, pt):
            road_removed += 1
            continue
        if water_geom and _rejects(water_geom, water_full, c, pt):
            if is_spring:
                spring_exemptions += 1
            else:
                water_removed += 1
                continue
        if rail_geom and _rejects(rail_geom, rail_full, c, pt):
            rail_removed += 1
            continue
        if landuse_geom and _rejects(landuse_geom, landuse_full, c, pt):
            landuse_removed += 1
            continue
        keep.append((c, lon, lat))
    log.info("infrastructure_filter_result", original=original, remaining=len(keep), road_removed=road_removed, water_removed=water_removed, rail_removed=rail_removed, landuse_removed=landuse_removed, spring_exemptions=spring_exemptions)
    return keep
