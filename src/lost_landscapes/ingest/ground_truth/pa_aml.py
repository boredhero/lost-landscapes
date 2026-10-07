"""PA Abandoned Mine Land (AML) Inventory loader — 11,249 mine sites.

Download from: https://www.pasda.psu.edu/ (search "AML Inventory")
or PA DEP GIS: https://gis.dep.pa.gov/
Format: Shapefile with point/polygon geometries.
"""

import time
from pathlib import Path

import geopandas as gpd
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy.ext.asyncio import AsyncSession

from lost_landscapes.db.models import FeatureType, GroundTruthSite, GroundTruthSource
from lost_landscapes.utils.log_manager import log


async def load_pa_aml(session: AsyncSession, data_dir: str) -> int:
    """Load PA AML inventory into ground_truth_sites."""
    shapefile_path = Path(data_dir) / "ground_truth" / "pa_aml"
    log.info("pa_aml_load_start", search_path=str(shapefile_path))
    shp_files = list(shapefile_path.glob("*.shp"))
    if not shp_files:
        log.warning("pa_aml_not_found", path=str(shapefile_path))
        return 0
    shp_file = shp_files[0]
    log.info("pa_aml_reading_shapefile", file=str(shp_file))
    t0 = time.monotonic()
    try:
        gdf = gpd.read_file(shp_file)
    except Exception as e:
        log.error("pa_aml_shapefile_read_failed", file=str(shp_file), error=str(e), exception=True)
        return 0
    original_crs = str(gdf.crs) if gdf.crs else "none"
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        log.debug("pa_aml_reprojecting", from_crs=original_crs, to_crs="EPSG:4326")
        gdf = gdf.to_crs(epsg=4326)
    log.info("pa_aml_shapefile_loaded", record_count=len(gdf), crs=original_crs, elapsed_s=round(time.monotonic() - t0, 2))
    count = 0
    skipped_empty = 0
    batch = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            skipped_empty += 1
            continue
        if geom.geom_type != "Point":
            geom = geom.centroid
        site = GroundTruthSite(
            name=str(row.get("MINE_NAME", "") or row.get("SITE_NAME", "") or f"AML-{count}"),
            feature_type=FeatureType.MINE_PORTAL,
            geometry=from_shape(Point(geom.x, geom.y), srid=4326),
            source=GroundTruthSource.PA_AML,
            source_id=str(row.get("AML_ID", "") or row.get("OBJECTID", "")),
            metadata_={
                "county": str(row.get("COUNTY", "")),
                "mine_type": str(row.get("MINE_TYPE", "")),
                "status": str(row.get("STATUS", "")),
                "hazard_class": str(row.get("HAZARD", "")),
            },
        )
        batch.append(site)
        count += 1
        if len(batch) >= 1000:
            session.add_all(batch)
            await session.flush()
            log.debug("pa_aml_batch_flushed", batch_size=1000, running_total=count)
            batch.clear()
    if batch:
        session.add_all(batch)
        await session.flush()
    await session.commit()
    elapsed = round(time.monotonic() - t0, 2)
    log.info("pa_aml_load_complete", count=count, skipped_empty=skipped_empty, elapsed_s=elapsed)
    return count
