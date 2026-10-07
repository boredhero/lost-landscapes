"""USGS NY Karst Closed Depression Inventory — 5,023 features statewide.

Source: USGS Scientific Investigations Report 2020-5030
Download: https://www.sciencebase.gov/catalog/item/562a313ae4b011227bf1fe23
Format: Geodatabase or shapefile.
"""

import time
from pathlib import Path

import geopandas as gpd
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy.ext.asyncio import AsyncSession

from lost_landscapes.db.models import FeatureType, GroundTruthSite, GroundTruthSource
from lost_landscapes.utils.log_manager import log


async def load_usgs_ny_karst(session: AsyncSession, data_dir: str) -> int:
    """Load USGS NY closed depression inventory."""
    base_path = Path(data_dir) / "ground_truth" / "usgs_ny_karst"
    log.info("usgs_ny_karst_load_start", search_path=str(base_path))
    # Try geodatabase first, then shapefile
    gdb_files = list(base_path.glob("*.gdb"))
    shp_files = list(base_path.glob("*.shp"))
    t0 = time.monotonic()
    if gdb_files:
        source_file = str(gdb_files[0])
        log.info("usgs_ny_karst_reading_geodatabase", file=source_file)
        try:
            gdf = gpd.read_file(gdb_files[0])
        except Exception as e:
            log.error("usgs_ny_karst_gdb_read_failed", file=source_file, error=str(e), exception=True)
            return 0
    elif shp_files:
        source_file = str(shp_files[0])
        log.info("usgs_ny_karst_reading_shapefile", file=source_file)
        try:
            gdf = gpd.read_file(shp_files[0])
        except Exception as e:
            log.error("usgs_ny_karst_shapefile_read_failed", file=source_file, error=str(e), exception=True)
            return 0
    else:
        log.warning("usgs_ny_not_found", path=str(base_path))
        return 0
    original_crs = str(gdf.crs) if gdf.crs else "none"
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        log.debug("usgs_ny_karst_reprojecting", from_crs=original_crs, to_crs="EPSG:4326")
        gdf = gdf.to_crs(epsg=4326)
    log.info("usgs_ny_karst_file_loaded", record_count=len(gdf), source_file=source_file, crs=original_crs, elapsed_s=round(time.monotonic() - t0, 2))
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
            name=str(row.get("NAME", "") or f"NY-Depression-{count}"),
            feature_type=FeatureType.DEPRESSION,
            geometry=from_shape(Point(geom.x, geom.y), srid=4326),
            source=GroundTruthSource.USGS_NY,
            source_id=str(row.get("OBJECTID", "") or row.get("FID", "")),
            metadata_={
                "source_method": str(row.get("SOURCE", "")),
                "county": str(row.get("COUNTY", "")),
                "geology": str(row.get("GEOLOGY", "")),
            },
        )
        batch.append(site)
        count += 1
        if len(batch) >= 1000:
            session.add_all(batch)
            await session.flush()
            log.debug("usgs_ny_karst_batch_flushed", batch_size=1000, running_total=count)
            batch.clear()
    if batch:
        session.add_all(batch)
        await session.flush()
    await session.commit()
    elapsed = round(time.monotonic() - t0, 2)
    log.info("usgs_ny_karst_load_complete", count=count, skipped_empty=skipped_empty, elapsed_s=elapsed)
    return count
