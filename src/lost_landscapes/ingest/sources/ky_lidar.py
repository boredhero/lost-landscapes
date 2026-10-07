"""Kentucky LiDAR data source.

Downloads from KyFromAbove program via ArcGIS REST API.
Prefers Phase 2 COPC data (2022, newer) over Phase 1 (2012).
"""

import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from shapely.geometry import Polygon

from lost_landscapes.ingest.sources.base import DataSource, TileInfo
from lost_landscapes.utils.log_manager import log

KY_TILE_INDEX_URL = (
    "https://kygisserver.ky.gov/arcgis/rest/services/"
    "WGS84WM_Services/KY_Data_Tiles_PointCloud_WGS84WM/MapServer/0/query"
)


class KYLidarSource(DataSource):
    """Kentucky LiDAR data from KyFromAbove."""

    @property
    def name(self) -> str:
        return "ky"

    async def discover_tiles(self, bbox: Polygon) -> AsyncIterator[TileInfo]:
        """Query KyFromAbove tile index for tiles intersecting bbox."""
        bounds = bbox.bounds
        log.info("ky_discover_tiles_start", bbox_minx=bounds[0], bbox_miny=bounds[1], bbox_maxx=bounds[2], bbox_maxy=bounds[3])
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
                response = await client.get(KY_TILE_INDEX_URL, params=params)
                response.raise_for_status()
                data = response.json()
                elapsed = round(time.monotonic() - query_start, 2)
                log.info("ky_query_success", status_code=response.status_code, elapsed_s=elapsed, url=KY_TILE_INDEX_URL)
            except (httpx.HTTPError, Exception) as e:
                elapsed = round(time.monotonic() - query_start, 2)
                log.warning("ky_query_failed", error=str(e), elapsed_s=elapsed, exception=True)
                return
            features = data.get("features", [])
            tile_count = 0
            skipped = 0
            for feature in features:
                props = feature.get("properties", {})
                geom = feature.get("geometry")
                tile_name = props.get("tilename") or props.get("Name") or str(props.get("FID", ""))
                # Prefer Phase 2 (newer, COPC), fall back to Phase 1
                url = props.get("phase2_aws_url") or props.get("phase1_aws_url") or ""
                fmt = "laz"
                if url and ".copc.laz" in url:
                    fmt = "copc.laz"
                if url and geom:
                    from shapely.geometry import shape
                    tile_count += 1
                    yield TileInfo(
                        source_id=tile_name,
                        filename=f"ky_{tile_name}.laz",
                        url=url,
                        bbox=shape(geom),
                        crs=3089,
                        format=fmt,
                    )
                else:
                    skipped += 1
                    log.debug("ky_tile_skipped", tile_name=tile_name, has_url=bool(url), has_geom=bool(geom))
            log.info("ky_discover_tiles_complete", total_features=len(features), tiles_yielded=tile_count, tiles_skipped=skipped)

    async def download_tile(self, tile: TileInfo, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / tile.filename
        if dest_path.exists():
            log.debug("ky_tile_cached", source_id=tile.source_id, path=str(dest_path))
            return dest_path
        log.info("ky_download_start", source_id=tile.source_id, url=tile.url[:120], dest=str(dest_path))
        dl_start = time.monotonic()
        try:
            downloaded = await self._stream_download(tile.url, dest_path, timeout=300.0)
            elapsed = round(time.monotonic() - dl_start, 2)
            log.info("ky_download_complete", source_id=tile.source_id, bytes=downloaded, elapsed_s=elapsed, path=str(dest_path))
        except Exception as e:
            elapsed = round(time.monotonic() - dl_start, 2)
            log.error("ky_download_failed", source_id=tile.source_id, url=tile.url[:120], error=str(e), elapsed_s=elapsed, exception=True)
            raise
        return dest_path
