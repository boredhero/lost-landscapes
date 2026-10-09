"""Bounded WGS84 measurements and native DEM profiles; no display exaggeration."""

import math
from typing import Literal

import numpy as np
import rasterio
from pydantic import BaseModel, ConfigDict, model_validator
from pyproj import Geod, Transformer
from shapely.geometry import shape

from lost_landscapes.terrain_visualization import source_info

GEOD = Geod(ellps="WGS84")


class MeasurementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["Point", "LineString", "Polygon"]
    coordinates: list

    @model_validator(mode="after")
    def validate_geometry(self):
        try:
            points = [self.coordinates] if self.type == "Point" else (
                self.coordinates[0] if self.type == "Polygon" else self.coordinates
            )
            if self.type == "Polygon" and len(self.coordinates) != 1:
                raise ValueError("Use a single ring without holes")
            if not 1 <= len(points) <= 500:
                raise ValueError("Use at most 500 vertices")
            for point in points:
                if len(point) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in point):
                    raise ValueError("Finite longitude/latitude pairs required")
                if not (-180 <= point[0] <= 180 and -85 <= point[1] <= 85):
                    raise ValueError("Coordinates outside supported range")
            geometry = shape(self.model_dump())
            if geometry.is_empty or not geometry.is_valid:
                raise ValueError("Geometry must be valid and nonempty")
            if self.type == "Polygon" and points[0] != points[-1]:
                raise ValueError("Close the polygon ring")
            length = GEOD.geometry_length(geometry)
            if length > 10000 or (self.type != "Point" and length <= 0):
                raise ValueError("Use a nonzero line or perimeter no longer than 10 km")
        except (IndexError, TypeError, KeyError) as exc:
            raise ValueError("Invalid geometry") from exc
        return self


def measure(request, revision, records):
    geometry = shape(request.model_dump())
    result = {"method": "WGS84 ellipsoid; nearest native DEM cell", "revision": revision,
              "length_m": GEOD.geometry_length(geometry), "area_m2": None,
              "samples": [], "sources": []}
    if request.type == "Polygon":
        result["area_m2"] = abs(GEOD.geometry_area_perimeter(geometry)[0])
        return result
    points = request.coordinates if request.type == "LineString" else [request.coordinates]
    positions = []
    distances = []
    cumulative = 0.0
    # At most 201 samples over the full path, including both endpoints.
    segments = [GEOD.inv(*a, *b) for a, b in zip(points, points[1:])]
    targets = np.linspace(0, result["length_m"], 201) if segments else [0.0]
    segment = 0
    for target in targets:
        while segment < len(segments) - 1 and cumulative + segments[segment][2] < target:
            cumulative += segments[segment][2]
            segment += 1
        position = GEOD.fwd(*points[segment], segments[segment][0], target - cumulative)[:2] if segments else points[0]
        positions.append(position)
        distances.append(float(target))
    samples = [{"distance_m": d, "lon": p[0], "lat": p[1], "elevation_m": None, "source": None}
               for p, d in zip(positions, distances)]
    candidates = [r for r in sorted(records, key=lambda r: (r.resolution_m, str(r.path)))
                  if any(r.geographic_bounds[0] <= p[0] <= r.geographic_bounds[2]
                         and r.geographic_bounds[1] <= p[1] <= r.geographic_bounds[3] for p in positions)]
    if len(candidates) > 32:
        raise ValueError("Profile intersects more than 32 sources; draw a shorter line")
    for record in candidates:
        with rasterio.open(record.path) as src:
            info = source_info(src)
            if not info["eligible"]:
                continue
            transform = Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
            coords = [transform.transform(*p) for p in positions]
            source_id = str(record.path.parent.name + "/" + record.path.name)
            used = False
            for sample, value in zip(samples, src.sample(coords, indexes=1, masked=True)):
                if sample["elevation_m"] is not None or np.ma.is_masked(value[0]):
                    continue
                elevation = float(value[0]) * src.scales[0] + src.offsets[0]
                if math.isfinite(elevation):
                    sample.update(elevation_m=elevation, source=source_id)
                    used = True
            if used:
                result["sources"].append({"id": source_id, **info})
    result["samples"] = samples
    return result
