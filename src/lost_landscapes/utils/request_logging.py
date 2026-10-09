"""Request lifecycle timing, including streamed bodies and executor queue waits."""

import asyncio
import time
from contextvars import copy_context

from starlette.datastructures import MutableHeaders

from lost_landscapes.utils.log_manager import (
    generate_request_id,
    log,
    request_id_var,
    set_request_id,
)


class RequestLoggingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] == "/api/health":
            return await self.app(scope, receive, send)
        rid = generate_request_id()
        token = set_request_id(rid)
        started = time.perf_counter()
        fields = {"method": scope["method"], "path": scope["path"]}
        status, size, headers_ms, complete = 500, 0, None, False
        log.info("request_in", **fields)

        async def timed_send(message):
            nonlocal status, size, headers_ms, complete
            if message["type"] == "http.response.start":
                status = message["status"]
                headers_ms = round((time.perf_counter() - started) * 1000, 1)
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = rid
                headers.append("Server-Timing", f"app;dur={headers_ms}")
            await send(message)
            if message["type"] == "http.response.body":
                size += len(message.get("body", b""))
                if not message.get("more_body", False):
                    complete = True
                    elapsed = round((time.perf_counter() - started) * 1000, 1)
                    route = scope.get("route")
                    log.info("request_out", **fields, route=getattr(route, "path", scope["path"]),
                             status=status, headers_ms=headers_ms, elapsed_ms=elapsed,
                             response_bytes=size, slow=elapsed >= 1000)

        try:
            await self.app(scope, receive, timed_send)
        except BaseException as exc:
            log.error("request_cancelled" if isinstance(exc, asyncio.CancelledError) else "request_failed",
                      **fields, status=status, response_complete=complete, error_type=type(exc).__name__,
                      elapsed_ms=round((time.perf_counter() - started) * 1000, 1))
            raise
        finally:
            if not complete:
                log.warning("request_incomplete", **fields, status=status, response_bytes=size,
                            elapsed_ms=round((time.perf_counter() - started) * 1000, 1))
            request_id_var.reset(token)


async def timed_executor(pool, function, *args):
    """Keep request correlation in worker threads; separate queue and execution time."""
    queued = time.perf_counter()
    context = copy_context()

    def run():
        started = time.perf_counter()
        outcome = "ok"
        try:
            return function(*args)
        except BaseException:
            outcome = "error"
            raise
        finally:
            log.info("request_work", operation=function.__name__, outcome=outcome,
                     queue_ms=(started - queued) * 1000,
                     work_ms=(time.perf_counter() - started) * 1000)

    return await asyncio.get_running_loop().run_in_executor(pool, context.run, run)
