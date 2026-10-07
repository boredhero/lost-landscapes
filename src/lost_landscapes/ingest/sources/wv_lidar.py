"""West Virginia LiDAR data source.

Downloads from WV GIS Technical Center elevation data portal.
"""

import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from shapely.geometry import Polygon, shape

from lost_landscapes.ingest.sources.base import DataSource, TileInfo
from lost_landscapes.utils.log_manager import log

# WV elevation data REST endpoint
WV_ELEVATION_URL = "https://data.wvgis.wvu.edu/elevation"


class WVLidarSource(DataSource):
    """West Virginia LiDAR data from WVGIS."""

    @property
    def name(self) -> str:
        return "wv"

    async def discover_tiles(self, bbox: Polygon) -> AsyncIterator[TileInfo]:
        """Query WV tile index for tiles intersecting bbox.

        WV uses a tile index served via their elevation portal.
        We query their ArcGIS REST services for available tiles.
        """
        bounds = bbox.bounds
        log.info("wv_discover_start", bbox=bounds)
        # WV serves data through an ArcGIS MapServer
        wv_query_url = (
            "https://services.wvgis.wvu.edu/arcgis/rest/services/"
            "Elevation/Index_LiDAR_702/MapServer/0/query"
        )
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
                response = await client.get(wv_query_url, params=params)
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, Exception) as e:
                log.warning("wv_query_failed", error=str(e), exception=True)
                return
            features = data.get("features", [])
            log.debug("wv_query_response", features_returned=len(features))
            for feature in features:
                props = feature.get("properties", {})
                geom = feature.get("geometry")
                tile_name = props.get("Name") or props.get("TILE") or str(props.get("FID", ""))
                url = props.get("URL") or props.get("DOWNLOAD_URL", "")
                if url and geom:
                    tile_count += 1
                    log.debug("wv_tile_discovered", tile_name=tile_name, url=url[:120])
                    yield TileInfo(
                        source_id=tile_name,
                        filename=f"wv_{tile_name}.laz",
                        url=url,
                        bbox=shape(geom),
                        crs=26917,  # UTM 17N
                        format="laz",
                    )
                else:
                    skipped_no_url += 1
        log.info("wv_discover_complete", tiles_found=tile_count, skipped_no_url=skipped_no_url, elapsed_s=time.monotonic() - t0)

    async def download_tile(self, tile: TileInfo, dest_dir: Path) -> Path:
        """Download a WV LAZ tile."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / tile.filename
        if dest_path.exists():
            log.info("wv_tile_cached", tile_id=tile.source_id, path=str(dest_path))
            return dest_path
        log.info("wv_download_start", tile_id=tile.source_id, url=tile.url[:120], dest=str(dest_path))
        t0 = time.monotonic()
        try:
            downloaded = await self._stream_download(tile.url, dest_path, timeout=300.0)
            elapsed = time.monotonic() - t0
            log.info("wv_download_complete", tile_id=tile.source_id, path=str(dest_path), bytes=downloaded, elapsed_s=elapsed)
        except httpx.HTTPStatusError as e:
            log.error("wv_download_http_error", tile_id=tile.source_id, status=e.response.status_code, error=str(e), exception=True)
            raise
        except Exception as e:
            log.error("wv_download_failed", tile_id=tile.source_id, url=tile.url[:120], error=str(e), exception=True)
            raise
        return dest_path
