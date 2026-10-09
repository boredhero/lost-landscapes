# Investigations and measurements

Open the notebook (pencil button) to create named investigations and mark points,
lines, or single-ring areas. Drawing switches to a top-down map; finishing or
cancelling restores 3D when it was previously enabled. Click to place vertices,
undo the last vertex, and finish. Mobile users can close the panel while drawing.

Each finding stores its geometry, title, notes, evidence references, review state,
timestamps, and terrain-view context. Evidence references are text (including
URLs and map citations), not uploaded attachments. Investigations are private to
this browser's local storage, without an account or analysis worker. Export the
notebook as GeoJSON to back it up or share it. Import adds copies without replacing
existing investigations. Legacy saved candidates migrate into the first notebook;
the old storage is preserved. Storage errors are visible; export work before
leaving if saving fails. No server synchronization is implemented.

Measure a finding to calculate WGS84 ellipsoidal line length, polygon perimeter
and area, or point elevation. Lines receive 201 evenly spaced distance samples,
including endpoints, from nearest native DEM cells. Supported sources follow the
terrain inspection rules (local projected metre grids, spacing at most 5 m).
Masks, scale/offset, and missing coverage are respected. Regional terrain and
3D exaggeration never enter the measurements. Samples show source identity,
resolution, declared/assumed units, vertical datum and inventory revision.
Unknown elevations and source boundaries break the chart. Vertical datums are
not harmonized and this is not survey-grade measurement. Profiles export as CSV;
measurements and provenance are also retained in the GeoJSON backup. Refresh
measurements explicitly when source data changes.

Requests are limited to 500 vertices, 10 km of line/perimeter, 201 samples and 32
intersecting sources. Invalid or self-crossing polygons cannot be measured. The
notebook accepts up to 100 imported investigations with 1,000 findings each and
limits import files to 5 MB. Import validates geometry coordinates and profiles.

Validation: native synthetic DEM tests cover geodesic lengths/areas, scale and
offset, missing elevation and invalid inputs. Desktop/mobile browser checks cover
point/line/area drawing, notes/evidence/review, profile and area measurement,
GeoJSON round trips, reload persistence, and restoration of the 3D view.

## Scanning and shortlist review

Open the automatic shortlist (sparkle button) to inspect the highest-scoring
candidates in the current map view. The list is limited to 100 candidates with
scores at least 0.4; it is not a complete inventory. Saving copies the suggestion,
its score, morphometrics, source-pass metadata and originating scan/configuration
into the selected investigation. Re-saving opens the existing finding rather
than creating a duplicate. Human review remains separate from the original
machine output, and the snapshot survives later server changes.

Current scans still use the depression-oriented `sinkhole_survey` configuration.
They do not yet discover every feature family in the roadmap. Analysis remains
opt-in and requires the existing database, queue and CPU worker. Scan views are
bounded to 4 km across; the legacy consumer flow now uses the same limits and
queue failure handling. Queued jobs stay pending until a worker starts them.
Frontend clients normalize API states consistently and stop polling terminal jobs.
The main viewer reconnects to its tracked job after a same-tab refresh, provides
retry and cancellation controls, and reports partial tile failures.

Cancellation is cooperative: it persists a terminal state under a row lock,
revokes queued Celery work without killing a shared worker, and checks state
before downloads, native derivative processing, detection and committing results.
An already-running native tool/phase may finish before stopping. Status updates
and detection commits lock the same job row, so a late completion cannot overwrite
cancellation or append detections after cancellation commits. Already committed
partial results remain available. Scans use separate raw and processed paths and
no longer delete earlier detections or terrain at startup. Repeat scans can thus
produce separate candidate records for the same physical shape; physical-feature
deduplication across scans is future work.

The tests exercise job state transitions, pending and in-flight cancellation,
broker failure, callbacks, malformed configuration, persistence contracts and
browser reconnect/review flows. They do not constitute a production throughput
or live Redis/PostGIS/native-processing soak test.

For a bounded local regression gate, run `scripts/check_changes.sh`. It uses cached
Ruff, targeted measurement/job tests and frontend contract/lint/build checks,
with hard per-command timeouts (15–45 seconds). It does not download dependencies,
load terrain in a browser or start a live scan. Full native-tool coverage remains
in CI. Browser job-state checks use fixture terrain and a 60-second total deadline;
real DEM visual checks are separate from the job/persistence workflow.
