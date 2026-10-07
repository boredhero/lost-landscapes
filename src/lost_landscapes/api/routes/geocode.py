"""Zip code geocoding proxy — avoids CORS issues with external API."""

import time

import httpx
from fastapi import APIRouter, HTTPException, Query

from lost_landscapes.utils.log_manager import log

router = APIRouter(tags=["geocode"])

ZIPPOPOTAM_URL = "https://api.zippopotam.us/us"


@router.get("/geocode")
async def geocode_zip(
    zip: str = Query(..., min_length=5, max_length=5, pattern=r"^\d{5}$"),
):
    """Geocode a US zip code via Zippopotam.us.

    Returns lat/lon coordinates for the zip code centroid.
    Free API, no auth required, no rate limits.
    """
    log.info("geocode_request", zip_code=zip)
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{ZIPPOPOTAM_URL}/{zip}")
        except httpx.HTTPError as e:
            log.error("geocode_http_error", zip_code=zip, error=str(e), exception=True)
            raise HTTPException(status_code=502, detail="Geocoding service unavailable")
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    if resp.status_code == 404:
        log.warning("geocode_zip_not_found", zip_code=zip, elapsed_ms=elapsed_ms)
        raise HTTPException(status_code=404, detail="Invalid or unrecognized zip code")
    if resp.status_code != 200:
        log.error("geocode_upstream_error", zip_code=zip, status_code=resp.status_code, elapsed_ms=elapsed_ms)
        raise HTTPException(status_code=502, detail="Geocoding service error")
    data = resp.json()
    places = data.get("places", [])
    if not places:
        log.warning("geocode_no_places", zip_code=zip, elapsed_ms=elapsed_ms)
        raise HTTPException(status_code=404, detail="Invalid or unrecognized zip code")
    place = places[0]
    result = {
        "lat": float(place["latitude"]),
        "lon": float(place["longitude"]),
        "city": place.get("place name", ""),
        "state": place.get("state abbreviation", ""),
    }
    log.info("geocode_success", zip_code=zip, city=result["city"], state=result["state"], elapsed_ms=elapsed_ms)
    return result
