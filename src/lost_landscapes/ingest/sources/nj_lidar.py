"""New Jersey LiDAR data source.

Downloads from NJGIN via ArcGIS REST FeatureServers.
NJ splits data into per-region services; we query the most relevant ones.
"""

import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from shapely.geometry import Polygon

from lost_landscapes.ingest.sources.base import DataSource, TileInfo
from lost_landscapes.utils.log_manager import log

# NJ has separate FeatureServers per LiDAR project
NJ_SERVICES = [
    ("https://services2.arcgis.com/XVOqAjTOJ5P6ngMu/arcgis/rest/services/Grid_LiDAR_Northwest_2018/FeatureServer/0/query", "nw2018"),
    ("https://services2.arcgis.com/XVOqAjTOJ5P6ngMu/arcgis/rest/services/Grid_LiDAR_South_2019/FeatureServer/0/query", "south2019"),
    ("https://services2.arcgis.com/XVOqAjTOJ5P6ngMu/arcgis/rest/services/Grid_LiDAR_DVRPC_2015/FeatureServer/0/query", "dvrpc2015"),
    ("https://services2.arcgis.com/XVOqAjTOJ5P6ngMu/arcgis/rest/services/Grid_LiDAR_NortheastNJPostSandy_2014/FeatureServer/0/query", "ne2014"),
]


class NJLidarSource(DataSource):
    """New Jersey LiDAR data from NJGIN."""

    @property
    def name(self) -> str:
        return "nj"

    async def discover_tiles(self, bbox: Polygon) -> AsyncIterator[TileInfo]:
        """Query NJ tile indices for tiles intersecting bbox."""
        bounds = bbox.bounds
        log.info("nj_discover_start", bbox_minx=bounds[0], bbox_miny=bounds[1], bbox_maxx=bounds[2], bbox_maxy=bounds[3], services_count=len(NJ_SERVICES))
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
        seen = set()
        total_yielded = 0
        discover_start = time.monotonic()
        async with httpx.AsyncClient(timeout=60.0) as client:
            for url, tag in NJ_SERVICES:
                svc_start = time.monotonic()
                log.debug("nj_service_query", service=tag, url=url[:100])
                try:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    data = response.json()
                except (httpx.HTTPError, Exception) as e:
                    log.warning("nj_query_failed", service=tag, error=str(e), exception=True)
                    continue
                features = data.get("features", [])
                svc_elapsed = round(time.monotonic() - svc_start, 2)
                log.debug("nj_service_response", service=tag, feature_count=len(features), elapsed_s=svc_elapsed, status_code=response.status_code)
                skipped_no_url = 0
                skipped_no_geom = 0
                skipped_duplicate = 0
                for feature in features:
                    props = feature.get("properties", {})
                    geom = feature.get("geometry")
                    tile_name = props.get("Name") or props.get("TILE") or str(props.get("FID", ""))
                    dl_url = props.get("Download_Link") or props.get("URL") or ""
                    key = f"{tag}_{tile_name}"
                    if not dl_url:
                        skipped_no_url += 1
                        continue
                    if not geom:
                        skipped_no_geom += 1
                        continue
                    if key in seen:
                        skipped_duplicate += 1
                        continue
                    seen.add(key)
                    total_yielded += 1
                    from shapely.geometry import shape
                    yield TileInfo(
                        source_id=key,
                        filename=f"nj_{key}.laz",
                        url=dl_url,
                        bbox=shape(geom),
                        crs=3424,
                        format="laz",
                    )
                if skipped_no_url or skipped_no_geom or skipped_duplicate:
                    log.debug("nj_service_skipped", service=tag, no_url=skipped_no_url, no_geom=skipped_no_geom, duplicate=skipped_duplicate)
        discover_elapsed = round(time.monotonic() - discover_start, 2)
        log.info("nj_discover_complete", total_tiles=total_yielded, total_seen=len(seen), elapsed_s=discover_elapsed)

    async def download_tile(self, tile: TileInfo, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / tile.filename
        if dest_path.exists():
            log.debug("nj_tile_cached", tile=tile.source_id, path=str(dest_path))
            return dest_path
        log.info("nj_download_start", tile=tile.source_id, url=tile.url[:120], dest=str(dest_path))
        dl_start = time.monotonic()
        try:
            downloaded = await self._stream_download(tile.url, dest_path, timeout=300.0)
        except Exception as e:
            log.error("nj_download_failed", tile=tile.source_id, error=str(e), exception=True)
            raise
        dl_elapsed = round(time.monotonic() - dl_start, 2)
        size_mb = round(downloaded / (1024 * 1024), 2)
        log.info("nj_download_complete", tile=tile.source_id, size_mb=size_mb, elapsed_s=dl_elapsed, path=str(dest_path))
        return dest_path
