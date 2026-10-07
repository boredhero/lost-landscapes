"""Pydantic request/response schemas for the API."""

from datetime import datetime

from pydantic import BaseModel

# --- Detection schemas ---

class DetectionProperties(BaseModel):
    feature_type: str | None = None
    confidence: float = 0.0
    depth_m: float | None = None
    area_m2: float | None = None
    circularity: float | None = None
    wall_slope_deg: float | None = None
    source_passes: dict | list | None = None
    morphometrics: dict | None = None
    validated: bool | None = None
    validation_notes: str | None = None


class DetectionFeature(BaseModel):
    type: str = "Feature"
    id: str
    geometry: dict
    properties: DetectionProperties


class DetectionCollection(BaseModel):
    type: str = "FeatureCollection"
    features: list[DetectionFeature]
    total_count: int = 0


class DetectionDetail(BaseModel):
    id: str
    feature_type: str | None
    confidence: float
    depth_m: float | None
    area_m2: float | None
    circularity: float | None
    morphometrics: dict | None
    source_passes: dict | list | None
    validated: bool | None
    validation_notes: str | None
    pass_results: list[dict] = []
    validation_events: list[dict] = []
    created_at: datetime | None = None


# --- Job schemas ---

class JobCreate(BaseModel):
    job_type: str = "full_pipeline"
    bbox: dict | None = None  # GeoJSON geometry
    pass_config: str = "sinkhole_survey"  # TOML config name


class JobStatus(BaseModel):
    id: str
    job_type: str
    status: str
    progress: float = 0.0
    result_summary: dict | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class JobList(BaseModel):
    jobs: list[JobStatus]


# --- Validation schemas ---

class ValidationRequest(BaseModel):
    verdict: str  # confirmed, rejected, uncertain
    notes: str | None = None


class ValidationResponse(BaseModel):
    status: str = "ok"
    verdict: str
    detection_id: str


# --- Ground Truth schemas ---

class GroundTruthCreate(BaseModel):
    name: str
    feature_type: str
    lat: float
    lon: float
    notes: str | None = None


class GroundTruthSiteOut(BaseModel):
    id: str
    name: str
    feature_type: str
    lat: float
    lon: float
    source: str
    metadata: dict | None = None


# --- Dataset schemas ---

class DatasetOut(BaseModel):
    id: str
    name: str
    source: str
    state: str | None
    tile_count: int
    status: str
    created_at: datetime | None


# --- Export schemas ---

class ExportRequest(BaseModel):
    format: str = "geojson"  # geojson, csv, kml
    bbox: dict | None = None
    feature_types: list[str] | None = None
    min_confidence: float = 0.0
