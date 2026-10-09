"""Optional evidence tiles. External outages never enter the terrain render pool."""

import asyncio
import io

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError

from lost_landscapes.context_sources import intersects, request_for_tile, source_catalog

router = APIRouter(prefix="/landscape/context", tags=["landscape-context"])
_slots = asyncio.Semaphore(4)
MAX_BYTES = 2_000_000
REQUEST_DEADLINE = 6
_empty = io.BytesIO()
Image.new("RGBA", (256, 256)).save(_empty, format="PNG")
EMPTY_TILE = _empty.getvalue()


@router.get("")
def catalog():
    try:
        return {"version": 1, "sources": [s.public() for s in source_catalog().values()]}
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, "Evidence catalog unavailable; terrain remains available") from exc


async def fetch_image(url, params):
    # Includes queue wait, connection, streamed bytes and validation in one deadline.
    async with asyncio.timeout(REQUEST_DEADLINE):
        async with _slots:
            async with httpx.AsyncClient(timeout=4, follow_redirects=False) as client:
                async with client.stream("GET", url, params=params) as response:
                    response.raise_for_status()
                    if response.headers.get("content-type", "").split(";")[0] not in ("image/png", "image/jpeg"):
                        raise ValueError("Provider did not return imagery")
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > MAX_BYTES:
                            raise ValueError("Provider image exceeds request limit")
            with Image.open(io.BytesIO(chunks)) as img:
                if img.size != (256, 256) or img.format not in ("PNG", "JPEG"):
                    raise ValueError("Unexpected evidence tile dimensions or format")
                img.verify()
            return bytes(chunks)


@router.get("/{source_id}/tiles/{z}/{x}/{y}.png")
async def tile(source_id: str, z: int, x: int, y: int):
    try:
        source = source_catalog().get(source_id)
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, "Evidence catalog unavailable") from exc
    if source is None or not (0 <= z <= 22 and 0 <= x < 2**z and 0 <= y < 2**z):
        raise HTTPException(404, "Unknown source or tile")
    if not source.min_zoom <= z <= source.max_zoom or not intersects(source, z, x, y):
        return Response(EMPTY_TILE, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})
    url, params = request_for_tile(source, z, x, y)
    try:
        data = await fetch_image(url, params)
    except (TimeoutError, httpx.HTTPError, OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise HTTPException(503, "Evidence provider unavailable; retry or remove this overlay") from exc
    # Ordinary short-lived viewing cache only; no offline/bulk provider imagery export.
    return Response(data, media_type="image/png" if data.startswith(b"\x89PNG") else "image/jpeg",
                    headers={"Cache-Control": "private, max-age=300"})
