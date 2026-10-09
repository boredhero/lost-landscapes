"""Progress reporting callbacks for Celery tasks."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID

from lost_landscapes.config import settings
from lost_landscapes.db.models import Job, JobStatus
from lost_landscapes.utils.log_manager import log


@asynccontextmanager
async def _async_session():
    """One-shot async session with a fresh engine — same pattern as tasks.py.
    Required because each asyncio.run() creates a new event loop, and asyncpg
    connections are bound to the loop they were created on."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    engine = create_async_engine(settings.database_url, echo=False, pool_size=1)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


async def _update_progress(job_id: str, percent: float, message: str) -> None:
    """Update job progress in the database."""
    async with _async_session() as session:
        job = await session.get(Job, UUID(job_id), with_for_update=True, populate_existing=True)
        if job and job.status in (JobStatus.PENDING, JobStatus.RUNNING):
            job.progress = percent
            log.debug("job_progress_updated", job_id=job_id[:8], percent=round(percent, 1), message=message)
            if percent >= 100:
                job.status = JobStatus.COMPLETED
                job.completed_at = datetime.now(UTC)
                log.info("job_marked_completed", job_id=job_id[:8])
            await session.commit()
        else:
            log.warning("job_progress_update_job_not_found", job_id=job_id[:8], percent=percent)


def update_job_progress(job_id: str, percent: float, message: str = "") -> None:
    """Update job progress — sync wrapper for use in Celery tasks.
    Uses asyncio.run() directly since Celery prefork workers are synchronous."""
    try:
        asyncio.run(_update_progress(job_id, percent, message))
    except Exception as e:
        log.warning("job_progress_update_failed", job_id=job_id[:8], percent=round(percent, 1), error=str(e))
