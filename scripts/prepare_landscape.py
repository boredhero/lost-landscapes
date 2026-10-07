#!/usr/bin/env python3
"""Bake a bounded study area's terrain and relief cache; report CPU timings."""

import argparse
import json
import math
import statistics
import time
from concurrent.futures import ThreadPoolExecutor

from lost_landscapes.api.routes.landscape import render_tile
from lost_landscapes.config import settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("area", help="Study-area ID in data/study-areas.json")
    parser.add_argument("--min-zoom", type=int, default=12)
    parser.add_argument("--max-zoom", type=int, default=16)
    parser.add_argument(
        "--max-tiles", type=int, default=1500, help="Refuse unexpectedly large bakes"
    )
    args = parser.parse_args()
    if not 0 <= args.min_zoom <= args.max_zoom <= 18:
        parser.error("Zoom range must be within 0–18")
    areas = json.loads((settings.data_dir / "study-areas.json").read_text())
    area = next((area for area in areas if area["id"] == args.area), None)
    if area is None:
        parser.error("Study area not found")
    west, south, east, north = area["bounds"]
    tiles = []
    for zoom in range(args.min_zoom, args.max_zoom + 1):
        count = 2**zoom

        def x(lon):
            return max(0, min(count - 1, int((lon + 180) / 360 * count)))

        def y(lat):
            return max(
                0,
                min(
                    count - 1,
                    int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * count),
                ),
            )

        for tx in range(x(west), x(east) + 1):
            for ty in range(y(north), y(south) + 1):
                for layer in ("terrain", "relief"):
                    tiles.append((layer, zoom, tx, ty))
    if len(tiles) > args.max_tiles:
        parser.error(f"Bake would create {len(tiles)} files; reduce the bounds or zoom range")

    def prepare(tile):
        start = time.perf_counter()
        data = render_tile(*tile)
        return (time.perf_counter() - start, len(data))

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=settings.terrain_workers) as pool:
        first = list(pool.map(prepare, tiles))
        elapsed = time.perf_counter() - start
        warm = list(pool.map(prepare, tiles))
    print(
        json.dumps(
            {
                "files": len(tiles),
                "elapsed_s": round(elapsed, 3),
                "workers": settings.terrain_workers,
                "median_first_ms": round(statistics.median(t[0] for t in first) * 1000, 2),
                "median_cached_ms": round(statistics.median(t[0] for t in warm) * 1000, 2),
                "total_mb": round(sum(t[1] for t in first) / 1e6, 2),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
