"""Celery application factory."""

# Disable PROJ network BEFORE any pyproj/rasterio import — prevents grid-based
# NAD83→WGS84 pipelines that return inf in forked Celery workers.
# The simple geocentric transform (~4m accuracy) is more than sufficient for LiDAR.
import pyproj.network

pyproj.network.set_network_enabled(False)

from celery import Celery

from lost_landscapes.config import settings
from lost_landscapes.utils.log_manager import log

log.info("celery_app_initializing", broker=settings.redis_url.split("@")[-1] if "@" in settings.redis_url else settings.redis_url, proj_network="disabled")

app = Celery("lost_landscapes")
app.config_from_object(
    {
        "broker_url": settings.redis_url,
        "result_backend": settings.redis_url.replace("/0", "/1"),
        "task_serializer": "json",
        "result_serializer": "json",
        "accept_content": ["json"],
        "task_track_started": True,
        "task_acks_late": True,
        "worker_prefetch_multiplier": 1,
        "task_routes": {
            "lost_landscapes.workers.tasks.download_tile": {"queue": "ingest"},
            "lost_landscapes.workers.tasks.process_tile": {"queue": "process"},
            "lost_landscapes.workers.tasks.run_detection": {"queue": "detect"},
            "lost_landscapes.workers.tasks.run_ml_pass": {"queue": "gpu"},
        },
        "task_time_limit": 7200,
        "task_soft_time_limit": 6600,
    }
)

app.autodiscover_tasks(["lost_landscapes.workers"])

# Periodic tasks (Celery Beat)
app.conf.beat_schedule = {
    "storage-eviction": {
        "task": "lost_landscapes.workers.tasks.run_storage_eviction",
        "schedule": 86400.0,  # Daily
    },
}

log.info("celery_app_configured", queues=["ingest", "process", "detect", "gpu"], task_time_limit=7200, beat_tasks=list(app.conf.beat_schedule.keys()))
