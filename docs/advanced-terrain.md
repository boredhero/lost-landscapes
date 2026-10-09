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

VAT and the expanded performance report are the next delivery in this sequence.
