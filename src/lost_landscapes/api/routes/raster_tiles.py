"""Raster tile endpoints — serve hillshade, terrain-rgb, and composited terrain tiles.

Composited terrain tiles serve high-res LiDAR DEMs where available,
falling back to AWS Terrarium global tiles (~30m) elsewhere.
Relief tiles use USGS MDOW (multi-directional hillshade) with hypsometric
elevation coloring. All DEMs are mosaiced into a seamless GDAL VRT so there
are no gaps between adjacent COPC tiles.
Uses a lazy cache: first request computes + caches, subsequent requests are instant.
"""

import asyncio
import io
import math
import os
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np
from fastapi import APIRouter, Query
from fastapi.responses import Response
from scipy.ndimage import distance_transform_edt

from lost_landscapes.config import settings
from lost_landscapes.utils.log_manager import log

TILE_RENDER_SIZE = 256
_relief_pool = ThreadPoolExecutor(max_workers=8)

# Seamless DEM mosaic VRT — rebuilt every 2 minutes to pick up new tiles
_dem_vrt_path: str | None = None
_dem_vrt_time: float = 0.0


def _get_dem_vrts() -> list[str]:
    """Build per-CRS GDAL VRTs mosaicing all processed DEMs into seamless rasters.
    Groups DEMs by CRS (UTM zone), builds one VRT per group via gdalbuildvrt.
    VRTs are virtual XML files — zero data copying, GDAL reads source tiles on demand.
    Rebuilds every 2 minutes to pick up newly processed tiles."""
    global _dem_vrt_path, _dem_vrt_time
    import time as _time
    now = _time.time()
    if _dem_vrt_path and (now - _dem_vrt_time) < _DEM_CACHE_TTL:
        # Return cached list if all files still exist
        cached = _dem_vrt_path if isinstance(_dem_vrt_path, list) else [_dem_vrt_path]
        if all(Path(p).exists() for p in cached):
            log.debug("dem_vrt_cache_hit", vrt_count=len(cached), age_s=round(now - _dem_vrt_time, 1))
            return cached
    rebuild_start = _time.time()
    import rasterio
    dem_paths = sorted(settings.processed_dir.glob("*/*_dem.tif"))
    if not dem_paths:
        log.debug("dem_vrt_no_dems_found")
        return []
    # Group by CRS (usually 1-2 UTM zones per region)
    crs_groups: dict[str, list[str]] = {}
    for p in dem_paths:
        try:
            with rasterio.open(p) as src:
                epsg = src.crs.to_epsg() or "unknown"
            crs_groups.setdefault(str(epsg), []).append(str(p))
        except Exception as e:
            log.warning("dem_crs_read_failed", path=str(p), error=str(e))
    vrt_dir = settings.data_dir / "tile_cache"
    vrt_dir.mkdir(parents=True, exist_ok=True)
    vrts = []
    for crs_id, paths in crs_groups.items():
        vrt_path = str(vrt_dir / f"dems_{crs_id}.vrt")
        filelist = str(vrt_dir / f"dems_{crs_id}_list.txt")
        try:
            with open(filelist, "w") as f:
                f.write("\n".join(paths))
            subprocess.run(["gdalbuildvrt", "-input_file_list", filelist, vrt_path], check=True, capture_output=True, timeout=60)
            vrts.append(vrt_path)
        except Exception as e:
            log.warning("vrt_build_failed", crs=crs_id, count=len(paths), error=str(e))
    _dem_vrt_path = vrts
    _dem_vrt_time = now
    log.info("dem_vrts_rebuilt", groups=len(vrts), total_dems=len(dem_paths), elapsed_ms=round((_time.time() - rebuild_start) * 1000, 1))
    return vrts


router = APIRouter(tags=["raster_tiles"])

# In-memory cache of processed DEM bounds: {path: (west, south, east, north)}
_dem_bounds_cache: dict[str, tuple[float, float, float, float]] | None = None
_dem_bounds_cache_time: float = 0.0
_DEM_CACHE_TTL = 120.0  # rescan every 2 minutes so new tiles show up without restart
AWS_TERRAIN_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
# Shared httpx client — reuses TLS connections to AWS across all tile requests
_http_client: httpx.AsyncClient | None = None
# PNG minimum valid size (header + IHDR + IEND = ~67 bytes minimum)
_MIN_PNG_BYTES = 67

def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=15.0, limits=httpx.Limits(max_connections=20, max_keepalive_connections=10))
    return _http_client

def _atomic_write(path: Path, data: bytes) -> None:
    """Write bytes to path atomically via temp file + rename (prevents partial reads)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        os.write(fd, data)
        os.close(fd)
        os.rename(tmp, str(path))
    except Exception as e:
        log.error("atomic_write_failed", path=str(path), error=str(e), exception=True)
        os.close(fd) if not os.get_inheritable(fd) else None
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _tile_to_bbox(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Convert ZXY tile coords to WGS84 bounding box."""
    n = 2 ** z
    lon_min = x / n * 360 - 180
    lon_max = (x + 1) / n * 360 - 180
    lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return lon_min, lat_min, lon_max, lat_max


def _multidirectional_hillshade(dem: np.ndarray, cell_size_x: float, cell_size_y: float, altitude: float = 45.0) -> np.ndarray:
    """USGS multi-directional oblique-weighted (MDOW) hillshade — 6 azimuths.
    Produces much more even illumination than single-direction hillshade,
    eliminating the harsh shadow/bright bias of a single sun angle."""
    alt_rad = np.radians(altitude)
    dzdy, dzdx = np.gradient(dem, cell_size_y, cell_size_x)
    slope = np.sqrt(dzdx**2 + dzdy**2)
    aspect = np.arctan2(-dzdy, dzdx)
    azimuths = [225, 270, 315, 360, 45, 90]
    weights = [0.167, 0.278, 0.167, 0.111, 0.056, 0.222]
    result = np.zeros_like(dem, dtype=np.float64)
    for az, w in zip(azimuths, weights):
        az_rad = np.radians(az)
        hs = (np.cos(alt_rad) * slope * np.cos(az_rad - aspect) + np.sin(alt_rad)) / (1.0 + slope)
        result += w * np.clip(hs, 0, 1)
    return np.clip(result * 255, 0, 255).astype(np.uint8)


def _elevation_colormap(elevation: np.ndarray) -> np.ndarray:
    """Hypsometric color ramp — green valleys → tan hills → gray peaks.
    Returns (H, W, 3) uint8 array."""
    breaks = [0, 100, 200, 400, 700, 1200, 2000, 3500]
    colors = [
        (72, 133, 75), (106, 163, 88), (166, 194, 114), (209, 197, 140),
        (186, 163, 130), (170, 160, 150), (200, 200, 200), (245, 245, 245),
    ]
    rgb = np.zeros((*elevation.shape, 3), dtype=np.uint8)
    for ch in range(3):
        rgb[..., ch] = np.interp(elevation, breaks, [c[ch] for c in colors]).astype(np.uint8)
    return rgb


def _render_relief_tile(z: int, x: int, y: int) -> bytes | None:
    """Render a MDOW relief tile from seamless per-CRS VRT mosaics.
    Composites elevation from all VRTs (one per UTM zone), then GDAL
    handles stitching adjacent COPC tiles within each zone seamlessly.
    scipy gap-fills remaining tiny holes at DEM edges.
    Returns RGBA PNG with transparency outside LiDAR coverage."""
    t0 = time.perf_counter()
    import rasterio
    from PIL import Image
    from rasterio.transform import from_bounds
    from rasterio.warp import Resampling, reproject
    vrts = _get_dem_vrts()
    if not vrts:
        log.debug("relief_tile_no_vrts", z=z, x=x, y=y)
        return None
    bbox = _tile_to_bbox(z, x, y)
    west, south, east, north = bbox
    size = TILE_RENDER_SIZE
    pad = 3
    full = size + 2 * pad
    dx = (east - west) / size * pad
    dy = (north - south) / size * pad
    dst_transform = from_bounds(west - dx, south - dy, east + dx, north + dy, full, full)
    # Composite from all VRTs (usually 1, sometimes 2 for zone boundaries)
    elev = np.full((full, full), np.nan, dtype=np.float32)
    for vrt_path in vrts:
        try:
            buf = np.full((1, full, full), np.nan, dtype=np.float32)
            with rasterio.open(vrt_path) as src:
                reproject(source=rasterio.band(src, 1), destination=buf, dst_transform=dst_transform, dst_crs="EPSG:4326", dst_nodata=np.nan, resampling=Resampling.cubic)
            patch = buf[0]
            patch_valid = np.isfinite(patch)
            elev = np.where(patch_valid & ~np.isfinite(elev), patch, elev)
        except Exception as e:
            log.warning("relief_vrt_read_failed", vrt=vrt_path, z=z, x=x, y=y, error=str(e))
    valid = np.isfinite(elev)
    coverage_pct = round(float(np.count_nonzero(valid)) / valid.size * 100, 1)
    log.debug("relief_tile_composited", z=z, x=x, y=y, vrt_count=len(vrts), coverage_pct=coverage_pct)
    if not valid.any():
        log.debug("relief_tile_no_coverage", z=z, x=x, y=y)
        return None
    # Fill gaps at DEM edges with nearest-neighbor (up to 30px so gaps stay
    # closed even at high zoom where each pixel covers less ground)
    nan_mask = ~valid
    if nan_mask.any() and valid.any():
        dist, ind = distance_transform_edt(nan_mask, return_distances=True, return_indices=True)
        fill_mask = nan_mask & (dist <= 30)
        if fill_mask.any():
            filled_px = int(np.count_nonzero(fill_mask))
            elev[fill_mask] = elev[ind[0][fill_mask], ind[1][fill_mask]]
            valid = valid | fill_mask
            log.debug("relief_tile_gap_filled", z=z, x=x, y=y, filled_pixels=filled_px)
    # Fill remaining nodata with median (for gradient edge handling)
    fill_val = float(np.nanmedian(elev[valid])) if valid.any() else 0.0
    elev_clean = np.where(valid, elev, fill_val)
    # Cell size in meters at tile center latitude
    center_lat = (south + north) / 2
    m_per_deg_x = 111320 * math.cos(math.radians(center_lat))
    m_per_deg_y = 110540
    pixel_deg_x = (east - west + 2 * dx) / full
    pixel_deg_y = (north - south + 2 * dy) / full
    cell_x = pixel_deg_x * m_per_deg_x
    cell_y = pixel_deg_y * m_per_deg_y
    hs = _multidirectional_hillshade(elev_clean, cell_x, cell_y)
    color_rgb = _elevation_colormap(elev_clean)
    hs_f = hs.astype(np.float32) / 255.0
    composited = np.zeros((*elev.shape, 4), dtype=np.uint8)
    composited[..., 0] = np.clip(color_rgb[..., 0].astype(np.float32) * hs_f, 0, 255).astype(np.uint8)
    composited[..., 1] = np.clip(color_rgb[..., 1].astype(np.float32) * hs_f, 0, 255).astype(np.uint8)
    composited[..., 2] = np.clip(color_rgb[..., 2].astype(np.float32) * hs_f, 0, 255).astype(np.uint8)
    composited[..., 3] = np.where(valid, 255, 0).astype(np.uint8)
    tile = composited[pad:pad + size, pad:pad + size]
    img = Image.fromarray(tile, mode="RGBA")
    buf_io = io.BytesIO()
    img.save(buf_io, format="PNG", optimize=True)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    png_data = buf_io.getvalue()
    if elapsed_ms > 500:
        log.warning("relief_tile_slow_render", z=z, x=x, y=y, elapsed_ms=elapsed_ms, bytes=len(png_data))
    else:
        log.debug("relief_tile_complete", z=z, x=x, y=y, elapsed_ms=elapsed_ms, bytes=len(png_data))
    return png_data


TRANSPARENT_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@router.get("/raster/{layer}/{z}/{x}/{y}.png")
async def get_raster_tile(layer: str, z: int, x: int, y: int):
    """Serve a raster tile as PNG.
    Supported layers: hillshade (MDOW relief), slope, svf, lrm
    Terrain layer is handled by the composited terrain endpoint.
    """
    if layer == "terrain":
        return await get_composited_terrain_tile(z, x, y)
    # Check tile cache first
    cache_dir = settings.data_dir / "tile_cache" / layer / str(z) / str(x)
    tile_path = cache_dir / f"{y}.png"
    if tile_path.exists():
        data = tile_path.read_bytes()
        if len(data) >= _MIN_PNG_BYTES:
            log.debug("raster_tile_cache_hit", layer=layer, z=z, x=x, y=y, bytes=len(data))
            return Response(content=data, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
        log.warning("raster_tile_cache_corrupt", layer=layer, z=z, x=x, y=y, bytes=len(data))
        tile_path.unlink(missing_ok=True)
    # On-the-fly rendering for hillshade/relief layer from seamless VRT mosaic.
    # Runs entirely in thread pool so VRT build + rasterio never blocks the
    # async event loop (which would starve health checks → autoheal kills us).
    if layer == "hillshade":
        try:
            loop = asyncio.get_event_loop()
            png_bytes = await loop.run_in_executor(_relief_pool, _render_relief_tile, z, x, y)
            if png_bytes:
                await loop.run_in_executor(None, _atomic_write, tile_path, png_bytes)
                log.info("relief_tile_rendered", z=z, x=x, y=y, bytes=len(png_bytes))
                return Response(content=png_bytes, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
        except Exception as e:
            log.error("relief_render_failed", z=z, x=x, y=y, error=str(e), error_type=type(e).__name__, exception=True)
    log.debug("raster_tile_transparent_fallback", layer=layer, z=z, x=x, y=y)
    return Response(content=TRANSPARENT_PNG, media_type="image/png", headers={"Cache-Control": "public, max-age=60"})


def _scan_dem_bounds() -> dict[str, tuple[float, float, float, float]]:
    """Scan processed DEMs on disk and cache their WGS84 bounds.
    Cache expires every 2 minutes so newly processed tiles are found without restart.
    """
    global _dem_bounds_cache, _dem_bounds_cache_time
    import time as _time
    if _dem_bounds_cache is not None and (_time.time() - _dem_bounds_cache_time) < _DEM_CACHE_TTL:
        log.debug("dem_bounds_cache_hit", count=len(_dem_bounds_cache), age_s=round(_time.time() - _dem_bounds_cache_time, 1))
        return _dem_bounds_cache

    import rasterio
    from pyproj import Transformer

    from lost_landscapes.utils.crs import resolve_epsg

    bounds = {}
    processed_dir = settings.processed_dir
    if not processed_dir.exists():
        log.debug("dem_bounds_no_processed_dir", path=str(processed_dir))
        _dem_bounds_cache = bounds
        _dem_bounds_cache_time = _time.time()
        return bounds

    for dem_path in processed_dir.glob("*/*_dem.tif"):
        try:
            with rasterio.open(dem_path) as src:
                b = src.bounds
                crs = src.crs
                if not crs:
                    continue
                try:
                    epsg = resolve_epsg(crs)
                except ValueError:
                    log.warning("dem_bounds_crs_failed", path=str(dem_path), crs=str(crs)[:80])
                    continue
                if epsg == 4326:
                    west, south, east, north = b.left, b.bottom, b.right, b.top
                else:
                    transformer = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
                    west, south = transformer.transform(b.left, b.bottom)
                    east, north = transformer.transform(b.right, b.top)
                    if not all(math.isfinite(v) for v in (west, south, east, north)):
                        log.warning("dem_bounds_infinite", path=str(dem_path), epsg=epsg)
                        continue
                bounds[str(dem_path)] = (west, south, east, north)
        except Exception as e:
            log.warning("dem_scan_failed", path=str(dem_path), error=str(e))

    log.info("dem_bounds_scanned", count=len(bounds))
    _dem_bounds_cache = bounds
    _dem_bounds_cache_time = _time.time()
    return bounds


def _find_dem_for_tile(west: float, south: float, east: float, north: float) -> str | None:
    """Find a processed DEM that overlaps the given WGS84 bbox.
    Returns the DEM with the most overlap (best coverage for this tile)."""
    bounds = _scan_dem_bounds()
    best_path = None
    best_overlap = 0.0
    for path, (dw, ds, de, dn) in bounds.items():
        ow = max(dw, west)
        os_ = max(ds, south)
        oe = min(de, east)
        on = min(dn, north)
        if ow < oe and os_ < on:
            overlap = (oe - ow) * (on - os_)
            if overlap > best_overlap:
                best_overlap = overlap
                best_path = path
    if best_path:
        log.debug("dem_for_tile_found", dem=Path(best_path).name, overlap=round(best_overlap, 8))
    return best_path


def _find_all_dems_for_tile(west: float, south: float, east: float, north: float) -> list[str]:
    """Find ALL processed DEMs that overlap the given WGS84 bbox, sorted by overlap area."""
    bounds = _scan_dem_bounds()
    results = []
    for path, (dw, ds, de, dn) in bounds.items():
        ow = max(dw, west)
        os_ = max(ds, south)
        oe = min(de, east)
        on = min(dn, north)
        if ow < oe and os_ < on:
            overlap = (oe - ow) * (on - os_)
            results.append((path, overlap))
    results.sort(key=lambda x: x[1], reverse=True)
    dem_list = [r[0] for r in results]
    log.debug("all_dems_for_tile_found", count=len(dem_list), bbox=f"{west:.4f},{south:.4f},{east:.4f},{north:.4f}")
    return dem_list


def _render_terrain_tile_from_vrt(z: int, x: int, y: int) -> bytes | None:
    """Render a 256x256 Terrarium-encoded PNG from the seamless VRT mosaic.
    Uses the same VRT as relief tiles so 3D mesh and hillshade have
    identical coverage — eliminating seam mismatch between them."""
    t0 = time.perf_counter()
    import rasterio
    from PIL import Image
    from rasterio.transform import from_bounds
    from rasterio.warp import Resampling, reproject
    vrts = _get_dem_vrts()
    if not vrts:
        log.debug("terrain_vrt_tile_no_vrts", z=z, x=x, y=y)
        return None
    bbox = _tile_to_bbox(z, x, y)
    west, south, east, north = bbox
    dst_transform = from_bounds(west, south, east, north, 256, 256)
    elev = np.full((256, 256), np.nan, dtype=np.float32)
    for vrt_path in vrts:
        try:
            buf = np.full((1, 256, 256), np.nan, dtype=np.float32)
            with rasterio.open(vrt_path) as src:
                reproject(source=rasterio.band(src, 1), destination=buf, dst_transform=dst_transform, dst_crs="EPSG:4326", dst_nodata=np.nan, resampling=Resampling.cubic)
            patch = buf[0]
            patch_valid = np.isfinite(patch)
            elev = np.where(patch_valid & ~np.isfinite(elev), patch, elev)
        except Exception as e:
            log.warning("terrain_vrt_read_failed", vrt=vrt_path, z=z, x=x, y=y, error=str(e))
    if not np.isfinite(elev).any():
        log.debug("terrain_vrt_tile_no_coverage", z=z, x=x, y=y)
        return None
    elevation = np.nan_to_num(elev, nan=0.0)
    encoded = elevation + 32768.0
    r = np.floor(encoded / 256).astype(np.uint8)
    g = np.floor(encoded % 256).astype(np.uint8)
    b = np.floor((encoded * 256) % 256).astype(np.uint8)
    img = Image.fromarray(np.stack([r, g, b], axis=-1), mode="RGB")
    out = io.BytesIO()
    img.save(out, format="PNG")
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    png_data = out.getvalue()
    if elapsed_ms > 500:
        log.warning("terrain_vrt_tile_slow_render", z=z, x=x, y=y, elapsed_ms=elapsed_ms, bytes=len(png_data))
    else:
        log.debug("terrain_vrt_tile_complete", z=z, x=x, y=y, elapsed_ms=elapsed_ms, bytes=len(png_data))
    return png_data


@router.get("/raster/terrain/{z}/{x}/{y}.png")
async def get_composited_terrain_tile(z: int, x: int, y: int):
    """Serve composited terrain tiles — LiDAR where available, AWS Terrarium elsewhere.

    Uses Terrarium encoding: elevation = (R * 256 + G + B / 256) - 32768
    Lazy cache: first request computes + saves to disk, subsequent requests serve cached.
    Atomic writes prevent MapLibre from reading partially-written PNGs (→ DOMException).
    """
    tile_path = settings.data_dir / "tile_cache" / "terrain" / str(z) / str(x) / f"{y}.png"
    # 1. Serve from cache — validate size to reject corrupt/partial files
    if tile_path.exists():
        data = tile_path.read_bytes()
        if len(data) >= _MIN_PNG_BYTES:
            log.debug("terrain_tile_cache_hit", z=z, x=x, y=y, bytes=len(data))
            return Response(content=data, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
        log.warning("terrain_tile_cache_corrupt", z=z, x=x, y=y, bytes=len(data))
        tile_path.unlink(missing_ok=True)
    # 2. Try seamless VRT mosaic (same source as relief tiles — ensures 3D mesh
    #    and hillshade overlay have identical coverage, preventing MapLibre seam artifacts)
    try:
        loop = asyncio.get_event_loop()
        png_bytes = await loop.run_in_executor(_relief_pool, _render_terrain_tile_from_vrt, z, x, y)
        if png_bytes:
            _atomic_write(tile_path, png_bytes)
            log.info("terrain_tile_rendered_from_vrt", z=z, x=x, y=y, bytes=len(png_bytes))
            return Response(content=png_bytes, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
        log.debug("terrain_tile_no_vrt_coverage", z=z, x=x, y=y)
    except Exception as e:
        log.error("terrain_vrt_render_failed", z=z, x=x, y=y, error=str(e), exception=True)
    # 3. Proxy from AWS — don't cache to disk (LiDAR DEM may become available after next scan)
    try:
        resp = await _get_http_client().get(AWS_TERRAIN_URL.format(z=z, x=x, y=y))
        if resp.status_code == 200 and len(resp.content) >= _MIN_PNG_BYTES:
            log.debug("terrain_tile_aws_proxy", z=z, x=x, y=y, bytes=len(resp.content))
            return Response(content=resp.content, media_type="image/png", headers={"Cache-Control": "no-store"})
        log.warning("terrain_tile_aws_bad_response", z=z, x=x, y=y, status=resp.status_code, bytes=len(resp.content))
    except Exception as e:
        log.warning("aws_terrain_proxy_failed", z=z, x=x, y=y, error=str(e))
    # 4. Flat fallback — always valid, MapLibre can always decode this
    log.warning("terrain_tile_flat_fallback", z=z, x=x, y=y)
    return Response(content=_make_flat_terrarium_png_256(), media_type="image/png", headers={"Cache-Control": "public, max-age=60"})


@router.post("/raster/terrain/warm")
async def warm_terrain_cache(
    west: float = Query(..., description="West longitude"),
    south: float = Query(..., description="South latitude"),
    east: float = Query(..., description="East longitude"),
    north: float = Query(..., description="North latitude"),
    min_zoom: int = Query(12, ge=0, le=20),
    max_zoom: int = Query(15, ge=0, le=20),
):
    """Pre-render and cache all terrain tiles for a bbox across zoom levels.

    Uses shared httpx client, atomic writes, and batched concurrent fetches
    (10 at a time) to avoid saturating the event loop or AWS connections.
    """
    log.info("terrain_cache_warm_start", west=west, south=south, east=east, north=north, min_zoom=min_zoom, max_zoom=max_zoom)
    cached = 0
    rendered = 0
    proxied = 0
    client = _get_http_client()
    sem = asyncio.Semaphore(5)
    async def _warm_one(z: int, x: int, y: int) -> str:
        tile_path = settings.data_dir / "tile_cache" / "terrain" / str(z) / str(x) / f"{y}.png"
        if tile_path.exists() and tile_path.stat().st_size >= _MIN_PNG_BYTES:
            return "cached"
        try:
            png_bytes = _render_terrain_tile_from_vrt(z, x, y)
            if png_bytes:
                _atomic_write(tile_path, png_bytes)
                return "rendered"
        except Exception as e:
            log.warning("warm_render_failed", z=z, x=x, y=y, error=str(e))
        async with sem:
            try:
                resp = await client.get(AWS_TERRAIN_URL.format(z=z, x=x, y=y))
                if resp.status_code == 200 and len(resp.content) >= _MIN_PNG_BYTES:
                    _atomic_write(tile_path, resp.content)
                    return "proxied"
            except Exception as e:
                log.warning("warm_aws_proxy_failed", z=z, x=x, y=y, error=str(e))
                pass
        return "failed"
    tasks = []
    for z in range(min_zoom, max_zoom + 1):
        n = 2 ** z
        x_min = int((west + 180) / 360 * n)
        x_max = int((east + 180) / 360 * n)
        y_min = int((1 - math.log(math.tan(math.radians(north)) + 1 / math.cos(math.radians(north))) / math.pi) / 2 * n)
        y_max = int((1 - math.log(math.tan(math.radians(south)) + 1 / math.cos(math.radians(south))) / math.pi) / 2 * n)
        for x in range(x_min, x_max + 1):
            for y in range(y_min, y_max + 1):
                tasks.append(_warm_one(z, x, y))
    results = await asyncio.gather(*tasks)
    cached = results.count("cached")
    rendered = results.count("rendered")
    proxied = results.count("proxied")
    log.info("terrain_cache_warmed", cached=cached, rendered=rendered, proxied=proxied, total=len(results))
    return {"cached": cached, "rendered": rendered, "proxied": proxied}


_flat_terrain_cache: bytes | None = None


def _make_flat_terrarium_png_256() -> bytes:
    """Create a 256x256 Terrarium PNG encoding elevation = 0m.

    MapLibre's raster-dem decoder requires 256x256 tiles.
    Terrarium: 0m = (128 * 256 + 0 + 0/256) - 32768 = 0. So R=128, G=0, B=0.
    """
    global _flat_terrain_cache
    if _flat_terrain_cache is not None:
        return _flat_terrain_cache
    log.debug("flat_terrarium_png_generating")
    from PIL import Image
    img = Image.new("RGB", (256, 256), (128, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    _flat_terrain_cache = buf.getvalue()
    return _flat_terrain_cache


@router.get("/raster/terrain/coverage")
async def get_terrain_coverage(
    west: float = Query(..., description="West longitude"),
    south: float = Query(..., description="South latitude"),
    east: float = Query(..., description="East longitude"),
    north: float = Query(..., description="North latitude"),
    z: int = Query(..., ge=0, le=20, description="Zoom level for tile grid"),
):
    """Return GeoJSON tile grid for the viewport with source metadata per tile.

    Each feature is a tile boundary polygon with a `source` property:
    - "lidar": tile is rendered from a custom LiDAR DEM
    - "aws": tile would be proxied from AWS Terrarium
    """
    n = 2 ** z
    x_min = max(0, int((west + 180) / 360 * n))
    x_max = min(n - 1, int((east + 180) / 360 * n))
    y_min_f = (1 - math.log(math.tan(math.radians(min(north, 85.05))) + 1 / math.cos(math.radians(min(north, 85.05)))) / math.pi) / 2 * n
    y_max_f = (1 - math.log(math.tan(math.radians(max(south, -85.05))) + 1 / math.cos(math.radians(max(south, -85.05)))) / math.pi) / 2 * n
    y_min = max(0, int(y_min_f))
    y_max = min(n - 1, int(y_max_f))
    # Cap at 200 tiles to avoid blowing up the response at low zoom
    tile_count = (x_max - x_min + 1) * (y_max - y_min + 1)
    if tile_count > 200:
        log.debug("terrain_coverage_capped", z=z, tile_count=tile_count)
        return {"type": "FeatureCollection", "features": []}
    features = []
    for tx in range(x_min, x_max + 1):
        for ty in range(y_min, y_max + 1):
            bbox = _tile_to_bbox(z, tx, ty)
            dem_path = _find_dem_for_tile(*bbox)
            source = "lidar" if dem_path else "aws"
            features.append({
                "type": "Feature",
                "properties": {"z": z, "x": tx, "y": ty, "source": source},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [bbox[0], bbox[1]], [bbox[2], bbox[1]],
                        [bbox[2], bbox[3]], [bbox[0], bbox[3]],
                        [bbox[0], bbox[1]],
                    ]],
                },
            })
    lidar_count = sum(1 for f in features if f["properties"]["source"] == "lidar")
    log.debug("terrain_coverage_served", z=z, total_tiles=len(features), lidar_tiles=lidar_count)
    return {"type": "FeatureCollection", "features": features}


@router.get("/raster/terrain-rgb/{z}/{x}/{y}.png")
async def get_terrain_rgb_tile(
    z: int,
    x: int,
    y: int,
):
    """Serve terrain-RGB tiles for MapLibre 3D terrain.

    Terrain-RGB encodes elevation as: elevation = -10000 + ((R * 256 * 256 + G * 256 + B) * 0.1)
    """
    cache_dir = settings.processed_dir / "tile_cache" / "terrain-rgb" / str(z) / str(x)
    tile_path = cache_dir / f"{y}.png"

    if tile_path.exists():
        data = tile_path.read_bytes()
        log.debug("terrain_rgb_cache_hit", z=z, x=x, y=y, bytes=len(data))
        return Response(
            content=data,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )
    # Not cached — return sea level terrain-rgb (elevation = 0)
    log.debug("terrain_rgb_cache_miss_flat_fallback", z=z, x=x, y=y)
    # RGB for 0m: R=1, G=134, B=160 (since 0 = -10000 + (1*65536 + 134*256 + 160) * 0.1)
    FLAT_PNG = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05"
        b"\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return Response(
        content=FLAT_PNG,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=60"},
    )
