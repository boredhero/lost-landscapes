# Lost Landscapes

Deployment: https://anomalies.martinospizza.dev on `boredhero.dyndns.org`.

A LiDAR terrain explorer built from Lost Landscapes. The first version focuses on a
clear map interface and high-resolution bare-earth terrain. It does **not** yet
detect or verify archaeological ruins.

## Explore

- Open directly onto an imported study area, without a splash screen or mandatory scan.
- Switch between **LiDAR**, **Aerial**, and a synchronized **Compare** divider.
- Use visible 2D/3D, zoom, north reset, tilt, and elevation exaggeration controls.
- Inspect terrain candidates and save places on the current browser/device.
- Search imported study areas, US ZIP codes, or `latitude, longitude`.
- When analysis is enabled, submit a bounded area and keep using the map while it runs.

The original specialist interface remains at `/playground`, loaded separately.
The default preview works without PostGIS, Redis, or a detection worker.

### Terrain inspection views

Open **Terrain controls** to switch between the default Landscape view,
Slope, Local relief, and Directional light. Local relief shows signed elevation
relative to a square neighborhood mean, with 10, 25, or 50 metre half-widths
(rounded up to source cells). Blue indicates lower ground and orange higher
ground; the fixed colour scale saturates at −2/+2 m. Slope uses a fixed
0–60° scale. Directional light offers eight compass directions at 45° altitude.
These are visualization aids, not archaeological classifications.

**Sky-view factor**, **Positive openness** and **Negative openness** inspect the
surrounding horizon in 16 directions, using 10/25/50 m search radii. They require
zoom 16 or closer and bounded native support. Openness is displayed over 60–120°,
with negative openness using reversed shading; flat ground is 90°. SVF is shown
over 0–1. See [advanced terrain methods and reference checks](docs/advanced-terrain.md).

**Archaeological topography (VAT)** blends hillshade, slope, positive openness
and SVF using fixed general-terrain settings. It shares the horizon radius and
zoom limits; its brightness is a visual composite, not a detection score.

Inspection layers calculate on the native DEM grid before resampling for the
map. They use only eligible local north-up projected metre rasters with source
spacing at most 5 m, and are available at zoom 14–18 (16–18 for horizon views; higher map zooms enlarge
the final tile). Exaggerating the 3D view does not change their calculations.
The data panel reports source eligibility, native spacing, effective neighborhood
size and elevation units. Undeclared elevation units are explicitly assumed to
be metres; acquisition dates and vertical references remain unverified.

Complete neighborhoods are required. Neighboring rasters can supply measured
cells across file boundaries when their declared survey ID, vertical datum,
metre elevation units, CRS, spacing and pixel alignment agree. Missing metadata
or incompatible sources leave unsupported edges blank. No elevations are
interpolated across missing ground, and no vertical-datum conversion is attempted.
Overlaps use deterministic source priority after applying band scale/offset.
Each native working window is capped at four million cells, with at most 32
contributing files. Per-request accounting bounds both native reads (including
overlaps) and processing windows to eight million cells; a neighborhood that
exceeds its budget is skipped rather than partially used or silently coarsened.
Regional fallback elevation never
enters these inspection calculations. Tiles are cached by source, algorithm and
visualization settings.

For a new import, declare verified common survey provenance with
`--survey-id` and `--vertical-datum` on `scripts/import_study_area.py`. If the
source omits elevation units, `--elevation-units m` explicitly declares metre
elevations; it does not convert them. These options write `LL_SURVEY_ID`,
`LL_VERTICAL_DATUM` and band-unit metadata to the imported copies. Conflicting
existing declarations are rejected, and external masks/auxiliary metadata are
preserved. Only group files from the same verified acquisition/processing survey.
Existing imports with unknown provenance remain usable individually; they are
not automatically declared compatible. The source panel explains eligibility.

The [staged development plan](docs/development-plan.md) covers remaining terrain
views, measurements, investigations, historical context, separate detector
families, scientific evaluation and locally trained models. Stage 1's bounded
terrain views and reference/performance checks are implemented; later product
stages and production release remain pending.

The [evaluation protocol](docs/evaluation-protocol.md) defines versioned survey,
region, label and prediction contracts. An offline validator checks evidence and
spatial splits; a bounded point baseline counts misses, duplicates and false
positives. Its included examples are synthetic and do not measure real-world
detection accuracy.

```sh
uv run --no-sync python -m lost_landscapes.benchmark validate tests/fixtures/benchmark/synthetic-manifest.json
uv run --no-sync python -m lost_landscapes.benchmark score-points tests/fixtures/benchmark/synthetic-manifest.json tests/fixtures/benchmark/synthetic-predictions.json
```

## Terrain and performance

The new `/api/landscape` renderer reads intersecting LiDAR DEMs into 512-pixel
Web Mercator tiles, with elevation and shaded relief available through zoom 18.
Multidirectional lighting uses padded neighboring samples. Missing elevations
are filled from regional terrain and feathered at coverage boundaries, rather
than converted into sea-level cliffs. RGB elevation is decoded before resampling.

Terrain and relief are cached on disk under a source revision; data changes
invalidate the tile URLs. Cached requests bypass the rendering queue. Slow
regional-elevation downloads use a separate pool from the bounded CPU renderer.
Imported raster overviews and pre-baking reduce work during exploration.

**No server GPU is required.** The browser renders the 3D scene. Comparison uses
two synchronized browser canvases, so it has a higher client GPU cost than one
map. The backend default is two terrain render threads, one tile being analyzed,
two derivative workers, and one Celery process in the CPU deployment.

### Data assumptions

Import projected, meter-based, single-band bare-earth DEMs with elevation in
meters. This prototype assumes compatible vertical references; it does not
perform vertical-datum harmonization. Source resolution and classification
quality limit visible detail. The original point-cloud ingestion pipeline is
retained for analysis, but the preview can use already-derived LiDAR DEMs.

## Local development

Python dependencies use `uv`; geospatial processing also needs PDAL, GDAL and
WhiteboxTools. The Docker image supplies native tools. For a local environment:

```sh
uv sync --frozen --extra dev --python 3.12
uv run --no-sync uvicorn lost_landscapes.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`. Vite proxies to the local API, not the old `.111`
compute node. `DATA_DIR` defaults to `./data`; copy `.env.example` to `.env` to
change settings. Keep `ENABLE_ANALYSIS=false` for the terrain-only preview.

### Import and prepare a real study area

```sh
uv run --no-sync python scripts/import_study_area.py /path/to/ground-dem.tif \
  --name 'Woodland study area' \
  --source 'USGS 3DEP · dataset name and acquisition year'

uv run --no-sync python scripts/prepare_landscape.py woodland-study-area \
  --min-zoom 12 --max-zoom 16
```

Pass several DEM paths to import adjacent tiles. The importer copies the files,
builds raster overviews, and records attribution and bounds in
`data/study-areas.json`. Existing destination files are not overwritten. Confirm
that the data is bare earth and its vertical units are meters before import.
The preparation command refuses oversized bakes and reports first-pass and
cached timing. Higher zooms can remain on demand or be baked for a smaller area.
Data files and generated tiles are intentionally excluded from Git. Preserve
file timestamps when transferring a prepared data directory (for example,
`tar --format=pax`) so source revisions remain stable between hosts.

## Single-host CPU deployment

`compose.cpu.yml` is isolated from Lost Landscapes and the host's other applications:
no fixed container names, GPU device mounts, exposed database ports, or `.111`
connections. The API binds only to `127.0.0.1:9750` for a reverse proxy or SSH
forward. It does not alter nginx or existing deployments.

```sh
cp .env.example .env
# Set POSTGRES_PASSWORD in .env; leave ENABLE_ANALYSIS=false for preview.
docker compose -f compose.cpu.yml up --build -d
```

This starts only the terrain API/UI. Put the imported `data/` directory beside
the compose file. To add the existing CPU detection pipeline, set
`ENABLE_ANALYSIS=true` and run:

```sh
docker compose -f compose.cpu.yml --profile analysis up --build -d
```

The profile adds PostGIS, persistent Redis, schema migrations, and one worker.
Memory limits total approximately 10.25 GiB for API, database, Redis and worker;
actual idle usage is lower. One fresh scan can still be expensive. The new UI
limits each request to a bounding rectangle no more than 4 km across and the
worker processes at most four source tiles. This can yield partial coverage;
it is not a promise to finish an entire viewport in a fixed time.

A terrain-only preview on the remote host can be viewed privately with:

```sh
ssh -L 9750:127.0.0.1:9750 noah@boredhero.dyndns.org
```

Then open `http://localhost:9750`. All application processing and storage stay
on that host. This is a browser access tunnel, not a dependency on the desktop.

## Validation and remaining work

```sh
uv run --no-sync pytest tests/unit/ -q
cd frontend && npm run build
```

Terrain regression tests cover fractional elevation encoding, nodata handling,
Web Mercator sampling, transparent coverage, and cache invalidation. Browser
checks should use real data and cover 3D, comparison alignment, 2D, mobile layout,
search, and error states.

The inherited detectors still classify depressions, caves, and related terrain
anomalies. Ruins-specific geometry detection, historical maps, field validation,
and vertical-reference harmonization are future work. A higher zoom limit alone
does not guarantee finer rendered mesh detail; assess it against real features.

## Origin

Derived from an earlier LiDAR terrain exploration project, retaining its Git
history and GPL-3.0-or-later license. The Python package is `lost_landscapes`.
The repository is public. `master` requires a pull request and passing CI,
including for administrators. Push development changes to `develop`. CI runs
Ruff, ESLint with zero warnings, and TypeScript first; only then do native
Python tests and the production frontend build run. Tests stop on first failure.

Merging develop into master triggers production CI and then deploys the exact
tested commit to the standalone CPU host. A dedicated SSH key can invoke only
the installed deployment script, with host identity pinned in GitHub secrets.
The script builds a commit-tagged image before replacing the API and restores
the previous image if health checks fail. Data and .env remain on the host. Compose reads DATABASE_URL and
POSTGRES_PASSWORD directly from that host-only environment file; neither value
is constructed in the checked-in Compose configuration.
Deployments run only on changes merged into master; there is no manual trigger. The host deployment entrypoint is
scripts/deploy_host.sh, installed separately from release files.

Dependabot checks uv, npm, GitHub Actions, and Docker every Monday at 09:00
America/New_York. Minor/patch updates are grouped per ecosystem; major updates
remain separate for review. Version-update PRs target master and run the same
CI checks. This schedule activates once .github/dependabot.yml reaches master.
Security updates are separate from this weekly version-update schedule.
