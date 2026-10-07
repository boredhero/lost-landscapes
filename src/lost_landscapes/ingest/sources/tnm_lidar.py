"""USGS TNMAccess LiDAR data source.

Universal fallback source using the USGS National Map Access API.
Covers all US states with individual LAZ tile download URLs.
Used for states without their own tile index services (VT, TN, IN, NH, ME, RI, DE).
"""

import re
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from shapely.geometry import Polygon, box

from lost_landscapes.ingest.sources.base import DataSource, TileInfo
from lost_landscapes.utils.log_manager import log

TNM_API_URL = "https://tnmaccess.nationalmap.gov/api/v1/products"


class TNMLidarSource(DataSource):
    """USGS TNMAccess LiDAR — universal US coverage."""

    @property
    def name(self) -> str:
        return "tnm"

    async def discover_tiles(self, bbox: Polygon) -> AsyncIterator[TileInfo]:
        """Query TNMAccess for LAZ tiles intersecting bbox."""
        bounds = bbox.bounds
        log.info("tnm_discover_start", bbox=bounds)
        params = {
            "datasets": "Lidar Point Cloud (LPC)",
            "bbox": f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}",
            "prodFormats": "LAZ",
            "max": 50,
            "offset": 0,
            "outputFormat": "JSON",
        }
        seen = set()
        tile_count = 0
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Paginate up to 500 tiles
            for page in range(10):
                params["offset"] = page * 50
                log.debug("tnm_api_request", page=page, offset=params["offset"])
                try:
                    response = await client.get(TNM_API_URL, params=params)
                    response.raise_for_status()
                    data = response.json()
                except (httpx.HTTPError, Exception) as e:
                    log.warning("tnm_query_failed", error=str(e), page=page, exception=True)
                    return
                items = data.get("items", [])
                total = data.get("total", 0)
                log.debug("tnm_api_response", page=page, items_returned=len(items), total_available=total)
                if not items:
                    log.info("tnm_discover_empty_page", page=page)
                    return
                for item in items:
                    url = item.get("downloadLazURL") or item.get("downloadURL") or ""
                    title = item.get("title") or item.get("sourceId") or ""
                    bb = item.get("boundingBox", {})
                    if not url or not bb or url in seen:
                        continue
                    seen.add(url)
                    try:
                        tile_bbox = box(bb["minX"], bb["minY"], bb["maxX"], bb["maxY"])
                    except (KeyError, TypeError) as e:
                        log.warning("tnm_bbox_parse_failed", item_title=title[:80], error=str(e))
                        continue
                    # Extract a short tile name from the URL
                    tile_name = Path(url).stem
                    # Parse acquisition year from publication date, title, or URL
                    pub_date = item.get("publicationDate") or item.get("dateCreated") or ""
                    year_match = re.search(r'(\d{4})', pub_date)
                    if not year_match:
                        year_match = re.search(r'[_/](\d{4})[_/]', url + "/" + title)
                    acq_year = int(year_match.group(1)) if year_match and 1990 <= int(year_match.group(1)) <= 2030 else None
                    tile_count += 1
                    log.debug("tnm_tile_discovered", tile_name=tile_name, year=acq_year, size_bytes=item.get("sizeInBytes"))
                    yield TileInfo(
                        source_id=tile_name,
                        filename=f"tnm_{tile_name}.laz",
                        url=url,
                        bbox=tile_bbox,
                        crs=4326,
                        file_size_bytes=item.get("sizeInBytes"),
                        acquisition_year=acq_year,
                        format="laz",
                    )
                if params["offset"] + 50 >= total:
                    log.info("tnm_discover_complete", tiles_found=tile_count, pages_fetched=page + 1, elapsed_s=time.monotonic() - t0)
                    return
        log.info("tnm_discover_complete", tiles_found=tile_count, pages_fetched=10, elapsed_s=time.monotonic() - t0)

    async def download_tile(self, tile: TileInfo, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / tile.filename
        if dest_path.exists():
            log.info("tnm_tile_cached", path=str(dest_path))
            return dest_path
        log.info("tnm_download_start", tile_id=tile.source_id, url=tile.url[:120], dest=str(dest_path))
        t0 = time.monotonic()
        try:
            downloaded = await self._stream_download(tile.url, dest_path, timeout=300.0)
            elapsed = time.monotonic() - t0
            log.info("tnm_download_complete", tile_id=tile.source_id, path=str(dest_path), bytes=downloaded, elapsed_s=elapsed)
        except httpx.HTTPStatusError as e:
            log.error("tnm_download_http_error", tile_id=tile.source_id, status=e.response.status_code, error=str(e), exception=True)
            raise
        except Exception as e:
            log.error("tnm_download_failed", tile_id=tile.source_id, url=tile.url[:120], error=str(e), exception=True)
            raise
        return dest_path
