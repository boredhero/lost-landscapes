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
    parser.add_argument("--include-vat", action="store_true", help="Also run official blending functions (requires Matplotlib)")
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "-C", str(args.rvt_source), "rev-parse", "HEAD"], text=True).strip()
    if revision != RVT_COMMIT:
        parser.error(f"Expected RVT commit {RVT_COMMIT}, got {revision}")
    vis = load_module(args.rvt_source / "rvt" / "vis.py", "reference_vis")
    blend = load_module(args.rvt_source / "rvt" / "blend_func.py", "reference_blend") if args.include_vat else None
    recipe = json.loads((args.rvt_source / "settings" / "blender_VAT.json").read_text())
    data, vat_data, cases = {}, {}, []
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
                if blend is not None:
                    images = {
                        "Sky-View Factor": positive["svf"], "Openness - Positive": positive["opns"],
                        "Slope gradient": vis.slope_aspect(dem.copy(), spacing, spacing, output_units="degree")["slope"],
                        "Hillshade": vis.hillshade(dem.copy(), spacing, spacing, sun_azimuth=315, sun_elevation=35),
                    }
                    output = None
                    for layer in reversed(recipe["combination"]["layers"]):
                        active = blend.normalize_image(layer["visualization_method"],
                                                       images[layer["visualization_method"]].copy(),
                                                       layer["min"], layer["max"], layer["norm"].lower())
                        if output is None:
                            output = active
                        else:
                            # RVT overlay mutates its background. Preserve the original for opacity.
                            top = blend.blend_images(layer["blend_mode"], active, output.copy())
                            output = blend.render_images(top, output, layer["opacity"])
                    vat_data[key] = output[interior]
                cases.append({"key": key, "spacing_m": spacing, "radius_m": radius, "margin_cells": cells})
    args.output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output / "horizons.npz", **data)
    if blend is not None:
        np.savez_compressed(args.output / "vat.npz", **vat_data)
        (args.output / "vat-manifest.json").write_text(json.dumps({
            "revision": RVT_COMMIT, "settings": "settings/blender_VAT.json", "recipe": recipe,
            "hillshade_azimuth": 315, "hillshade_altitude": 35,
            "radius": "Shared physical radius from horizon fixture cases, converted to native cells",
            "reference": "rvt.vis plus rvt.blend_func.normalize_image, blend_images, render_images",
            "opacity": "Background copies preserve standard opacity semantics across in-place overlay calls",
        }, indent=2) + "\n")
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
