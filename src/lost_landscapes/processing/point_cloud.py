"""Point cloud analysis — density anomalies and multi-return patterns.

These analyses operate on raw point cloud data (not DEM) and are critical
for detecting cave entrances where LiDAR pulses penetrate openings.

Requires PDAL for point cloud reading — runs on remote worker only.
For unit testing, synthetic point arrays are used directly.
"""

import time

import numpy as np
from numpy.typing import NDArray

from lost_landscapes.utils.log_manager import log


def compute_point_density(
    x: NDArray[np.float64],
    y: NDArray[np.float64],
    z: NDArray[np.float64],
    cell_size: float = 2.0,
    bounds: tuple[float, float, float, float] | None = None,
) -> tuple[NDArray[np.float32], NDArray[np.float32], tuple[float, float, float, float]]:
    """Compute point density grid from point cloud.

    Returns (density_grid, z_score_grid, bounds).
    Low z-scores indicate voids where LiDAR enters openings.
    """
    t0 = time.perf_counter()
    log.info("compute_point_density_start", point_count=len(x), cell_size=cell_size, bounds_provided=bounds is not None)
    if bounds is None:
        bounds = (x.min(), y.min(), x.max(), y.max())
    xmin, ymin, xmax, ymax = bounds
    ncols = max(1, int(np.ceil((xmax - xmin) / cell_size)))
    nrows = max(1, int(np.ceil((ymax - ymin) / cell_size)))
    log.debug("compute_point_density_grid", ncols=ncols, nrows=nrows, bounds=bounds, extent_x=round(xmax - xmin, 2), extent_y=round(ymax - ymin, 2))
    # Bin points into grid
    col_idx = np.clip(((x - xmin) / cell_size).astype(int), 0, ncols - 1)
    row_idx = np.clip(((ymax - y) / cell_size).astype(int), 0, nrows - 1)
    density = np.zeros((nrows, ncols), dtype=np.float32)
    np.add.at(density, (row_idx, col_idx), 1)
    # Z-score normalization
    mean_density = np.mean(density[density > 0]) if np.any(density > 0) else 1.0
    std_density = np.std(density[density > 0]) if np.any(density > 0) else 1.0
    if std_density < 1e-10:
        std_density = 1.0
    z_scores = (density - mean_density) / std_density
    elapsed = time.perf_counter() - t0
    occupied_cells = int(np.sum(density > 0))
    avg_density = float(round(mean_density, 2))
    log.info("compute_point_density_complete", elapsed_s=round(elapsed, 4), point_count=len(x), grid_shape=(nrows, ncols), occupied_cells=occupied_cells, mean_density=avg_density, std_density=round(float(std_density), 2), min_zscore=round(float(z_scores.min()), 2), max_zscore=round(float(z_scores.max()), 2))
    return density, z_scores, bounds


def compute_multi_return_ratio(
    x: NDArray[np.float64],
    y: NDArray[np.float64],
    return_number: NDArray[np.int32],
    number_of_returns: NDArray[np.int32],
    classification: NDArray[np.int32] | None = None,
    cell_size: float = 5.0,
    bounds: tuple[float, float, float, float] | None = None,
) -> tuple[NDArray[np.float32], tuple[float, float, float, float]]:
    """Compute multi-return ratio grid.

    High ratio of multi-return points in non-vegetated areas signals
    openings where LiDAR enters caves/mines.

    Args:
        return_number: return number for each point (1 = first)
        number_of_returns: total returns per pulse
        classification: point classification (3,4,5 = vegetation, excluded)
        cell_size: grid cell size in meters
    """
    t0 = time.perf_counter()
    total_points = len(x)
    log.info("compute_multi_return_ratio_start", point_count=total_points, cell_size=cell_size, has_classification=classification is not None, bounds_provided=bounds is not None)
    # Filter out vegetation if classification provided
    mask = np.ones(len(x), dtype=bool)
    if classification is not None:
        mask = ~np.isin(classification, [3, 4, 5])  # exclude veg classes
        veg_filtered = int(np.sum(~mask))
        log.debug("multi_return_veg_filter", total=total_points, filtered_out=veg_filtered, remaining=int(np.sum(mask)))
    x_filt = x[mask]
    y_filt = y[mask]
    nr_filt = number_of_returns[mask]
    if bounds is None:
        if len(x_filt) == 0:
            log.warning("compute_multi_return_ratio_empty", reason="no_points_after_filtering")
            return np.zeros((1, 1), dtype=np.float32), (0, 0, 1, 1)
        bounds = (x_filt.min(), y_filt.min(), x_filt.max(), y_filt.max())
    xmin, ymin, xmax, ymax = bounds
    ncols = max(1, int(np.ceil((xmax - xmin) / cell_size)))
    nrows = max(1, int(np.ceil((ymax - ymin) / cell_size)))
    log.debug("multi_return_grid", ncols=ncols, nrows=nrows, filtered_points=len(x_filt))
    col_idx = np.clip(((x_filt - xmin) / cell_size).astype(int), 0, ncols - 1)
    row_idx = np.clip(((ymax - y_filt) / cell_size).astype(int), 0, nrows - 1)
    # Count total points per cell
    total_count = np.zeros((nrows, ncols), dtype=np.float32)
    np.add.at(total_count, (row_idx, col_idx), 1)
    # Count multi-return points (return_number > 1 OR number_of_returns > 1)
    multi_mask = (nr_filt > 1)
    multi_count = np.zeros((nrows, ncols), dtype=np.float32)
    if np.any(multi_mask):
        np.add.at(multi_count, (row_idx[multi_mask], col_idx[multi_mask]), 1)
    # Ratio
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(total_count > 0, multi_count / total_count, 0)
    elapsed = time.perf_counter() - t0
    multi_return_pct = round(float(np.sum(multi_mask)) / len(nr_filt) * 100, 1) if len(nr_filt) > 0 else 0
    log.info("compute_multi_return_ratio_complete", elapsed_s=round(elapsed, 4), point_count=total_points, filtered_points=len(x_filt), multi_return_points=int(np.sum(multi_mask)), multi_return_pct=multi_return_pct, grid_shape=(nrows, ncols), mean_ratio=round(float(ratio.mean()), 4), max_ratio=round(float(ratio.max()), 4))
    return ratio.astype(np.float32), bounds
