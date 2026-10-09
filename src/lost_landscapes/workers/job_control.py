"""Serialized job transitions and cooperative cancellation checkpoints."""

from datetime import UTC, datetime
from uuid import UUID

from lost_landscapes.db.models import Job, JobStatus

ACTIVE = (JobStatus.PENDING, JobStatus.RUNNING)


class JobStopped(Exception):
    """A terminal or missing job must not perform more work."""


async def active_job(session, job_id):
    # Cancellation, status updates and result commits all take this same row lock.
    # This prevents a late worker commit from resurrecting a cancelled job.
    job = await session.get(Job, UUID(str(job_id)), with_for_update=True, populate_existing=True)
    if job is None or job.status not in ACTIVE:
        raise JobStopped(str(job_id))
    return job


async def transition(session, job_id, status, progress, message="", summary=None, stage=None):
    job = await active_job(session, job_id)
    state = JobStatus(status.lower())
    job.status = state
    job.progress = max(job.progress or 0, min(100, progress))
    if state == JobStatus.RUNNING and job.started_at is None:
        job.started_at = datetime.now(UTC)
    if state not in ACTIVE:
        job.completed_at = datetime.now(UTC)
    if summary is not None:
        job.result_summary = dict(summary)
    elif stage:
        job.result_summary = {**(job.result_summary or {}), "stage": stage}
    if state == JobStatus.FAILED:
        job.error_message = message
    await session.commit()
