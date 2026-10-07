"""SQLAlchemy + GeoAlchemy2 ORM models."""

import enum
import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# --- Enums ---


class DataSourceEnum(enum.StrEnum):
    USGS_3DEP = "usgs_3dep"
    PASDA = "pasda"
    WV = "wv"
    NY = "ny"
    OH = "oh"
    NC = "nc"
    MD = "md"


class TileStatus(enum.StrEnum):
    DISCOVERED = "discovered"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"


class FeatureType(enum.StrEnum):
    SINKHOLE = "sinkhole"
    CAVE_ENTRANCE = "cave_entrance"
    MINE_PORTAL = "mine_portal"
    DEPRESSION = "depression"
    COLLAPSE_PIT = "collapse_pit"
    SPRING = "spring"
    LAVA_TUBE = "lava_tube"
    SALT_DOME_COLLAPSE = "salt_dome_collapse"
    UNKNOWN = "unknown"


class JobType(enum.StrEnum):
    INGEST = "ingest"
    PROCESS = "process"
    DETECT = "detect"
    FULL_PIPELINE = "full_pipeline"


class JobStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GroundTruthSource(enum.StrEnum):
    MANUAL = "manual"
    PASDA_KARST = "pasda_karst"
    PA_AML = "pa_aml"
    USGS_NY = "usgs_ny"
    USGS_NATIONAL = "usgs_national"
    OHIO_EPA = "ohio_epa"
    NC_CAVE_SURVEY = "nc_cave_survey"
    MD_KARST_SURVEY = "md_karst_survey"
    MA_USGS_MINES = "ma_usgs_mines"
    LA_SUBSIDENCE = "la_subsidence"
    CA_BLM_AML = "ca_blm_aml"


class ValidationVerdict(enum.StrEnum):
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    UNCERTAIN = "uncertain"


# --- Models ---


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255))
    source: Mapped[DataSourceEnum] = mapped_column(Enum(DataSourceEnum))
    state: Mapped[str | None] = mapped_column(String(2))
    acquisition_year: Mapped[int | None] = mapped_column(Integer)
    resolution_m: Mapped[float | None] = mapped_column(Float)
    crs: Mapped[int | None] = mapped_column(Integer)
    bbox = mapped_column(Geometry("POLYGON", srid=4326), nullable=True)
    tile_count: Mapped[int] = mapped_column(Integer, default=0)
    total_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[TileStatus] = mapped_column(
        Enum(TileStatus), default=TileStatus.DISCOVERED
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tiles: Mapped[list["Tile"]] = relationship(back_populates="dataset")


class Tile(Base):
    __tablename__ = "tiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id")
    )
    filename: Mapped[str] = mapped_column(String(512))
    file_path: Mapped[str] = mapped_column(String(1024))
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    point_count: Mapped[int | None] = mapped_column(Integer)
    bbox = mapped_column(Geometry("POLYGON", srid=4326), nullable=True)
    crs: Mapped[int | None] = mapped_column(Integer)
    has_dem: Mapped[bool] = mapped_column(Boolean, default=False)
    dem_path: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[TileStatus] = mapped_column(
        Enum(TileStatus), default=TileStatus.DISCOVERED
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    dataset: Mapped["Dataset"] = relationship(back_populates="tiles")
    detections: Mapped[list["Detection"]] = relationship(back_populates="tile")


class Detection(Base):
    __tablename__ = "detections"
    __table_args__ = (
        Index("ix_detections_geometry", "geometry", postgresql_using="gist"),
        Index("ix_detections_type_confidence", "feature_type", "confidence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tiles.id"), nullable=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id")
    )
    feature_type: Mapped[FeatureType] = mapped_column(
        Enum(FeatureType), default=FeatureType.UNKNOWN
    )
    geometry = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    outline = mapped_column(Geometry("POLYGON", srid=4326), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    depth_m: Mapped[float | None] = mapped_column(Float)
    area_m2: Mapped[float | None] = mapped_column(Float)
    circularity: Mapped[float | None] = mapped_column(Float)
    depth_area_ratio: Mapped[float | None] = mapped_column(Float)
    wall_slope_deg: Mapped[float | None] = mapped_column(Float)
    source_passes: Mapped[dict | None] = mapped_column(JSONB)
    morphometrics: Mapped[dict | None] = mapped_column(JSONB)
    validated: Mapped[bool | None] = mapped_column(Boolean)
    validation_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    tile: Mapped["Tile"] = relationship(back_populates="detections")
    job: Mapped["Job | None"] = relationship(back_populates="detections")
    pass_results: Mapped[list["PassResult"]] = relationship(back_populates="detection")
    validation_events: Mapped[list["ValidationEvent"]] = relationship(
        back_populates="detection"
    )


class GroundTruthSite(Base):
    __tablename__ = "ground_truth_sites"
    __table_args__ = (
        Index("ix_ground_truth_geometry", "geometry", postgresql_using="gist"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255))
    feature_type: Mapped[FeatureType] = mapped_column(Enum(FeatureType))
    geometry = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    source: Mapped[GroundTruthSource] = mapped_column(Enum(GroundTruthSource))
    source_id: Mapped[str | None] = mapped_column(String(255))
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_type: Mapped[JobType] = mapped_column(Enum(JobType))
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), default=JobStatus.PENDING
    )
    region = mapped_column(Geometry("POLYGON", srid=4326), nullable=True)
    config: Mapped[dict | None] = mapped_column(JSONB)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    result_summary: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    celery_task_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    detections: Mapped[list["Detection"]] = relationship(back_populates="job")


class PassResult(Base):
    __tablename__ = "pass_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    detection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("detections.id", ondelete="CASCADE")
    )
    pass_name: Mapped[str] = mapped_column(String(100))
    raw_score: Mapped[float] = mapped_column(Float)
    parameters: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    detection: Mapped["Detection"] = relationship(back_populates="pass_results")


class ValidationEvent(Base):
    __tablename__ = "validation_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    detection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("detections.id", ondelete="CASCADE")
    )
    verdict: Mapped[ValidationVerdict] = mapped_column(Enum(ValidationVerdict))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    detection: Mapped["Detection"] = relationship(back_populates="validation_events")


class Comment(Base):
    """User comments on detections — visible to everyone on the map."""

    __tablename__ = "comments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    detection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("detections.id", ondelete="CASCADE")
    )
    text: Mapped[str] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    detection: Mapped["Detection"] = relationship()


class SavedDetection(Base):
    """User-saved/highlighted detections."""

    __tablename__ = "saved_detections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    detection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("detections.id", ondelete="CASCADE")
    )
    label: Mapped[str | None] = mapped_column(String(255))
    color: Mapped[str | None] = mapped_column(String(7))  # hex color
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    detection: Mapped["Detection"] = relationship()
