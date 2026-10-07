"""Connecticut LiDAR data source.

Downloads from CT ECO via ArcGIS REST API.
Prefers 2023 LAZ data over 2016 LAS when available.
"""

import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from shapely.geometry import Polygon

from lost_landscapes.ingest.sources.base import DataSource, TileInfo
from lost_landscapes.utils.log_manager import log

CT_TILE_INDEX_URL = (
    "https://cteco.uconn.edu/ctraster/rest/services/"
    "maps/download_grids/MapServer/1/query"
)


class CTLidarSource(DataSource):
    """Connecticut LiDAR data from CT ECO."""

    @property
    def name(self) -> str:
        return "ct"

    async def discover_tiles(self, bbox: Polygon) -> AsyncIterator[TileInfo]:
        """Query CT ECO tile index for tiles intersecting bbox."""
        bounds = bbox.bounds
        log.info("ct_discover_tiles_start", bbox_minx=bounds[0], bbox_miny=bounds[1], bbox_maxx=bounds[2], bbox_maxy=bounds[3])
        # CT ECO does not support resultRecordCount
        params = {
            "where": "1=1",
            "geometry": f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "outSR": "4326",
            "outFields": "*",
            "returnGeometry": "true",
            "f": "geojson",
        }
        query_start = time.monotonic()
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.get(CT_TILE_INDEX_URL, params=params)
                response.raise_for_status()
                data = response.json()
                elapsed = round(time.monotonic() - query_start, 2)
                log.info("ct_query_success", status_code=response.status_code, elapsed_s=elapsed, url=CT_TILE_INDEX_URL)
            except (httpx.HTTPError, Exception) as e:
                elapsed = round(time.monotonic() - query_start, 2)
                log.warning("ct_query_failed", error=str(e), elapsed_s=elapsed, exception=True)
                return
            features = data.get("features", [])
            tile_count = 0
            skipped = 0
            for feature in features:
                props = feature.get("properties", {})
                geom = feature.get("geometry")
                tile_name = props.get("Tile") or props.get("name") or str(props.get("FID", ""))
                # Prefer 2023 LAZ over 2016 LAS
                url = props.get("elev_2023_laz") or props.get("elev_2016_las") or ""
                if url and geom:
                    from shapely.geometry import shape
                    tile_count += 1
                    yield TileInfo(
                        source_id=tile_name,
                        filename=f"ct_{tile_name}.laz",
                        url=url,
                        bbox=shape(geom),
                        crs=6434,
                        format="laz",
                    )
                else:
                    skipped += 1
                    log.debug("ct_tile_skipped", tile_name=tile_name, has_url=bool(url), has_geom=bool(geom))
            log.info("ct_discover_tiles_complete", total_features=len(features), tiles_yielded=tile_count, tiles_skipped=skipped)

    async def download_tile(self, tile: TileInfo, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / tile.filename
        if dest_path.exists():
            log.debug("ct_tile_cached", source_id=tile.source_id, path=str(dest_path))
            return dest_path
        log.info("ct_download_start", source_id=tile.source_id, url=tile.url[:120], dest=str(dest_path))
        dl_start = time.monotonic()
        try:
            downloaded = await self._stream_download(tile.url, dest_path, timeout=300.0)
            elapsed = round(time.monotonic() - dl_start, 2)
            log.info("ct_download_complete", source_id=tile.source_id, bytes=downloaded, elapsed_s=elapsed, path=str(dest_path))
        except Exception as e:
            elapsed = round(time.monotonic() - dl_start, 2)
            log.error("ct_download_failed", source_id=tile.source_id, url=tile.url[:120], error=str(e), elapsed_s=elapsed, exception=True)
            raise
        return dest_path
