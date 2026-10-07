"""Vector tile (MVT) endpoint — serves detections as Mapbox Vector Tiles.

Uses PostGIS ST_AsMVT for on-the-fly vector tile generation.
This is critical for rendering 100K+ detections without shipping
massive GeoJSON to the frontend.
"""

import math
import time

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from lost_landscapes.api.deps import get_db
from lost_landscapes.utils.log_manager import log

router = APIRouter(tags=["tiles"])


def _tile_to_bbox(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Convert ZXY tile coords to WGS84 bounding box."""
    n = 2 ** z
    lon_min = x / n * 360 - 180
    lon_max = (x + 1) / n * 360 - 180
    lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return lon_min, lat_min, lon_max, lat_max


@router.get("/tiles/{z}/{x}/{y}.mvt")
async def get_vector_tile(
    z: int,
    x: int,
    y: int,
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
):
    """Serve detections as Mapbox Vector Tiles (MVT).

    Uses PostGIS ST_AsMVTGeom + ST_AsMVT for efficient on-the-fly generation.
    """
    log.debug("mvt_tile_request", z=z, x=x, y=y, min_confidence=min_confidence)
    t0 = time.perf_counter()
    bbox = _tile_to_bbox(z, x, y)
    # ST_AsMVT query — point layer + outline polygon layer
    query = text("""
        WITH tile_bounds AS (
            SELECT ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326) AS geom
        ),
        tile_data AS (
            SELECT
                ST_AsMVTGeom(d.geometry, tb.geom, 4096, 256, true) AS geom,
                d.id::text AS id,
                d.feature_type::text AS feature_type,
                d.confidence,
                d.depth_m,
                d.area_m2,
                d.validated
            FROM detections d, tile_bounds tb
            WHERE ST_Intersects(d.geometry, tb.geom)
              AND d.confidence >= :min_confidence
            LIMIT 100000
        ),
        outline_data AS (
            SELECT
                ST_AsMVTGeom(ST_ForcePolygonCW(d.outline), tb.geom, 4096, 256, true) AS geom,
                d.id::text AS id,
                d.feature_type::text AS feature_type,
                d.confidence
            FROM detections d, tile_bounds tb
            WHERE d.outline IS NOT NULL
              AND ST_Intersects(d.outline, tb.geom)
              AND d.confidence >= :min_confidence
            LIMIT 100000
        )
        SELECT
            COALESCE((SELECT ST_AsMVT(tile_data, 'detections', 4096, 'geom') FROM tile_data), ''::bytea)
            || COALESCE((SELECT ST_AsMVT(outline_data, 'outlines', 4096, 'geom') FROM outline_data), ''::bytea)
        AS mvt
    """)
    result = await db.execute(query, {
        "xmin": bbox[0],
        "ymin": bbox[1],
        "xmax": bbox[2],
        "ymax": bbox[3],
        "min_confidence": min_confidence,
    })
    row = result.fetchone()
    mvt_data = row[0] if row and row[0] else b""
    tile_bytes = len(mvt_data)
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    log.debug("mvt_tile_generated", z=z, x=x, y=y, tile_bytes=tile_bytes, elapsed_ms=elapsed_ms)
    if tile_bytes == 0:
        log.debug("mvt_tile_empty", z=z, x=x, y=y, min_confidence=min_confidence)
    return Response(
        content=bytes(mvt_data),
        media_type="application/x-protobuf",
        headers={
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/tiles/ground-truth/{z}/{x}/{y}.mvt")
async def get_ground_truth_tile(
    z: int,
    x: int,
    y: int,
    db: AsyncSession = Depends(get_db),
):
    """Serve ground truth sites as vector tiles."""
    log.debug("ground_truth_tile_request", z=z, x=x, y=y)
    t0 = time.perf_counter()
    bbox = _tile_to_bbox(z, x, y)
    query = text("""
        WITH tile_bounds AS (
            SELECT ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326) AS geom
        ),
        tile_data AS (
            SELECT
                ST_AsMVTGeom(g.geometry, tb.geom, 4096, 256, true) AS geom,
                g.id::text AS id,
                g.name,
                g.feature_type::text AS feature_type,
                g.source::text AS source
            FROM ground_truth_sites g, tile_bounds tb
            WHERE ST_Intersects(g.geometry, tb.geom)
        )
        SELECT ST_AsMVT(tile_data, 'ground_truth', 4096, 'geom') AS mvt
        FROM tile_data
    """)
    result = await db.execute(query, {
        "xmin": bbox[0], "ymin": bbox[1],
        "xmax": bbox[2], "ymax": bbox[3],
    })
    row = result.fetchone()
    mvt_data = row[0] if row and row[0] else b""
    log.debug("ground_truth_tile_generated", z=z, x=x, y=y, tile_bytes=len(mvt_data), elapsed_ms=round((time.perf_counter() - t0) * 1000, 1))
    return Response(
        content=bytes(mvt_data),
        media_type="application/x-protobuf",
        headers={"Cache-Control": "public, max-age=3600"},
    )
