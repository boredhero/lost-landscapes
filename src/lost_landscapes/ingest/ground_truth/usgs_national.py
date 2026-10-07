"""USGS National Karst Map loader — karst areas across entire US.

Source: USGS Open-File Report 2014-1156
Download: https://pubs.usgs.gov/of/2014/1156/
Format: Shapefile (269MB, polygon geometries for karst-prone areas).

We filter to target states and extract centroids.
"""

import time
from pathlib import Path

import geopandas as gpd
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy.ext.asyncio import AsyncSession

from lost_landscapes.db.models import FeatureType, GroundTruthSite, GroundTruthSource
from lost_landscapes.utils.log_manager import log

TARGET_STATES = {
    "PA", "WV", "OH", "NY", "NC", "MD", "MA", "LA", "CA",
    "Pennsylvania", "West Virginia", "Ohio", "New York",
    "North Carolina", "Maryland", "Massachusetts", "Louisiana", "California",
}


async def load_usgs_national(session: AsyncSession, data_dir: str) -> int:
    """Load USGS national karst map, filtered to target states."""
    base_path = Path(data_dir) / "ground_truth" / "usgs_national"
    log.info("usgs_national_load_start", search_path=str(base_path))
    shp_files = list(base_path.glob("*.shp"))
    if not shp_files:
        log.warning("usgs_national_not_found", path=str(base_path))
        return 0
    shp_file = shp_files[0]
    log.info("usgs_national_reading_shapefile", file=str(shp_file))
    t0 = time.monotonic()
    try:
        gdf = gpd.read_file(shp_file)
    except Exception as e:
        log.error("usgs_national_shapefile_read_failed", file=str(shp_file), error=str(e), exception=True)
        return 0
    original_crs = str(gdf.crs) if gdf.crs else "none"
    total_records = len(gdf)
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        log.debug("usgs_national_reprojecting", from_crs=original_crs, to_crs="EPSG:4326")
        gdf = gdf.to_crs(epsg=4326)
    log.info("usgs_national_shapefile_loaded", record_count=total_records, crs=original_crs, elapsed_s=round(time.monotonic() - t0, 2))
    # Filter to target states if state column exists
    state_col = None
    for col in ("STATE", "State", "state", "STUSPS", "NAME"):
        if col in gdf.columns:
            state_col = col
            break
    if state_col:
        pre_filter = len(gdf)
        gdf = gdf[gdf[state_col].isin(TARGET_STATES)]
        log.info("usgs_national_state_filter", column=state_col, before=pre_filter, after=len(gdf), target_states=sorted(TARGET_STATES))
    else:
        log.warning("usgs_national_no_state_column", columns=list(gdf.columns)[:20])
    count = 0
    skipped_empty = 0
    batch = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            skipped_empty += 1
            continue
        centroid = geom.centroid
        site = GroundTruthSite(
            name=str(row.get("UNIT_NAME", "") or row.get("MAP_UNIT", "") or f"USGS-Karst-{count}"),
            feature_type=FeatureType.UNKNOWN,  # karst area, not specific feature
            geometry=from_shape(Point(centroid.x, centroid.y), srid=4326),
            source=GroundTruthSource.USGS_NATIONAL,
            source_id=str(row.get("OBJECTID", "") or row.get("FID", "")),
            metadata_={
                "rock_type": str(row.get("ROCK_TYPE", "")),
                "state": str(row.get(state_col, "")) if state_col else "",
                "area_km2": float(geom.area) if geom.area else 0,
            },
        )
        batch.append(site)
        count += 1
        if len(batch) >= 500:
            session.add_all(batch)
            await session.flush()
            log.debug("usgs_national_batch_flushed", batch_size=500, running_total=count)
            batch.clear()
    if batch:
        session.add_all(batch)
        await session.flush()
    await session.commit()
    elapsed = round(time.monotonic() - t0, 2)
    log.info("usgs_national_load_complete", count=count, skipped_empty=skipped_empty, total_in_shapefile=total_records, elapsed_s=elapsed)
    return count
