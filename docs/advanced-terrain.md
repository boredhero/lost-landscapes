# Advanced terrain views

Sky-view factor and positive/negative openness use the horizon method implemented
by the [Relief Visualization Toolbox](https://github.com/EarthObservation/RVT_py).
The reference revision is `bab109c409fedf77ccec7de5fd84c48b791df3d2`.
These are inspection visualizations, not archaeological classifications.

## Method and units

Search 16 equally spaced directions on the native projected metre grid. Along
each direction, collect cell centers nearest to physical ray samples spaced at
one third of the smaller native cell spacing, starting at one such cell. Round
the nominal 10/25/50 m radius up to that spacing. Deduplicate snapped positions
within each ray and calculate each sample's true ground distance. Snapping can
extend a ray by up to half a cell diagonal beyond the rounded nominal radius.
Rectangular grids use separate horizontal and vertical spacing.

The maximum elevation angle in direction i is h_i. In the RVT visible-sky
convention, SVF is the mean of `1 - sin(max(h_i, 0))`, ranging from zero to one.
Positive openness is `90° - mean(h_i in degrees)`; negative openness applies the
same calculation to negated elevations. It is not the inverse of positive
openness. A flat plane has SVF 1 and both openness values 90°; a tilted plane can
have lower SVF. No display exaggeration is applied to these calculations.

SVF uses black-to-white 0–1 display scaling. Positive openness uses black-to-white
60–120° and negative openness white-to-black 60–120°; values outside those display
limits saturate, while the computed quantities retain their physical values.
The [RVT SVF](https://rvt-py.readthedocs.io/en/latest/listofvis_svf.html) and
[openness documentation](https://rvt-py.readthedocs.io/en/latest/listofvis_openness.html)
describe these conventions and interpretation limits.

## Coverage and bounded work

Complete rectangular support enclosing the sampled rays is required. A missing
cell anywhere in that neighborhood makes the output unavailable. This is stricter
than RVT's reflected raster edges and treatment of missing surrounding cells;
we do not interpret absent ground as open sky. Compatible-source neighborhoods
from Delivery C1 supply measured data across file boundaries when possible.

Horizon views require zoom 16 or closer. A radius may span at most 128 minimum
native cells. A request may perform at most 240 million sampled-cell comparisons;
windows exceeding the remaining budget are skipped, never coarsened. The existing
four-million-cell window, eight-million-cell read/processing request and 32-source
neighborhood caps also apply. Zooming closer can reduce window work, but cannot
make an unsupported radius on a very fine source eligible. Source metadata lists
the supported radii. Transparent pixels and the UI guidance expose these limits.

Parameters, algorithm version and the complete source inventory revision remain
part of PNG cache identity. Views are calculated before scalar reprojection;
support masks are reprojected separately to avoid interpolating across gaps.

## Independent references

`tests/fixtures/terrain-reference/horizons.npz` contains synthetic numeric outputs
from the pinned official RVT implementation. The adjacent manifest records the
source, settings and 18 cases: inclined planes and mixed mounds/depressions at
1/2/3 m spacing and 10/25/50 m radii. Comparisons cover the full interior with
complete support and deliberately exclude the reference's reflected edges.
Tolerances are 0.000002 for SVF and 0.0002° for openness (float32 reference versus
float64 intermediate calculations). CI needs no network access or RVT installation.

To reproduce, obtain that RVT revision and run:

```sh
uv run --no-sync python scripts/generate_terrain_reference.py --rvt-source /path/to/RVT_py
uv run --no-sync pytest tests/unit/test_terrain_horizon.py -q
```

Additional analytic and tiled-reference tests cover rectangular cells, flat
surfaces, sign behavior, nodata, overlap/corner continuity, low-zoom API handling
and work limits. Reference agreement establishes algorithm behavior, not site
detection accuracy or source survey quality.

## VAT composite

The VAT view follows the general-terrain ranges and grayscale blending settings
in RVT's `settings/blender_VAT.json`, with its default 315° azimuth / 35° altitude
hillshade. From bottom to top:

| Component | Fixed display range | Blend | Opacity |
| --- | --- | --- | --- |
| Hillshade | 0–1 | Normal | 100% |
| Slope | 0–50°, inverted | Luminosity | 50% |
| Positive openness | 68–93° | Overlay | 50% |
| SVF | 0.7–1 | Multiply | 25% |

Both horizon components use the selected 10/25/50 m radius and 16 directions.
This shared physical radius is explicit; it is not an assertion that every
survey uses RVT's default ten-pixel neighborhood. Component normalization and
blending occur on the native grid before display reprojection. The four layers
must have valid support; no tile-dependent histogram stretching or substituted
hillshade is used. VAT brightness is neither a physical measurement nor a
site-likelihood score. This implements general-terrain VAT, not combined VAT.
See the [official VAT description](https://rvt-py.readthedocs.io/en/latest/listofvis_VAT.html).

`vat.npz` contains 18 corresponding reference composites produced by RVT's
terrain functions and its `normalize_image`, `blend_images` and `render_images`
functions. The generator preserves a copy of the unblended background when
applying opacity: RVT's overlay function mutates its argument in place. This
tests the stated standard opacity semantics, not that side effect of the full
upstream blender. The allowed composite difference is 0.00002 in normalized
brightness. `vat-manifest.json` records the exact reference settings.

To regenerate both sets, use the same pinned checkout and add `--include-vat`.
RVT's blending module imports Matplotlib, so use a separate reference environment
with NumPy, SciPy and Matplotlib. Matplotlib and RVT are not runtime dependencies
of the terrain server, and ordinary CI uses the committed numeric fixtures.

## Performance evaluation

`scripts/benchmark_terrain.py` provides repeatable function-level measurements
with a private temporary PNG cache. It tests two locations, zooms 16/17/18,
10/25/50 m radii and all four advanced layers against the existing relief view.
One pass starts with an empty PNG cache; the second checks that every cached PNG
is byte-identical. Reports include tile timings, actual supported-pixel fractions,
per-layer median/p95, fully transparent case counts and peak process RSS.
One- and two-worker modes allow bounded concurrency comparisons. The script does
not change imported rasters or the application's persistent caches.

```sh
uv run --no-sync python scripts/benchmark_terrain.py --dataset imported --workers 2 --output /tmp/advanced-imported.json
uv run --no-sync python scripts/benchmark_terrain.py --dataset synthetic --workers 1 --output /tmp/advanced-synthetic-1.json
uv run --no-sync python scripts/benchmark_terrain.py --dataset synthetic --workers 2 --output /tmp/advanced-synthetic-2.json
```

Imported mode uses the existing Western Pennsylvania engineering fixture;
synthetic mode creates a complete 1 m, four-file survey with declared compatible
provenance and varied relief. The synthetic case tests the joined path that the
current demo's incomplete provenance intentionally does not enable.
The reports in `docs/benchmarks/` are local measurements, not deployment capacity
or HTTP/browser latency claims. Cold means empty PNG cache, not cold OS disk
cache. Peak RSS includes the harness and fixture creation. Source revision,
algorithm version, platform and logical CPU count are recorded per report.

Recorded run summary (208 cold cases plus 208 warm checks; no entirely
transparent sampled tiles):

| Dataset / workers | Cold batch wall time | Advanced-view cold p95 range | Warm call p95 | Peak process RSS |
| --- | --- | --- | --- | --- |
| Imported / 2 | 18.443 s for 78 cases | 966–1266 ms | 0.469 ms | 193.82 MiB |
| Synthetic joined / 1 | 14.034 s for 65 cases | 410–776 ms | 0.159 ms | 167.85 MiB |
| Synthetic joined / 2 | 10.488 s for 65 cases | 662–749 ms | 0.433 ms | 187.37 MiB |

Batch wall time includes PNG support/hash checks and scheduling; per-call timings
cover the renderer/cache call itself. Two synthetic locations share a zoom-16
tile, so duplicate requests are removed from the cold matrix. Some imported tiles
are partially supported; each report preserves those fractions. These figures
do not establish a speed ranking among algorithms because the cases, cache
warming and concurrent scheduling affect timings. Keeping the horizon views at
zoom 16+, bounded work and two terrain workers is supported by this sample; wider
deployment load testing remains an operational follow-up.

Observed maximum reference errors over all supported comparison pixels were
0.00000125 for SVF, 0.0001152° for positive openness, 0.0001265° for negative
openness and 0.00000215 for VAT normalized brightness.
