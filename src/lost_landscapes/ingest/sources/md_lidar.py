"""Maryland LiDAR data source.

Downloads from MD iMAP via ArcGIS REST API.
"""

import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from shapely.geometry import Polygon

from lost_landscapes.ingest.sources.base import DataSource, TileInfo
from lost_landscapes.utils.log_manager import log

# MD iMAP LiDAR tile availability endpoint
MD_LIDAR_URL = (
    "https://lidar.geodata.md.gov/imap/rest/services/"
    "Status/MD_AvailableAcquisitions/MapServer/0/query"
)


class MDLidarSource(DataSource):
    """Maryland LiDAR data from MD iMAP."""

    @property
    def name(self) -> str:
        return "md"

    async def discover_tiles(self, bbox: Polygon) -> AsyncIterator[TileInfo]:
        """Query MD tile index for tiles intersecting bbox."""
        bounds = bbox.bounds
        log.info("md_discover_tiles_start", bbox_minx=bounds[0], bbox_miny=bounds[1], bbox_maxx=bounds[2], bbox_maxy=bounds[3])
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
        query_start = time.monotonic()
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.get(MD_LIDAR_URL, params=params)
                response.raise_for_status()
                data = response.json()
                elapsed = round(time.monotonic() - query_start, 2)
                log.info("md_query_success", status_code=response.status_code, elapsed_s=elapsed, url=MD_LIDAR_URL)
            except (httpx.HTTPError, Exception) as e:
                elapsed = round(time.monotonic() - query_start, 2)
                log.warning("md_query_failed", error=str(e), elapsed_s=elapsed, exception=True)
                return
            features = data.get("features", [])
            tile_count = 0
            skipped = 0
            for feature in features:
                props = feature.get("properties", {})
                geom = feature.get("geometry")
                tile_name = props.get("Name") or props.get("TILE") or str(props.get("FID", ""))
                url = props.get("URL") or props.get("DOWNLOAD_URL", "")
                if url and geom:
                    from shapely.geometry import shape
                    tile_count += 1
                    yield TileInfo(
                        source_id=tile_name,
                        filename=f"md_{tile_name}.laz",
                        url=url,
                        bbox=shape(geom),
                        crs=26985,  # NAD83 / Maryland
                        format="laz",
                    )
                else:
                    skipped += 1
                    log.debug("md_tile_skipped", tile_name=tile_name, has_url=bool(url), has_geom=bool(geom))
            log.info("md_discover_tiles_complete", total_features=len(features), tiles_yielded=tile_count, tiles_skipped=skipped)

    async def download_tile(self, tile: TileInfo, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / tile.filename
        if dest_path.exists():
            log.debug("md_tile_cached", source_id=tile.source_id, path=str(dest_path))
            return dest_path
        log.info("md_download_start", source_id=tile.source_id, url=tile.url[:120], dest=str(dest_path))
        dl_start = time.monotonic()
        try:
            downloaded = await self._stream_download(tile.url, dest_path, timeout=300.0)
        except Exception as e:
            elapsed = round(time.monotonic() - dl_start, 2)
            log.error("md_download_failed", source_id=tile.source_id, url=tile.url[:120], error=str(e), elapsed_s=elapsed, exception=True)
            raise
        elapsed = round(time.monotonic() - dl_start, 2)
        log.info("md_download_complete", source_id=tile.source_id, bytes=downloaded, elapsed_s=elapsed, path=str(dest_path))
        return dest_path
