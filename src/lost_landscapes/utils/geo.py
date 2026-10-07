"""Geographic utility functions."""

import numpy as np
from shapely.geometry import Polygon, box

from lost_landscapes.utils.log_manager import log


def bbox_to_polygon(west: float, south: float, east: float, north: float) -> Polygon:
    """Create a Shapely polygon from bounding box coordinates."""
    log.debug("bbox_to_polygon", west=west, south=south, east=east, north=north)
    return box(west, south, east, north)


def degrees_to_meters(lat: float, lon_delta: float, lat_delta: float) -> tuple[float, float]:
    """Approximate conversion of degree deltas to meters at a given latitude."""
    lat_m = lat_delta * 111_320.0
    lon_m = lon_delta * 111_320.0 * np.cos(np.radians(lat))
    log.debug("degrees_to_meters", lat=lat, lon_delta=lon_delta, lat_delta=lat_delta, lon_m=round(lon_m, 2), lat_m=round(lat_m, 2))
    return lon_m, lat_m


def meters_to_degrees(lat: float, x_m: float, y_m: float) -> tuple[float, float]:
    """Approximate conversion of meter deltas to degrees at a given latitude."""
    lat_deg = y_m / 111_320.0
    lon_deg = x_m / (111_320.0 * np.cos(np.radians(lat)))
    log.debug("meters_to_degrees", lat=lat, x_m=x_m, y_m=y_m, lon_deg=round(lon_deg, 6), lat_deg=round(lat_deg, 6))
    return lon_deg, lat_deg
