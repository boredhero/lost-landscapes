"""Maryland karst features loader — Maryland Geological Survey.

Source: Maryland Geological Survey (MGS) karst feature data.
53+ caves, 2100+ karst features in Hagerstown Valley and western MD.
"""

import time

import httpx
from geoalchemy2.shape import from_shape
from shapely.geometry import Point, shape
from sqlalchemy.ext.asyncio import AsyncSession

from lost_landscapes.db.models import FeatureType, GroundTruthSite, GroundTruthSource
from lost_landscapes.utils.log_manager import log

# USGS MRDS REST endpoint — filter to Maryland
MRDS_URL = "https://mrdata.usgs.gov/mrds/wfs"


async def load_md_karst(session: AsyncSession, data_dir: str) -> int:
    """Load Maryland karst and mine features from USGS MRDS.
    Filters to Maryland for caves, mines, and karst features.
    """
    t0 = time.monotonic()
    log.info("md_karst_load_start", data_dir=data_dir)
    count = 0
    batch = []
    skipped_no_geom = 0
    skipped_parse_fail = 0
    type_counts = {"mine_portal": 0, "cave_entrance": 0, "sinkhole": 0}
    lats = []
    lons = []
    params = {
        "service": "WFS",
        "version": "1.1.0",
        "request": "GetFeature",
        "typeName": "mrds",
        "outputFormat": "application/json",
        "CQL_FILTER": "state_name='Maryland'",
        "maxFeatures": "5000",
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            t_req = time.monotonic()
            response = await client.get(MRDS_URL, params=params)
            response.raise_for_status()
            data = response.json()
            elapsed_req = round(time.monotonic() - t_req, 3)
            log.info("md_mrds_query_ok", url=MRDS_URL, status=response.status_code, response_bytes=len(response.content), elapsed_s=elapsed_req)
        except (httpx.HTTPError, Exception) as e:
            log.warning("md_mrds_query_failed", url=MRDS_URL, error=str(e), exception=True)
            return 0
        features = data.get("features", [])
        log.info("md_mrds_results", count=len(features))
        for feature in features:
            props = feature.get("properties", {})
            geom_data = feature.get("geometry")
            if not geom_data:
                skipped_no_geom += 1
                continue
            try:
                geom = shape(geom_data)
            except Exception as e:
                log.debug("geom_parse_failed", source="md_karst", error=str(e), exception=True)
                skipped_parse_fail += 1
                continue
            if geom.geom_type != "Point":
                log.debug("md_karst_centroid_fallback", original_type=geom.geom_type)
                geom = geom.centroid
            commodity = str(props.get("commod1", "") or "").upper()
            site_type = str(props.get("site_type", "") or "").upper()
            if "COAL" in commodity:
                ft = FeatureType.MINE_PORTAL
                type_counts["mine_portal"] += 1
            elif "CAVE" in site_type:
                ft = FeatureType.CAVE_ENTRANCE
                type_counts["cave_entrance"] += 1
            elif "LIMESTONE" in commodity or "DOLOMITE" in commodity:
                ft = FeatureType.SINKHOLE
                type_counts["sinkhole"] += 1
            else:
                ft = FeatureType.MINE_PORTAL
                type_counts["mine_portal"] += 1
            site = GroundTruthSite(
                name=str(props.get("site_name", "") or f"MD-{count}"),
                feature_type=ft,
                geometry=from_shape(Point(geom.x, geom.y), srid=4326),
                source=GroundTruthSource.MD_KARST_SURVEY,
                source_id=str(props.get("dep_id", "") or props.get("rec_id", "")),
                metadata_={
                    "commodity": commodity,
                    "county": str(props.get("county", "")),
                    "site_type": site_type,
                },
            )
            batch.append(site)
            lats.append(geom.y)
            lons.append(geom.x)
            count += 1
            if len(batch) >= 500:
                session.add_all(batch)
                await session.flush()
                log.debug("md_karst_batch_flushed", batch_size=500, total_so_far=count)
                batch.clear()
    if batch:
        session.add_all(batch)
        await session.flush()
        log.debug("md_karst_final_batch_flushed", batch_size=len(batch))
    await session.commit()
    elapsed = round(time.monotonic() - t0, 3)
    extent = {"lat_min": round(min(lats), 4), "lat_max": round(max(lats), 4), "lon_min": round(min(lons), 4), "lon_max": round(max(lons), 4)} if lats else {}
    log.info("md_karst_load_done", count=count, type_counts=type_counts, skipped_no_geom=skipped_no_geom, skipped_parse_fail=skipped_parse_fail, extent=extent, elapsed_s=elapsed)
    return count
