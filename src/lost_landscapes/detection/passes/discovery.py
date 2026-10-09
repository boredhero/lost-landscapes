"""Experimental morphology, not archaeological/geological origin classification."""

import numpy as np
from rasterio.features import geometry_mask
from scipy import ndimage
from scipy.spatial import cKDTree
from shapely.geometry import MultiPoint, Polygon

from lost_landscapes.detection.base import DetectionPass, FeatureType
from lost_landscapes.detection.geometry_support import (
    VERSION,
    bounded_parameters,
    candidate,
    metrics,
    regions,
    supported_mask,
)
from lost_landscapes.detection.registry import register_pass


class GeometryPass(DetectionPass):
    version = VERSION
    required_derivatives = ["discovery_lrm_10", "discovery_lrm_25", "discovery_slope"]

    def inputs(self, data, defaults):
        params = bounded_parameters(data.config, defaults)
        for key in self.required_derivatives:
            if key not in data.derivatives or data.derivatives[key].shape != data.dem.shape:
                raise ValueError(f"Missing or misaligned derivative: {key}")
        return params, data.derivatives["discovery_lrm_10"], data.derivatives["discovery_slope"]


@register_pass
class RaisedFeaturesPass(GeometryPass):
    name = "raised_features"

    def run(self, data):
        p, relief, slope = self.inputs(data, {"threshold_m": 0.5, "min_area_m2": 20, "max_area_m2": 10000,
                                             "max_aspect_ratio": 3, "flat_slope_deg": 5})
        result = []
        for poly, window, mask in regions(supported_mask(relief, p["threshold_m"]), data.transform, p["min_area_m2"], p["max_area_m2"]):
            m = metrics(poly)
            if m["aspect_ratio"] > p["max_aspect_ratio"] or poly.interiors:
                continue
            values = relief[window][mask]
            core = ndimage.binary_erosion(mask, border_value=0)
            if not core.any():
                core = mask
            flat = float(np.mean(slope[window][core] <= p["flat_slope_deg"]))
            m.update(height_residual_m=float(values.max()), summit_flat_fraction=flat)
            kind = FeatureType.PLATFORM if flat >= 0.65 and m["rectangularity"] >= 0.65 else FeatureType.MOUND
            result.append(candidate(self.name, kind, poly, m, p, "Compact positive relief; summit flatness separates platform-like from mound-like shapes."))
        return result


@register_pass
class LinearFeaturesPass(GeometryPass):
    name = "linear_features"

    def run(self, data):
        p, relief, _ = self.inputs(data, {"threshold_m": 0.4, "min_area_m2": 20, "max_area_m2": 20000,
                                         "min_length_m": 20, "max_width_m": 15, "min_aspect_ratio": 4})
        result = []
        for sign, kind in ((1, FeatureType.LINEAR_BANK), (-1, FeatureType.LINEAR_DITCH)):
            for poly, window, mask in regions(supported_mask(relief, p["threshold_m"], sign), data.transform, p["min_area_m2"], p["max_area_m2"]):
                m = metrics(poly)
                if poly.interiors or m["length_m"] < p["min_length_m"] or m["width_m"] > p["max_width_m"] or m["aspect_ratio"] < p["min_aspect_ratio"]:
                    continue
                m.update(signed_relief_m=float(np.median(relief[window][mask])))
                result.append(candidate(self.name, kind, poly, m, p, "Elongated raised or lowered footprint. Banks, roads, ditches, drainage and modern earthworks can look alike."))
        return result


@register_pass
class EnclosuresPass(GeometryPass):
    name = "enclosures"

    def run(self, data):
        p, relief, _ = self.inputs(data, {"threshold_m": 0.4, "min_area_m2": 20, "max_area_m2": 20000, "min_interior_m2": 50})
        result = []
        for sign in (1, -1):
            for ring, _, _ in regions(supported_mask(relief, p["threshold_m"], sign), data.transform, p["min_area_m2"], p["max_area_m2"]):
                if not ring.interiors:
                    continue
                interior_area = sum(Polygon(hole).area for hole in ring.interiors)
                if interior_area < p["min_interior_m2"]:
                    continue
                # Only complete, finite interiors count: NoData holes are not enclosures.
                outer = Polygon(ring.exterior)
                inside = geometry_mask([outer], relief.shape, data.transform, invert=True)
                if not np.isfinite(relief[inside]).all():
                    continue
                m = metrics(outer)
                m.update(interior_area_m2=interior_area, boundary_area_m2=ring.area, polarity=sign)
                result.append(candidate(self.name, FeatureType.ENCLOSURE, outer, m, p,
                                        "Continuous thresholded bank or ditch surrounds a finite interior. This does not establish an archaeological enclosure."))
        return result


@register_pass
class RepeatedPatternsPass(GeometryPass):
    name = "repeated_patterns"

    def run(self, data):
        p, relief, _ = self.inputs(data, {"threshold_m": 0.5, "min_area_m2": 20, "max_area_m2": 2000,
                                         "max_spacing_m": 80, "min_members": 3, "max_spacing_cv": 0.25})
        objects = [(poly, metrics(poly)) for poly, _, _ in regions(supported_mask(relief, p["threshold_m"]), data.transform, p["min_area_m2"], p["max_area_m2"])
                   if not poly.interiors]
        objects = [(poly, m) for poly, m in objects if m["aspect_ratio"] <= 3]
        if len(objects) < p["min_members"]:
            return []
        centers = np.array([[poly.centroid.x, poly.centroid.y] for poly, _ in objects])
        tree = cKDTree(centers)
        neighbors = tree.query_ball_point(centers, p["max_spacing_m"])
        unseen = set(range(len(objects)))
        result = []
        while unseen:
            todo = [min(unseen)]
            members = set()
            while todo:
                i = todo.pop()
                if i in members:
                    continue
                members.add(i)
                todo.extend(j for j in neighbors[i] if j not in members)
            unseen -= members
            if len(members) < p["min_members"]:
                continue
            ids = sorted(members)
            distances = cKDTree(centers[ids]).query(centers[ids], k=2)[0][:, 1]
            cv = float(distances.std() / max(distances.mean(), 1e-9))
            areas = np.array([objects[i][1]["area_m2"] for i in ids])
            if cv > p["max_spacing_cv"] or areas.max() / areas.min() > 2:
                continue
            hull = MultiPoint(centers[ids]).convex_hull.buffer(float(np.sqrt(areas.mean()) / 2))
            m = metrics(hull)
            m.update(member_count=len(ids), mean_spacing_m=float(distances.mean()), spacing_cv=cv)
            c = candidate(self.name, FeatureType.REPEATED_PATTERN, hull, m, p,
                          "Similarly sized positive features with regular nearest-neighbor spacing. Orchards, spoil and natural patterns are alternatives.")
            c.metadata["member_centers_projected"] = centers[ids].tolist()
            result.append(c)
        return result


@register_pass
class GeologicalFormsPass(GeometryPass):
    name = "geological_forms"

    def run(self, data):
        p, _, slope = self.inputs(data, {"threshold_m": 1, "min_area_m2": 100, "max_area_m2": 50000, "min_scarp_slope_deg": 25})
        relief = data.derivatives["discovery_lrm_25"]
        result = []
        for sign, kind in ((1, FeatureType.RIDGE), (-1, FeatureType.HOLLOW)):
            for poly, window, mask in regions(supported_mask(relief, p["threshold_m"], sign), data.transform, p["min_area_m2"], p["max_area_m2"]):
                m = metrics(poly)
                if m["aspect_ratio"] < 3 or poly.interiors:
                    continue
                m["signed_relief_m"] = float(np.median(relief[window][mask]))
                result.append(candidate(self.name, kind, poly, m, p, "Broad elongated relief at a 25 m neighborhood scale; geological origin is unresolved."))
        valid = np.isfinite(relief) & np.isfinite(slope)
        steep = supported_mask(np.where(valid, slope, np.nan), p["min_scarp_slope_deg"])
        for poly, window, mask in regions(steep, data.transform, p["min_area_m2"], p["max_area_m2"]):
            m = metrics(poly)
            # A scarp may curve or turn corners; use band thickness rather than
            # forcing its overall bounding box to be a straight line.
            m["band_width_m"] = 2 * poly.area / max(poly.length, 1e-9)
            if poly.length / 2 < 20 or m["band_width_m"] > 15:
                continue
            m["mean_slope_deg"] = float(slope[window][mask].mean())
            result.append(candidate(self.name, FeatureType.SCARP, poly, m, p, "Elongated steep face. Landslide scarps, rock faces and road cuts require contextual review."))
        return result
