#!/usr/bin/env python3
"""Seed the database with known validation sites for testing.

Usage: uv run python scripts/seed_validation_sites.py
"""

import asyncio
import json
from pathlib import Path

from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import select, func

from lost_landscapes.db.engine import async_session_factory
from lost_landscapes.db.models import FeatureType, GroundTruthSite, GroundTruthSource

FEATURE_TYPE_MAP = {
    "cave_entrance": FeatureType.CAVE_ENTRANCE,
    "mine_portal": FeatureType.MINE_PORTAL,
    "sinkhole": FeatureType.SINKHOLE,
    "depression": FeatureType.DEPRESSION,
}


async def seed():
    sites_file = Path(__file__).parent.parent / "tests" / "fixtures" / "known_sites.json"
    with open(sites_file) as f:
        data = json.load(f)

    async with async_session_factory() as session:
        # Check if already seeded
        count_result = await session.execute(
            select(func.count()).select_from(GroundTruthSite).where(
                GroundTruthSite.source == GroundTruthSource.MANUAL
            )
        )
        existing = count_result.scalar_one()
        if existing > 0:
            print(f"Already seeded ({existing} manual sites exist). Skipping.")
            return

        sites = data["validation_sites"]
        for site_data in sites:
            feature_type = FEATURE_TYPE_MAP.get(site_data["type"], FeatureType.UNKNOWN)

            site = GroundTruthSite(
                name=site_data["name"],
                feature_type=feature_type,
                geometry=from_shape(
                    Point(site_data["lon"], site_data["lat"]),
                    srid=4326,
                ),
                source=GroundTruthSource.MANUAL,
                source_id=f"validation_{site_data['name'].lower().replace(' ', '_')}",
                metadata_={
                    "state": site_data.get("state", ""),
                    "county": site_data.get("county", ""),
                    "coordinate_confidence": site_data.get("confidence", ""),
                },
            )
            session.add(site)

        await session.commit()
        print(f"Seeded {len(sites)} validation sites.")


if __name__ == "__main__":
    asyncio.run(seed())
