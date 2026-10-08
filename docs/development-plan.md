# Research-informed development plan

Status: implementation plan; Stage 1 is partially implemented and checked locally.
The first terrain slice is prepared for delivery on `develop`; production release
remains pending. The acceptance criteria below are release gates, not claims that
every item has passed. Later stages remain pending. This plan follows the CPU deployment
and delivery rules in `CLAUDE.md`.

## Objective and working assumptions

Make Lost Landscapes useful for investigating archaeological and unusual terrain
features: reveal morphology, compare independent evidence, record interpretations,
and measure whether automated suggestions actually help. A terrain anomaly is a
candidate observation, not a verified archaeological site, cave, or sinkhole.

Keep the default explorer usable without PostGIS, Redis, or a worker. Preserve
the existing LiDAR, aerial, comparison, and 2D/3D workflows. Additional processing
must fit the bounded CPU renderer and use native geospatial tools where needed.

Confirmed product direction:

- Give manual exploration and ranked automated shortlists equal importance.
- Cover old roads, settlements, mining/industrial remains, and unusual natural
  terrain; do not narrow the product to a single feature family or region.

Use the imported Pittsburgh-area data as the initial engineering fixture for
rendering and interaction checks, not as a universal scientific benchmark.
Select additional representative regions and reviewed examples as the benchmark
develops. Broad product scope does not imply a model or geometric threshold
transfers to every landscape; release detectors with explicit evaluated coverage.

## Implementation order and milestones

The stage numbers below group capabilities; the delivery sequence here determines
what to build next. Benchmark design starts early, and the first automatic review
workflow ships before the full detector suite. Manual exploration and automated
suggestions share the same investigation records and evidence tools.

| Delivery | Concrete scope | Completion gate | Dependency |
| --- | --- | --- | --- |
| A — Release the existing terrain slice | Review the local slope, local-relief, directional-light and provenance changes; retain angled 3D, terrain exaggeration and aerial comparison. | Required CI passes; desktop/mobile review covers 3D and layer switching; limitations documented; PR ready for owner review. | Current local implementation |
| B — Establish the evaluation contract | Define survey/region manifests, feature families, evidence labels, uncertain and negative examples, spatial split rules and baseline metrics. Select candidate evaluation areas without claiming they are labeled. | Versioned schema and example fixtures; no tuning against held-out areas; missing detections count as misses. | Can proceed alongside A |
| C — Finish terrain coverage and advanced views | First implement compatible-source neighborhoods; then genuine SVF, positive/negative openness and VAT in separate changes. Use bounded preprocessing and cache products where interactive calculation is too expensive. | Continuity across compatible sources; gaps remain explicit; reference-output comparisons and CPU/memory measurements pass. | A |
| D — Save and measure investigations | Versioned local investigation storage, migration of existing saves, point/line/polygon drawing, notes, evidence, measurements, elevation profiles and import/export. | Existing saves survive migration; reload and round-trip export preserve records; measurements ignore visual exaggeration. | A; may proceed alongside C |
| E — Make scanning dependable | Fix job status handling and worker cancellation; audit physical units and misleading algorithm labels; add bounded scan submission, shortlist review and save-to-investigation. Preserve the existing detector's stated limitations. | Real worker completion, failure and cancellation tests; each result records source, settings and algorithm; manual and machine findings use the same review flow. | B, D |
| F — Add contextual evidence and field review | Introduce a source-adapter contract, then initial historical map/aerial and geological/mining sources; record attribution and dates; export field packets and import observations. | Demonstrated desk review → field export → observation import; outages leave terrain usable; IDs and geometry round-trip. | D |
| G — Expand geometry detection incrementally | Deliver raised and depressed features first, linear features next, then enclosures/repeated patterns and geological families. Each family has independent parameters and explanatory measurements. | Each family passes synthetic tests and a reviewed regional benchmark before being promoted beyond experimental use. | B, C, E; appropriate contextual evidence from F |
| H — Publish measured performance | Complete the evaluation runner and reports alongside the first new family; extend it for every subsequent family. Measure accuracy, duplicates, false positives per area and review effort against baselines. | Reproducible held-out results with regional limits and failures; no skipped misses or neighboring-feature leakage. | B plus reviewed examples; runs alongside G |
| I — Add selective machine learning | Train only where reviewed labels and measured baseline weaknesses justify it; version models, preprocessing and intended regions together. | Demonstrated held-out benefit and acceptable CPU inference cost; reproducible training and rollback. | G, H and sufficient labels |

**First usable discovery milestone:** A + B + D + E. A user can explore in
angled 3D, inspect terrain layers, mark and measure a feature, run the bounded
existing scan, review its suggestions, and save either kind of finding with
evidence. This milestone does not claim broad archaeological detection accuracy.

**Complete non-ML milestone:** A–H, including all Stage 1 follow-ups and evaluated
feature families. ML is a separate evidence-dependent milestone, not a prerequisite
for a useful explorer.

### Immediate next work

1. Review the current diff against Stage 1's first-slice acceptance criteria;
   resolve any outstanding findings and update the recorded validation.
2. Run required checks in the supported native-tool environment. Preserve the
   distinction between locally skipped checks and checks actually passed in CI.
3. Package A as a focused commit on `develop` and a PR to `master` when delivering
   the implementation. Include screenshots of angled 3D and mobile controls,
   test results and the remaining Stage 1 limitations. Owner merges.
4. Begin B's manifest/label contract and D's persistence contract before adding
   more UI or detector output formats. Define one investigation schema with
   geometry, observations, proposed interpretations, evidence, provenance,
   review state and revisions; keep detector scores separate from human judgment.
5. Implement C's compatible-source neighborhoods before advanced views that need
   larger terrain neighborhoods. Inspect source CRS, grid alignment, resolution
   and vertical metadata explicitly; unsupported combinations remain unavailable.

### Scope decisions and open dependencies

- Angled 3D with shaded relief remains a first-class workflow in every delivery.
  Directional hillshade is supported; physically cast shadows are not currently
  implemented and are not required by this roadmap.
- Start investigations locally with export/import. Shared accounts, permissions
  and server synchronization need an explicit design before shared writes ship;
  they do not block local investigations or automatic shortlist review.
- Regional context providers, accessible evaluation data and expert/field labels
  remain research dependencies. Confirm access and terms when selecting actual
  sources; do not invent coverage or treat imported data as reviewed truth.
- New detector families stay experimental until evaluated. Broad discovery means
  supporting multiple families over time, not promising to identify every kind
  of interesting feature automatically.
- Track progress per delivery as planned, implemented locally, validated,
  PR-ready, or released. A written plan or passing software test does not mark
  a feature released or scientifically validated.

## Research basis

Archaeological interpretation combines terrain visualizations with historical
maps, aerial imagery, geology, soils, and existing records. Record feature
geometry, interpretation rationale, sources, and uncertainty. Visibility,
interpretation confidence, and dating confidence are different properties [1].

Tree throws, modern land use, missing data, and acquisition or processing
artifacts can resemble archaeological features. Ground-point coverage and raster
cell size are different; a fine grid does not guarantee fine measured detail [2].
Useful quality products include ground-point density and terrain-model confidence
where the source data support them [3].

Field review can improve models and still leave cases unresolved. One burial-mound
study checked 237 candidates and used the results to improve local filtering and
orthophoto classification [4]. Closed-depression studies likewise distinguish a
real depression from its explanation: roads and drainage barriers can create
false basins, and DEM morphology alone does not establish karst origin [5, 6].

Evaluation should reflect the feature: localized mounds and extensive field
systems need different matching rules [7]. These principles guide the proposed
features below; the roadmap is our engineering proposal, not a published recipe.

## Stage 1 — Reliable terrain visualization foundation

**Status:** PARTIAL — first visualization slice implemented and checked locally.
**Depends on:** existing imported DEM renderer and disk cache.

The first slice includes slope, signed local relief with 10/25/50 m square
half-widths, eight directional-light presets, source provenance, and live explorer
controls. Genuine SVF/openness/VAT, cross-source neighborhoods, and broader
performance evaluation remain follow-ups; Stage 1 is not complete.

Deliver existing multidirectional relief plus slope, directional hillshade, and
signed simple local relief presets in the main explorer. Directional hillshade
offers eight compass azimuths in 45° steps with light altitude fixed at 45°.
Simple local relief means elevation minus a square-neighborhood mean [8]; it is
not a reconstructed terrain model or an archaeological classifier. Offer square
half-widths of 10, 25, and 50 metres, rounding up to whole source cells. Display
positive and negative residuals distinctly and explain the scale. Preserve
existing relief as the default.

- Parameterize derivative tiles with validated, bounded settings and include
  visualization, parameters, algorithm revision, and source revision in cache
  identity. Keep cached requests outside the expensive rendering queue.
- Calculate inspection derivatives on the native source grid before display
  reprojection. Compute slopes from projected ground spacing and meter-based
  elevations; the display grid must not determine the analysis neighborhood.
  Detail layers use supported local sources from zoom 14 onward. Bound native
  window size, source work, kernel size, and concurrency; publish the actual
  supported limits with the implementation rather than silently approximating
  unsupported requests with coarser data.
- Require a complete valid neighborhood for inspection derivatives. The first
  implementation deliberately leaves transparent strips at missing-data and
  source-file edges; it does not stitch neighboring source files. Padding a
  requested display tile within one source prevents display-tile seams but does
  not solve source boundaries. Explicitly distinguish regional fallback terrain
  used for context/3D shape from detailed inspection coverage.
- Show available source attribution, resolution, units, and processing context.
  Missing acquisition dates, classification quality, or vertical-datum metadata
  must stay unknown rather than being inferred from filenames or display zoom.
- Keep settings understandable in LiDAR and comparison modes; preserve map
  alignment and existing navigation on desktop and mobile.

**Acceptance criteria:** synthetic flat and inclined surfaces produce expected
slope; positive/negative test landforms have the correct residual sign;
overlapping display tiles from the same source agree; missing neighborhoods
remain transparent instead of creating false features; parameter/source changes
cannot reuse incompatible cached tiles. Native-grid calculations retain their
physical scale across display zooms. Real-data review covers layer switching,
comparison, 2D/3D, coverage boundaries, loading/errors, and mobile controls.
Record cold/warm tile timings and memory behavior against current relief on the
same machine and area; investigate regressions before expanding defaults.
Run relevant Python tests, Ruff, ESLint with zero warnings, TypeScript, and the
production build. Report any unavailable native-tool checks explicitly.

**Validation recorded for the first slice:** local Python suite: 197 passed and
72 skipped, including checks requiring unavailable native tools and optional ML
dependencies; Ruff,
frontend ESLint, TypeScript, and production build passed. Browser checks at
1440 px and 390 px found zero JavaScript errors or horizontal overflow and
successful terrain API requests. Screenshot review identified a mobile comparison
control overlap, which was fixed and rechecked. Additional browser checks passed
for 3D comparison, zoom-to-detail guidance, source metadata and an empty catalog.
These results do not establish
scientific detection accuracy or complete the remaining Stage 1 acceptance criteria.

A local single-process sample used ten copied USGS Western Pennsylvania DEMs,
the point 40.499, −79.970, zooms 14/16/18, and a fresh temporary PNG cache.
Across those three tiles, first renders were 195–479 ms for existing relief,
146–918 ms for slope, 162–733 ms for 25 m local relief, and 190–712 ms for
directional hillshade. Warm in-process disk-cache reads were 0.09–0.13 ms; these
are not HTTP or browser latency measurements. Peak process RSS was about 292 MiB.
One machine, location and request sequence cannot establish production latency
or concurrent memory use. Native source processing is intentionally more
expensive than the existing display-grid shading at wider views.

Strict complete-neighborhood support left only 28%, 42%, and 93% of the sampled
local-relief tiles visible at zooms 14, 16 and 18, respectively. These figures
depend on source holes/borders and the selected location; they are not measures
of LiDAR coverage or detector accuracy. Source mosaicking and explicit quality
visualization remain important follow-up work.

**Stage 1 follow-up deliverables:** add genuine sky-view factor, positive and
negative openness, and a documented visualization-for-archaeological-topography
(VAT) composite using established algorithms and blending settings [8]. These
are visualization improvements in their own right, not work deferred until new
detectors. Add mosaic-aware source-edge support for compatible neighboring DEMs,
with explicit handling of incompatible resolution, projection, vertical reference,
and nodata. Validate against the official RVT implementations or equivalent
reference outputs on shared fixtures; test cross-source continuity without
inventing elevations at unsupported boundaries. Retain strict transparency where
the required neighborhood cannot be established. Release these follow-ups as
separate changes after the initial bounded derivative implementation is verified.

**Parallel early work:** define the benchmark protocol and choose candidate
regions before detector tuning begins (see Stage 5). Selecting evaluation data
is an early dependency even though the full evaluation harness lands later.

## Stage 2 — Measurements and persistent investigations

**Status:** pending. **Depends on:** Stage 1.

Add map-drawn elevation profiles with distance/elevation axes, height/depth,
length and area measurements, and visible source/coverage limitations. Measurements
must use ground coordinates and unexaggerated elevations, not screen pixels or
the 3D exaggeration setting.

Evolve saved candidates into investigations with points, lines, and polygons.
Store observed morphology separately from proposed explanations. Support notes,
alternative interpretations, source links, reproducible visualization settings,
author/date, and revision history. Keep machine score, human confidence, and
verification status separate; support unresolved outcomes. Dating stays unknown
unless supported by explicitly recorded evidence.

Define a persistence contract and migration for existing browser saves first.
Preserve a terrain-only local workflow and provide import/export; add server
persistence deliberately without making optional analysis services necessary
for browsing. Shared writes require an explicit identity/access design.

**Acceptance criteria:** existing saves migrate without loss; reload and
export/import preserve geometry and evidence; edits retain original predictions;
profiles handle mixed coverage/nodata and use correct units; measurements do not
change when display exaggeration changes. An investigation can be reviewed and
left unresolved without implying verification.

## Stage 3 — Historical context and field review

**Status:** pending. **Depends on:** Stages 1–2 and region-specific source choices.

Add source adapters for dated historical maps and aerial imagery, followed by
regional geology, soils, hydrography, land-use, and known-site/mining inventories
where accessible. Start with one reliable source of each needed type rather
than promising universal coverage. Retain attribution, dates, resolution,
licensing/access constraints, and source links. Allow transparent overlays or
synchronized comparison without hiding temporal and georeferencing differences.

Provide a field packet with candidate geometry, map context, evidence, and stable
IDs; export GeoJSON and a suitable field waypoint format. Import observations,
photos/references, reviewer and date, with supported/rejected/unresolved outcomes.
Distinguish field observation from specialist interpretation or archaeological
dating. Maintain private/shared visibility intentionally for saved investigations.

**Acceptance criteria:** demonstrate a complete desk-review → export → field-note
import → revised interpretation cycle. Source outages leave terrain usable;
records retain attribution and dates; exports round-trip IDs and geometry without
silently changing coordinate order or reference system. No source is presented
as exhaustive ground truth.

## Stage 4 — Feature-family geometry detectors

**Status:** pending. **Depends on:** Stages 1–2, regional evidence, and the early
Stage 5 benchmark specification and locked evaluation split.

Develop independent detectors and regional presets for selected families:

- Raised features: mounds, platforms, terraces, spoil heaps.
- Depressions: pits, extraction workings, closed basins; classify origin later.
- Linear/network features: banks, ditches, walls, hollow ways, former roads.
- Enclosures and repeated patterns: rectilinear boundaries and field systems.
- Geological morphology where appropriate: landslide scarps and deposits,
  drainage-related features, and karst-like depressions with contextual evidence.

Use multi-scale shape, slope, curvature, local relief, and spatial relationships
as appropriate. Reuse the genuine sky-view factor, openness, and composite
visualizations delivered by Stage 1 follow-ups with their recorded provenance.
Return geometry and explanatory measurements, not just a point and opaque score.
Keep an unclassified anomaly option and explicit hard-negative categories.

**Acceptance criteria:** each family has synthetic correctness tests and a
regional reviewed evaluation; documented scale limits; negative examples; and
measured benefit over the existing baseline. A depression detector must not
automatically claim a cave or archaeological feature. Context filters must be
tested for lost true positives as well as removed false positives.

## Stage 5 — Reproducible scientific benchmark

**Status:** protocol starts alongside Stage 1; full harness pending.
**Depends on:** independently reviewed labels and stable detector outputs.

Create a versioned dataset manifest with survey provenance, coverage, regional
boundaries, labels, reviewer evidence, and uncertainty. Preserve original labels
and adjudication history. Include reviewed negative areas and difficult natural,
modern, agricultural, and processing-artifact lookalikes. An unlabeled location
is not automatically negative.

Lock spatially separated training, validation, and held-out test regions before
tuning. Prevent neighboring tiles or the same physical feature from leaking
across splits. Where feasible, obtain independent or blinded review and record
disagreement. Use representative field validation and acknowledge its limits.

Match discrete objects by a justified location/footprint rule; evaluate elongated
or extensive patterns with appropriate geometry/coverage metrics [7]. Count
misses, duplicates, and wrong-family predictions. Report per-family precision,
recall, false positives per square kilometre, and reviewer time per useful
candidate; stratify by region, source resolution, terrain and vegetation.
Evaluate existence detection separately from proposed origin/classification.

**Acceptance criteria:** runs reproduce from dataset/version/config manifests;
an empty prediction set records misses rather than skipped successes; a nearby
wrong feature does not count as a hit; results include uncertainty/sample size
and comparison with simple baselines. Define achievable numeric targets after
the baseline is measured, not retrospectively after viewing test results.
Keep held-out data untouched during threshold selection.

## Stage 6 — Locally trained machine learning

**Status:** pending. **Depends on:** Stages 2–5 and sufficient reviewed labels.

Train narrow models for selected feature families and data conditions. Compare
them with geometry baselines using the same held-out protocol. Incorporate
validated false positives and uncertain-review queues; do not recycle predictions
as verified training labels. Consider multi-derivative inputs and independent
aerial/context evidence where the regional data justify them [4].

Version model, preprocessing, label set and intended region together. Calibrate
scores on validation data and expose them as model scores unless probability
calibration is demonstrated. Measure CPU inference cost and permit optional
offline training without making production dependent on a GPU.

**Acceptance criteria:** measurable held-out improvement at a useful review
workload; documented failure cases and regional limits; reproducible training
and inference; model rollback; no regression to default terrain browsing.

## Foundational follow-up issues

These are known audit findings to reproduce and fix in focused changes. They
are not marked resolved by this plan or by adding visualization presets.

| Finding | Required correction and acceptance evidence | Timing |
| --- | --- | --- |
| API statuses are lowercase while the explorer checks uppercase values | Establish one status contract; completion/failure clear busy state in integration coverage. | Before promoting scans in the main explorer |
| Cancellation updates state without reliably stopping worker work | Cooperative cancellation at bounded processing checkpoints; stop scheduling work and avoid later success overwriting cancellation. | Before expanding scan workloads |
| A sky-view-factor fallback is mislabeled | Return an explicit unavailable/alternative result or implement real SVF; output metadata identifies the actual algorithm. | Before derivative/detector use of SVF |
| Scale settings mix meters and pixels | Audit every neighborhood and size threshold; convert through raster spacing and test equivalent ground features at different resolutions. | Stage 1 for new layers; before Stage 4 for inherited detectors |
| Sinkhole-oriented gates suppress other feature families | Make family-specific requirements explicit; positive archaeological features must not require depression or karst evidence. | Before Stage 4 |
| Known-site validation accepts any nearby result and skips missing detections | Replace accuracy claims with the Stage 5 protocol; retain software smoke tests separately. | Protocol now, harness in Stage 5 |

## Delivery and review

### Delivery A — terrain foundation

Implemented: slope, signed local relief, directional hillshade, source metadata,
desktop/mobile controls and the research-informed roadmap. Existing angled 3D
terrain and aerial comparison are preserved. Local validation was repeated before
the delivery commit: 197 Python tests passed, 72 skipped, Ruff 0.15.7 and frontend
ESLint passed, and TypeScript plus the production frontend build passed. Native
tool validation in GitHub CI is a separate gate. The prior browser checks and
terrain performance measurements are recorded under Stage 1 above.

Remaining Stage 1 work includes compatible-source neighborhoods and genuine
SVF/openness/VAT. Delivery A does not complete the entire stage. The next delivery
is B: a versioned evaluation manifest and label contract with example fixtures,
spatial split rules and meaningful miss/duplicate handling.

Deliver stages as small reviewable changes; a stage can span multiple PRs.
Documentation status and validation results must reflect actual implementation.
Development pushes go to `develop`, with PRs targeting `master`. The owner merges;
deployment follows repository CI. Preserve production data, host environment,
and existing TLS configuration. Do not couple work to the desktop worker.

## Primary references

1. Lozić and Štular, *Documentation of Archaeology-Specific Workflow for Airborne
   LiDAR Data Processing* (2021): https://www.mdpi.com/2076-3263/11/1/26
2. Historic England, *Using Airborne Lidar in Archaeological Survey* (2018):
   https://historicengland.org.uk/images-books/publications/using-airborne-lidar-in-archaeological-survey/
3. *Airborne LiDAR Point Cloud Processing for Archaeology. Pipeline and QGIS
   Toolbox* (2021): https://www.mdpi.com/2072-4292/13/16/3225
4. *The Synergy between Artificial Intelligence, Remote Sensing, and Archaeological
   Fieldwork Validation* (2024): https://www.mdpi.com/2072-4292/16/11/1933
5. Doctor and Young, *An evaluation of automated GIS tools for delineating karst
   sinkholes and closed depressions from 1-meter LIDAR-derived digital elevation
   data* (2013): https://www.usgs.gov/publications/evaluation-automated-gis-tools-delineating-karst-sinkholes-and-closed-depressions-1
6. USGS, *Assessment and validation of depressions in digital elevation models
   from multiple elevation data sources* (published 2025):
   https://pubs.usgs.gov/publication/sir20245134/full
7. Fiorucci et al., *Deep Learning for Archaeological Object Detection on LiDAR:
   New Evaluation Measures and Insights* (2022):
   https://www.mdpi.com/2072-4292/14/7/1694
8. ZRC SAZU / Relief Visualization Toolbox, official software and method reference:
   https://www.zrc-sazu.si/en/rvt and
   https://rvt-py.readthedocs.io/en/latest/listofvis_slrm.html
