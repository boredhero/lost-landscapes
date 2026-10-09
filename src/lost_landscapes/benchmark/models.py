"""Strict benchmark contracts with explicit evidence and spatial split checks."""

import json
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError
from shapely.geometry import shape
from shapely.ops import transform, unary_union

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Coordinate = tuple[
    Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)],
    Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)],
]
Family = Literal["raised", "depression", "linear", "enclosure", "geological", "unclassified"]
Split = Literal["train", "validation", "test"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Point(Contract):
    type: Literal["Point"] = "Point"
    coordinates: Coordinate


class LineString(Contract):
    type: Literal["LineString"] = "LineString"
    coordinates: list[Coordinate] = Field(min_length=2)

    @model_validator(mode="after")
    def nonzero_line(self):
        if not shape(self.model_dump()).is_valid or len(set(self.coordinates)) < 2:
            raise ValueError("Line must contain distinct positions")
        return self


class Polygon(Contract):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[Coordinate]] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_polygon(self):
        if any(len(ring) < 4 or ring[0] != ring[-1] for ring in self.coordinates):
            raise ValueError("Polygon rings must be explicitly closed with at least four positions")
        geom = shape(self.model_dump())
        if geom.is_empty or not geom.is_valid or geom.area == 0:
            raise ValueError("Polygon must be valid and have positive area")
        return self


Geometry = Annotated[Point | LineString | Polygon, Field(discriminator="type")]


def project(geometry, transformer):
    return transform(transformer.transform, shape(geometry.model_dump()))


def unique(items, description):
    if len(items) != len(set(items)):
        raise ValueError(f"Duplicate {description}")


class Evidence(Contract):
    reference: Text
    description: Text


class Survey(Contract):
    id: Text
    title: Text
    source: Text
    content_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    license: Text
    acquired_on: date | None
    resolution_m: Positive
    vertical_datum: Text | None
    footprint: Polygon


class FamilyReview(Contract):
    family: Family
    completeness: Literal["exhaustive", "partial"]
    reviewer: Text
    reviewed_on: date
    evidence: list[Evidence] = Field(min_length=1)


class Region(Contract):
    id: Text
    independence_group: Text
    split: Split
    geometry: Polygon
    survey_ids: list[Text] = Field(min_length=1)
    reviews: list[FamilyReview] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_references(self):
        unique(self.survey_ids, "survey references")
        unique([review.family for review in self.reviews], "family reviews")
        return self


class LabelReview(Contract):
    revision: int = Field(ge=1)
    status: Literal["present", "absent", "uncertain"]
    reviewer: Text
    reviewed_on: date
    evidence: list[Evidence] = Field(min_length=1)
    observation: Text
    interpretation: Text | None
    visibility: Literal["low", "medium", "high", "unknown"]
    interpretation_confidence: Literal["low", "medium", "high", "unknown"]
    dating_evidence: Text | None


class Label(Contract):
    id: Text
    feature_id: Text
    region_id: Text
    family: Family
    geometry: Geometry
    reviews: list[LabelReview] = Field(min_length=1)

    @model_validator(mode="after")
    def ordered_history(self):
        if [r.revision for r in self.reviews] != list(range(1, len(self.reviews) + 1)):
            raise ValueError("Review revisions must be consecutive, starting at one")
        dates = [r.reviewed_on for r in self.reviews]
        if dates != sorted(dates):
            raise ValueError("Review history must be chronological")
        return self


class Protocol(Contract):
    id: Text
    evaluation_crs: Text
    split_buffer_m: Positive
    point_tolerance_m: Positive
    matching_rationale: Text
    split_locked_on: date
    split_locked_by: Text
    split_rationale: Text

    @model_validator(mode="after")
    def metric_crs(self):
        try:
            crs = CRS.from_user_input(self.evaluation_crs)
        except CRSError as exc:
            raise ValueError("Unrecognized evaluation CRS") from exc
        if (
            not crs.is_projected
            or crs.to_epsg() in (3857, 3395)
            or len(crs.axis_info) != 2
            or any(axis.unit_conversion_factor != 1 for axis in crs.axis_info)
            or crs.area_of_use is None
        ):
            raise ValueError(
                "Evaluation CRS must be a local projected metre CRS with known area of use"
            )
        if self.split_buffer_m < 2 * self.point_tolerance_m:
            raise ValueError("Split buffer must be at least twice the point matching tolerance")
        return self


class Manifest(Contract):
    schema_version: Literal[1]
    dataset_id: Text
    dataset_version: Text
    purpose: Literal["synthetic", "reviewed-data"]
    description: Text
    protocol: Protocol
    surveys: list[Survey] = Field(min_length=1)
    regions: list[Region] = Field(min_length=1)
    labels: list[Label]

    @model_validator(mode="after")
    def integrity(self):
        unique([s.id for s in self.surveys], "survey IDs")
        unique([r.id for r in self.regions], "region IDs")
        unique([label.id for label in self.labels], "label IDs")
        # Multiple observations of one object must be adjudicated into one label.
        unique([label.feature_id for label in self.labels], "physical feature IDs")
        crs = CRS.from_user_input(self.protocol.evaluation_crs)
        transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        surveys = {s.id: shape(s.footprint.model_dump()) for s in self.surveys}
        regions = {r.id: shape(r.geometry.model_dump()) for r in self.regions}
        projected = {}
        groups = {}
        area = crs.area_of_use
        for region in self.regions:
            if groups.setdefault(region.independence_group, region.split) != region.split:
                raise ValueError("An independence group cannot span splits")
            if any(s not in surveys for s in region.survey_ids):
                raise ValueError(f"Unknown survey reference in {region.id}")
            geom = regions[region.id]
            w, s, e, n = geom.bounds
            if not (area.west <= w <= e <= area.east and area.south <= s <= n <= area.north):
                raise ValueError(f"Region {region.id} lies outside the evaluation CRS area of use")
            if not unary_union([surveys[s] for s in region.survey_ids]).covers(geom):
                raise ValueError(f"Region {region.id} exceeds referenced survey footprints")
            projected[region.id] = project(region.geometry, transformer)
        for index, left in enumerate(self.regions):
            for right in self.regions[index + 1 :]:
                a, b = projected[left.id], projected[right.id]
                if a.intersects(b):
                    raise ValueError("Regions must not overlap or share boundaries")
                if left.split != right.split and a.distance(b) < self.protocol.split_buffer_m:
                    raise ValueError("Regions in different splits violate the spatial buffer")
        for label in self.labels:
            if label.region_id not in regions:
                raise ValueError(f"Unknown region for label {label.id}")
            if not regions[label.region_id].covers(shape(label.geometry.model_dump())):
                raise ValueError(f"Label {label.id} is outside its region")
        for index, left in enumerate(self.labels):
            for right in self.labels[index + 1 :]:
                if (
                    left.region_id == right.region_id
                    and left.family == right.family
                    and shape(left.geometry.model_dump()).equals(shape(right.geometry.model_dump()))
                ):
                    raise ValueError(
                        "Coincident same-family labels must be adjudicated into one feature"
                    )
        return self


class Prediction(Contract):
    id: Text
    family: Family
    geometry: Point
    score: Annotated[float, Field(ge=0, le=1)] | None


class PredictionSet(Contract):
    schema_version: Literal[1]
    dataset_id: Text
    dataset_version: Text
    manifest_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    split: Split
    families: list[Family] = Field(min_length=1)
    algorithm: Text
    algorithm_version: Text
    configuration: dict
    predictions: list[Prediction]

    @model_validator(mode="after")
    def declared_families(self):
        unique(self.families, "evaluated families")
        unique([p.id for p in self.predictions], "prediction IDs")
        if any(p.family not in self.families for p in self.predictions):
            raise ValueError("Every prediction family must be declared")
        json.dumps(self.configuration, allow_nan=False)
        return self
