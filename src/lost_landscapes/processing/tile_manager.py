"""Tile manager — spatial indexing and tile grid management.

Maintains an R-tree index of all processed tiles for fast spatial queries.
Handles overlap buffers for edge-effect mitigation during detection.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from rtree import index as rtree_index
from shapely.geometry import Polygon

from lost_landscapes.utils.log_manager import log


@dataclass
class ManagedTile:
    """A tile tracked by the TileManager."""

    tile_id: UUID
    bbox: Polygon
    dem_path: Path | None = None
    derivative_paths: dict[str, Path] = field(default_factory=dict)
    point_cloud_path: Path | None = None
    crs: int = 32617
    resolution_m: float = 1.0


class TileManager:
    """Spatial index and metadata for all processed tiles."""

    def __init__(self):
        self._idx = rtree_index.Index()
        self._tiles: dict[int, ManagedTile] = {}
        self._counter = 0
        log.debug("tile_manager_init")

    def add_tile(self, tile: ManagedTile) -> int:
        """Add a tile to the spatial index. Returns internal index ID."""
        idx_id = self._counter
        self._counter += 1
        self._tiles[idx_id] = tile
        bounds = tile.bbox.bounds  # (minx, miny, maxx, maxy)
        self._idx.insert(idx_id, bounds)
        log.debug("tile_manager_add", idx_id=idx_id, tile_id=str(tile.tile_id), bounds=bounds, crs=tile.crs, resolution_m=tile.resolution_m, total_tiles=self._counter)
        return idx_id

    def query_bbox(
        self,
        west: float,
        south: float,
        east: float,
        north: float,
    ) -> list[ManagedTile]:
        """Find all tiles intersecting a bounding box."""
        t0 = time.perf_counter()
        hits = list(self._idx.intersection((west, south, east, north)))
        results = [self._tiles[i] for i in hits]
        elapsed = time.perf_counter() - t0
        log.debug("tile_manager_query_bbox", west=west, south=south, east=east, north=north, hits=len(results), elapsed_s=round(elapsed, 6), total_tiles=self._counter)
        return results

    def query_polygon(self, polygon: Polygon) -> list[ManagedTile]:
        """Find all tiles intersecting an arbitrary polygon."""
        t0 = time.perf_counter()
        bounds = polygon.bounds
        candidates = self.query_bbox(*bounds)
        results = [t for t in candidates if t.bbox.intersects(polygon)]
        elapsed = time.perf_counter() - t0
        log.debug("tile_manager_query_polygon", polygon_bounds=bounds, candidates=len(candidates), intersecting=len(results), elapsed_s=round(elapsed, 6))
        return results

    def get_neighbors(self, tile: ManagedTile, buffer_m: float = 100.0) -> list[ManagedTile]:
        """Find tiles neighboring a given tile (for overlap processing).

        Args:
            tile: the reference tile
            buffer_m: buffer distance in approximate meters (degrees approximation)
        """
        # Approximate meters to degrees at typical latitude (~40°N)
        buffer_deg = buffer_m / 111_320.0
        buffered = tile.bbox.buffer(buffer_deg)
        neighbors = self.query_polygon(buffered)
        result = [t for t in neighbors if t.tile_id != tile.tile_id]
        log.debug("tile_manager_get_neighbors", tile_id=str(tile.tile_id), buffer_m=buffer_m, buffer_deg=round(buffer_deg, 8), candidates=len(neighbors), neighbors=len(result))
        return result

    def count(self) -> int:
        return len(self._tiles)

    def all_tiles(self) -> list[ManagedTile]:
        return list(self._tiles.values())
