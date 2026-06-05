"""Offline OSM data provider using Geofabrik PBF + osmium CLI.

Replaces the Overpass API with a local PBF file (~10GB for full US) queried
via osmium-tool (C++ CLI). Results are cached as GeoParquet with 30-day TTL
and grid-quantized keys so neighboring tiles share cached data.

osmium-tool is called via subprocess, consistent with how PDAL/GDAL/WBT
are used throughout the codebase.
"""

import hashlib
import json
import math
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Polygon

from hole_finder.config import settings
from hole_finder.utils.log_manager import log

# Serialize `osmium extract` calls. Each extract reads from the 12 GB US PBF;
# parallel extracts (one per tile × {buildings,roads,water,rail,landuse}) thrash
# disk I/O on the same large file and many cross the 180s timeout. A single
# extract takes ~24s on this hardware, so serializing across the worker is
# strictly faster than the previous parallel-and-time-out behavior. Export is
# NOT serialized — it operates on tiny per-tile clip files with negligible I/O.
_OSMIUM_EXTRACT_LOCK = threading.Semaphore(1)

GEOFABRIK_US_URL = "https://download.geofabrik.de/north-america/us-latest.osm.pbf"
PBF_PATH = settings.data_dir / "osm" / "us-latest.osm.pbf"
# Approximate state bounding boxes (west, south, east, north) for PBF routing.
# PA west extended to -80.60 to fully cover the Pittsburgh metro tiles.
STATE_PBFS: dict[str, tuple[tuple[float, float, float, float], str]] = {
    "pennsylvania":   ((-80.60, 39.72, -74.69, 42.27), "pennsylvania-latest.osm.pbf"),
    "west-virginia":  ((-82.64, 37.20, -77.72, 40.64), "west-virginia-latest.osm.pbf"),
    "ohio":           ((-84.82, 38.40, -80.52, 41.98), "ohio-latest.osm.pbf"),
    "new-york":       ((-79.76, 40.50, -71.85, 45.01), "new-york-latest.osm.pbf"),
    "north-carolina": ((-84.32, 33.84, -75.46, 36.59), "north-carolina-latest.osm.pbf"),
    "maryland":       ((-79.49, 37.91, -75.05, 39.72), "maryland-latest.osm.pbf"),
    "massachusetts":  ((-73.51, 41.24, -69.93, 42.89), "massachusetts-latest.osm.pbf"),
    "louisiana":      ((-94.04, 28.92, -88.82, 33.02), "louisiana-latest.osm.pbf"),
    "california":     ((-124.41, 32.53, -114.13, 42.01), "california-latest.osm.pbf"),
}
CACHE_DIR = settings.data_dir / "cache" / "osm"
CACHE_TTL_S = 30 * 86400  # 30 days
GRID_SIZE = 0.05  # ~5km grid cells for cache key quantization
OSMIUM_CONFIGS_DIR = Path("/app/configs/osmium") if Path("/app/configs/osmium").exists() else Path(__file__).resolve().parent.parent.parent.parent / "configs" / "osmium"
# Highway values — ALL paved/graded roads, not just major highways.
# Residential streets, service roads, and parking aisles cause the most false positives.
HIGHWAY_VALUES = {"motorway", "trunk", "primary", "secondary", "tertiary", "residential", "service", "unclassified", "living_street", "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"}
WATERWAY_VALUES = {"river", "stream", "canal", "drain", "ditch"}
RAILWAY_VALUES = {"rail", "light_rail"}
# Landuse/amenity/leisure values that produce false positives in LiDAR
EXCLUDE_LANDUSE = {"industrial", "commercial", "retail", "construction", "quarry", "landfill"}
EXCLUDE_AMENITY = {"parking"}
EXCLUDE_LEISURE = {"golf_course", "pitch", "track", "sports_centre", "stadium"}
EXCLUDE_MANMADE = {"bridge", "pier", "breakwater", "embankment"}


def _grid_cell(west: float, south: float, east: float, north: float) -> str:
    """Quantize a bbox to a grid cell key for cache deduplication."""
    gw = math.floor(west / GRID_SIZE) * GRID_SIZE
    gs = math.floor(south / GRID_SIZE) * GRID_SIZE
    ge = math.ceil(east / GRID_SIZE) * GRID_SIZE
    gn = math.ceil(north / GRID_SIZE) * GRID_SIZE
    return f"{gw:.3f}_{gs:.3f}_{ge:.3f}_{gn:.3f}"


def _cache_path(feature_type: str, grid_cell: str) -> Path:
    key = hashlib.md5(f"{feature_type}_{grid_cell}".encode()).hexdigest()[:16]
    return CACHE_DIR / f"{feature_type}_{key}.parquet"


def _get_cached(feature_type: str, grid_cell: str) -> list | None:
    """Return cached geometries if fresh, else None."""
    path = _cache_path(feature_type, grid_cell)
    if not path.exists():
        return None
    age_s = time.time() - path.stat().st_mtime
    if age_s > CACHE_TTL_S:
        log.debug("osm_cache_expired", feature_type=feature_type, age_days=round(age_s / 86400, 1))
        path.unlink(missing_ok=True)
        return None
    try:
        gdf = gpd.read_parquet(path)
        geoms = list(gdf.geometry)
        log.info("osm_cache_hit", feature_type=feature_type, count=len(geoms), age_hours=round(age_s / 3600, 1))
        return geoms
    except Exception as e:
        log.warning("osm_cache_read_failed", feature_type=feature_type, error=str(e))
        path.unlink(missing_ok=True)
        return None


def _set_cached(feature_type: str, grid_cell: str, geometries: list) -> None:
    """Write geometries to GeoParquet cache."""
    if not geometries:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        gdf = gpd.GeoDataFrame(geometry=geometries, crs="EPSG:4326")
        path = _cache_path(feature_type, grid_cell)
        gdf.to_parquet(path)
        log.debug("osm_cache_written", feature_type=feature_type, count=len(geometries), size_kb=round(path.stat().st_size / 1024, 1))
    except Exception as e:
        log.warning("osm_cache_write_failed", feature_type=feature_type, error=str(e))


def _resolve_pbf_path(west: float, south: float, east: float, north: float) -> Path:
    """Return the smallest available PBF covering the bbox center, else us-latest fallback."""
    cx = (west + east) / 2
    cy = (south + north) / 2
    for state, (bounds, fname) in STATE_PBFS.items():
        sw, ss, se, sn = bounds
        if sw <= cx <= se and ss <= cy <= sn:
            candidate = settings.data_dir / "osm" / fname
            if candidate.exists():
                return candidate
            log.debug("osm_state_pbf_missing", state=state, path=str(candidate), fallback="us-latest.osm.pbf")
    return PBF_PATH


def _extract_geojson(west: float, south: float, east: float, north: float, config_name: str) -> gpd.GeoDataFrame | None:
    """Extract features from PBF using osmium CLI. Returns GeoDataFrame or None."""
    pbf_path = _resolve_pbf_path(west, south, east, north)
    if not pbf_path.exists():
        log.warning("osm_pbf_missing", path=str(pbf_path), hint="Download from Geofabrik: wget -O {path} {url}".format(path=pbf_path, url=GEOFABRIK_US_URL))
        return None
    config_path = OSMIUM_CONFIGS_DIR / f"{config_name}.json"
    if not config_path.exists():
        log.error("osmium_config_missing", config=config_name, path=str(config_path))
        return None
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="osm_") as tmpdir:
        clip_path = Path(tmpdir) / "clip.osm.pbf"
        geojson_path = Path(tmpdir) / "features.geojson"
        # Step 1: Extract bbox from PBF (serialized — see _OSMIUM_EXTRACT_LOCK).
        log.debug("osm_using_pbf", pbf=pbf_path.name, bbox=f"{west},{south},{east},{north}")
        extract_cmd = ["osmium", "extract", "--bbox", f"{west},{south},{east},{north}", "--strategy=smart", "--overwrite", "-o", str(clip_path), str(pbf_path)]
        with _OSMIUM_EXTRACT_LOCK:
            try:
                result = subprocess.run(extract_cmd, capture_output=True, text=True, timeout=180)
                if result.returncode != 0:
                    log.error("osmium_extract_failed", returncode=result.returncode, stderr=result.stderr[:500])
                    return None
            except subprocess.TimeoutExpired:
                log.error("osmium_extract_timeout", bbox=f"{west},{south},{east},{north}", timeout_s=180)
                return None
            except FileNotFoundError:
                log.error("osmium_not_installed", hint="apt-get install osmium-tool")
                return None
        # Step 2: Export to GeoJSON with tag filter
        export_cmd = ["osmium", "export", "--config", str(config_path), "--overwrite", "-o", str(geojson_path), "-f", "geojson", str(clip_path)]
        try:
            result = subprocess.run(export_cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                log.error("osmium_export_failed", config=config_name, returncode=result.returncode, stderr=result.stderr[:500])
                return None
        except subprocess.TimeoutExpired:
            log.error("osmium_export_timeout", config=config_name)
            return None
        # Step 3: Read GeoJSON with geopandas
        if not geojson_path.exists() or geojson_path.stat().st_size < 10:
            log.debug("osmium_export_empty", config=config_name)
            return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
        try:
            gdf = gpd.read_file(geojson_path)
        except Exception as e:
            log.warning("osmium_geojson_read_failed", config=config_name, error=str(e))
            return None
    elapsed = time.perf_counter() - t0
    log.info("osm_extract_complete", config=config_name, features=len(gdf), elapsed_ms=round(elapsed * 1000, 1), bbox=f"{west},{south},{east},{north}")
    return gdf


def _get_geometries(west: float, south: float, east: float, north: float, feature_type: str, config_name: str, tag_filter: dict | None = None) -> list:
    """Get geometries for a feature type, using cache or osmium extraction."""
    cell = _grid_cell(west, south, east, north)
    cached = _get_cached(feature_type, cell)
    if cached is not None:
        return cached
    # Cache miss — extract from PBF
    # Use the grid cell bbox (slightly expanded) for extraction so cache is reusable
    parts = cell.split("_")
    gw, gs, ge, gn = float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])
    gdf = _extract_geojson(gw, gs, ge, gn, config_name)
    if gdf is None or gdf.empty:
        return []
    # Filter by specific tag values if needed
    geoms = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        if tag_filter:
            props = row.to_dict()
            if not any(props.get(k) in v if isinstance(v, set) else props.get(k) == v for k, v in tag_filter.items()):
                continue
        if not geom.is_valid:
            geom = geom.buffer(0)
        if geom.is_valid and not geom.is_empty:
            geoms.append(geom)
    _set_cached(feature_type, cell, geoms)
    log.info("osm_features_loaded", feature_type=feature_type, count=len(geoms), from_cache=False)
    return geoms


def get_building_polygons(west: float, south: float, east: float, north: float) -> list[Polygon]:
    """Get building footprint polygons from offline OSM data."""
    return _get_geometries(west, south, east, north, "buildings", "buildings")


def get_cemetery_polygons(west: float, south: float, east: float, north: float) -> list[Polygon]:
    """Get cemetery/graveyard polygons from offline OSM data."""
    return _get_geometries(west, south, east, north, "cemeteries", "cemeteries")


def get_road_geometries(west: float, south: float, east: float, north: float) -> list:
    """Get road linestrings from offline OSM data. Filters to major roads only."""
    return _get_geometries(west, south, east, north, "roads", "roads", tag_filter={"highway": HIGHWAY_VALUES})


def get_water_geometries(west: float, south: float, east: float, north: float) -> list:
    """Get waterway linestrings and water body polygons from offline OSM data."""
    return _get_geometries(west, south, east, north, "water", "water")


def get_railway_geometries(west: float, south: float, east: float, north: float) -> list:
    """Get railway linestrings from offline OSM data."""
    return _get_geometries(west, south, east, north, "railways", "railways", tag_filter={"railway": RAILWAY_VALUES})


def get_landuse_polygons(west: float, south: float, east: float, north: float) -> list:
    """Get landuse/amenity/leisure polygons that produce false positives (parking, industrial, golf, etc)."""
    return _get_geometries(west, south, east, north, "landuse", "landuse", tag_filter={"landuse": EXCLUDE_LANDUSE, "amenity": EXCLUDE_AMENITY, "leisure": EXCLUDE_LEISURE, "man_made": EXCLUDE_MANMADE})
