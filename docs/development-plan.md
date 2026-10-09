# Research-informed development plan

Status: Stage 1's bounded terrain visualization implementation and reference/
performance checks are complete for delivery on `develop`. Production release
is pending. The evaluation foundation, local investigations/measurements, and scan lifecycle/
shortlist workflow are implemented. The full scientific evaluation harness,
historical context, richer investigation tools and broader detectors remain incomplete.
The acceptance criteria below are release gates, not claims that
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

1. Delivery A was committed and pushed to `develop` as `e0da889`; native-tool
   GitHub CI passed. Draft PR #15 tracks the work; production release is pending.
2. Delivery B now supplies the manifest/label contract, synthetic fixtures,
   spatial validation and bounded point-scoring baseline described in
   [the evaluation protocol](evaluation-protocol.md). Real-data cohort selection
   and review remain dependencies; synthetic results are not accuracy evidence.
3. Delivery C1 now implements compatible-source terrain neighborhoods with
   explicit provenance and grid checks. Delivery C2 adds genuine SVF and both
   openness views with pinned RVT reference comparisons. Delivery C3 adds VAT and
   expanded performance checks. Stage 1 is implemented within documented limits.
4. Begin D's persistence contract before adding more investigation UI or detector
   output formats. Define one investigation schema with
   geometry, observations, proposed interpretations, evidence, provenance,
   review state and revisions; keep detector scores separate from human judgment.
5. Validate each delivery, commit and push to the same `develop` branch, then
   inspect CI before proceeding. Update the existing draft PR as scope grows;
   the owner controls merging to `master`.

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

**Status:** IMPLEMENTED — bounded terrain views, source joins, reference comparisons
and local performance checks delivered in A/C1/C2/C3; production release pending.
**Depends on:** existing imported DEM renderer and disk cache.

The first slice includes slope, signed local relief with 10/25/50 m square
half-widths, eight directional-light presets, source provenance, and live explorer
controls. Delivery C1 adds compatible-source neighborhoods; C2 adds genuine SVF
and positive/negative openness; C3 adds documented VAT and expanded local
performance checks. Source-quality limitations, real missing ground, unknown
joining metadata and workload caps remain explicit. Production capacity testing
and additional regional data are ongoing follow-ups, not implied by this status.

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
  implementation left transparent strips at missing-data and source-file edges.
  Delivery C1 joins compatible declared sources; incomplete neighborhoods and
  incompatible or unknown source boundaries still remain transparent.
  Explicitly distinguish regional fallback terrain
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
of LiDAR coverage or detector accuracy. Delivery C1 provides source mosaicking
when verified compatibility metadata is available; explicit quality visualization
and wider real-data validation remain follow-up work.

**Advanced-view deliverables (completed in C2/C3):** genuine sky-view factor,
positive and negative openness, and a documented visualization-for-archaeological-topography
(VAT) composite using established algorithms and blending settings [8]. These
are visualization improvements in their own right, not work deferred until new
detectors. Delivery C1 supplies mosaic-aware source-edge support for compatible
neighboring DEMs; incompatible resolution, projection, vertical reference and
missing support remain separate. Validate advanced visualizations against the
official RVT implementations or equivalent
reference outputs on shared fixtures; test cross-source continuity without
inventing elevations at unsupported boundaries. Retain strict transparency where
the required neighborhood cannot be established. Release these follow-ups as
separate changes after the initial bounded derivative implementation is verified.

**Parallel early work:** define the benchmark protocol and choose candidate
regions before detector tuning begins (see Stage 5). Selecting evaluation data
is an early dependency even though the full evaluation harness lands later.

## Stage 2 — Measurements and persistent investigations

**Status:** local core implemented in Delivery D; richer history, geometry editing and shared server persistence remain pending. **Depends on:** Stage 1.

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

**Status:** version 1 contract and synthetic point baseline implemented in
Delivery B; reviewed real datasets and the full harness remain pending.
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

Remaining Stage 1 work at this delivery included compatible-source neighborhoods
and genuine SVF/openness/VAT. Delivery A did not complete the entire stage. The next delivery
is recorded below.

### Delivery B — evaluation contract and point baseline

Implemented: strict version 1 models for source provenance, geographic regions,
spatial splits, label review history and reproducible prediction inputs; offline
validation/schema/scoring commands; explicitly synthetic fixtures; and
[the evaluation protocol](evaluation-protocol.md). The point baseline enforces
one-to-one same-family matching, counts empty predictions as misses and duplicate
suggestions as false positives, and excludes unresolved or unreviewed areas.
Nonpoint labels are stored but cannot silently enter point scoring.

The unit coverage exercises spatial leakage, physical-feature duplication,
projection and evidence validation, changed-manifest rejection, false negatives,
wrong-family results, duplicates, exclusions and CLI behavior. Candidate real-data
cohorts are documented as selection targets, not acquired or reviewed benchmarks.
No detector accuracy claim or model training is included. Delivery C follows,
starting with compatible-source terrain neighborhoods.

Local validation for this delivery: 30 new benchmark tests passed; the full unit
suite passed with 227 tests and 72 native-tool/optional-dependency skips. Ruff
0.15.7 passed. The documented validate and score commands ran successfully against
the committed synthetic examples. Native-tool tests run separately in GitHub CI.

### Delivery C1 — compatible-source terrain neighborhoods

Implemented: bounded neighborhood reads across aligned native grids with the
same declared survey ID, vertical datum and metre elevation units. Projection,
spacing and pixel alignment must also agree. Scale/offset is applied before
joining; deterministic overlap preference is shared across all source windows.
Neighbors outside the visible tile are considered when the calculation needs
their measured cells. Missing or incompatible support stays transparent. Cache
identity advances to `native-v3-mosaic` and source metadata changes invalidate it.

The importer accepts verified survey/datum/unit declarations and preserves
external masks and auxiliary metadata. The source panel explains whether a file
can participate in joining. Existing unknown metadata is not silently upgraded.
All ten DEMs in the local demo lack complete joining declarations, so this
delivery intentionally does not claim improved coverage for that dataset.

Validation: 24 new tests compare four-tile edge/corner joins to a continuous
reference for slope, hillshade and all local-relief radii. They cover missing
ground, outside-view halos, incompatible datums/grids/units, scaled elevation,
overlap order, processing limits, metadata cache invalidation and import masks.
The full local suite passed with 251 tests and 72 native-tool/optional-dependency
skips; Ruff, ESLint, TypeScript and the production build passed.
Browser checks passed for desktop/mobile terrain views, the new provenance
message, 3D comparison and empty coverage, with no JavaScript errors, failed
terrain API requests or horizontal overflow.

A repeat of the Stage 1 ten-DEM single-process sample (still unjoined because
provenance is incomplete) measured 135–330 ms cold relief renders, 102–614 ms
slope, 152–472 ms local relief and 96–536 ms directional hillshade, with about
279 MiB peak RSS. These limited measurements are not concurrent production
benchmarks or proof of speedup. Joined synthetic correctness tests exercise the
new path separately. The window/source/read caps remain enforced.

At the end of C1, the remaining work was genuine sky-view factor, positive/negative
openness and VAT. These are delivered in C2/C3 below.

### Delivery C2 — SVF and positive/negative openness

Implemented native physical horizon searches in 16 directions, with 10/25/50 m
radius controls, legends and zoom guidance. New views require zoom 16 or closer,
at most 128 native radius cells and at most 240 million sampled-cell comparisons
per request. Missing neighborhoods remain transparent and compatible DEM joins
are reused. Display exaggeration does not change the scientific quantities.

The 18 pinned official RVT reference cases agree over supported interiors within
0.000002 SVF and 0.0002° openness. Additional tests cover analytic surfaces,
rectangular cells, sign behavior, gaps, tile joins, limits and low-zoom requests.
Local validation: 279 tests passed, 72 skipped for native tools/optional
dependencies; Ruff, frontend ESLint, TypeScript and production build passed.
Browser review passed all new views, radius switching, mobile layout and 3D
comparison with zero JavaScript errors, failed terrain requests or overflow.
Methods and reproduction commands are in [advanced terrain](advanced-terrain.md).

VAT and the expanded performance evaluation follow in C3.

### Delivery C3 — VAT and expanded performance checks

Implemented the four-component general-terrain VAT composite with fixed RVT
normalization ranges, standard blend/opacity semantics and 315°/35° hillshade.
It uses the selected physical search radius for both horizon components and
preserves missing support. Brightness is explicitly a visualization rather than
a physical measurement or detection score. The precise recipe is published in
catalog metadata, the UI and [advanced terrain documentation](advanced-terrain.md).

Eighteen official-function reference composites agree within 0.00002 normalized
brightness; observed maximum difference was 0.00000215. The generator records
the reference revision and settings, including background copies needed to
preserve opacity when calling RVT's in-place overlay function.

The repeatable benchmark covers two locations, three zooms, three radii, all four
advanced views and legacy relief, on imported and synthetic joined terrain.
Three runs cover 208 cold cases and their byte-identical warm-cache repeats,
including one/two-worker comparisons. No sampled tile was entirely transparent.
Peak process RSS was 168–194 MiB; imported advanced-view cold p95 was 966–1266 ms.
Raw results are in `docs/benchmarks/`; these are local render/cache measurements,
not HTTP response times or production capacity claims.

Local validation: 300 tests passed and 72 native-tool/optional-dependency checks
were skipped; Ruff, frontend ESLint, TypeScript and production build passed.
Final browser checks passed SVF, both openness views, VAT, radius switching,
2D/3D, aerial comparison and mobile layout with no JavaScript errors, failed
terrain requests or horizontal overflow. Angled 3D remains available for all views.
Deliveries D and E are now implemented below; the next planned delivery is F, historical context and field review.

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

### Delivery D — implemented: local investigations and measurements

Named device-local investigations now contain manual points, lines and areas,
notes, evidence references, review states and saved terrain context. WGS84
ellipsoidal measurements and native DEM profiles include missing-data handling,
source metadata and CSV export. Versioned GeoJSON export/import preserves findings;
legacy saved candidates migrate without deleting the original copy. Desktop and
mobile drawing, persistence and export workflows have been exercised. See
[investigations.md](investigations.md) for bounds and limitations. Shared accounts,
server synchronization, attachments and geometry vertex editing remain later work.

### Delivery E — implemented: scan lifecycle and shortlist review

API job states normalize consistently in frontend clients. The main viewer
restores scan tracking after refresh, supports cancellation/reconnect, clears
terminal jobs, and reports partial failures. The specialist viewer uses a single
bounded polling subscription rather than conflicting WebSocket retries. Consumer
scans share the bounded submission and queue-failure path.

Cancellation and worker progress/result writes serialize on the job row. Pending
work is revoked; running work stops at cooperative phase boundaries. Native work
already in progress may finish before stopping. Scan-specific file paths prevent
cross-scan deletion/cleanup, and scans preserve prior detections and terrain.
All-failed tile runs report failure rather than successful completion.

The current-view shortlist supports inspecting candidates and saving immutable
prediction snapshots into investigations, with independent human review/notes.
Repeated saves are idempotent per candidate within an investigation. New worker
results carry originating job/configuration metadata. Depression-specific
classification remains unchanged; broader feature families are Delivery G.

Later work includes shared server persistence/identity, attachments, richer edit
history and geometry editing, cross-scan physical-feature deduplication, and
production queue load/worker-crash recovery testing. Next planned delivery is F,
historical context and field-review tools.
