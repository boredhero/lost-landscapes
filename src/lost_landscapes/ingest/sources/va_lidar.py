"""Virginia LiDAR data source.

Downloads from VGIN (Virginia Geographic Information Network) via ArcGIS REST API.
Download URLs are wrapped in HTML anchor tags and need href extraction.
"""

import re
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from shapely.geometry import Polygon, shape

from lost_landscapes.ingest.sources.base import DataSource, TileInfo
from lost_landscapes.utils.log_manager import log

VA_TILE_INDEX_URL = (
    "https://vginmaps.vdem.virginia.gov/arcgis/rest/services/"
    "Download/Virginia_LiDAR_Downloads/MapServer/1/query"
)
_HREF_RE = re.compile(r'href="([^"]+)"')


def _extract_href(html: str) -> str | None:
    """Extract URL from an HTML anchor tag like <a href="...">text</a>."""
    m = _HREF_RE.search(html)
    return m.group(1) if m else None


class VALidarSource(DataSource):
    """Virginia LiDAR data from VGIN."""

    @property
    def name(self) -> str:
        return "va"

    async def discover_tiles(self, bbox: Polygon) -> AsyncIterator[TileInfo]:
        """Query VGIN tile index for tiles intersecting bbox."""
        bounds = bbox.bounds
        log.info("va_discover_start", bbox=bounds)
        params = {
            "where": "1=1",
            "geometry": f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "outSR": "4326",
            "outFields": "*",
            "returnGeometry": "true",
            "f": "geojson",
            "resultRecordCount": 500,
        }
        tile_count = 0
        skipped_no_url = 0
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.get(VA_TILE_INDEX_URL, params=params)
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, Exception) as e:
                log.warning("va_query_failed", error=str(e), exception=True)
                return
            features = data.get("features", [])
            log.debug("va_query_response", features_returned=len(features))
            for feature in features:
                props = feature.get("properties", {})
                geom = feature.get("geometry")
                tile_name = props.get("TileName") or props.get("Name") or str(props.get("FID", ""))
                raw_url = props.get("PointCloudDownload") or props.get("DEMDownload") or ""
                url = _extract_href(raw_url) if "<a " in raw_url else raw_url
                if url and geom:
                    tile_count += 1
                    log.debug("va_tile_discovered", tile_name=tile_name, url=url[:120])
                    yield TileInfo(
                        source_id=tile_name,
                        filename=f"va_{tile_name}.laz",
                        url=url,
                        bbox=shape(geom),
                        crs=26917,
                        format="laz",
                    )
                else:
                    skipped_no_url += 1
        log.info("va_discover_complete", tiles_found=tile_count, skipped_no_url=skipped_no_url, elapsed_s=time.monotonic() - t0)

    async def download_tile(self, tile: TileInfo, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / tile.filename
        if dest_path.exists():
            log.info("va_tile_cached", tile_id=tile.source_id, path=str(dest_path))
            return dest_path
        log.info("va_download_start", tile_id=tile.source_id, url=tile.url[:120], dest=str(dest_path))
        t0 = time.monotonic()
        try:
            downloaded = await self._stream_download(tile.url, dest_path, timeout=300.0)
            elapsed = time.monotonic() - t0
            log.info("va_download_complete", tile_id=tile.source_id, path=str(dest_path), bytes=downloaded, elapsed_s=elapsed)
        except httpx.HTTPStatusError as e:
            log.error("va_download_http_error", tile_id=tile.source_id, status=e.response.status_code, error=str(e), exception=True)
            raise
        except Exception as e:
            log.error("va_download_failed", tile_id=tile.source_id, url=tile.url[:120], error=str(e), exception=True)
            raise
        return dest_path
