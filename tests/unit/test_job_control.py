from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from lost_landscapes.api.routes import jobs
from lost_landscapes.api.schemas import JobCreate
from lost_landscapes.db.models import JobStatus, JobType
from lost_landscapes.workers import callbacks, tasks
from lost_landscapes.workers.job_control import JobStopped, active_job, transition


def job(status=JobStatus.PENDING):
    return SimpleNamespace(id=uuid4(), status=status, progress=0, started_at=None,
                           completed_at=None, result_summary=None, error_message=None,
                           celery_task_id=None, job_type=JobType.FULL_PIPELINE, created_at=None)


def session_for(record):
    return SimpleNamespace(get=AsyncMock(return_value=record), commit=AsyncMock())


@pytest.mark.parametrize("state", [JobStatus.CANCELLED, JobStatus.COMPLETED, JobStatus.FAILED])
async def test_terminal_jobs_never_resurrect(state):
    record = job(state)
    session = session_for(record)
    for next_state in ("RUNNING", "COMPLETED", "FAILED"):
        with pytest.raises(JobStopped):
            await transition(session, record.id, next_state, 100)
    assert record.status == state
    session.commit.assert_not_called()
    assert session.get.call_args.kwargs == {"with_for_update": True, "populate_existing": True}


async def test_progress_is_monotonic_and_records_start_completion():
    record = job()
    session = session_for(record)
    await transition(session, record.id, "RUNNING", 40, stage="analyzing")
    assert record.started_at is not None
    await transition(session, record.id, "RUNNING", 20, stage="finishing")
    assert record.progress == 40
    assert record.result_summary["stage"] == "finishing"
    await transition(session, record.id, "COMPLETED", 100, summary={"tiles_ok": 1})
    assert record.completed_at is not None
    assert record.status == JobStatus.COMPLETED


async def test_missing_job_stops():
    with pytest.raises(JobStopped):
        await active_job(session_for(None), uuid4())


async def test_cancel_is_idempotent_and_revokes_without_killing(monkeypatch):
    record = job(JobStatus.RUNNING)
    record.celery_task_id = "task-id"
    revoke = Mock()
    monkeypatch.setattr(tasks.app.control, "revoke", revoke)
    session = session_for(record)
    assert (await jobs.cancel_job(record.id, session))["status"] == "cancelled"
    assert record.completed_at is not None
    await jobs.cancel_job(record.id, session)
    revoke.assert_called_once_with("task-id", terminate=False)
    session.commit.assert_awaited_once()
    assert session.get.call_args.kwargs["with_for_update"] is True
    with pytest.raises(JobStopped):
        await transition(session, record.id, "COMPLETED", 100)


async def test_cancel_completed_conflicts():
    record = job(JobStatus.COMPLETED)
    with pytest.raises(HTTPException) as exc:
        await jobs.cancel_job(record.id, session_for(record))
    assert exc.value.status_code == 409


async def test_cancel_survives_broker_outage(monkeypatch):
    record = job()
    record.celery_task_id = "unavailable"
    monkeypatch.setattr(tasks.app.control, "revoke", Mock(side_effect=RuntimeError("offline")))
    await jobs.cancel_job(record.id, session_for(record))
    assert record.status == JobStatus.CANCELLED


def test_cancelled_queued_pipeline_never_discovers(monkeypatch):
    record = job(JobStatus.CANCELLED)
    @asynccontextmanager
    async def factory():
        yield session_for(record)
    monkeypatch.setattr(tasks, "_async_session", factory)
    discover = AsyncMock(side_effect=AssertionError("Cancelled work must not discover tiles"))
    monkeypatch.setattr("lost_landscapes.ingest.manager.discover_tiles_for_bbox", discover)
    result = tasks.run_full_pipeline.run(str(record.id), "sinkhole_survey", {"type": "Polygon"})
    assert result == {"status": "stopped"}
    discover.assert_not_called()


def test_cancel_during_discovery_stops_before_download(monkeypatch):
    record = job()
    record.config = {}
    @asynccontextmanager
    async def factory():
        yield session_for(record)
    async def discover(*args):
        record.status = JobStatus.CANCELLED
        return [], "usgs_3dep"
    monkeypatch.setattr(tasks, "_async_session", factory)
    monkeypatch.setattr("lost_landscapes.ingest.manager.discover_tiles_for_bbox", discover)
    result = tasks.run_full_pipeline.run(str(record.id), "sinkhole_survey", {"type": "Polygon", "coordinates": [[[-80, 40], [-79.99, 40], [-79.99, 40.01], [-80, 40]]]})
    assert result == {"status": "stopped"}
    assert record.status == JobStatus.CANCELLED


async def test_legacy_callback_respects_cancellation(monkeypatch):
    record = job(JobStatus.CANCELLED)
    session = session_for(record)
    @asynccontextmanager
    async def factory():
        yield session
    monkeypatch.setattr(callbacks, "_async_session", factory)
    await callbacks._update_progress(str(record.id), 100, "done")
    assert record.status == JobStatus.CANCELLED
    assert record.progress == 0
    session.commit.assert_not_called()


async def test_queue_failure_returns_failure_not_permanent_pending(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(jobs.settings, "enable_analysis", True)
    record = job()
    session = session_for(record)
    session.add = Mock()
    async def refresh(created):
        created.id = record.id
    session.refresh = AsyncMock(side_effect=refresh)
    monkeypatch.setattr(tasks.run_full_pipeline, "delay", Mock(side_effect=RuntimeError("offline")))
    body = JobCreate(bbox={"type": "Polygon", "coordinates": [[[-80, 40], [-79.99, 40], [-79.99, 40.01], [-80, 40]]]})
    with pytest.raises(HTTPException) as exc:
        await jobs.create_job(body, session)
    assert exc.value.status_code == 503
    created = session.add.call_args.args[0]
    assert created.status == JobStatus.FAILED


@pytest.mark.parametrize("config", ["../secret", "does_not_exist"])
async def test_reject_unknown_configuration(monkeypatch, config):
    monkeypatch.setattr(jobs.settings, "enable_analysis", True)
    body = JobCreate(pass_config=config, bbox={"type": "Polygon", "coordinates": [[[-80, 40], [-79.99, 40], [-79.99, 40.01], [-80, 40]]]})
    with pytest.raises(HTTPException) as exc:
        await jobs.create_job(body, session_for(None))
    assert exc.value.status_code == 422


def test_dem_scan_retains_source_before_raw_cleanup(tmp_path, monkeypatch):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    from lost_landscapes.processing import pipeline

    raw = tmp_path / "raw.tif"
    with rasterio.open(raw, "w", driver="GTiff", count=1, width=4, height=4,
                       dtype="float32", crs="EPSG:32617", transform=from_origin(500000, 4500000, 1, 1)) as src:
        src.write(np.ones((4, 4), dtype="float32"), 1)
    monkeypatch.setattr(pipeline, "fill_depressions", lambda *args: (None, 0))
    monkeypatch.setattr(pipeline, "compute_all_derivatives", lambda *args, **kwargs: {})
    result = pipeline.ProcessingPipeline(tmp_path / "processed", namespace="scan-a-").process_dem_file(raw)
    raw.unlink()
    assert result.dem_path.is_file()
    assert result.dem_path.parent.name == "scan-a-raw"
    with rasterio.open(result.dem_path) as src:
        assert src.read(1).sum() == 16
