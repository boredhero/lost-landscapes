"""USGS 3DEP LiDAR source via STAC API + COPC from Planetary Computer.

Data is free and requires no API key. Uses pystac-client to query the
Microsoft Planetary Computer STAC catalog for 3DEP COPC tiles.

Download URLs require SAS token signing (Azure blob storage has public
access disabled). The planetary-computer SDK handles this automatically
via a free, unauthenticated token endpoint.
"""

import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import planetary_computer
from shapely.geometry import Polygon, shape

from lost_landscapes.ingest.sources.base import DataSource, TileInfo
from lost_landscapes.utils.log_manager import log

# Planetary Computer STAC endpoint (free, no auth for search)
STAC_API_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION_ID = "3dep-lidar-copc"


class USGS3DEPSource(DataSource):
    """USGS 3DEP LiDAR data via Planetary Computer STAC + COPC."""

    @property
    def name(self) -> str:
        return "usgs_3dep"

    async def discover_tiles(self, bbox: Polygon) -> AsyncIterator[TileInfo]:
        """Query STAC catalog for COPC tiles intersecting the bounding box."""
        bounds = bbox.bounds  # (minx, miny, maxx, maxy)
        log.info("3dep_discover_start", bbox=bounds)
        search_body = {
            "collections": [COLLECTION_ID],
            "bbox": list(bounds),
            "limit": 250,
        }
        tile_count = 0
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=60.0) as client:
            url = f"{STAC_API_URL}/search"
            page = 1
            while True:
                log.info("stac_search", url=url, page=page, bbox=bounds)
                try:
                    response = await client.post(url, json=search_body)
                    response.raise_for_status()
                    data = response.json()
                except httpx.HTTPStatusError as e:
                    log.error("stac_search_http_error", page=page, status=e.response.status_code, error=str(e), exception=True)
                    return
                except Exception as e:
                    log.error("stac_search_failed", page=page, error=str(e), exception=True)
                    return
                features = data.get("features", [])
                log.debug("stac_search_response", page=page, features_returned=len(features))
                if not features:
                    log.info("3dep_discover_no_more_features", page=page)
                    break
                for item in features:
                    tile_info = self._parse_stac_item(item)
                    if tile_info:
                        tile_count += 1
                        yield tile_info
                # Follow next link for pagination
                next_link = None
                for link in data.get("links", []):
                    if link.get("rel") == "next":
                        next_link = link.get("body") or link.get("href")
                        break
                if next_link and isinstance(next_link, dict):
                    search_body = next_link
                    page += 1
                elif next_link and isinstance(next_link, str):
                    url = next_link
                    page += 1
                else:
                    break
        log.info("3dep_discover_complete", tiles_found=tile_count, pages_fetched=page, elapsed_s=time.monotonic() - t0)

    def _parse_stac_item(self, item: dict) -> TileInfo | None:
        """Parse a STAC item into TileInfo."""
        try:
            item_id = item["id"]
            geometry = shape(item["geometry"])
            properties = item.get("properties", {})
            # Find the COPC asset
            assets = item.get("assets", {})
            copc_asset = assets.get("data") or assets.get("copc")
            if not copc_asset:
                log.debug("stac_item_no_copc_asset", item_id=item_id, available_assets=list(assets.keys()))
                return None
            href = copc_asset["href"]
            # Try to get file size from asset
            file_size = copc_asset.get("file:size")
            # Extract acquisition year from datetime
            dt_str = properties.get("datetime", "")
            year = None
            if dt_str and len(dt_str) >= 4:
                try:
                    year = int(dt_str[:4])
                except ValueError as e:
                    log.debug("stac_year_parse_failed", datetime_str=dt_str[:20], error=str(e))
            log.debug("stac_item_parsed", item_id=item_id, year=year, file_size=file_size, crs=properties.get("proj:epsg", 4326))
            return TileInfo(
                source_id=item_id,
                filename=f"{item_id}.copc.laz",
                url=href,
                bbox=geometry,
                crs=properties.get("proj:epsg", 4326),
                file_size_bytes=file_size,
                acquisition_year=year,
                format="copc",
            )
        except (KeyError, TypeError) as e:
            log.warning("stac_parse_error", item_id=item.get("id"), error=str(e), exception=True)
            return None

    async def download_tile(self, tile: TileInfo, dest_dir: Path) -> Path:
        """Download a COPC tile via HTTP with Planetary Computer SAS signing.

        Azure blob storage requires a SAS token. planetary_computer.sign()
        appends the token to the URL. Tokens are free, no account needed,
        cached for ~24h by the SDK.
        """
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / tile.filename
        if dest_path.exists():
            log.info("3dep_tile_cached", tile_id=tile.source_id, path=str(dest_path))
            return dest_path
        # Sign the URL with a Planetary Computer SAS token
        try:
            signed_url = planetary_computer.sign(tile.url)
        except Exception as e:
            log.error("3dep_sas_sign_failed", tile_id=tile.source_id, error=str(e), exception=True)
            raise
        log.info("3dep_download_start", tile_id=tile.source_id, url=signed_url[:120], dest=str(dest_path))
        t0 = time.monotonic()
        try:
            downloaded = await self._stream_download(signed_url, dest_path, timeout=300.0)
            elapsed = time.monotonic() - t0
            log.info("3dep_download_complete", tile_id=tile.source_id, path=str(dest_path), bytes=downloaded, elapsed_s=elapsed)
        except httpx.HTTPStatusError as e:
            log.error("3dep_download_http_error", tile_id=tile.source_id, status=e.response.status_code, error=str(e), exception=True)
            raise
        except Exception as e:
            log.error("3dep_download_failed", tile_id=tile.source_id, url=tile.url[:120], error=str(e), exception=True)
            raise
        return dest_path
