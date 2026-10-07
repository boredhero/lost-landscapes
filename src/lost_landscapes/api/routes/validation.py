"""Validation workflow — confirm/reject/annotate detections + add ground truth."""

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lost_landscapes.api.deps import get_db
from lost_landscapes.api.schemas import (
    GroundTruthCreate,
    GroundTruthSiteOut,
    ValidationRequest,
    ValidationResponse,
)
from lost_landscapes.db.models import (
    Detection,
    FeatureType,
    GroundTruthSite,
    GroundTruthSource,
    ValidationEvent,
    ValidationVerdict,
)
from lost_landscapes.utils.log_manager import log

router = APIRouter(tags=["validation"])


@router.post("/detections/{detection_id}/validate", response_model=ValidationResponse)
async def validate_detection(
    detection_id: uuid.UUID,
    body: ValidationRequest,
    db: AsyncSession = Depends(get_db),
):
    """Record a validation verdict (confirm/reject/uncertain) for a detection."""
    log.info("validate_detection_requested", detection_id=str(detection_id), verdict=body.verdict)
    detection = await db.get(Detection, detection_id)
    if not detection:
        log.warning("validate_detection_not_found", detection_id=str(detection_id))
        raise HTTPException(status_code=404, detail="Detection not found")
    try:
        verdict = ValidationVerdict(body.verdict.upper())
    except ValueError:
        log.warning("validate_detection_invalid_verdict", detection_id=str(detection_id), verdict=body.verdict)
        raise HTTPException(status_code=400, detail=f"Invalid verdict: {body.verdict}")
    event = ValidationEvent(
        detection_id=detection_id,
        verdict=verdict,
        notes=body.notes,
    )
    db.add(event)
    # Update detection's validated flag based on latest verdict
    detection.validated = verdict == ValidationVerdict.CONFIRMED
    detection.validation_notes = body.notes
    await db.commit()
    log.info("detection_validated", detection_id=str(detection_id), verdict=verdict.value, validated_flag=detection.validated)
    return ValidationResponse(
        verdict=verdict.value,
        detection_id=str(detection_id),
    )


@router.get("/ground-truth")
async def list_ground_truth(
    west: float | None = Query(None),
    south: float | None = Query(None),
    east: float | None = Query(None),
    north: float | None = Query(None),
    limit: int = Query(1000, le=10000),
    db: AsyncSession = Depends(get_db),
):
    """List ground truth sites, optionally within a bounding box."""
    has_bbox = all(v is not None for v in [west, south, east, north])
    log.info("list_ground_truth_requested", has_bbox=has_bbox, bbox=[west, south, east, north] if has_bbox else None, limit=limit)
    t0 = time.perf_counter()
    stmt = select(GroundTruthSite).limit(limit)
    if has_bbox:
        from geoalchemy2.functions import ST_MakeEnvelope
        envelope = ST_MakeEnvelope(west, south, east, north, 4326)
        stmt = stmt.where(GroundTruthSite.geometry.ST_Within(envelope))
    result = await db.execute(stmt)
    sites = result.scalars().all()
    log.info("ground_truth_listed", count=len(sites), has_bbox=has_bbox, elapsed_ms=round((time.perf_counter() - t0) * 1000, 1))
    out = []
    for s in sites:
        try:
            pt = to_shape(s.geometry)
            lat, lon = pt.y, pt.x
        except Exception as e:
            log.warning("ground_truth_geom_conversion_failed", site_id=str(s.id), error=str(e))
            lat, lon = 0.0, 0.0

        out.append(GroundTruthSiteOut(
            id=str(s.id),
            name=s.name,
            feature_type=s.feature_type.value if s.feature_type else "unknown",
            lat=lat,
            lon=lon,
            source=s.source.value if s.source else "unknown",
            metadata=s.metadata_,
        ))

    return {"type": "FeatureCollection", "features": [
        {
            "type": "Feature",
            "id": site.id,
            "geometry": {"type": "Point", "coordinates": [site.lon, site.lat]},
            "properties": {
                "name": site.name,
                "feature_type": site.feature_type,
                "source": site.source,
            },
        }
        for site in out
    ]}


@router.post("/ground-truth")
async def create_ground_truth(
    body: GroundTruthCreate,
    db: AsyncSession = Depends(get_db),
):
    """Add a new ground truth site (e.g., from map click in validation UI)."""
    log.info("create_ground_truth_requested", name=body.name, feature_type=body.feature_type, lat=body.lat, lon=body.lon)
    try:
        feature_type = FeatureType(body.feature_type)
    except ValueError:
        log.warning("create_ground_truth_unknown_feature_type", provided=body.feature_type, fallback="UNKNOWN")
        feature_type = FeatureType.UNKNOWN
    site = GroundTruthSite(
        name=body.name,
        feature_type=feature_type,
        geometry=from_shape(Point(body.lon, body.lat), srid=4326),
        source=GroundTruthSource.MANUAL,
        metadata_={"notes": body.notes} if body.notes else None,
    )
    db.add(site)
    await db.commit()
    await db.refresh(site)
    log.info("ground_truth_created", site_id=str(site.id), name=site.name, feature_type=feature_type.value)
    return {"id": str(site.id), "name": site.name, "status": "created"}
