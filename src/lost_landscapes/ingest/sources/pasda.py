"""Pennsylvania Spatial Data Access (PASDA) LiDAR source.

Downloads from PASDA via their ArcGIS REST API tile index + direct HTTP.
PAMAP program tiles are on a 10,000ft x 10,000ft grid.
"""

import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from shapely.geometry import Polygon, box, shape

from lost_landscapes.ingest.sources.base import DataSource, TileInfo
from lost_landscapes.utils.log_manager import log

# PASDA ArcGIS REST endpoint for PAMAP LiDAR tile index
PASDA_TILE_INDEX_URL = (
    "https://maps.psiee.psu.edu/arcgis/rest/services/PAMAP/PAMAP_LiDAR/MapServer/0/query"
)


class PASDASource(DataSource):
    """Pennsylvania PAMAP LiDAR data from PASDA."""

    @property
    def name(self) -> str:
        return "pasda"

    async def discover_tiles(self, bbox: Polygon) -> AsyncIterator[TileInfo]:
        """Query PASDA tile index for tiles intersecting bbox."""
        bounds = bbox.bounds  # (minx, miny, maxx, maxy)
        log.info("pasda_discover_start", bbox_minx=bounds[0], bbox_miny=bounds[1], bbox_maxx=bounds[2], bbox_maxy=bounds[3])
        params = {
            "where": "1=1",
            "geometry": f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "outSR": "4326",
            "outFields": "*",
            "returnGeometry": "true",
            "f": "geojson",
            "resultRecordCount": 1000,
        }
        discover_start = time.monotonic()
        async with httpx.AsyncClient(timeout=60.0) as client:
            log.debug("pasda_api_request", url=PASDA_TILE_INDEX_URL[:100])
            try:
                response = await client.get(PASDA_TILE_INDEX_URL, params=params)
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, Exception) as e:
                log.error("pasda_query_failed", error=str(e), exception=True)
                return
            features = data.get("features", [])
            api_elapsed = round(time.monotonic() - discover_start, 2)
            log.debug("pasda_api_response", feature_count=len(features), elapsed_s=api_elapsed, status_code=response.status_code)
            yielded = 0
            skipped_no_geom = 0
            constructed_urls = 0
            for feature in features:
                props = feature.get("properties", {})
                geom = feature.get("geometry")
                if not geom:
                    skipped_no_geom += 1
                    continue
                tile_name = props.get("TILE_NAME") or props.get("Name") or props.get("FID", "unknown")
                download_url = props.get("DOWNLOAD_URL") or props.get("URL", "")
                if not download_url:
                    # Construct URL from tile name pattern
                    download_url = f"https://www.pasda.psu.edu/uci/LidarDownload.aspx?tile={tile_name}"
                    constructed_urls += 1
                yielded += 1
                yield TileInfo(
                    source_id=str(tile_name),
                    filename=f"{tile_name}.laz",
                    url=download_url,
                    bbox=shape(geom) if geom.get("type") else box(*bounds),
                    crs=2272,  # PA State Plane South (NAD83)
                    file_size_bytes=props.get("FILE_SIZE"),
                    acquisition_year=props.get("YEAR"),
                    format="laz",
                )
            discover_elapsed = round(time.monotonic() - discover_start, 2)
            log.info("pasda_discover_complete", total_tiles=yielded, skipped_no_geom=skipped_no_geom, constructed_urls=constructed_urls, elapsed_s=discover_elapsed)

    async def download_tile(self, tile: TileInfo, dest_dir: Path) -> Path:
        """Download a PASDA LAZ tile via HTTP."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / tile.filename
        if dest_path.exists():
            log.debug("pasda_tile_cached", tile=tile.source_id, path=str(dest_path))
            return dest_path
        log.info("pasda_download_start", tile=tile.source_id, url=tile.url[:120], dest=str(dest_path))
        dl_start = time.monotonic()
        try:
            bytes_downloaded = await self._stream_download(tile.url, dest_path, timeout=300.0)
        except Exception as e:
            log.error("pasda_download_failed", tile=tile.source_id, error=str(e), exception=True)
            raise
        dl_elapsed = round(time.monotonic() - dl_start, 2)
        size_mb = round(bytes_downloaded / (1024 * 1024), 2)
        log.info("pasda_download_complete", tile=tile.source_id, size_mb=size_mb, elapsed_s=dl_elapsed, path=str(dest_path))
        return dest_path
