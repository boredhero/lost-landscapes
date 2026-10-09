#!/usr/bin/env python3
"""Repeatable local tile benchmarks with isolated PNG caches and bounded concurrency.

Measures render/cache functions, not HTTP/browser latency. Imported data is read
only. Synthetic mode exercises a fully supported four-file join independently.
"""

import argparse
import hashlib
import io
import json
import math
import os
import platform
import resource
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import from_origin
from rasterio.warp import transform, transform_bounds

from lost_landscapes import terrain_visualization as visualization
from lost_landscapes.api.routes import landscape


def synthetic_sources(directory):
    records = []
    for row in range(2):
        for col in range(2):
            rows, cols = np.indices((512, 512), dtype=np.float32)
            x, y = cols + col * 512 - 512, rows + row * 512 - 512
            values = 200 + 0.03 * x - 0.1 * y + 4 * np.sin(x / 25) * np.cos(y / 17)
            path = directory / f"synthetic-{row}-{col}.tif"
            with rasterio.open(path, "w", driver="GTiff", width=512, height=512, count=1,
                               dtype="float32", crs="EPSG:32617",
                               transform=from_origin(500000 + col * 512, 4500000 - row * 512, 1, 1)) as dst:
                dst.write(values, 1)
                dst.set_band_unit(1, "m")
                dst.update_tags(LL_SURVEY_ID="benchmark-synthetic", LL_VERTICAL_DATUM="synthetic")
            with rasterio.open(path) as src:
                records.append(landscape.Dem(path, transform_bounds(src.crs, "EPSG:3857", *src.bounds),
                                              transform_bounds(src.crs, "EPSG:4326", *src.bounds), 1))
    lons, lats = transform("EPSG:32617", "EPSG:4326", [500512, 500700], [4499488, 4499300])
    return records, list(zip(lons, lats, strict=True))


def run_case(case):
    started = time.perf_counter()
    png = landscape.render_tile(case["layer"], case["z"], case["x"], case["y"], case["radius_m"])
    elapsed = (time.perf_counter() - started) * 1000
    alpha = np.asarray(Image.open(io.BytesIO(png)))[..., 3]
    return {**case, "milliseconds": round(elapsed, 3), "png_sha256": hashlib.sha256(png).hexdigest(),
            "supported_percent": round(float((alpha > 0).mean() * 100), 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=["imported", "synthetic"], required=True)
    parser.add_argument("--workers", type=int, choices=[1, 2], default=2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    original_dir, original_inventory = landscape.settings.data_dir, landscape.inventory
    with tempfile.TemporaryDirectory(prefix="landscapes-terrain-benchmark-") as temporary:
        directory = Path(temporary)
        if args.dataset == "synthetic":
            records, points = synthetic_sources(directory)
            revision = "synthetic-v1-" + visualization.VERSION
        else:
            revision, records = landscape.inventory()
            points = [(-79.970, 40.499), (-79.986, 40.499)]
            if not records:
                parser.error("No imported DEMs; use --dataset synthetic or import the study data first")
        landscape.settings.data_dir = directory / "cache"
        landscape.inventory = lambda: (revision, records)
        cases = []
        identities = set()
        for lon, lat in points:
            for z in (16, 17, 18):
                x = int((lon + 180) / 360 * 2**z)
                y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2**z)
                for layer in ("relief", "svf", "openness-positive", "openness-negative", "vat"):
                    for radius in ((25,) if layer == "relief" else (10, 25, 50)):
                        key = (layer, z, x, y, radius)
                        if key in identities:
                            continue
                        identities.add(key)
                        cases.append({"layer": layer, "z": z, "x": x, "y": y, "radius_m": radius})
        try:
            batches = {}
            for phase in ("cold_png_cache", "warm_png_cache"):
                started = time.perf_counter()
                with ThreadPoolExecutor(max_workers=args.workers) as pool:
                    rows = list(pool.map(run_case, cases))
                batches[phase] = {"wall_seconds": round(time.perf_counter() - started, 3), "tiles": rows}
            cold, warm = batches["cold_png_cache"]["tiles"], batches["warm_png_cache"]["tiles"]
            if any(a["png_sha256"] != b["png_sha256"] for a, b in zip(cold, warm, strict=True)):
                raise RuntimeError("Warm cache changed tile bytes")
            summary = {}
            for layer in sorted({case["layer"] for case in cases}):
                rows = [row for row in cold if row["layer"] == layer]
                measured = [row["milliseconds"] for row in rows]
                summary[layer] = {"cases": len(rows), "cold_p50_ms": round(float(np.median(measured)), 3),
                                  "cold_p95_ms": round(float(np.percentile(measured, 95)), 3),
                                  "fully_transparent_cases": sum(row["supported_percent"] == 0 for row in rows)}
            report = {"dataset": args.dataset, "algorithm": visualization.VERSION,
                      "source_revision": revision, "source_count": len(records), "workers": args.workers,
                      "platform": platform.platform(), "logical_cpus": os.cpu_count(),
                      "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
                      "summary": summary, "batches": batches,
                      "limitations": "Local function timings, not HTTP. Cold refers to an empty PNG cache, not OS disk cache. Peak RSS includes harness and synthetic fixture creation. Two sample locations; no production capacity claim."}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps({"output": str(args.output), "summary": summary,
                              "peak_rss_mib": report["peak_rss_mib"]}, indent=2))
        finally:
            landscape.settings.data_dir, landscape.inventory = original_dir, original_inventory


if __name__ == "__main__":
    main()
