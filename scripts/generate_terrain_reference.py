#!/usr/bin/env python3
"""Regenerate offline reference fixtures from a pinned official RVT checkout."""

import argparse
import importlib.util
import json
import subprocess
from pathlib import Path

import numpy as np

RVT_COMMIT = "bab109c409fedf77ccec7de5fd84c48b791df3d2"


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rvt-source", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=Path("tests/fixtures/terrain-reference"))
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "-C", str(args.rvt_source), "rev-parse", "HEAD"], text=True).strip()
    if revision != RVT_COMMIT:
        parser.error(f"Expected RVT commit {RVT_COMMIT}, got {revision}")
    vis = load_module(args.rvt_source / "rvt" / "vis.py", "reference_vis")
    data, cases = {}, []
    rows, cols = np.indices((129, 129), dtype=np.float32)
    for spacing in (1, 2, 3):
        x, y = (cols - 64) * spacing, (rows - 64) * spacing
        surfaces = {
            "plane": 100 + 0.2 * x - 0.3 * y,
            "landforms": 100 + 0.03 * x + 0.07 * y
            + 6 * np.exp(-((x - 10)**2 + (y + 5)**2) / 150)
            - 8 * np.exp(-((x + 10)**2 + (y - 5)**2) / 100)
            + 2 * np.sin(x / 13) * np.cos(y / 11),
        }
        for name, dem in surfaces.items():
            for radius in (10, 25, 50):
                key = f"{name}-{spacing}m-{radius}m"
                cells = int(np.ceil(radius / spacing))
                positive = vis.sky_view_factor(dem.copy(), resolution=spacing, compute_svf=True,
                                               compute_opns=True, svf_n_dir=16, svf_r_max=cells, svf_noise=0)
                negative = vis.sky_view_factor(-dem.copy(), resolution=spacing, compute_svf=False,
                                               compute_opns=True, svf_n_dir=16, svf_r_max=cells, svf_noise=0)
                # Compare the complete valid interior; no reflected reference edges enter tests.
                interior = (slice(cells, -cells), slice(cells, -cells))
                data[key + "/dem"] = dem.astype(np.float32)
                data[key + "/svf"] = positive["svf"][interior]
                data[key + "/openness-positive"] = positive["opns"][interior]
                data[key + "/openness-negative"] = negative["opns"][interior]
                cases.append({"key": key, "spacing_m": spacing, "radius_m": radius, "margin_cells": cells})
    args.output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output / "horizons.npz", **data)
    (args.output / "manifest.json").write_text(json.dumps({
        "source": "https://github.com/EarthObservation/RVT_py", "revision": RVT_COMMIT,
        "reference_function": "rvt.vis.sky_view_factor", "directions": 16, "noise": 0,
        "license": "RVT source: Apache-2.0. Stored files contain synthetic numeric outputs, not vendored source.",
        "comparison": "Complete finite interior only; application masks missing support instead of reflecting edges.",
        "cases": cases,
    }, indent=2) + "\n")
    print(f"Generated {len(cases)} official-reference cases in {args.output}")


if __name__ == "__main__":
    main()
