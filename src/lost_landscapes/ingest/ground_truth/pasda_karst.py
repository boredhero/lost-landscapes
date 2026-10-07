"""PASDA Karst Features loader — 111,000+ karst feature points across 14 PA counties.

Download from: https://www.pasda.psu.edu/uci/DataSummary.aspx?dataset=3073
Format: Shapefile with point geometries.
"""

import time
from pathlib import Path

import geopandas as gpd
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy.ext.asyncio import AsyncSession

from lost_landscapes.db.models import FeatureType, GroundTruthSite, GroundTruthSource
from lost_landscapes.utils.log_manager import log

# Mapping from PASDA feature type codes to our enum
PASDA_TYPE_MAP = {
    "SINKHOLE": FeatureType.SINKHOLE,
    "SURFACE DEPRESSION": FeatureType.DEPRESSION,
    "CAVE": FeatureType.CAVE_ENTRANCE,
    "CAVE ENTRANCE": FeatureType.CAVE_ENTRANCE,
    "SPRING": FeatureType.SPRING,
    "MINE": FeatureType.MINE_PORTAL,
    "SURFACE MINE": FeatureType.MINE_PORTAL,
    "COLLAPSE": FeatureType.COLLAPSE_PIT,
}


async def load_pasda_karst(session: AsyncSession, data_dir: str) -> int:
    """Load PASDA karst features shapefile into ground_truth_sites table.

    Args:
        session: async DB session
        data_dir: directory containing downloaded shapefiles

    Returns:
        Number of features loaded
    """
    shapefile_path = Path(data_dir) / "ground_truth" / "pasda_karst"
    log.info("pasda_karst_load_start", search_path=str(shapefile_path))
    # Look for .shp file in the directory
    shp_files = list(shapefile_path.glob("*.shp"))
    if not shp_files:
        log.warning("pasda_karst_not_found", path=str(shapefile_path))
        return 0
    shp_file = shp_files[0]
    log.info("pasda_karst_reading_shapefile", file=str(shp_file))
    t0 = time.monotonic()
    try:
        gdf = gpd.read_file(shp_file)
    except Exception as e:
        log.error("pasda_karst_shapefile_read_failed", file=str(shp_file), error=str(e), exception=True)
        return 0
    original_crs = str(gdf.crs) if gdf.crs else "none"
    # Reproject to WGS84 if needed
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        log.debug("pasda_karst_reprojecting", from_crs=original_crs, to_crs="EPSG:4326")
        gdf = gdf.to_crs(epsg=4326)
    log.info("pasda_karst_shapefile_loaded", record_count=len(gdf), crs=original_crs, elapsed_s=round(time.monotonic() - t0, 2))
    count = 0
    skipped_empty = 0
    unmapped_types = {}
    batch = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            skipped_empty += 1
            continue
        # Get centroid if not a point
        if geom.geom_type != "Point":
            geom = geom.centroid
        # Map feature type
        raw_type = str(row.get("FEAT_TYPE", "") or row.get("TYPE", "") or "").upper().strip()
        feature_type = PASDA_TYPE_MAP.get(raw_type, FeatureType.UNKNOWN)
        if feature_type == FeatureType.UNKNOWN and raw_type:
            unmapped_types[raw_type] = unmapped_types.get(raw_type, 0) + 1
        site = GroundTruthSite(
            name=str(row.get("NAME", "") or row.get("FEAT_NAME", "") or f"PASDA-{count}"),
            feature_type=feature_type,
            geometry=from_shape(Point(geom.x, geom.y), srid=4326),
            source=GroundTruthSource.PASDA_KARST,
            source_id=str(row.get("OBJECTID", "") or row.get("FID", "")),
            metadata_={
                "county": str(row.get("COUNTY", "")),
                "quad": str(row.get("QUAD_NAME", "")),
                "raw_type": raw_type,
            },
        )
        batch.append(site)
        count += 1
        if len(batch) >= 1000:
            session.add_all(batch)
            await session.flush()
            log.debug("pasda_karst_batch_flushed", batch_size=1000, running_total=count)
            batch.clear()
    if batch:
        session.add_all(batch)
        await session.flush()
    await session.commit()
    elapsed = round(time.monotonic() - t0, 2)
    if unmapped_types:
        log.warning("pasda_karst_unmapped_types", types=unmapped_types)
    log.info("pasda_karst_load_complete", count=count, skipped_empty=skipped_empty, elapsed_s=elapsed)
    return count
