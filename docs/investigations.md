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
