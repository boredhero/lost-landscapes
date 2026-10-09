"""Explicit live provider smoke check; bounded requests, no bulk imagery download."""

import asyncio
import math
import time

from lost_landscapes.api.routes.context import fetch_image
from lost_landscapes.context_sources import request_for_tile, source_catalog


async def check(source):
    w, s, e, n = source.bounds
    lon, lat = (w + e) / 2, (s + n) / 2
    z = min(max(14, source.min_zoom), source.max_zoom)
    x = int((lon + 180) / 360 * 2**z)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2**z)
    started = time.monotonic()
    try:
        data = await fetch_image(*request_for_tile(source, z, x, y))
        print(f"{source.id}: OK {len(data)} bytes, {time.monotonic() - started:.2f}s")
        return True
    except Exception as exc:
        print(f"{source.id}: FAIL {type(exc).__name__}: {exc}")
        return False


async def main():
    results = await asyncio.gather(*(check(source) for source in source_catalog().values()))
    return all(results)


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(main()) else 1)
