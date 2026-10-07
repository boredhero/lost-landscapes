"""Unified ground truth loader — orchestrates all sub-loaders.

Each source is deleted before re-loading to ensure idempotency.
Re-running load_all_ground_truth always produces a clean dataset.
"""

import time

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from lost_landscapes.db.models import GroundTruthSite, GroundTruthSource
from lost_landscapes.ingest.ground_truth.ca_blm_aml import load_ca_blm_aml
from lost_landscapes.ingest.ground_truth.la_subsidence import load_la_subsidence
from lost_landscapes.ingest.ground_truth.ma_mines import load_ma_mines
from lost_landscapes.ingest.ground_truth.md_karst import load_md_karst
from lost_landscapes.ingest.ground_truth.nc_caves import load_nc_caves
from lost_landscapes.ingest.ground_truth.ohio_karst import load_ohio_karst
from lost_landscapes.ingest.ground_truth.pa_aml import load_pa_aml
from lost_landscapes.ingest.ground_truth.pasda_karst import load_pasda_karst
from lost_landscapes.ingest.ground_truth.usgs_national import load_usgs_national
from lost_landscapes.ingest.ground_truth.usgs_ny_karst import load_usgs_ny_karst
from lost_landscapes.utils.log_manager import log

# Maps orchestrator name → GroundTruthSource enum for pre-delete
_SOURCE_MAP = {
    "pasda_karst": GroundTruthSource.PASDA_KARST,
    "pa_aml": GroundTruthSource.PA_AML,
    "usgs_ny": GroundTruthSource.USGS_NY,
    "usgs_national": GroundTruthSource.USGS_NATIONAL,
    "ohio_epa": GroundTruthSource.OHIO_EPA,
    "nc_cave_survey": GroundTruthSource.NC_CAVE_SURVEY,
    "md_karst_survey": GroundTruthSource.MD_KARST_SURVEY,
    "ma_usgs_mines": GroundTruthSource.MA_USGS_MINES,
    "la_subsidence": GroundTruthSource.LA_SUBSIDENCE,
    "ca_blm_aml": GroundTruthSource.CA_BLM_AML,
}


async def load_all_ground_truth(session: AsyncSession, data_dir: str) -> dict[str, int]:
    """Load all ground truth datasets. Returns counts per source.
    Deletes existing records per source before re-loading for idempotency."""
    t0 = time.monotonic()
    results = {}
    loaders = [
        ("pasda_karst", load_pasda_karst),
        ("pa_aml", load_pa_aml),
        ("usgs_ny", load_usgs_ny_karst),
        ("usgs_national", load_usgs_national),
        ("ohio_epa", load_ohio_karst),
        ("nc_cave_survey", load_nc_caves),
        ("md_karst_survey", load_md_karst),
        ("ma_usgs_mines", load_ma_mines),
        ("la_subsidence", load_la_subsidence),
        ("ca_blm_aml", load_ca_blm_aml),
    ]
    log.info("ground_truth_load_all_start", data_dir=data_dir, loader_count=len(loaders))
    for name, loader_fn in loaders:
        try:
            t_loader = time.monotonic()
            source_enum = _SOURCE_MAP.get(name)
            if source_enum:
                result = await session.execute(delete(GroundTruthSite).where(GroundTruthSite.source == source_enum))
                deleted = result.rowcount
                if deleted:
                    log.info("ground_truth_pre_delete", source=name, deleted=deleted)
                await session.commit()
            count = await loader_fn(session, data_dir)
            elapsed_loader = round(time.monotonic() - t_loader, 3)
            results[name] = count
            log.info("ground_truth_loaded", source=name, count=count, elapsed_s=elapsed_loader)
        except Exception as e:
            log.error("ground_truth_error", source=name, error=str(e), exception=True)
            results[name] = 0
    total = sum(results.values())
    failed = [k for k, v in results.items() if v == 0]
    elapsed = round(time.monotonic() - t0, 3)
    log.info("ground_truth_load_all_done", total_records=total, sources_loaded=len(results), sources_failed=len(failed), failed_sources=failed, per_source=results, elapsed_s=elapsed)
    return results
