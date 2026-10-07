"""Centralized logging for Lost Landscapes — date-based files + console output.

Singleton logger that writes structured key=value logs to:
  /data/lost-landscapes/logs/YYYY-MM-DD.log (persistent across restarts)
  + stderr (captured by Docker)

Every log line includes a correlation ID when available:
  - API requests: 8-char hex hash set by RequestLoggingMiddleware
  - Celery tasks: Celery task ID (truncated to 8 chars)
  - CLI: "cli" literal

Usage:
  from lost_landscapes.utils.log_manager import log
  log.info("tile_processed", tile_id="ABC123", elapsed_s=1.5)
  log.error("pipeline_failed", error=str(e), tile_id="ABC123")
"""

import contextvars
import hashlib
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

EASTERN = timezone(timedelta(hours=-5))
LOG_DIR = Path(os.environ.get("LOSTLANDSCAPES_LOG_DIR", str(Path(os.environ.get("DATA_DIR", "data")) / "logs")))
_lock = threading.Lock()
_instance = None

# ── Correlation ID propagation ──────────────────────────────────────────
# Set once per request/task, automatically included in every log line.
# Works across async awaits (contextvars) and in sync Celery workers.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")


def generate_request_id() -> str:
    """Generate an 8-char hex hash for request correlation."""
    raw = f"{time.time_ns()}{threading.current_thread().ident}"
    return hashlib.sha256(raw.encode()).hexdigest()[:8]


def set_request_id(rid: str) -> contextvars.Token:
    """Set the correlation ID for the current context. Returns a reset token."""
    return request_id_var.set(rid)


def get_request_id() -> str:
    """Get the current correlation ID (empty string if none set)."""
    return request_id_var.get()


class _EasternFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=EASTERN)
        return dt.strftime("%Y-%m-%d %H:%M:%S %Z")


class _DateFileHandler(logging.Handler):
    """Writes to LOG_DIR/YYYY-MM-DD.log, rotating at midnight Eastern."""
    def __init__(self, log_dir: Path):
        super().__init__()
        self._log_dir = log_dir
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._current_date: str | None = None
        self._file = None
        self._file_lock = threading.Lock()

    def _today(self) -> str:
        return datetime.now(tz=EASTERN).strftime("%Y-%m-%d")

    def _ensure_file(self):
        today = self._today()
        if today != self._current_date or self._file is None:
            if self._file is not None:
                try:
                    self._file.close()
                except Exception:
                    pass
            path = self._log_dir / f"{today}.log"
            self._file = open(path, "a", encoding="utf-8")
            self._current_date = today

    def emit(self, record):
        try:
            msg = self.format(record)
            with self._file_lock:
                self._ensure_file()
                self._file.write(msg + "\n")
                self._file.flush()
        except Exception:
            self.handleError(record)

    def close(self):
        with self._file_lock:
            if self._file is not None:
                try:
                    self._file.close()
                except Exception:
                    pass
        super().close()


class LogManager:
    """Structured logger with date-based file output, console output, and correlation IDs."""
    def __init__(self):
        self._process_type = _detect_process_type()
        self._logger = logging.getLogger("lostlandscapes")
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False
        if self._logger.handlers:
            return
        fmt = _EasternFormatter("%(asctime)s [%(levelname)s] %(message)s")
        console = logging.StreamHandler(sys.stderr)
        console.setLevel(logging.INFO)
        console.setFormatter(fmt)
        self._logger.addHandler(console)
        try:
            file_handler = _DateFileHandler(LOG_DIR)
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(fmt)
            self._logger.addHandler(file_handler)
        except Exception as e:
            console.stream.write(f"[log_manager] File handler failed: {e}\n")

    def _format_msg(self, event: str, **kwargs) -> str:
        rid = request_id_var.get()
        parts = [f"proc={self._process_type}"]
        if rid:
            parts.append(f"rid={rid}")
        parts.append(f"event={event}")
        for k, v in kwargs.items():
            if isinstance(v, float):
                v = round(v, 3)
            parts.append(f"{k}={v}")
        return " | ".join(parts)

    def debug(self, event: str, **kwargs):
        self._logger.debug(self._format_msg(event, **kwargs))

    def info(self, event: str, **kwargs):
        self._logger.info(self._format_msg(event, **kwargs))

    def warning(self, event: str, **kwargs):
        self._logger.warning(self._format_msg(event, **kwargs))

    def error(self, event: str, **kwargs):
        exc = kwargs.pop("exception", None)
        self._logger.error(self._format_msg(event, **kwargs), exc_info=exc)

    def critical(self, event: str, **kwargs):
        exc = kwargs.pop("exception", None)
        self._logger.critical(self._format_msg(event, **kwargs), exc_info=exc)


def _detect_process_type() -> str:
    """Detect whether we're running as api, celery-worker, or cli."""
    argv = " ".join(sys.argv)
    if "celery" in argv and "worker" in argv:
        return "worker"
    if "uvicorn" in argv or "gunicorn" in argv:
        return "api"
    return "cli"


def get_log() -> LogManager:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = LogManager()
    return _instance


log = get_log()
