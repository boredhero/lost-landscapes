"""CPU-only, versioned terrain tiles for the landscape explorer.

Read only intersecting DEMs into a bounded Web Mercator window. Elevation and
shading share the same grid; source revisions invalidate both disk and browser
caches. Global terrain fills uncovered pixels instead of converting nodata to
sea level. This module does not require PostGIS or a worker to view terrain.
"""

import asyncio
import hashlib
import io
import json
import math
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx
import numpy as np
import rasterio
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from PIL import Image
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject, transform_bounds
from scipy.ndimage import distance_transform_edt
from starlette.concurrency import run_in_threadpool

from lost_landscapes.config import settings

router = APIRouter(prefix="/landscape", tags=["landscape"])
SIZE = 512
PAD = 8
WORLD = 20037508.342789244
RENDER_VERSION = "v2"
_pool = ThreadPoolExecutor(max_workers=settings.terrain_workers)
_background_pool = ThreadPoolExecutor(max_workers=6)
_http = httpx.Client(timeout=8, limits=httpx.Limits(max_connections=6, max_keepalive_connections=6))
_locks = [threading.Lock() for _ in range(64)]
_inventory_lock = threading.Lock()
_inventory_time = 0.0
_inventory: tuple[str, list] = ("empty", [])


@dataclass(frozen=True)
class Dem:
    path: Path
    bounds: tuple[float, float, float, float]  # EPSG:3857
    geographic_bounds: tuple[float, float, float, float]
    resolution_m: float


def inventory() -> tuple[str, list[Dem]]:
    global _inventory, _inventory_time
    with _inventory_lock:
        if time.monotonic() - _inventory_time < 15:
            return _inventory
        digest = hashlib.sha256(RENDER_VERSION.encode())
        records = []
        for path in sorted(settings.processed_dir.glob("*/*_dem.tif")):
            stat = path.stat()
            digest.update(f"{path.relative_to(settings.processed_dir)}:{stat.st_size}:{stat.st_mtime_ns}".encode())
            with rasterio.open(path) as src:
                if not src.crs:
                    continue
                bounds = transform_bounds(src.crs, "EPSG:3857", *src.bounds)
                geo = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
                # Estimate ground spacing from projected extent, including geographic inputs.
                latitude = (geo[1] + geo[3]) / 2
                resolution = (bounds[2] - bounds[0]) / src.width * math.cos(math.radians(latitude))
                records.append(Dem(path, bounds, geo, round(resolution, 2)))
        _inventory = (digest.hexdigest()[:16], records)
        _inventory_time = time.monotonic()
        return _inventory


def tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    width = 2 * WORLD / 2**z
    return (
        -WORLD + x * width,
        WORLD - (y + 1) * width,
        -WORLD + (x + 1) * width,
        WORLD - y * width,
    )


def read_elevation(z: int, x: int, y: int, records: list[Dem], pad: int = PAD) -> np.ndarray:
    west, south, east, north = tile_bounds(z, x, y)
    pixel = (east - west) / SIZE
    extent = (west - pixel * pad, south - pixel * pad, east + pixel * pad, north + pixel * pad)
    full = SIZE + 2 * pad
    target = from_bounds(*extent, full, full)
    result = np.full((full, full), np.nan, dtype=np.float32)
    # Prefer finer rasters in overlaps, consistently across adjacent tiles.
    for dem in sorted(records, key=lambda d: (d.resolution_m, str(d.path))):
        w, s, e, n = dem.bounds
        if e <= extent[0] or w >= extent[2] or n <= extent[1] or s >= extent[3]:
            continue
        patch = np.full_like(result, np.nan)
        with rasterio.open(dem.path) as src:
            reproject(
                rasterio.band(src, 1),
                patch,
                dst_transform=target,
                dst_crs="EPSG:3857",
                dst_nodata=np.nan,
                resampling=Resampling.bilinear,
                num_threads=1,
            )
        np.copyto(result, patch, where=np.isfinite(patch) & ~np.isfinite(result))
    return result


def decode_terrarium(data: bytes) -> np.ndarray:
    rgb = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"), dtype=np.float32)
    return rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768


def encode_terrarium(elevation: np.ndarray) -> bytes:
    if not np.isfinite(elevation).all():
        raise ValueError("Cannot encode missing elevations")
    values = np.clip(elevation + 32768, 0, 65535.996)
    rgb = np.stack(
        [np.floor(values / 256), np.floor(values % 256), np.floor(values * 256 % 256)], axis=-1
    ).astype(np.uint8)
    out = io.BytesIO()
    Image.fromarray(rgb).save(out, format="PNG")
    return out.getvalue()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@lru_cache(maxsize=32)
def background_parent(z: int, x: int, y: int) -> np.ndarray:
    path = settings.data_dir / "landscape-cache" / "background" / str(z) / str(x) / f"{y}.png"
    if path.exists():
        data = path.read_bytes()
    else:
        response = _http.get(
            f"https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png", timeout=8
        )
        response.raise_for_status()
        data = response.content
        decode_terrarium(data)  # Validate before persisting.
        atomic_write(path, data)
    return decode_terrarium(data)


def background(z: int, x: int, y: int) -> np.ndarray:
    # Parent cropping happens in floating-point elevations, never in encoded RGB.
    parent_z = min(z, 14)
    factor = 2 ** (z - parent_z)
    parent_x, parent_y = x // factor, y // factor
    array = background_parent(parent_z, parent_x, parent_y)
    output = np.empty((SIZE, SIZE), dtype=np.float32)
    reproject(
        array,
        output,
        src_transform=from_bounds(
            *tile_bounds(parent_z, parent_x, parent_y), array.shape[1], array.shape[0]
        ),
        src_crs="EPSG:3857",
        dst_transform=from_bounds(*tile_bounds(z, x, y), SIZE, SIZE),
        dst_crs="EPSG:3857",
        resampling=Resampling.bilinear,
        num_threads=1,
    )
    return output


def composite_elevation(local: np.ndarray, base: np.ndarray, padding: int = 0) -> np.ndarray:
    """Fill nodata and soften coverage edges without introducing sea-level walls."""
    valid = np.isfinite(local)
    weight = np.minimum(distance_transform_edt(valid) / PAD, 1.0)
    if padding:
        local = local[padding:-padding, padding:-padding]
        valid = valid[padding:-padding, padding:-padding]
        weight = weight[padding:-padding, padding:-padding]
    return np.where(valid, np.nan_to_num(local) * weight + base * (1 - weight), base)


def shaded_relief(elevation: np.ndarray, z: int, y: int) -> bytes:
    valid = np.isfinite(elevation)
    if not valid.any():
        rgba = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
    else:
        # Padding supplies neighboring samples; nearest fill is only used for lighting,
        # and never changes the visible coverage mask or the actual terrain heights.
        _, nearest = distance_transform_edt(~valid, return_indices=True)
        filled = np.where(valid, elevation, elevation[tuple(nearest)])
        latitude = math.atan(math.sinh(math.pi * (1 - 2 * (y + 0.5) / 2**z)))
        spacing = 2 * WORLD / 2**z / SIZE * math.cos(latitude)
        dy, dx = np.gradient(filled, spacing)
        normal_length = np.sqrt(dx * dx + dy * dy + 1)
        illumination = np.zeros_like(filled)
        for azimuth, weight in [(315, 0.50), (45, 0.20), (270, 0.20), (90, 0.10)]:
            az = math.radians(azimuth)
            altitude = math.radians(40)
            light = (
                -dx * math.sin(az) * math.cos(altitude)
                + dy * math.cos(az) * math.cos(altitude)
                + math.sin(altitude)
            ) / normal_length
            illumination += weight * np.clip(light, 0, 1)
        # Quiet limestone/olive tones emphasize landforms instead of elevation bands.
        intensity = np.clip(0.30 + 0.84 * illumination, 0, 1)
        color = np.array([228, 230, 211], dtype=np.float32)
        rgb = np.clip(intensity[..., None] * color, 0, 255).astype(np.uint8)
        rgba = np.dstack((rgb, valid.astype(np.uint8) * 255))[PAD:-PAD, PAD:-PAD]
    out = io.BytesIO()
    Image.fromarray(rgba).save(out, format="PNG")
    return out.getvalue()


def render_tile(layer: str, z: int, x: int, y: int) -> bytes:
    revision, records = inventory()
    path = settings.data_dir / "landscape-cache" / revision / layer / str(z) / str(x) / f"{y}.png"
    # Striped locks bound lock memory and collapse identical concurrent requests.
    with _locks[hash(str(path)) % len(_locks)]:
        if path.exists():
            return path.read_bytes()
        local = read_elevation(z, x, y, records)
        if layer == "relief":
            data = shaded_relief(local, z, y)
        else:
            center = local[PAD:-PAD, PAD:-PAD]
            if not np.isfinite(local).all():
                center = composite_elevation(local, background(z, x, y), PAD)
            data = encode_terrarium(center)
        atomic_write(path, data)
        return data


@router.get("/catalog")
def catalog():
    revision, records = inventory()
    manifest = settings.data_dir / "study-areas.json"
    areas = json.loads(manifest.read_text()) if manifest.exists() else []
    if not areas and records:
        first = records[0]
        areas = [
            {
                "id": "local",
                "name": "Local LiDAR study area",
                "bounds": first.geographic_bounds,
                "description": "Explore the available bare-earth elevation data.",
                "source": "Imported LiDAR DEM",
                "resolution_m": first.resolution_m,
            }
        ]
    return {
        "revision": revision,
        "areas": areas,
        "tile_count": len(records),
        "analysis_enabled": settings.enable_analysis,
        "coverage": [record.geographic_bounds for record in records],
    }


@router.get("/tiles/{layer}/{z}/{x}/{y}.png")
async def tile(layer: str, z: int, x: int, y: int, v: str = Query("")):
    if (
        layer not in ("terrain", "relief")
        or not (0 <= z <= 18)
        or not (0 <= x < 2**z and 0 <= y < 2**z)
    ):
        raise HTTPException(404, "Tile outside supported range")
    revision, records = await run_in_threadpool(inventory)
    path = settings.data_dir / "landscape-cache" / revision / layer / str(z) / str(x) / f"{y}.png"
    loop = asyncio.get_running_loop()
    try:
        if path.exists():
            data = await run_in_threadpool(path.read_bytes)
        else:
            local = await loop.run_in_executor(_pool, read_elevation, z, x, y, records)
            if layer == "relief":
                data = await loop.run_in_executor(_pool, shaded_relief, local, z, y)
            else:
                center = local[PAD:-PAD, PAD:-PAD]
                if not np.isfinite(local).all():
                    # Slow upstream I/O must not starve local relief or cached tiles.
                    base = await loop.run_in_executor(_background_pool, background, z, x, y)
                    center = await loop.run_in_executor(
                        _pool, composite_elevation, local, base, PAD
                    )
                data = await loop.run_in_executor(_pool, encode_terrarium, center)
            await run_in_threadpool(atomic_write, path, data)
    except (httpx.HTTPError, OSError, ValueError) as exc:
        raise HTTPException(503, "Terrain temporarily unavailable") from exc
    cache = "public, max-age=31536000, immutable" if v == revision else "public, max-age=15"
    return Response(data, media_type="image/png", headers={"Cache-Control": cache})
