"""Detection CRUD and spatial query endpoints."""

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2.shape import to_shape
from shapely.geometry import mapping
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from lost_landscapes.api.deps import get_db
from lost_landscapes.api.schemas import (
    DetectionCollection,
    DetectionDetail,
    DetectionFeature,
    DetectionProperties,
)
from lost_landscapes.db.models import Detection, FeatureType, PassResult, ValidationEvent
from lost_landscapes.utils.log_manager import log

router = APIRouter(tags=["detections"])


def _detection_to_feature(d: Detection) -> DetectionFeature:
    """Convert a Detection ORM object to a GeoJSON Feature."""
    try:
        point = to_shape(d.geometry)
        geom = {"type": "Point", "coordinates": [point.x, point.y]}
    except Exception as e:
        log.warning("detection_geom_conversion_failed", detection_id=str(d.id), error=str(e))
        geom = {"type": "Point", "coordinates": [0, 0]}

    return DetectionFeature(
        id=str(d.id),
        geometry=geom,
        properties=DetectionProperties(
            outline=mapping(to_shape(d.outline)) if d.outline is not None else None,
            feature_type=d.feature_type.value if d.feature_type else None,
            confidence=d.confidence or 0.0,
            depth_m=d.depth_m,
            area_m2=d.area_m2,
            circularity=d.circularity,
            wall_slope_deg=d.wall_slope_deg,
            source_passes=d.source_passes,
            morphometrics=d.morphometrics,
            validated=d.validated,
            validation_notes=d.validation_notes,
        ),
    )


@router.get("/detections", response_model=DetectionCollection)
async def list_detections(
    west: float = Query(..., description="Bounding box west longitude"),
    south: float = Query(..., description="Bounding box south latitude"),
    east: float = Query(..., description="Bounding box east longitude"),
    north: float = Query(..., description="Bounding box north latitude"),
    feature_type: list[str] | None = Query(None, description="Filter by feature type"),
    source_pass: str | None = Query(None, description="Filter by source detection pass name"),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    validated: bool | None = Query(None, description="Filter by validation status"),
    limit: int = Query(10000, le=50000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Query detections within a bounding box, returned as GeoJSON FeatureCollection."""
    from geoalchemy2.functions import ST_MakeEnvelope
    log.info("list_detections_requested", bbox=[west, south, east, north], feature_type=feature_type, source_pass=source_pass, min_confidence=min_confidence, validated=validated, limit=limit, offset=offset)
    t0 = time.perf_counter()
    envelope = ST_MakeEnvelope(west, south, east, north, 4326)
    stmt = (
        select(Detection)
        .where(Detection.geometry.ST_Within(envelope))
        .where(Detection.confidence >= min_confidence)
    )
    if feature_type:
        ft_enums = [FeatureType(ft) for ft in feature_type if ft in {kind.value for kind in FeatureType}]
        if ft_enums:
            stmt = stmt.where(Detection.feature_type.in_(ft_enums))
            log.debug("list_detections_feature_type_filter", ft_enums=[ft.value for ft in ft_enums])
    if source_pass:
        stmt = stmt.where(or_(Detection.source_passes.contains([source_pass]),
                              Detection.source_passes.contains({"source_passes": [source_pass]})))
    if validated is not None:
        stmt = stmt.where(Detection.validated == validated)
    # Count total before pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()
    stmt = stmt.order_by(Detection.confidence.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    detections = result.scalars().all()
    features = [_detection_to_feature(d) for d in detections]
    log.info("detections_listed", total=total, returned=len(features), elapsed_ms=round((time.perf_counter() - t0) * 1000, 1))
    return DetectionCollection(features=features, total_count=total)


@router.get("/detections/count")
async def count_detections(
    lat: float = Query(..., description="Center latitude"),
    lon: float = Query(..., description="Center longitude"),
    radius_km: float = Query(3.0, ge=0.1, le=50.0, description="Search radius in km"),
    db: AsyncSession = Depends(get_db),
):
    """Fast count of detections near a point. Used to decide whether to trigger processing."""
    from sqlalchemy import text
    log.info("count_detections_requested", lat=lat, lon=lon, radius_km=radius_km)
    t0 = time.perf_counter()
    result = await db.execute(
        text("""
            SELECT COUNT(*) FROM detections
            WHERE ST_DWithin(
                geometry::geography,
                ST_SetSRID(ST_Point(:lon, :lat), 4326)::geography,
                :radius_m
            )
        """),
        {"lat": lat, "lon": lon, "radius_m": radius_km * 1000},
    )
    count = result.scalar_one()
    log.info("detections_counted", lat=lat, lon=lon, radius_km=radius_km, count=count, elapsed_ms=round((time.perf_counter() - t0) * 1000, 1))
    return {"count": count}


@router.get("/detections/{detection_id}", response_model=DetectionDetail)
async def get_detection(
    detection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get detailed info for a single detection."""
    log.debug("get_detection_requested", detection_id=str(detection_id))
    t0 = time.perf_counter()
    detection = await db.get(Detection, detection_id)
    if not detection:
        log.warning("get_detection_not_found", detection_id=str(detection_id))
        raise HTTPException(status_code=404, detail="Detection not found")
    # Load pass results
    pr_stmt = select(PassResult).where(PassResult.detection_id == detection_id)
    pass_results = (await db.execute(pr_stmt)).scalars().all()
    # Load validation events
    ve_stmt = select(ValidationEvent).where(ValidationEvent.detection_id == detection_id)
    val_events = (await db.execute(ve_stmt)).scalars().all()
    log.info("detection_detail_loaded", detection_id=str(detection_id), pass_results=len(pass_results), validation_events=len(val_events), elapsed_ms=round((time.perf_counter() - t0) * 1000, 1))
    return DetectionDetail(
        id=str(detection.id),
        feature_type=detection.feature_type.value if detection.feature_type else None,
        confidence=detection.confidence or 0.0,
        depth_m=detection.depth_m,
        area_m2=detection.area_m2,
        circularity=detection.circularity,
        morphometrics=detection.morphometrics,
        source_passes=detection.source_passes,
        validated=detection.validated,
        validation_notes=detection.validation_notes,
        pass_results=[
            {"pass_name": pr.pass_name, "raw_score": pr.raw_score, "parameters": pr.parameters}
            for pr in pass_results
        ],
        validation_events=[
            {"verdict": ve.verdict.value, "notes": ve.notes, "created_at": str(ve.created_at)}
            for ve in val_events
        ],
        created_at=detection.created_at,
    )
