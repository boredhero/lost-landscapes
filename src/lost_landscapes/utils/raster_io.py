"""Rasterio read/write helpers."""

from pathlib import Path

import numpy as np
import rasterio
from numpy.typing import NDArray
from rasterio.transform import Affine

from lost_landscapes.utils.crs import resolve_epsg
from lost_landscapes.utils.log_manager import log


def read_dem(path: Path) -> tuple[NDArray[np.float32], Affine, int]:
    """Read a single-band DEM GeoTIFF.
    Returns (array, transform, epsg_code).
    """
    log.debug("read_dem_start", path=str(path))
    with rasterio.open(path) as src:
        dem = src.read(1).astype(np.float32)
        transform = src.transform
        nodata = src.nodata
        raw_crs = src.crs
        crs = resolve_epsg(raw_crs)
    nodata_count = int(np.isnan(dem).sum()) if nodata is None else int((dem == nodata).sum())
    log.info("read_dem_complete", path=str(path), height=dem.shape[0], width=dem.shape[1], epsg=crs, nodata_value=nodata, nodata_pixels=nodata_count, dtype=str(dem.dtype))
    return dem, transform, crs


def write_raster(
    path: Path,
    data: NDArray[np.float32],
    transform: Affine,
    crs: int,
    nodata: float | None = None,
) -> None:
    """Write a single-band float32 raster to GeoTIFF."""
    log.debug("write_raster_start", path=str(path), height=data.shape[0], width=data.shape[1], epsg=crs, nodata=nodata)
    profile = {
        "driver": "GTiff",
        "dtype": "float32",
        "width": data.shape[1],
        "height": data.shape[0],
        "count": 1,
        "crs": f"EPSG:{crs}",
        "transform": transform,
        "compress": "deflate",
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
    }
    if nodata is not None:
        profile["nodata"] = nodata
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)
    size_mb = round(path.stat().st_size / 1e6, 2) if path.exists() else 0
    log.info("write_raster_complete", path=str(path), height=data.shape[0], width=data.shape[1], epsg=crs, nodata=nodata, size_mb=size_mb)
