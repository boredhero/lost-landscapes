"""Export endpoints — GeoJSON, CSV, KML downloads."""

import csv
import io
import json
import time

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from geoalchemy2.functions import ST_MakeEnvelope
from geoalchemy2.shape import to_shape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lost_landscapes.api.deps import get_db
from lost_landscapes.db.models import Detection, FeatureType
from lost_landscapes.utils.log_manager import log

router = APIRouter(tags=["exports"])


@router.get("/export/geojson")
async def export_geojson(
    west: float = Query(...),
    south: float = Query(...),
    east: float = Query(...),
    north: float = Query(...),
    min_confidence: float = Query(0.0),
    feature_type: list[str] | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Export detections as downloadable GeoJSON."""
    log.info("export_geojson_requested", bbox=[west, south, east, north], min_confidence=min_confidence, feature_type=feature_type)
    t0 = time.perf_counter()
    envelope = ST_MakeEnvelope(west, south, east, north, 4326)
    stmt = (
        select(Detection)
        .where(Detection.geometry.ST_Within(envelope))
        .where(Detection.confidence >= min_confidence)
        .limit(100000)
    )
    if feature_type:
        ft_enums = [FeatureType(ft) for ft in feature_type if ft in FeatureType.__members__]
        if ft_enums:
            stmt = stmt.where(Detection.feature_type.in_(ft_enums))
    result = await db.execute(stmt)
    detections = result.scalars().all()
    log.info("export_geojson_query_complete", detection_count=len(detections), elapsed_ms=round((time.perf_counter() - t0) * 1000, 1))
    features = []
    for d in detections:
        try:
            pt = to_shape(d.geometry)
            geom = {"type": "Point", "coordinates": [pt.x, pt.y]}
        except Exception as e:
            log.warning("geojson_export_geom_failed", detection_id=str(d.id), error=str(e))
            continue

        features.append({
            "type": "Feature",
            "id": str(d.id),
            "geometry": geom,
            "properties": {
                "feature_type": d.feature_type.value if d.feature_type else None,
                "confidence": d.confidence,
                "depth_m": d.depth_m,
                "area_m2": d.area_m2,
                "circularity": d.circularity,
                "validated": d.validated,
            },
        })

    geojson = {"type": "FeatureCollection", "features": features}
    payload = json.dumps(geojson, indent=2).encode()
    log.info("export_geojson_complete", feature_count=len(features), size_bytes=len(payload), elapsed_ms=round((time.perf_counter() - t0) * 1000, 1))
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/geo+json",
        headers={"Content-Disposition": "attachment; filename=detections.geojson"},
    )


@router.get("/export/csv")
async def export_csv(
    west: float = Query(...),
    south: float = Query(...),
    east: float = Query(...),
    north: float = Query(...),
    min_confidence: float = Query(0.0),
    db: AsyncSession = Depends(get_db),
):
    """Export detections as downloadable CSV."""
    log.info("export_csv_requested", bbox=[west, south, east, north], min_confidence=min_confidence)
    t0 = time.perf_counter()
    envelope = ST_MakeEnvelope(west, south, east, north, 4326)
    stmt = (
        select(Detection)
        .where(Detection.geometry.ST_Within(envelope))
        .where(Detection.confidence >= min_confidence)
        .limit(100000)
    )
    result = await db.execute(stmt)
    detections = result.scalars().all()
    log.info("export_csv_query_complete", detection_count=len(detections), elapsed_ms=round((time.perf_counter() - t0) * 1000, 1))
    output = io.StringIO()
    writer = csv.writer(output)
    headers = ["id", "lat", "lon", "feature_type", "confidence", "depth_m", "area_m2", "circularity", "validated"]
    writer.writerow(headers)

    for d in detections:
        try:
            pt = to_shape(d.geometry)
            lat, lon = pt.y, pt.x
        except Exception as e:
            log.warning("csv_export_geom_failed", detection_id=str(d.id), error=str(e))
            continue

        writer.writerow([
            str(d.id), lat, lon,
            d.feature_type.value if d.feature_type else "",
            d.confidence, d.depth_m, d.area_m2, d.circularity, d.validated,
        ])

    csv_payload = output.getvalue().encode()
    log.info("export_csv_complete", row_count=len(detections), size_bytes=len(csv_payload), elapsed_ms=round((time.perf_counter() - t0) * 1000, 1))
    return StreamingResponse(
        io.BytesIO(csv_payload),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=detections.csv"},
    )
