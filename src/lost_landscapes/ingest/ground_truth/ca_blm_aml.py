"""California abandoned mines and lava tube features loader.

Sources:
- USGS MRDS: 22,000+ mine records for California
- NPS Lava Beds National Monument: 700+ lava tubes (via known sites)
"""

import time

import httpx
from geoalchemy2.shape import from_shape
from shapely.geometry import Point, shape
from sqlalchemy.ext.asyncio import AsyncSession

from lost_landscapes.db.models import FeatureType, GroundTruthSite, GroundTruthSource
from lost_landscapes.utils.log_manager import log

MRDS_URL = "https://mrdata.usgs.gov/mrds/wfs"

# Known CA cave/lava tube sites with precise coordinates
KNOWN_CA_SITES = [
    {
        "name": "Lava Beds NM - Valentine Cave",
        "lat": 41.7147,
        "lon": -121.5083,
        "type": FeatureType.LAVA_TUBE,
        "notes": "Lava Beds National Monument, 700+ lava tubes",
    },
    {
        "name": "Lava Beds NM - Mushpot Cave",
        "lat": 41.7139,
        "lon": -121.5103,
        "type": FeatureType.LAVA_TUBE,
        "notes": "Visitor center cave, Cave Loop area",
    },
    {
        "name": "Crystal Cave Sequoia",
        "lat": 36.5861,
        "lon": -118.8306,
        "type": FeatureType.CAVE_ENTRANCE,
        "notes": "Marble cave in Sequoia National Park, 200+ caves in park",
    },
    {
        "name": "Moaning Cavern",
        "lat": 38.0680,
        "lon": -120.4660,
        "type": FeatureType.CAVE_ENTRANCE,
        "notes": "Largest public cavern chamber in CA, Calaveras County",
    },
    {
        "name": "Lake Shasta Caverns",
        "lat": 40.7567,
        "lon": -122.3281,
        "type": FeatureType.CAVE_ENTRANCE,
        "notes": "Limestone cave, Shasta County",
    },
    {
        "name": "Boyden Cavern",
        "lat": 36.7750,
        "lon": -118.5694,
        "type": FeatureType.CAVE_ENTRANCE,
        "notes": "Marble cave, Kings Canyon, Sierra Nevada",
    },
    {
        "name": "Subway Cave",
        "lat": 40.6839,
        "lon": -121.4211,
        "type": FeatureType.LAVA_TUBE,
        "notes": "Hat Creek lava tube, Lassen National Forest",
    },
]


async def load_ca_blm_aml(session: AsyncSession, data_dir: str) -> int:
    """Load California mine and cave features."""
    t0 = time.monotonic()
    log.info("ca_blm_aml_load_start", data_dir=data_dir, known_sites=len(KNOWN_CA_SITES))
    count = 0
    batch = []
    skipped_no_geom = 0
    skipped_parse_fail = 0
    lats = []
    lons = []
    # First: insert known cave/lava tube sites
    for site_data in KNOWN_CA_SITES:
        site = GroundTruthSite(
            name=site_data["name"],
            feature_type=site_data["type"],
            geometry=from_shape(Point(site_data["lon"], site_data["lat"]), srid=4326),
            source=GroundTruthSource.CA_BLM_AML,
            source_id=f"ca_known_{site_data['name'].lower().replace(' ', '_').replace('-', '_')}",
            metadata_={"notes": site_data["notes"]},
        )
        batch.append(site)
        lats.append(site_data["lat"])
        lons.append(site_data["lon"])
        count += 1
    log.info("ca_known_sites_queued", count=count)
    # Second: query USGS MRDS for California mines
    params = {
        "service": "WFS",
        "version": "1.1.0",
        "request": "GetFeature",
        "typeName": "mrds",
        "outputFormat": "application/json",
        "CQL_FILTER": "state_name='California'",
        "maxFeatures": "10000",
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            t_req = time.monotonic()
            response = await client.get(MRDS_URL, params=params)
            response.raise_for_status()
            data = response.json()
            elapsed_req = round(time.monotonic() - t_req, 3)
            log.info("ca_mrds_query_ok", url=MRDS_URL, status=response.status_code, response_bytes=len(response.content), elapsed_s=elapsed_req)
        except (httpx.HTTPError, Exception) as e:
            log.warning("ca_mrds_query_failed", url=MRDS_URL, error=str(e), exception=True)
            if batch:
                session.add_all(batch)
                await session.flush()
            await session.commit()
            log.info("ca_blm_aml_load_done", count=count, mrds_fetched=False, elapsed_s=round(time.monotonic() - t0, 3))
            return count
        features = data.get("features", [])
        log.info("ca_mrds_results", count=len(features))
        for feature in features:
            props = feature.get("properties", {})
            geom_data = feature.get("geometry")
            if not geom_data:
                skipped_no_geom += 1
                continue
            try:
                geom = shape(geom_data)
            except Exception as e:
                log.debug("geom_parse_failed", source="ca_blm_aml", error=str(e), exception=True)
                skipped_parse_fail += 1
                continue
            if geom.geom_type != "Point":
                log.debug("ca_blm_aml_centroid_fallback", original_type=geom.geom_type)
                geom = geom.centroid
            commodity = str(props.get("commod1", "") or "").upper()
            if "GOLD" in commodity or "AU" in commodity:
                ft = FeatureType.MINE_PORTAL
            elif "SILVER" in commodity or "AG" in commodity:
                ft = FeatureType.MINE_PORTAL
            elif "COPPER" in commodity:
                ft = FeatureType.MINE_PORTAL
            else:
                ft = FeatureType.MINE_PORTAL
            site = GroundTruthSite(
                name=str(props.get("site_name", "") or f"CA-{count}"),
                feature_type=ft,
                geometry=from_shape(Point(geom.x, geom.y), srid=4326),
                source=GroundTruthSource.CA_BLM_AML,
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
                log.debug("ca_blm_aml_batch_flushed", batch_size=500, total_so_far=count)
                batch.clear()
    if batch:
        session.add_all(batch)
        await session.flush()
        log.debug("ca_blm_aml_final_batch_flushed", batch_size=len(batch))
    await session.commit()
    elapsed = round(time.monotonic() - t0, 3)
    extent = {"lat_min": round(min(lats), 4), "lat_max": round(max(lats), 4), "lon_min": round(min(lons), 4), "lon_max": round(max(lons), 4)} if lats else {}
    log.info("ca_blm_aml_load_done", count=count, skipped_no_geom=skipped_no_geom, skipped_parse_fail=skipped_parse_fail, extent=extent, elapsed_s=elapsed)
    return count
