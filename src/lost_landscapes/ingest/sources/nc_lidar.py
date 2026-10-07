"""North Carolina LiDAR data source.

Uses NOAA Coastal LiDAR S3 bucket (NC 2015 Phase 3 statewide COPC).
Dataset 6209: 0.7m point spacing, LAS 1.4, NAD83(2011)/UTM zone 17N.
Tiles organized by county folders on S3.
"""

import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from shapely.geometry import Polygon

from lost_landscapes.ingest.sources.base import DataSource, TileInfo
from lost_landscapes.utils.log_manager import log

NOAA_S3_BASE = "https://noaa-nos-coastal-lidar-pds.s3.amazonaws.com"
NOAA_S3_PREFIX = "laz/geoid18/6209"
# County folder names on S3 follow pattern: "{County}CoNC"
# FCC API returns "Guilford County" → we convert to "GuilfordCoNC"


def _county_to_s3_folder(county_name: str) -> str:
    """Convert FCC county name to NOAA S3 folder name.
    'Guilford County' → 'GuilfordCoNC', 'Wake County' → 'WakeCoNC'"""
    name = county_name.replace(" County", "").replace(" ", "")
    return f"{name}CoNC"


async def _resolve_county(lat: float, lon: float) -> str | None:
    """Resolve lat/lon to county name via FCC Census Area API."""
    log.debug("fcc_county_resolve_start", lat=lat, lon=lon)
    resolve_start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("https://geo.fcc.gov/api/census/area", params={"lat": lat, "lon": lon, "format": "json"})
            resp.raise_for_status()
            results = resp.json().get("results", [])
            elapsed = round(time.monotonic() - resolve_start, 2)
            if results:
                county = results[0].get("county_name")
                log.info("fcc_county_resolved", lat=lat, lon=lon, county=county, elapsed_s=elapsed)
                return county
            log.warning("fcc_county_no_results", lat=lat, lon=lon, elapsed_s=elapsed)
    except Exception as e:
        elapsed = round(time.monotonic() - resolve_start, 2)
        log.warning("fcc_county_resolve_failed", lat=lat, lon=lon, error=str(e), elapsed_s=elapsed, exception=True)
    return None


async def _list_s3_tiles(county_folder: str) -> list[tuple[str, str]]:
    """List all COPC tile keys+URLs from a county folder on S3.
    Returns list of (tile_name, full_url)."""
    tiles = []
    prefix = f"{NOAA_S3_PREFIX}/{county_folder}/"
    marker = ""
    log.debug("s3_list_tiles_start", county_folder=county_folder, prefix=prefix)
    list_start = time.monotonic()
    page_count = 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        for _ in range(20):  # Max 20 pages of 1000
            params = {"prefix": prefix, "max-keys": "1000"}
            if marker:
                params["marker"] = marker
            try:
                resp = await client.get(f"{NOAA_S3_BASE}/", params=params)
                resp.raise_for_status()
            except Exception as e:
                log.error("s3_list_page_failed", county_folder=county_folder, page=page_count, error=str(e), exception=True)
                raise
            page_count += 1
            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp.text)
            ns = {'s3': 'http://s3.amazonaws.com/doc/2006-03-01/'}
            contents = root.findall('.//s3:Contents', ns)
            if not contents:
                log.debug("s3_list_page_empty", county_folder=county_folder, page=page_count)
                break
            for c in contents:
                key = c.find('s3:Key', ns).text
                if key.endswith('.copc.laz'):
                    tile_name = Path(key).stem.replace(".copc", "")
                    url = f"{NOAA_S3_BASE}/{key}"
                    tiles.append((tile_name, url))
                marker = key
            is_truncated = root.findtext('{http://s3.amazonaws.com/doc/2006-03-01/}IsTruncated', 'false')
            if is_truncated.lower() != 'true':
                break
    elapsed = round(time.monotonic() - list_start, 2)
    log.info("s3_list_tiles_complete", county_folder=county_folder, pages=page_count, copc_tiles=len(tiles), elapsed_s=elapsed)
    return tiles


class NCLidarSource(DataSource):
    """North Carolina LiDAR from NOAA S3 (2015 Phase 3 statewide COPC)."""

    @property
    def name(self) -> str:
        return "nc"

    async def discover_tiles(self, bbox: Polygon) -> AsyncIterator[TileInfo]:
        """Discover NC COPC tiles by resolving bbox center to county, listing S3."""
        bounds = bbox.bounds
        log.info("nc_discover_tiles_start", bbox_minx=bounds[0], bbox_miny=bounds[1], bbox_maxx=bounds[2], bbox_maxy=bounds[3])
        centroid = bbox.centroid
        county_name = await _resolve_county(centroid.y, centroid.x)
        if not county_name:
            log.warning("nc_no_county", lat=centroid.y, lon=centroid.x)
            return
        folder = _county_to_s3_folder(county_name)
        log.info("nc_s3_discovery", county=county_name, folder=folder)
        try:
            tile_list = await _list_s3_tiles(folder)
        except Exception as e:
            log.warning("nc_s3_list_failed", folder=folder, error=str(e), exception=True)
            return
        if not tile_list:
            log.info("nc_s3_no_tiles", folder=folder)
            return
        log.info("nc_s3_tiles_found", folder=folder, count=len(tile_list))
        # Yield all tiles with the search bbox as approximate coverage.
        # The task's distance sorting will pick the nearest ones.
        for tile_name, url in tile_list:
            yield TileInfo(
                source_id=tile_name,
                filename=f"nc_{tile_name}.copc.laz",
                url=url,
                bbox=bbox,  # Approximate — all tiles share the search bbox
                crs=6543,   # NAD83(2011) / UTM zone 17N
                acquisition_year=2015,
                format="copc",
            )

    async def download_tile(self, tile: TileInfo, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / tile.filename
        if dest_path.exists():
            log.debug("nc_tile_cached", source_id=tile.source_id, path=str(dest_path))
            return dest_path
        log.info("nc_download_start", source_id=tile.source_id, url=tile.url[:120], dest=str(dest_path))
        dl_start = time.monotonic()
        try:
            downloaded = await self._stream_download(tile.url, dest_path, timeout=600.0)
        except Exception as e:
            elapsed = round(time.monotonic() - dl_start, 2)
            log.error("nc_download_failed", source_id=tile.source_id, url=tile.url[:120], error=str(e), elapsed_s=elapsed, exception=True)
            raise
        elapsed = round(time.monotonic() - dl_start, 2)
        log.info("nc_download_complete", source_id=tile.source_id, path=str(dest_path), bytes=downloaded, elapsed_s=elapsed)
        return dest_path
