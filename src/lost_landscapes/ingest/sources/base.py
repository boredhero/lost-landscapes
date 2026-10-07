"""Abstract base class for LiDAR data sources."""

import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx
from shapely.geometry import Polygon

from lost_landscapes.utils.log_manager import log


@dataclass
class TileInfo:
    """Metadata for a discoverable LiDAR tile."""

    source_id: str
    filename: str
    url: str
    bbox: Polygon
    crs: int
    file_size_bytes: int | None = None
    acquisition_year: int | None = None
    format: str = "laz"


class DataSource(ABC):
    """Abstract base for LiDAR data sources."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this data source."""
        ...

    @abstractmethod
    async def discover_tiles(self, bbox: Polygon) -> AsyncIterator[TileInfo]:
        """Find available tiles intersecting the bounding box."""
        ...

    @abstractmethod
    async def download_tile(self, tile: TileInfo, dest_dir: Path) -> Path:
        """Download a single tile. Return local file path."""
        ...

    async def _stream_download(self, url: str, dest_path: Path, timeout: float = 300.0) -> int:
        """Stream-download a URL to dest_path with atomic write (.tmp + rename).
        On failure, removes the tmp file so no corrupt partial files remain.
        Returns bytes downloaded."""
        tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    downloaded = 0
                    with open(tmp_path, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=1024 * 256):
                            f.write(chunk)
                            downloaded += len(chunk)
            tmp_path.rename(dest_path)
            return downloaded
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    async def download_region(self, bbox: Polygon, dest_dir: Path) -> list[Path]:
        """Download all tiles in a region."""
        bounds = bbox.bounds
        log.info("download_region_start", source=self.name, bbox_minx=bounds[0], bbox_miny=bounds[1], bbox_maxx=bounds[2], bbox_maxy=bounds[3], dest_dir=str(dest_dir))
        region_start = time.monotonic()
        paths = []
        tile_count = 0
        async for tile_info in self.discover_tiles(bbox):
            tile_count += 1
            log.debug("download_region_tile", source=self.name, tile_num=tile_count, source_id=tile_info.source_id, url=tile_info.url[:120])
            try:
                path = await self.download_tile(tile_info, dest_dir)
                paths.append(path)
            except Exception as e:
                log.error("download_region_tile_failed", source=self.name, source_id=tile_info.source_id, error=str(e), exception=True)
        elapsed = round(time.monotonic() - region_start, 2)
        log.info("download_region_complete", source=self.name, tiles_discovered=tile_count, tiles_downloaded=len(paths), elapsed_s=elapsed)
        return paths
