"""Ohio EPA Karst Features loader — query ArcGIS Online feature layer.

Source: Ohio EPA GIS Portal
Access: REST API query (no download needed, paginated results).
"""

import time

import httpx
from geoalchemy2.shape import from_shape
from shapely.geometry import Point, shape
from sqlalchemy.ext.asyncio import AsyncSession

from lost_landscapes.db.models import FeatureType, GroundTruthSite, GroundTruthSource
from lost_landscapes.utils.log_manager import log

# Ohio EPA karst feature service URL
OHIO_KARST_URL = (
    "https://services.arcgis.com/ULBthCfq5kAoGGkN/ArcGIS/rest/services/"
    "Known_and_Indicated_Karst_Locations/FeatureServer/0/query"
)


async def load_ohio_karst(session: AsyncSession, data_dir: str) -> int:
    """Load Ohio karst features from ArcGIS REST API."""
    log.info("ohio_karst_load_start", url=OHIO_KARST_URL)
    t0 = time.monotonic()
    count = 0
    offset = 0
    batch_size = 1000
    batch = []
    pages_fetched = 0
    skipped_no_geom = 0
    skipped_parse_fail = 0
    async with httpx.AsyncClient(timeout=60.0) as client:
        while True:
            params = {
                "where": "1=1",
                "outFields": "*",
                "outSR": "4326",
                "returnGeometry": "true",
                "f": "geojson",
                "resultRecordCount": batch_size,
                "resultOffset": offset,
            }
            try:
                t_req = time.monotonic()
                response = await client.get(OHIO_KARST_URL, params=params)
                response.raise_for_status()
                data = response.json()
                pages_fetched += 1
                log.debug("ohio_karst_page_fetched", page=pages_fetched, offset=offset, status=response.status_code, content_length=len(response.content), elapsed_s=round(time.monotonic() - t_req, 2))
            except (httpx.HTTPError, Exception) as e:
                log.warning("ohio_karst_query_failed", error=str(e), offset=offset, pages_fetched=pages_fetched, exception=True)
                break
            features = data.get("features", [])
            if not features:
                log.debug("ohio_karst_no_more_features", offset=offset)
                break
            for feature in features:
                props = feature.get("properties", {})
                geom_data = feature.get("geometry")
                if not geom_data:
                    skipped_no_geom += 1
                    continue
                try:
                    geom = shape(geom_data)
                except Exception as e:
                    log.debug("geom_parse_failed", source="ohio_karst", error=str(e), exception=True)
                    skipped_parse_fail += 1
                    continue
                if geom.geom_type != "Point":
                    geom = geom.centroid
                raw_type = str(props.get("TYPE", "") or props.get("Feature_Type", "")).upper()
                if "CAVE" in raw_type:
                    ft = FeatureType.CAVE_ENTRANCE
                elif "SINK" in raw_type:
                    ft = FeatureType.SINKHOLE
                elif "SPRING" in raw_type:
                    ft = FeatureType.SPRING
                else:
                    ft = FeatureType.UNKNOWN
                site = GroundTruthSite(
                    name=str(props.get("NAME", "") or f"OH-Karst-{count}"),
                    feature_type=ft,
                    geometry=from_shape(Point(geom.x, geom.y), srid=4326),
                    source=GroundTruthSource.OHIO_EPA,
                    source_id=str(props.get("OBJECTID", "")),
                    metadata_={
                        "county": str(props.get("COUNTY", "")),
                        "raw_type": raw_type,
                    },
                )
                batch.append(site)
                count += 1
                if len(batch) >= 500:
                    session.add_all(batch)
                    await session.flush()
                    log.debug("ohio_karst_batch_flushed", batch_size=500, running_total=count)
                    batch.clear()
            offset += len(features)
            if len(features) < batch_size:
                break
    if batch:
        session.add_all(batch)
        await session.flush()
    await session.commit()
    elapsed = round(time.monotonic() - t0, 2)
    log.info("ohio_karst_load_complete", count=count, pages_fetched=pages_fetched, skipped_no_geom=skipped_no_geom, skipped_parse_fail=skipped_parse_fail, elapsed_s=elapsed)
    return count
