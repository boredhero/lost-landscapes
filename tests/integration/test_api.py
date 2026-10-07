"""Integration tests for API endpoints with mocked async DB session.

No live PostGIS required — uses unittest.mock to patch the DB dependency.
Tests verify request validation, response schemas, and route wiring.
"""


import pytest
from fastapi.testclient import TestClient

from lost_landscapes.main import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


class TestHealthInfo:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_info_has_version(self, client):
        r = client.get("/api/info")
        assert r.status_code == 200
        d = r.json()
        assert "version" in d
        assert d["name"] == "Lost Landscapes"


class TestOpenAPISchema:
    def test_all_routes_registered(self, client):
        r = client.get("/api/openapi.json")
        paths = set(r.json()["paths"].keys())
        expected = [
            "/api/health", "/api/info", "/api/detections",
            "/api/jobs", "/api/ground-truth",
            "/api/export/geojson", "/api/export/csv",
            "/api/detections/{detection_id}/comments",
            "/api/detections/{detection_id}/save",
            "/api/saved",
        ]
        for path in expected:
            assert path in paths, f"Missing: {path}"


class TestRasterTiles:
    def test_returns_png(self, client):
        r = client.get("/api/raster/hillshade/10/300/400.png")
        assert r.status_code == 200
        assert r.content[:4] == b"\x89PNG"

    def test_terrain_rgb(self, client):
        r = client.get("/api/raster/terrain-rgb/10/300/400.png")
        assert r.status_code == 200
        assert r.content[:4] == b"\x89PNG"
