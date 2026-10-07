"""Data access layer for spatial queries."""

import time
import uuid

from geoalchemy2.functions import ST_DWithin, ST_GeogFromWKB, ST_MakeEnvelope
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lost_landscapes.db.models import Detection, FeatureType, GroundTruthSite
from lost_landscapes.utils.log_manager import log


async def get_detections_in_bbox(
    session: AsyncSession,
    west: float,
    south: float,
    east: float,
    north: float,
    feature_types: list[FeatureType] | None = None,
    min_confidence: float = 0.0,
    limit: int = 10000,
) -> list[Detection]:
    """Query detections within a bounding box."""
    log.debug("query_detections_in_bbox_start", west=west, south=south, east=east, north=north, srid=4326, min_confidence=min_confidence, feature_types=str(feature_types) if feature_types else "all", limit=limit)
    t0 = time.perf_counter()
    envelope = ST_MakeEnvelope(west, south, east, north, 4326)
    stmt = (
        select(Detection)
        .where(Detection.geometry.ST_Within(envelope))
        .where(Detection.confidence >= min_confidence)
        .order_by(Detection.confidence.desc())
        .limit(limit)
    )
    if feature_types:
        stmt = stmt.where(Detection.feature_type.in_(feature_types))
    try:
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
        elapsed_ms = (time.perf_counter() - t0) * 1000
        log.info("query_detections_in_bbox_complete", result_count=len(rows), elapsed_ms=round(elapsed_ms, 2), west=west, south=south, east=east, north=north, min_confidence=min_confidence, limit=limit)
        return rows
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        log.error("query_detections_in_bbox_failed", error=str(e), elapsed_ms=round(elapsed_ms, 2), west=west, south=south, east=east, north=north, exception=True)
        raise


async def get_detections_near_point(
    session: AsyncSession,
    lat: float,
    lon: float,
    radius_m: float = 200.0,
) -> list[Detection]:
    """Query detections within radius_m meters of a point."""
    log.debug("query_detections_near_point_start", lat=lat, lon=lon, radius_m=radius_m, srid=4326)
    t0 = time.perf_counter()
    point_wkt = f"SRID=4326;POINT({lon} {lat})"
    stmt = select(Detection).where(
        ST_DWithin(
            ST_GeogFromWKB(Detection.geometry),
            ST_GeogFromWKB(point_wkt),
            radius_m,
        )
    )
    try:
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
        elapsed_ms = (time.perf_counter() - t0) * 1000
        log.info("query_detections_near_point_complete", result_count=len(rows), elapsed_ms=round(elapsed_ms, 2), lat=lat, lon=lon, radius_m=radius_m)
        return rows
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        log.error("query_detections_near_point_failed", error=str(e), elapsed_ms=round(elapsed_ms, 2), lat=lat, lon=lon, radius_m=radius_m, exception=True)
        raise


async def get_ground_truth_near_point(
    session: AsyncSession,
    lat: float,
    lon: float,
    radius_m: float = 200.0,
) -> list[GroundTruthSite]:
    """Query ground truth sites within radius_m meters of a point."""
    log.debug("query_ground_truth_near_point_start", lat=lat, lon=lon, radius_m=radius_m, srid=4326)
    t0 = time.perf_counter()
    point_wkt = f"SRID=4326;POINT({lon} {lat})"
    stmt = select(GroundTruthSite).where(
        ST_DWithin(
            ST_GeogFromWKB(GroundTruthSite.geometry),
            ST_GeogFromWKB(point_wkt),
            radius_m,
        )
    )
    try:
        result = await session.execute(stmt)
        rows = list(result.scalars().all())
        elapsed_ms = (time.perf_counter() - t0) * 1000
        log.info("query_ground_truth_near_point_complete", result_count=len(rows), elapsed_ms=round(elapsed_ms, 2), lat=lat, lon=lon, radius_m=radius_m)
        return rows
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        log.error("query_ground_truth_near_point_failed", error=str(e), elapsed_ms=round(elapsed_ms, 2), lat=lat, lon=lon, radius_m=radius_m, exception=True)
        raise


async def get_detection_by_id(
    session: AsyncSession, detection_id: uuid.UUID
) -> Detection | None:
    log.debug("query_detection_by_id_start", detection_id=str(detection_id))
    t0 = time.perf_counter()
    try:
        result = await session.get(Detection, detection_id)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        log.info("query_detection_by_id_complete", detection_id=str(detection_id), found=result is not None, elapsed_ms=round(elapsed_ms, 2))
        return result
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        log.error("query_detection_by_id_failed", detection_id=str(detection_id), error=str(e), elapsed_ms=round(elapsed_ms, 2), exception=True)
        raise
