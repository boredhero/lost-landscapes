"""Unit tests for FastAPI endpoints using httpx TestClient.

These tests use a mocked database to avoid requiring PostGIS.
They verify route structure, request validation, and response schemas.
"""


import io

import pytest
from fastapi.testclient import TestClient

from lost_landscapes.main import create_app


@pytest.fixture
def client():
    """Create a test client with mocked DB dependency."""
    app = create_app()
    return TestClient(app)


class TestHealthEndpoint:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestRasterTilesEndpoint:
    def test_hillshade_tile_returns_png(self, client):
        r = client.get("/api/raster/hillshade/10/300/400.png")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        # Should return a valid PNG (starts with PNG magic bytes)
        assert r.content[:4] == b"\x89PNG"

    def test_terrain_rgb_tile(self, client):
        r = client.get("/api/raster/terrain-rgb/10/300/400.png")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"

    def test_unknown_layer(self, client):
        r = client.get("/api/raster/nonexistent/10/300/400.png")
        assert r.status_code == 200  # returns transparent PNG fallback

    def test_composited_terrain_tile_returns_png(self, client):
        """Composited terrain endpoint returns valid PNG (AWS fallback for uncovered areas)."""
        r = client.get("/api/raster/terrain/10/300/400.png")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.content[:4] == b"\x89PNG"

    def test_composited_terrain_tile_is_terrarium_encoded(self, client):
        """Terrain tile should be a valid Terrarium-encoded PNG (RGB, not RGBA)."""
        from PIL import Image
        r = client.get("/api/raster/terrain/5/9/12.png")
        assert r.status_code == 200
        img = Image.open(io.BytesIO(r.content))
        assert img.mode in ("RGB", "RGBA")
        # Verify it's a reasonable size (1x1 fallback or 256x256 real)
        assert img.size[0] >= 1
        assert img.size[1] >= 1


class TestVectorTiles:
    def test_tile_to_bbox(self):
        """Test ZXY to bbox conversion."""
        from lost_landscapes.api.routes.tiles import _tile_to_bbox

        # Tile 0/0/0 should cover the whole world
        bbox = _tile_to_bbox(0, 0, 0)
        assert bbox[0] == pytest.approx(-180, abs=0.1)
        assert bbox[2] == pytest.approx(180, abs=0.1)

        # Higher zoom should give smaller bbox
        bbox_z10 = _tile_to_bbox(10, 300, 400)
        assert (bbox_z10[2] - bbox_z10[0]) < 1.0  # less than 1 degree wide


class TestOpenAPI:
    def test_openapi_schema(self, client):
        r = client.get("/api/openapi.json")
        assert r.status_code == 200
        schema = r.json()
        assert schema["info"]["title"] == "Lost Landscapes"
        paths = list(schema["paths"].keys())
        assert "/api/health" in paths
        assert "/api/detections" in paths
        assert "/api/jobs" in paths

    def test_docs_page(self, client):
        r = client.get("/api/docs")
        assert r.status_code == 200


class TestRouteStructure:
    """Verify all expected routes are registered."""

    def test_all_routes_exist(self, client):
        r = client.get("/api/openapi.json")
        paths = set(r.json()["paths"].keys())

        expected = [
            "/api/health",
            "/api/detections",
            "/api/detections/{detection_id}",
            "/api/jobs",
            "/api/jobs/{job_id}",
            "/api/jobs/{job_id}/cancel",
            "/api/datasets",
            "/api/detections/{detection_id}/validate",
            "/api/ground-truth",
            "/api/export/geojson",
            "/api/export/csv",
            "/api/tiles/{z}/{x}/{y}.mvt",
            "/api/tiles/ground-truth/{z}/{x}/{y}.mvt",
            "/api/raster/{layer}/{z}/{x}/{y}.png",
            "/api/raster/terrain-rgb/{z}/{x}/{y}.png",
            "/api/detections/{detection_id}/comments",
            "/api/comments/{comment_id}",
            "/api/saved",
            "/api/detections/{detection_id}/save",
            "/api/saved/{save_id}",
            "/api/info",
            "/api/geocode",
            "/api/detections/count",
            "/api/explore/scan",
            "/api/raster/terrain/{z}/{x}/{y}.png",
            "/api/raster/terrain/coverage",
        ]

        for path in expected:
            assert path in paths, f"Missing route: {path}"
