"""Louisiana subsidence and salt dome collapse loader.

Source: USGS MRDS for mineral/salt sites + known salt dome monitoring locations.
Louisiana's primary hazard is salt dome collapse (evaporite dissolution),
not limestone karst.
"""

import time

import httpx
from geoalchemy2.shape import from_shape
from shapely.geometry import Point, shape
from sqlalchemy.ext.asyncio import AsyncSession

from lost_landscapes.db.models import FeatureType, GroundTruthSite, GroundTruthSource
from lost_landscapes.utils.log_manager import log

MRDS_URL = "https://mrdata.usgs.gov/mrds/wfs"

# Known salt dome collapse / subsidence sites with precise coordinates
KNOWN_LA_SITES = [
    {
        "name": "Bayou Corne Sinkhole",
        "lat": 30.0008,
        "lon": -91.1117,
        "type": FeatureType.SALT_DOME_COLLAPSE,
        "notes": "37-acre active salt dome collapse, Napoleonville Dome",
    },
    {
        "name": "Lake Peigneur",
        "lat": 30.0006,
        "lon": -91.9833,
        "type": FeatureType.SALT_DOME_COLLAPSE,
        "notes": "1980 drilling collapse into Jefferson Island salt mine",
    },
    {
        "name": "Grand Bayou Subsidence",
        "lat": 29.4500,
        "lon": -89.9500,
        "type": FeatureType.SALT_DOME_COLLAPSE,
        "notes": "Coastal subsidence area, Plaquemines Parish",
    },
]


async def load_la_subsidence(session: AsyncSession, data_dir: str) -> int:
    """Load Louisiana salt dome and subsidence features."""
    t0 = time.monotonic()
    log.info("la_subsidence_load_start", data_dir=data_dir, known_sites=len(KNOWN_LA_SITES))
    count = 0
    batch = []
    skipped_no_geom = 0
    skipped_parse_fail = 0
    type_counts = {"salt_dome_collapse": 0, "mine_portal": 0}
    lats = []
    lons = []
    # First: insert known salt dome collapse sites
    for site_data in KNOWN_LA_SITES:
        site = GroundTruthSite(
            name=site_data["name"],
            feature_type=site_data["type"],
            geometry=from_shape(Point(site_data["lon"], site_data["lat"]), srid=4326),
            source=GroundTruthSource.LA_SUBSIDENCE,
            source_id=f"la_known_{site_data['name'].lower().replace(' ', '_')}",
            metadata_={"notes": site_data["notes"]},
        )
        batch.append(site)
        lats.append(site_data["lat"])
        lons.append(site_data["lon"])
        type_counts["salt_dome_collapse"] += 1
        count += 1
    log.info("la_known_sites_queued", count=count)
    # Second: query USGS MRDS for Louisiana mineral resources (salt, sulfur)
    params = {
        "service": "WFS",
        "version": "1.1.0",
        "request": "GetFeature",
        "typeName": "mrds",
        "outputFormat": "application/json",
        "CQL_FILTER": "state_name='Louisiana'",
        "maxFeatures": "5000",
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            t_req = time.monotonic()
            response = await client.get(MRDS_URL, params=params)
            response.raise_for_status()
            data = response.json()
            elapsed_req = round(time.monotonic() - t_req, 3)
            log.info("la_mrds_query_ok", url=MRDS_URL, status=response.status_code, response_bytes=len(response.content), elapsed_s=elapsed_req)
        except (httpx.HTTPError, Exception) as e:
            log.warning("la_mrds_query_failed", url=MRDS_URL, error=str(e), exception=True)
            # Still commit the known sites
            if batch:
                session.add_all(batch)
                await session.flush()
            await session.commit()
            log.info("la_subsidence_load_done", count=count, mrds_fetched=False, elapsed_s=round(time.monotonic() - t0, 3))
            return count
        features = data.get("features", [])
        log.info("la_mrds_results", count=len(features))
        for feature in features:
            props = feature.get("properties", {})
            geom_data = feature.get("geometry")
            if not geom_data:
                skipped_no_geom += 1
                continue
            try:
                geom = shape(geom_data)
            except Exception as e:
                log.debug("geom_parse_failed", source="la_subsidence", error=str(e), exception=True)
                skipped_parse_fail += 1
                continue
            if geom.geom_type != "Point":
                log.debug("la_subsidence_centroid_fallback", original_type=geom.geom_type)
                geom = geom.centroid
            commodity = str(props.get("commod1", "") or "").upper()
            if "SALT" in commodity or "BRINE" in commodity:
                ft = FeatureType.SALT_DOME_COLLAPSE
                type_counts["salt_dome_collapse"] += 1
            elif "SULFUR" in commodity:
                ft = FeatureType.SALT_DOME_COLLAPSE
                type_counts["salt_dome_collapse"] += 1
            else:
                ft = FeatureType.MINE_PORTAL
                type_counts["mine_portal"] += 1
            site = GroundTruthSite(
                name=str(props.get("site_name", "") or f"LA-{count}"),
                feature_type=ft,
                geometry=from_shape(Point(geom.x, geom.y), srid=4326),
                source=GroundTruthSource.LA_SUBSIDENCE,
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
                log.debug("la_subsidence_batch_flushed", batch_size=500, total_so_far=count)
                batch.clear()
    if batch:
        session.add_all(batch)
        await session.flush()
        log.debug("la_subsidence_final_batch_flushed", batch_size=len(batch))
    await session.commit()
    elapsed = round(time.monotonic() - t0, 3)
    extent = {"lat_min": round(min(lats), 4), "lat_max": round(max(lats), 4), "lon_min": round(min(lons), 4), "lon_max": round(max(lons), 4)} if lats else {}
    log.info("la_subsidence_load_done", count=count, type_counts=type_counts, skipped_no_geom=skipped_no_geom, skipped_parse_fail=skipped_parse_fail, extent=extent, elapsed_s=elapsed)
    return count
