"""WebSocket endpoint for real-time job progress updates."""

import asyncio
import json
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from lost_landscapes.db.engine import async_session_factory
from lost_landscapes.db.models import Job
from lost_landscapes.utils.log_manager import log

router = APIRouter()


class ConnectionManager:
    """Manages active WebSocket connections for job progress."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        log.info("ws_client_connected", total_connections=len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            log.info("ws_client_disconnected", total_connections=len(self.active_connections))

    async def broadcast(self, message: dict):
        disconnected = []
        for conn in self.active_connections:
            try:
                await conn.send_json(message)
            except Exception as e:
                log.warning("ws_broadcast_send_failed", error=str(e))
                disconnected.append(conn)
        if disconnected:
            log.info("ws_broadcast_cleanup", dropped=len(disconnected))
        for conn in disconnected:
            self.disconnect(conn)


manager = ConnectionManager()


@router.websocket("/ws/jobs")
async def job_progress_ws(websocket: WebSocket):
    """WebSocket for real-time job progress. Polls DB every 2 seconds."""
    await manager.connect(websocket)
    try:
        while True:
            # Poll for active jobs and send updates
            t0 = time.perf_counter()
            async with async_session_factory() as session:
                # Include recently completed/failed jobs so clients catch the transition
                from datetime import UTC, datetime, timedelta
                cutoff = datetime.now(UTC) - timedelta(minutes=5)
                stmt = select(Job).where(
                    (Job.status.in_(["PENDING", "RUNNING"]))
                    | ((Job.status.in_(["COMPLETED", "FAILED"])) & (Job.completed_at >= cutoff))
                ).order_by(Job.created_at.desc()).limit(50)
                result = await session.execute(stmt)
                jobs = result.scalars().all()
                updates = []
                for j in jobs:
                    summary = j.result_summary or {}
                    updates.append({
                        "id": str(j.id),
                        "status": j.status.value if j.status else "unknown",
                        "progress": j.progress or 0.0,
                        "job_type": j.job_type.value if j.job_type else "unknown",
                        "stage": summary.get("stage"),
                        "source": summary.get("source"),
                        "total_detections": summary.get("total_detections"),
                        "download_mb": summary.get("download_mb"),
                        "tiles_done": summary.get("tiles_done"),
                        "tiles_total": summary.get("tiles_total"),
                        "detections_so_far": summary.get("detections_so_far"),
                    })
                if updates:
                    log.debug("ws_job_updates_sent", job_count=len(updates), elapsed_ms=round((time.perf_counter() - t0) * 1000, 1))
                    await websocket.send_json({"type": "job_updates", "jobs": updates})
            # Also listen for client messages (e.g., subscribe to specific job)
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
                # Client can send {"subscribe": "job_id"} to filter
                msg = json.loads(data)
                log.debug("ws_client_message", message_keys=list(msg.keys()))
                if "ping" in msg:
                    await websocket.send_json({"type": "pong"})
            except TimeoutError:
                pass  # normal — poll loop continues
            except json.JSONDecodeError as e:
                log.warning("ws_invalid_json", error=str(e))
    except WebSocketDisconnect:
        log.info("ws_disconnect_clean")
        manager.disconnect(websocket)
    except Exception as e:
        log.error("ws_connection_error", error=str(e), exception=True)
        manager.disconnect(websocket)
