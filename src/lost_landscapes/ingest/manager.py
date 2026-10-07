"""IngestManager — orchestrates tile discovery and download across data sources.

Source resolution: coordinates → FCC reverse geocode → state code → sources.
No region polygons needed for bbox/zip searches.
"""

import time
from pathlib import Path

import httpx
from shapely.geometry import Polygon

from lost_landscapes.config import settings
from lost_landscapes.ingest.sources.base import DataSource, TileInfo
from lost_landscapes.ingest.sources.ct_lidar import CTLidarSource
from lost_landscapes.ingest.sources.ky_lidar import KYLidarSource
from lost_landscapes.ingest.sources.md_lidar import MDLidarSource
from lost_landscapes.ingest.sources.nc_lidar import NCLidarSource
from lost_landscapes.ingest.sources.nj_lidar import NJLidarSource
from lost_landscapes.ingest.sources.ny_lidar import NYLidarSource
from lost_landscapes.ingest.sources.oh_ogrip import OHOGRIPSource
from lost_landscapes.ingest.sources.pasda import PASDASource
from lost_landscapes.ingest.sources.tnm_lidar import TNMLidarSource
from lost_landscapes.ingest.sources.usgs_3dep import USGS3DEPSource
from lost_landscapes.ingest.sources.va_lidar import VALidarSource
from lost_landscapes.ingest.sources.wv_lidar import WVLidarSource
from lost_landscapes.utils.log_manager import log

# Registry of all available data sources
SOURCE_REGISTRY: dict[str, type[DataSource]] = {
    "usgs_3dep": USGS3DEPSource,
    "tnm": TNMLidarSource,
    "pasda": PASDASource,
    "wv": WVLidarSource,
    "ny": NYLidarSource,
    "oh": OHOGRIPSource,
    "nc": NCLidarSource,
    "md": MDLidarSource,
    "va": VALidarSource,
    "ky": KYLidarSource,
    "nj": NJLidarSource,
    "ct": CTLidarSource,
}

# State code → state-specific LiDAR sources (beyond usgs_3dep/tnm)
STATE_SOURCES: dict[str, list[str]] = {
    "PA": ["pasda"],
    "WV": ["wv"],
    "NY": ["ny"],
    "OH": ["oh"],
    "NC": ["nc"],
    "MD": ["md"],
    "VA": ["va"],
    "KY": ["ky"],
    "NJ": ["nj"],
    "CT": ["ct"],
}


def get_source(name: str) -> DataSource:
    """Get a data source instance by name."""
    if name not in SOURCE_REGISTRY:
        log.error("get_source_unknown", source=name, available=str(list(SOURCE_REGISTRY.keys())))
        raise KeyError(f"Unknown source: {name!r}. Available: {list(SOURCE_REGISTRY.keys())}")
    log.debug("get_source", source=name)
    return SOURCE_REGISTRY[name]()


def resolve_state(lat: float, lon: float) -> str | None:
    """Reverse geocode lat/lon to US state code via FCC Area API.
    Returns 2-letter state code (e.g. 'PA', 'NC') or None if outside US."""
    log.debug("fcc_geocode_request", lat=round(lat, 5), lon=round(lon, 5))
    geocode_start = time.monotonic()
    try:
        resp = httpx.get(
            "https://geo.fcc.gov/api/census/area",
            params={"lat": lat, "lon": lon, "format": "json"},
            timeout=5.0,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        elapsed = round(time.monotonic() - geocode_start, 2)
        if results:
            state_code = results[0].get("state_code")
            log.debug("fcc_geocode_resolved", lat=round(lat, 5), lon=round(lon, 5), state=state_code, elapsed_s=elapsed)
            return state_code
        log.debug("fcc_geocode_no_results", lat=round(lat, 5), lon=round(lon, 5), elapsed_s=elapsed)
    except Exception as e:
        elapsed = round(time.monotonic() - geocode_start, 2)
        log.warning("fcc_geocode_failed", lat=lat, lon=lon, error=str(e), elapsed_s=elapsed, exception=True)
    return None


def get_sources_for_location(lat: float, lon: float) -> list[str]:
    """Determine data sources for a location: usgs_3dep first, then any
    state-specific source, then tnm as universal US fallback."""
    sources = ["usgs_3dep"]
    state = resolve_state(lat, lon)
    if state:
        log.info("state_resolved", state=state, lat=round(lat, 4), lon=round(lon, 4))
        state_specific = STATE_SOURCES.get(state, [])
        for s in state_specific:
            sources.append(s)
        if state_specific:
            log.debug("state_sources_added", state=state, sources=str(state_specific))
    else:
        log.info("state_unresolved", lat=round(lat, 4), lon=round(lon, 4), reason="outside_us_or_geocode_failed")
    sources.append("tnm")
    log.info("source_chain_resolved", lat=round(lat, 4), lon=round(lon, 4), sources=str(sources))
    return sources


async def discover_tiles_for_bbox(bbox: Polygon, lat: float, lon: float) -> tuple[list[TileInfo], str]:
    """Discover tiles for a bbox, trying sources in order until one returns results.
    Skips TNM legacy tiles that lack CRS metadata (2001-era data with State Plane coords).
    Returns (tiles, source_name_used)."""
    bounds = bbox.bounds
    log.info("discover_tiles_for_bbox_start", lat=round(lat, 4), lon=round(lon, 4), bbox_minx=bounds[0], bbox_miny=bounds[1], bbox_maxx=bounds[2], bbox_maxy=bounds[3])
    discover_start = time.monotonic()
    sources = get_sources_for_location(lat, lon)
    for src_idx, src_name in enumerate(sources):
        src = get_source(src_name)
        tiles = []
        src_start = time.monotonic()
        log.debug("source_discovery_attempt", source=src_name, source_index=src_idx, total_sources=len(sources))
        try:
            async for t in src.discover_tiles(bbox):
                tiles.append(t)
        except Exception as e:
            log.warning("source_discovery_failed", source=src_name, error=str(e), exception=True)
        src_elapsed = round(time.monotonic() - src_start, 2)
        log.debug("source_discovery_result", source=src_name, raw_tiles=len(tiles), elapsed_s=src_elapsed)
        if tiles:
            # TNM can return legacy tiles (pre-2010) with no embedded CRS — these use
            # unknown State Plane coords and produce garbage results. Filter them out.
            # Modern TNM tiles (2010+) have proper CRS embedded in the LAZ headers.
            if src_name == "tnm":
                before = len(tiles)
                tiles = [t for t in tiles if t.format == "copc" or (t.acquisition_year and t.acquisition_year >= 2010)]
                if len(tiles) < before:
                    log.warning("tnm_legacy_filtered", before=before, after=len(tiles), dropped=before - len(tiles), reason="pre-2010 or unknown-year legacy tiles")
            if tiles:
                total_elapsed = round(time.monotonic() - discover_start, 2)
                log.info("source_resolved", source=src_name, tiles=len(tiles), sources_tried=src_idx + 1, total_elapsed_s=total_elapsed)
                return tiles, src_name
            log.info("source_empty_after_filter", source=src_name)
        else:
            log.debug("source_returned_empty", source=src_name)
    total_elapsed = round(time.monotonic() - discover_start, 2)
    log.warning("discover_tiles_for_bbox_no_results", lat=round(lat, 4), lon=round(lon, 4), sources_tried=len(sources), total_elapsed_s=total_elapsed)
    return [], "none"


async def download_tiles(
    tiles: list[TileInfo],
    source_name: str,
    dest_dir: Path | None = None,
) -> list[Path]:
    """Download a list of tiles from a specific source."""
    source = get_source(source_name)
    if dest_dir is None:
        dest_dir = settings.raw_dir / source_name
    log.info("download_tiles_start", source=source_name, tile_count=len(tiles), dest_dir=str(dest_dir))
    batch_start = time.monotonic()
    paths = []
    failed = 0
    for idx, tile in enumerate(tiles):
        try:
            path = await source.download_tile(tile, dest_dir)
            paths.append(path)
            log.debug("download_tiles_progress", source=source_name, completed=idx + 1, total=len(tiles), tile=tile.source_id)
        except Exception as e:
            failed += 1
            log.error("download_failed", source=source_name, tile=tile.source_id, error=str(e), exception=True)
    batch_elapsed = round(time.monotonic() - batch_start, 2)
    log.info("download_tiles_complete", source=source_name, succeeded=len(paths), failed=failed, total=len(tiles), elapsed_s=batch_elapsed, dest_dir=str(dest_dir))
    return paths
