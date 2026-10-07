"""Synthetic DEM generators — writes real GeoTIFF files for native pipeline testing.

Every test uses the same GDAL/WhiteboxTools pipeline as production.
No numpy-only fallbacks.
"""

from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds

from lost_landscapes.detection.base import PassInput


def write_geotiff(path: Path, dem: np.ndarray, resolution: float = 1.0) -> Path:
    """Write a numpy array as a GeoTIFF."""
    h, w = dem.shape
    transform = from_bounds(0, 0, w * resolution, h * resolution, w, h)
    with rasterio.open(
        path, "w", driver="GTiff", height=h, width=w,
        count=1, dtype="float32", crs="EPSG:32617", transform=transform,
        compress="deflate",
    ) as dst:
        dst.write(dem.astype(np.float32), 1)
    return path


def make_sinkhole_geotiff(tmpdir: Path, depth: float = 5.0, radius: float = 12.0, size: int = 200) -> Path:
    """Create a GeoTIFF with a conical pit on a slight slope.

    The slight slope (0.01m/pixel) ensures WBT fill_depressions can determine
    pour direction. Perfectly flat surroundings cause fill algorithms to fail.
    """
    y = np.arange(size, dtype=np.float32) * 0.01
    dem = np.tile(y[:, np.newaxis], (1, size)) + 500.0
    ym, xm = np.mgrid[0:size, 0:size].astype(np.float32)
    dist = np.sqrt((xm - size / 2) ** 2 + (ym - size / 2) ** 2)
    pit_mask = dist < radius
    dem[pit_mask] -= depth * (1 - dist[pit_mask] / radius)
    return write_geotiff(tmpdir / "sinkhole_dem.tif", dem)


def make_flat_geotiff(tmpdir: Path, size: int = 200) -> Path:
    """Create a nearly flat GeoTIFF with tiny gradient.

    Not perfectly flat — WBT FillDepressions hangs on perfectly flat surfaces.
    The 0.001m/pixel gradient is imperceptible but prevents the hang.
    """
    y = np.arange(size, dtype=np.float32) * 0.001
    dem = np.tile(y[:, np.newaxis], (1, size)) + 500.0
    return write_geotiff(tmpdir / "flat_dem.tif", dem)


def make_slope_geotiff(tmpdir: Path, slope_deg: float = 10.0, size: int = 200) -> Path:
    """Create a uniform slope GeoTIFF."""
    y = np.arange(size, dtype=np.float32)
    slope_rise = np.tan(np.radians(slope_deg)) * y
    dem = np.tile(slope_rise[:, np.newaxis], (1, size)) + 500.0
    return write_geotiff(tmpdir / "slope_dem.tif", dem)


def make_pass_input_from_geotiff(
    dem_path: Path,
    derivative_paths: dict[str, Path] | None = None,
) -> PassInput:
    """Load a GeoTIFF into a PassInput with derivatives loaded as arrays."""
    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype(np.float32)
        transform = src.transform
        from lost_landscapes.utils.crs import resolve_epsg
        crs = resolve_epsg(src.crs)

    derivatives = {}
    if derivative_paths:
        for name, path in derivative_paths.items():
            with rasterio.open(path) as src:
                derivatives[name] = src.read(1).astype(np.float32)

    return PassInput(dem=dem, transform=transform, crs=crs, derivatives=derivatives)
