# Experimental terrain discovery

`landscape_discovery` adds five independent CPU passes. The main explorer defaults
to this preset; select the existing depression survey from the automatic shortlist
panel to use the old workflow. Scanning still requires the optional analysis worker.
This release has synthetic correctness tests, **not reviewed regional accuracy**.
It detects shapes, not archaeological dates, purpose, or geological causes.

| Pass | Output | Evidence and limits |
| --- | --- | --- |
| Raised features | Mound-like and platform-like footprints | Positive 10 m local relief, compactness, summit slope/flatness and rectangularity. Natural hummocks and modern spoil remain possible. |
| Linear features | Raised banks/possible roads and lowered ditch-like features | Signed relief, length, width and aspect ratio. Footprints, not traced centerline networks; winding paths may be missed. |
| Enclosures | Complete bank/ditch boundary surrounding an interior | Continuous threshold component with a finite enclosed area. Open/broken boundaries are not joined; natural rings can qualify. |
| Repeated patterns | Group footprint and projected member centers | At least three similarly sized compact positive features, with regular nearest-neighbor spacing. Not a general field-system or crop-mark detector. |
| Geological forms | Ridge-like, hollow-like and scarp-like shapes | 25 m relief or thin steep bands. Does not diagnose landslides, karst, subsurface caves or stability. |

## Inputs and scale

New discovery preprocessing runs once in the pass runner before the five passes.
It uses metre-grid DEM arrays to compute simple signed local relief with physical
10/25 m square half-widths and gradient slope. These arrays are shared by the passes.
It does not reuse the older detector pipeline's pixel-named LRM products or its
hillshade fallback labeled SVF. The legacy processing workflow still builds its
existing derivatives before detection; the timing below excludes that work and
source download/DEM generation.

North-up projected metre grids with 0.25–5 m cell spacing are supported, including
rectangular cells. Pixel radii round upward; derivative neighborhoods must be
complete. Masked DEM cells and nodata become NaN; raster scale/offset is applied.
Elevations are assumed metres when undeclared. Source boundaries are not joined
in detection: boundary-adjacent features are conservatively omitted. This differs
from the interactive terrain renderer's compatible-survey mosaics.

Per raster: at most four million cells, 20,000 connected components per mask and
200 polygonized regions per polarity/pass, largest first. Worker output retains
the existing 200-result tile cap. Oversized or invalid discovery inputs fail with
an explicit error rather than silently returning zero findings. Large rasters
need splitting; automatic tiled/overlapped detection is follow-up work.

Thresholds live independently in each pass and may be overridden with
`[passes.raised_features]`, `[passes.linear_features]`, `[passes.enclosures]`,
`[passes.repeated_patterns]` or `[passes.geological_forms]` in TOML. Unknown,
non-finite and non-positive settings are rejected. Defaults are experimental
engineering choices, not tuned archaeological thresholds.

## Candidate evidence and review

Each candidate records a polygon footprint, measurements, pass/version, resolved
parameters, grid spacing/CRS, explanatory text, alternative interpretations and
experimental status. Full-pipeline records also retain job/configuration identity;
file-based runs include the source DEM name, size and modification timestamp.
Scores in the 0.4–0.8 range rank contrast/shape evidence and are not probabilities.
Different families remain separate: no cross-family proximity fusion or
conversion to a depression class. Depression-specific roundness, rim and modern
infrastructure rejection do not discard roads/banks/platforms. This deliberately
leaves modern infrastructure and natural lookalikes for contextual review.

The map displays dashed candidate footprints. Inspect shows experimental status,
measurements and explanation. Saving a simple polygon preserves it as the finding
geometry. Outlines with holes remain in the immutable detection snapshot and use
a point finding because the investigation editor currently supports single rings.
GeoJSON notebook export/import retains prediction evidence separately from review.
The additive `b004` migration adds PostgreSQL enum member names for the new types;
existing records and legacy passes remain intact. Downgrade retains enum values.

## Validation and next release gates

Synthetic tests cover sloping-ground mounds, platforms, positive/negative linear
features, closed/open/NoData enclosures, regular/irregular arrangements, ridges,
hollows and scarps, flat planes, missing ground, metric resolution, bounds and
pipeline preservation. They do not establish precision or recall on real surveys.

Bounded timing command:

```sh
timeout 20s .venv/bin/python scripts/benchmark_discovery.py --size 1000
```

One local one-million-cell synthetic run took 0.259 seconds for shared
preprocessing plus all five passes, with 341.1 MiB peak process RSS. This includes
imports in peak memory but excludes downloads, native preprocessing, worker I/O,
and database writes. It is not a production-capacity claim.

Before removing experimental labels: acquire independently reviewed regional
examples and hard negatives; use the existing spatially separated benchmark
contract; measure each family separately, including missed features, duplicates,
false positives per area and review effort. Add centerline/network extraction,
broken/rectilinear enclosures, drainage/landslide-context models, cross-tile and
cross-scan deduplication only with corresponding evidence and tests.

Method context: [USGS landform classification](https://www.usgs.gov/ngp-standards-and-specifications/elevation-derived-hydrography-data-acquisition-specifications-16)
distinguishes landform shape classes; this implementation is a simpler local-relief
baseline, not Geomorphons. [scikit-image morphology documentation](https://scikit-image.org/docs/stable/api/skimage.morphology.html)
describes related connected-shape/morphological operations. These references do
not validate the chosen thresholds or archaeological interpretations.
