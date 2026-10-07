"""Massachusetts mine and cave features loader — USGS MRDS.

Source: USGS Mineral Resources Data System
160+ mines in Berkshire County marble belt, pyrite/mica mines.
"""

import time

import httpx
from geoalchemy2.shape import from_shape
from shapely.geometry import Point, shape
from sqlalchemy.ext.asyncio import AsyncSession

from lost_landscapes.db.models import FeatureType, GroundTruthSite, GroundTruthSource
from lost_landscapes.utils.log_manager import log

MRDS_URL = "https://mrdata.usgs.gov/mrds/wfs"


async def load_ma_mines(session: AsyncSession, data_dir: str) -> int:
    """Load Massachusetts mine features from USGS MRDS."""
    t0 = time.monotonic()
    log.info("ma_mines_load_start", data_dir=data_dir)
    count = 0
    batch = []
    skipped_no_geom = 0
    skipped_parse_fail = 0
    type_counts = {"cave_entrance": 0, "mine_portal": 0}
    lats = []
    lons = []
    params = {
        "service": "WFS",
        "version": "1.1.0",
        "request": "GetFeature",
        "typeName": "mrds",
        "outputFormat": "application/json",
        "CQL_FILTER": "state_name='Massachusetts'",
        "maxFeatures": "5000",
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            t_req = time.monotonic()
            response = await client.get(MRDS_URL, params=params)
            response.raise_for_status()
            data = response.json()
            elapsed_req = round(time.monotonic() - t_req, 3)
            log.info("ma_mrds_query_ok", url=MRDS_URL, status=response.status_code, response_bytes=len(response.content), elapsed_s=elapsed_req)
        except (httpx.HTTPError, Exception) as e:
            log.warning("ma_mrds_query_failed", url=MRDS_URL, error=str(e), exception=True)
            return 0
        features = data.get("features", [])
        log.info("ma_mrds_results", count=len(features))
        for feature in features:
            props = feature.get("properties", {})
            geom_data = feature.get("geometry")
            if not geom_data:
                skipped_no_geom += 1
                continue
            try:
                geom = shape(geom_data)
            except Exception as e:
                log.debug("geom_parse_failed", source="ma_mines", error=str(e), exception=True)
                skipped_parse_fail += 1
                continue
            if geom.geom_type != "Point":
                log.debug("ma_mines_centroid_fallback", original_type=geom.geom_type)
                geom = geom.centroid
            commodity = str(props.get("commod1", "") or "").upper()
            if "MARBLE" in commodity or "LIMESTONE" in commodity:
                ft = FeatureType.CAVE_ENTRANCE
                type_counts["cave_entrance"] += 1
            else:
                ft = FeatureType.MINE_PORTAL
                type_counts["mine_portal"] += 1
            site = GroundTruthSite(
                name=str(props.get("site_name", "") or f"MA-{count}"),
                feature_type=ft,
                geometry=from_shape(Point(geom.x, geom.y), srid=4326),
                source=GroundTruthSource.MA_USGS_MINES,
                source_id=str(props.get("dep_id", "") or props.get("rec_id", "")),
                metadata_={
                    "commodity": commodity,
                    "county": str(props.get("county", "")),
                },
            )
            batch.append(site)
            lats.append(geom.y)
            lons.append(geom.x)
            count += 1
            if len(batch) >= 500:
                session.add_all(batch)
                await session.flush()
                log.debug("ma_mines_batch_flushed", batch_size=500, total_so_far=count)
                batch.clear()
    if batch:
        session.add_all(batch)
        await session.flush()
        log.debug("ma_mines_final_batch_flushed", batch_size=len(batch))
    await session.commit()
    elapsed = round(time.monotonic() - t0, 3)
    extent = {"lat_min": round(min(lats), 4), "lat_max": round(max(lats), 4), "lon_min": round(min(lons), 4), "lon_max": round(max(lons), 4)} if lats else {}
    log.info("ma_mines_load_done", count=count, type_counts=type_counts, skipped_no_geom=skipped_no_geom, skipped_parse_fail=skipped_parse_fail, extent=extent, elapsed_s=elapsed)
    return count
