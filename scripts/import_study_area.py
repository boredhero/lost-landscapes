#!/usr/bin/env python3
"""Import existing bare-earth LiDAR DEMs without reclassifying a point cloud."""

import argparse
import json
import re
import shutil
from pathlib import Path

import rasterio
from rasterio.enums import Resampling
from rasterio.warp import transform_bounds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dem", nargs="+", type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--source", required=True, help="Dataset attribution and acquisition year")
    parser.add_argument("--description", default="Explore the landforms in this LiDAR study area.")
    parser.add_argument(
        "--survey-id", help="Verified common acquisition/processing group for neighbor joins"
    )
    parser.add_argument(
        "--vertical-datum", help="Verified vertical reference shared by this survey (no conversion)"
    )
    parser.add_argument(
        "--elevation-units",
        choices=["m"],
        help="Declare metre elevations if band units are missing; does not convert values",
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    slug = re.sub(r"[^a-z0-9]+", "-", args.name.lower()).strip("-")
    if not slug:
        parser.error("Name must contain letters or numbers")
    if bool(args.survey_id) != bool(args.vertical_datum):
        parser.error("--survey-id and --vertical-datum must be supplied together")
    if any(
        value is not None and not value.strip() for value in (args.survey_id, args.vertical_datum)
    ):
        parser.error("Survey ID and vertical datum must not be blank")
    # Validate every input before copying anything.
    inputs = []
    for source in args.dem:
        with rasterio.open(source) as src:
            if not src.crs or src.count != 1 or not src.crs.is_projected:
                parser.error(
                    f"{source}: expected a single-band projected DEM with elevation in meters"
                )
            if abs(src.crs.linear_units_factor[1] - 1.0) > 0.001:
                parser.error(f"{source}: convert horizontal coordinates to meters before importing")
            if args.elevation_units and (src.units[0] or "").strip().lower() not in (
                "",
                "m",
                "metre",
                "meter",
                "metres",
                "meters",
            ):
                parser.error(
                    f"{source}: convert elevation values to metres before declaring metre units"
                )
            for key, value in (
                ("LL_SURVEY_ID", args.survey_id),
                ("LL_VERTICAL_DATUM", args.vertical_datum),
            ):
                if value and src.tags().get(key, value.strip()).strip() != value.strip():
                    parser.error(f"{source}: supplied {key} conflicts with existing metadata")
            inputs.append(
                (source, transform_bounds(src.crs, "EPSG:4326", *src.bounds), abs(src.res[0]))
            )
    for index in range(len(inputs)):
        destination = (
            args.data_dir / "processed" / f"{slug}-{index:03d}" / f"{slug}-{index:03d}_dem.tif"
        )
        if destination.exists():
            parser.error(f"{destination} already exists; use a new area name for a new import")
    bounds = []
    for index, (source, extent, resolution) in enumerate(inputs):
        folder = args.data_dir / "processed" / f"{slug}-{index:03d}"
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / f"{slug}-{index:03d}_dem.tif"
        if destination.exists():
            parser.error(f"{destination} already exists; use a new area name for a new import")
        shutil.copy2(source, destination)
        # External masks and auxiliary metadata are part of the measured source.
        for suffix in (".msk", ".aux.xml"):
            sidecar = Path(str(source) + suffix)
            if sidecar.exists():
                shutil.copy2(sidecar, Path(str(destination) + suffix))
        with rasterio.open(destination, "r+") as dst:
            if args.survey_id:
                dst.update_tags(
                    LL_SURVEY_ID=args.survey_id.strip(),
                    LL_VERTICAL_DATUM=args.vertical_datum.strip(),
                )
            if args.elevation_units:
                dst.set_band_unit(1, "m")
            factors = [
                factor for factor in [2, 4, 8, 16] if min(dst.width, dst.height) // factor >= 16
            ]
            dst.build_overviews(factors, Resampling.average)
            dst.update_tags(ns="rio_overview", resampling="average")
        bounds.append(extent)
    manifest = args.data_dir / "study-areas.json"
    areas = json.loads(manifest.read_text()) if manifest.exists() else []
    areas = [area for area in areas if area["id"] != slug]
    areas.append(
        {
            "id": slug,
            "name": args.name,
            "source": args.source,
            "description": args.description,
            "resolution_m": round(min(item[2] for item in inputs), 2),
            "bounds": [
                min(b[0] for b in bounds),
                min(b[1] for b in bounds),
                max(b[2] for b in bounds),
                max(b[3] for b in bounds),
            ],
        }
    )
    temporary = manifest.with_suffix(".tmp")
    temporary.write_text(json.dumps(areas, indent=2) + "\n")
    temporary.replace(manifest)
    print(
        f"Imported {len(inputs)} DEMs into {args.data_dir}. Refresh the explorer after 15 seconds."
    )


if __name__ == "__main__":
    main()
