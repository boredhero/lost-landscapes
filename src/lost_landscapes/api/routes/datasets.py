"""Dataset management endpoints."""

import time

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lost_landscapes.api.deps import get_db
from lost_landscapes.api.schemas import DatasetOut
from lost_landscapes.db.models import Dataset
from lost_landscapes.utils.log_manager import log

router = APIRouter(tags=["datasets"])


@router.get("/datasets")
async def list_datasets(db: AsyncSession = Depends(get_db)):
    """List all ingested LiDAR datasets."""
    log.debug("list_datasets_requested")
    t0 = time.perf_counter()
    result = await db.execute(select(Dataset).order_by(Dataset.created_at.desc()))
    datasets = result.scalars().all()
    log.info("datasets_listed", count=len(datasets), elapsed_ms=round((time.perf_counter() - t0) * 1000, 1))
    return {
        "datasets": [
            DatasetOut(
                id=str(d.id),
                name=d.name,
                source=d.source.value if d.source else "unknown",
                state=d.state,
                tile_count=d.tile_count or 0,
                status=d.status.value if d.status else "unknown",
                created_at=d.created_at,
            )
            for d in datasets
        ]
    }
