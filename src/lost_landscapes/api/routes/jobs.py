"""Job submission, status, and management endpoints."""

import math
import time
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lost_landscapes.api.deps import get_db
from lost_landscapes.api.schemas import JobCreate, JobList, JobStatus
from lost_landscapes.config import settings
from lost_landscapes.db.models import Job, JobType
from lost_landscapes.db.models import JobStatus as JobStatusEnum
from lost_landscapes.utils.log_manager import log

router = APIRouter(tags=["jobs"])


class ConsumerScanRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    radius_km: float = Field(5.0, ge=0.5, le=10.0)


def _job_to_schema(j: Job) -> JobStatus:
    return JobStatus(
        id=str(j.id),
        job_type=j.job_type.value if j.job_type else "unknown",
        status=j.status.value if j.status else "unknown",
        progress=j.progress or 0.0,
        result_summary=j.result_summary,
        error_message=j.error_message,
        created_at=j.created_at,
        started_at=j.started_at,
        completed_at=j.completed_at,
    )


@router.get("/jobs", response_model=JobList)
async def list_jobs(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all jobs, optionally filtered by status."""
    log.debug("list_jobs_request", status_filter=status)
    t0 = time.perf_counter()
    stmt = select(Job).order_by(Job.created_at.desc()).limit(100)
    if status:
        try:
            status_enum = JobStatusEnum(status.upper())
            stmt = stmt.where(Job.status == status_enum)
        except ValueError as e:
            log.debug("invalid_job_status_filter", status=status, error=str(e))
            pass
    result = await db.execute(stmt)
    jobs = result.scalars().all()
    log.info("list_jobs_complete", count=len(jobs), status_filter=status, elapsed_ms=round((time.perf_counter() - t0) * 1000, 1))
    return JobList(jobs=[_job_to_schema(j) for j in jobs])


@router.post("/jobs", response_model=JobStatus)
async def create_job(
    body: JobCreate,
    db: AsyncSession = Depends(get_db),
):
    """Submit a new processing job."""
    if not settings.enable_analysis:
        raise HTTPException(503, "Analysis worker is not enabled on this deployment")
    if not body.bbox:
        raise HTTPException(422, "Select a bounded area to analyze")
    from shapely.geometry import shape
    try:
        geometry = shape(body.bbox)
        west, south, east, north = geometry.bounds
        width = (east - west) * 111.32 * math.cos(math.radians((south + north) / 2))
        height = (north - south) * 111.32
        if geometry.geom_type != "Polygon" or not geometry.is_valid or geometry.is_empty or not (
            -180 <= west < east <= 180 and -85 <= south < north <= 85 and width <= 4 and height <= 4
        ):
            raise ValueError("Invalid or oversized scan bounds")
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, "Choose an area less than 4 km across") from exc
    log.info("create_job_request", job_type=body.job_type, pass_config=body.pass_config, has_bbox=body.bbox is not None)
    try:
        job_type = JobType(body.job_type.upper())
    except ValueError as e:
        log.warning("create_job_unknown_type", requested=body.job_type, fallback="FULL_PIPELINE", error=str(e))
        job_type = JobType.FULL_PIPELINE
    region_geom = None
    if body.bbox:
        from geoalchemy2.shape import from_shape
        from shapely.geometry import shape
        region_geom = from_shape(shape(body.bbox), srid=4326)
    job = Job(
        job_type=job_type,
        status=JobStatusEnum.PENDING,
        region=region_geom,
        config={"pass_config": body.pass_config, "tile_limit": settings.scan_tile_limit},
        progress=0.0,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    log.info("job_created", job_id=str(job.id), job_type=job_type.value, status="PENDING")
    # Submit to Celery
    try:
        from lost_landscapes.workers.tasks import run_full_pipeline
        bbox_geojson = None
        if body.bbox:
            from shapely.geometry import shape
            bbox_geojson = body.bbox
        task = run_full_pipeline.delay(
            job_id=str(job.id),
            pass_config=body.pass_config,
            bbox_geojson=bbox_geojson,
        )
        job.celery_task_id = task.id
        # Worker changes PENDING to RUNNING when execution actually starts.
        await db.commit()
        log.info("job_submitted_to_celery", job_id=str(job.id), celery_task_id=task.id)
    except Exception as e:
        job.status = JobStatusEnum.FAILED
        job.error_message = "Analysis queue is unavailable. Please try again later."
        await db.commit()
        raise HTTPException(503, job.error_message) from e
    return _job_to_schema(job)


@router.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get status of a specific job."""
    log.debug("get_job_request", job_id=str(job_id))
    job = await db.get(Job, job_id)
    if not job:
        log.warning("get_job_not_found", job_id=str(job_id))
        raise HTTPException(status_code=404, detail="Job not found")
    log.debug("get_job_result", job_id=str(job_id), status=job.status.value if job.status else "unknown", progress=job.progress)
    return _job_to_schema(job)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a pending or running job."""
    log.info("cancel_job_request", job_id=str(job_id))
    job = await db.get(Job, job_id)
    if not job:
        log.warning("cancel_job_not_found", job_id=str(job_id))
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in (JobStatusEnum.PENDING, JobStatusEnum.RUNNING):
        log.warning("cancel_job_invalid_state", job_id=str(job_id), current_status=job.status.value)
        raise HTTPException(status_code=400, detail=f"Cannot cancel job in state {job.status.value}")
    previous_status = job.status.value
    job.status = JobStatusEnum.CANCELLED
    job.completed_at = datetime.now(UTC)
    await db.commit()
    log.info("job_cancelled", job_id=str(job_id), previous_status=previous_status)
    # Revoke Celery task if running
    # if job.celery_task_id:
    #     from lost_landscapes.workers.celery_app import app
    #     app.control.revoke(job.celery_task_id, terminate=True)
    return {"status": "cancelled", "job_id": str(job_id)}


@router.post("/explore/scan")
async def consumer_scan(
    body: ConsumerScanRequest,
    db: AsyncSession = Depends(get_db),
):
    """Start a small processing job for the consumer "Find a Hole Near Me" flow.

    Restricted to a small radius (max 5km) and 4 tiles to keep processing
    under 5 minutes. The consumer never sees the word "job" — this is
    presented as "scanning your area."
    """
    if not settings.enable_analysis:
        raise HTTPException(503, "Analysis worker is not enabled on this deployment")
    log.info("consumer_scan_request", lat=body.lat, lon=body.lon, radius_km=body.radius_km)
    r = body.radius_km / 111.32  # degrees approx
    bbox_geojson = {
        "type": "Polygon",
        "coordinates": [[
            [body.lon - r, body.lat - r],
            [body.lon + r, body.lat - r],
            [body.lon + r, body.lat + r],
            [body.lon - r, body.lat + r],
            [body.lon - r, body.lat - r],
        ]],
    }
    from geoalchemy2.shape import from_shape
    from shapely.geometry import shape
    region_geom = from_shape(shape(bbox_geojson), srid=4326)
    # Don't delete existing detections upfront — the Celery worker
    # clears them only after confirming tiles are available to process.
    # This preserves data when a scan finds no LiDAR coverage.
    job = Job(
        job_type=JobType.FULL_PIPELINE,
        status=JobStatusEnum.PENDING,
        region=region_geom,
        config={
            "pass_config": "sinkhole_survey",
            "tile_limit": settings.scan_tile_limit,
            "consumer": True,
            "center_lat": body.lat,
            "center_lon": body.lon,
            "radius_km": body.radius_km,
        },
        progress=0.0,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    log.info("consumer_scan_job_created", job_id=str(job.id), lat=body.lat, lon=body.lon, radius_km=body.radius_km)
    # Submit to Celery
    try:
        from lost_landscapes.workers.tasks import run_full_pipeline
        task = run_full_pipeline.delay(
            job_id=str(job.id),
            pass_config="sinkhole_survey",
            bbox_geojson=bbox_geojson,
        )
        job.celery_task_id = task.id
        job.status = JobStatusEnum.RUNNING
        job.started_at = datetime.now(UTC)
        await db.commit()
        log.info("consumer_scan_submitted", job_id=str(job.id), celery_task_id=task.id)
    except Exception as e:
        log.warning("consumer_scan_celery_failed", job_id=str(job.id), error=str(e), exception=True)
    # Estimate: ~75s per tile, assume 3 tiles avg
    estimated_minutes = round(3 * 75 / 60, 1)
    log.info("consumer_scan_response", job_id=str(job.id), estimated_minutes=estimated_minutes)
    return {
        "job_id": str(job.id),
        "estimated_minutes": estimated_minutes,
    }
