#!/usr/bin/env python3
"""Download all ground truth datasets for validation.

Usage: uv run python scripts/download_ground_truth.py [--data-dir /data/lost-landscapes]

Downloads:
- PASDA karst features shapefile (111K+ points)
- PA AML inventory shapefile (11,249 mines)
- USGS NY karst closed depressions (5,023 features)
- USGS national karst map shapefile (269MB)
"""

import asyncio
import zipfile
from pathlib import Path

import click
import httpx

from lost_landscapes.config import settings
from lost_landscapes.utils.log_manager import log

DOWNLOADS = {
    "pasda_karst": {
        "url": "https://www.pasda.psu.edu/uci/DataSummary.aspx?dataset=3073",
        "description": "PASDA Karst Features (111K+ points)",
        "notes": "Must be downloaded manually from PASDA website — no direct download link available",
    },
    "pa_aml": {
        "url": "https://newdata-padep.opendata.arcgis.com/datasets/PADEP-1::abandoned-mine-land-inventory-aml-problem-areas/about",
        "description": "PA Abandoned Mine Land Inventory (11,249 sites)",
        "notes": "Download shapefile from ArcGIS Hub",
    },
    "usgs_ny_karst": {
        "url": "https://www.sciencebase.gov/catalog/item/562a313ae4b011227bf1fe23",
        "description": "USGS NY Closed Depression Inventory (5,023 features)",
        "notes": "Download geodatabase from USGS ScienceBase",
    },
    "usgs_national": {
        "url": "https://pubs.usgs.gov/of/2014/1156/",
        "description": "USGS National Karst Map (all US)",
        "notes": "Download GIS shapefile package (269MB)",
    },
    "nc_caves": {
        "url": "https://mrdata.usgs.gov/mrds/",
        "description": "NC Cave Survey + USGS MRDS mines (1500+ caves, 700+ mica mines)",
        "notes": "Loaded via USGS MRDS WFS query filtered to North Carolina",
    },
    "md_karst": {
        "url": "https://www.mgs.md.gov/geology/caves/caves_in_maryland.html",
        "description": "MD Geological Survey karst (53 caves, 2100+ karst features)",
        "notes": "Loaded via USGS MRDS WFS query filtered to Maryland",
    },
    "ma_mines": {
        "url": "https://mrdata.usgs.gov/mrds/",
        "description": "MA USGS MRDS mines (160+ mines, Berkshire marble belt)",
        "notes": "Loaded via USGS MRDS WFS query filtered to Massachusetts",
    },
    "la_subsidence": {
        "url": "https://www.lsu.edu/lgs/",
        "description": "LA salt dome collapse and subsidence sites",
        "notes": "Known sites hardcoded + USGS MRDS salt/brine mining sites",
    },
    "ca_blm_aml": {
        "url": "https://mrdata.usgs.gov/mrds/",
        "description": "CA abandoned mines (22K+ MRDS) + known lava tubes and caves",
        "notes": "Known cave sites hardcoded + USGS MRDS query for CA mines",
    },
}


@click.command()
@click.option("--data-dir", default=None, help="Data directory (default: from config)")
def main(data_dir: str | None):
    """Print instructions for downloading ground truth datasets."""
    data_path = Path(data_dir) if data_dir else settings.data_dir
    gt_dir = data_path / "ground_truth"

    print("\n=== Ground Truth Dataset Download Guide ===\n")
    print(f"Target directory: {gt_dir}\n")

    for name, info in DOWNLOADS.items():
        target = gt_dir / name
        exists = target.exists() and any(target.iterdir()) if target.exists() else False
        status = "EXISTS" if exists else "NEEDED"

        print(f"[{status}] {info['description']}")
        print(f"  Dir:   {target}")
        print(f"  URL:   {info['url']}")
        print(f"  Notes: {info['notes']}")
        print()

    print("After downloading, place files in the directories listed above.")
    print("Then run: uv run python scripts/seed_validation_sites.py")
    print("And use the ground truth loaders to import into PostGIS.")


if __name__ == "__main__":
    main()
