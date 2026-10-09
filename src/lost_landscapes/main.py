"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from lost_landscapes import visits
from lost_landscapes.utils.log_manager import log
from lost_landscapes.utils.request_logging import RequestLoggingMiddleware

_vrt_timer = None

def _vrt_rebuild_loop():
    """Background thread that rebuilds VRT mosaics every 2 minutes.
    Runs independently of requests so health checks are never blocked."""
    import time as _time
    while True:
        try:
            from lost_landscapes.api.routes.raster_tiles import _get_dem_vrts
            t0 = _time.perf_counter()
            vrts = _get_dem_vrts()
            elapsed_ms = round((_time.perf_counter() - t0) * 1000, 1)
            log.info("vrt_rebuild_complete", vrt_count=len(vrts), elapsed_ms=elapsed_ms)
        except Exception as e:
            log.warning("vrt_rebuild_failed", error=str(e)[:200])
        _time.sleep(120)

@asynccontextmanager
async def lifespan(app: FastAPI):
    import threading

    import lost_landscapes.detection.passes  # noqa: F401
    log.info("app_startup", version=_load_info().get("version", "unknown"))
    # Start VRT rebuild loop in a daemon thread — runs forever, never blocks requests
    global _vrt_timer
    _vrt_timer = threading.Thread(target=_vrt_rebuild_loop, daemon=True)
    _vrt_timer.start()
    yield
    log.info("app_shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Lost Landscapes",
        description="LiDAR terrain anomaly detection API — caves, mines, sinkholes",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://anomalies.martinospizza.dev",
            "https://lostlandscapes.martinospizza.dev",
            "http://localhost:5173",
            "http://localhost:8000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Server-Timing"],
    )

    app.add_middleware(RequestLoggingMiddleware)

    # Register all routes
    from lost_landscapes.api.routes import (
        comments,
        context,
        datasets,
        debug,
        detections,
        exports,
        geocode,
        jobs,
        landscape,
        raster_tiles,
        tiles,
        validation,
        websocket,
    )

    app.include_router(visits.router, prefix="/api")
    app.include_router(landscape.router, prefix="/api")
    app.include_router(context.router, prefix="/api")
    app.include_router(detections.router, prefix="/api")
    app.include_router(comments.router, prefix="/api")
    app.include_router(jobs.router, prefix="/api")
    app.include_router(datasets.router, prefix="/api")
    app.include_router(validation.router, prefix="/api")
    app.include_router(exports.router, prefix="/api")
    app.include_router(tiles.router, prefix="/api")
    app.include_router(raster_tiles.router, prefix="/api")
    app.include_router(geocode.router, prefix="/api")
    app.include_router(debug.router)
    app.include_router(websocket.router)

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": _load_info().get("version", "unknown")}

    @app.get("/api/info")
    async def info():
        return _load_info()

    # Serve built frontend as SPA
    _mount_frontend(app)

    return app


def _load_info() -> dict:
    """Load info.yml for version display."""
    from pathlib import Path
    info_candidates = [
        Path(__file__).parent.parent.parent / "info.yml",
        Path("/app/info.yml"),
    ]
    for p in info_candidates:
        if p.exists():
            # Simple YAML-subset parser (key: value lines)
            data = {}
            for line in p.read_text().splitlines():
                line = line.strip()
                if ":" in line and not line.startswith("#"):
                    key, _, val = line.partition(":")
                    val = val.strip()
                    # Try numeric conversion
                    try:
                        val = int(val)
                    except (ValueError, TypeError):
                        pass
                    data[key.strip()] = val
            return data
    return {"version": "0.1.0", "name": "Lost Landscapes"}


def _mount_frontend(app: FastAPI) -> None:
    """Mount built frontend static files with SPA fallback."""
    from pathlib import Path

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    # Check for static dir (Docker) then frontend/dist (dev)
    for candidate in [
        Path(__file__).parent.parent.parent / "static",
        Path(__file__).parent.parent.parent / "frontend" / "dist",
    ]:
        if (candidate / "index.html").exists():
            static_dir = candidate
            break
    else:
        return  # no frontend built
    # Mount /assets for hashed JS/CSS bundles
    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="static-assets")
    # SPA catch-all: serve index.html for any non-API, non-asset route
    index_path = str(static_dir / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # Serve actual static files if they exist
        file_path = static_dir / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(index_path)


app = create_app()
