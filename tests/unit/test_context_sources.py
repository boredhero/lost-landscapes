import io
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError

from lost_landscapes.api.routes import context
from lost_landscapes.context_sources import Adapter, ContextSource, request_for_tile, source_catalog


def image_bytes():
    out = io.BytesIO()
    Image.new("RGB", (256, 256)).save(out, format="PNG")
    return out.getvalue()


def test_catalog_has_coverage_dates_attribution_and_no_provider_url_input():
    data = context.catalog()
    assert len(data["sources"]) >= 4
    for source in data["sources"]:
        assert source["date_kind"] and source["region"] and source["attribution"]
        assert source["verified_at"] and source["revision"]
        assert source["tile_url"].startswith("/api/landscape/context/")
        assert "adapter" not in source


def test_historical_sheet_is_locked_and_map_imprint_dates_distinguished():
    source = source_catalog()["usgs-pittsburgh-1904"]
    url, params = request_for_tile(source, 12, 1100, 1500)
    assert url.endswith("/exportImage")
    assert json.loads(params["mosaicRule"])["lockRasterIds"] == [135419]
    assert "1904" in source.date_label and "1957" in source.date_label


def test_map_export_selects_imagery_not_index():
    _, params = request_for_tile(source_catalog()["allegheny-aerial-2010"], 12, 1100, 1500)
    assert params["layers"] == "show:1"
    assert params["imageSR"] == "3857"
    assert source_catalog()["allegheny-aerial-2010"].date_kind == "publication"


def test_xyz_coordinate_order():
    url, params = request_for_tile(source_catalog()["pittsburgh-aerial-1939"], 12, 1100, 1500)
    assert url.endswith("/tile/12/1500/1100")
    assert params == {}


def test_europe_wms_requires_only_a_new_catalog_entry():
    # Fixture coordinates in Europe exercise region-independent routing and axis order.
    data = source_catalog()["pa-bedrock"].model_dump()
    data.update(id="europe-fixture", country="DE", region="European test fixture", bounds=[5, 47, 15, 55],
                adapter={"kind": "wms", "url": "https://example.org/wms", "layers": "geology", "styles": "default"})
    source = ContextSource.model_validate(data)
    url, params = request_for_tile(source, 1, 1, 0)
    assert url == "https://example.org/wms"
    assert params["VERSION"] == "1.3.0" and params["CRS"] == "EPSG:3857"
    assert list(map(float, params["BBOX"].split(","))) == [0, 0, 20037508.342789244, 20037508.342789244]
    assert params["LAYERS"] == "geology" and params["STYLES"] == "default"
    assert source.public()["country"] == "DE"


@pytest.mark.parametrize("adapter", [
    {"kind": "xyz", "url": "http://example.org/{z}/{x}/{y}"},
    {"kind": "xyz", "url": "https://example.org/no-coordinates"},
    {"kind": "wms", "url": "https://example.org/wms?url=anything", "layers": "x"},
    {"kind": "arcgis-image", "url": "https://example.org/images"},
])
def test_invalid_adapter_configuration_rejected(adapter):
    with pytest.raises(ValidationError):
        Adapter.model_validate(adapter)


async def test_outside_coverage_skips_provider(monkeypatch):
    fetch = AsyncMock()
    monkeypatch.setattr(context, "fetch_image", fetch)
    response = await context.tile("pa-bedrock", 10, 512, 512)
    assert response.body == context.EMPTY_TILE
    fetch.assert_not_called()


async def test_unknown_source_does_not_become_open_proxy(monkeypatch):
    fetch = AsyncMock()
    monkeypatch.setattr(context, "fetch_image", fetch)
    with pytest.raises(HTTPException) as exc:
        await context.tile("https://untrusted.invalid", 0, 0, 0)
    assert exc.value.status_code == 404
    fetch.assert_not_called()


@pytest.mark.parametrize("failure", [TimeoutError(), ValueError("JSON response"), httpx.ConnectError("down")])
async def test_provider_failure_is_bounded_overlay_error(monkeypatch, failure):
    monkeypatch.setattr(context, "fetch_image", AsyncMock(side_effect=failure))
    with pytest.raises(HTTPException) as exc:
        await context.tile("pa-bedrock", 14, 4551, 6172)
    assert exc.value.status_code == 503
    assert "overlay" in exc.value.detail


async def test_provider_png_response(monkeypatch):
    body = image_bytes()
    monkeypatch.setattr(context, "fetch_image", AsyncMock(return_value=body))
    response = await context.tile("pa-bedrock", 14, 4551, 6172)
    assert response.body == body
    assert response.media_type == "image/png"


async def test_request_timeout_includes_semaphore_wait(monkeypatch):
    import asyncio
    monkeypatch.setattr(context, "REQUEST_DEADLINE", 0.01)
    monkeypatch.setattr(context, "_slots", asyncio.Semaphore(0))
    with pytest.raises(TimeoutError):
        await context.fetch_image("https://example.org/never-requested", {})


@pytest.mark.parametrize("content_type,body,valid", [
    ("image/png", image_bytes(), True),
    ("application/json", b'{"error":"unavailable"}', False),
    ("image/png", b"not a PNG", False),
    ("image/png", b"x" * (context.MAX_BYTES + 1), False),
])
async def test_stream_validation(monkeypatch, content_type, body, valid):
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-type": content_type}, content=body))
    monkeypatch.setattr(context.httpx, "AsyncClient", lambda **kwargs: real_client(transport=transport, **kwargs))
    if valid:
        assert await context.fetch_image("https://example.org/test", {}) == body
    else:
        with pytest.raises((ValueError, OSError)):
            await context.fetch_image("https://example.org/test", {})
