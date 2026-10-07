"""Ohio OGRIP (Ohio Geographically Referenced Information Program) LiDAR source.

Downloads from OGRIP geodata download portal.
"""

import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from shapely.geometry import Polygon

from lost_landscapes.ingest.sources.base import DataSource, TileInfo
from lost_landscapes.utils.log_manager import log

# OGRIP tile index endpoint
OGRIP_URL = (
    "https://gis1.oit.ohio.gov/arcgis/rest/services/OSIP/osip_best_available_dem/ImageServer/query"
)


class OHOGRIPSource(DataSource):
    """Ohio OGRIP LiDAR data."""

    @property
    def name(self) -> str:
        return "oh"

    async def discover_tiles(self, bbox: Polygon) -> AsyncIterator[TileInfo]:
        """Query OGRIP for tiles intersecting bbox."""
        bounds = bbox.bounds
        log.info("oh_discover_start", bbox_minx=bounds[0], bbox_miny=bounds[1], bbox_maxx=bounds[2], bbox_maxy=bounds[3])
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
        discover_start = time.monotonic()
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                log.debug("oh_api_request", url=OGRIP_URL[:100])
                response = await client.get(OGRIP_URL, params=params)
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, Exception) as e:
                log.warning("oh_query_failed", error=str(e), exception=True)
                return
            features = data.get("features", [])
            api_elapsed = round(time.monotonic() - discover_start, 2)
            log.debug("oh_api_response", feature_count=len(features), elapsed_s=api_elapsed, status_code=response.status_code)
            yielded = 0
            skipped_no_url = 0
            skipped_no_geom = 0
            for feature in features:
                props = feature.get("properties", {})
                geom = feature.get("geometry")
                tile_name = props.get("Name") or props.get("TILE") or str(props.get("FID", ""))
                url = props.get("URL") or props.get("DOWNLOAD_URL", "")
                if not url:
                    skipped_no_url += 1
                    continue
                if not geom:
                    skipped_no_geom += 1
                    continue
                yielded += 1
                from shapely.geometry import shape
                yield TileInfo(
                    source_id=tile_name,
                    filename=f"oh_{tile_name}.laz",
                    url=url,
                    bbox=shape(geom),
                    crs=3735,  # Ohio State Plane South
                    format="laz",
                )
            discover_elapsed = round(time.monotonic() - discover_start, 2)
            log.info("oh_discover_complete", total_tiles=yielded, skipped_no_url=skipped_no_url, skipped_no_geom=skipped_no_geom, elapsed_s=discover_elapsed)

    async def download_tile(self, tile: TileInfo, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / tile.filename
        if dest_path.exists():
            log.debug("oh_tile_cached", tile=tile.source_id, path=str(dest_path))
            return dest_path
        log.info("oh_download_start", tile=tile.source_id, url=tile.url[:120], dest=str(dest_path))
        dl_start = time.monotonic()
        try:
            downloaded = await self._stream_download(tile.url, dest_path, timeout=300.0)
        except Exception as e:
            log.error("oh_download_failed", tile=tile.source_id, error=str(e), exception=True)
            raise
        dl_elapsed = round(time.monotonic() - dl_start, 2)
        size_mb = round(downloaded / (1024 * 1024), 2)
        log.info("oh_download_complete", tile=tile.source_id, size_mb=size_mb, elapsed_s=dl_elapsed, path=str(dest_path))
        return dest_path
