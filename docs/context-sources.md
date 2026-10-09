# Historical and environmental evidence

The **Historical evidence** control displays one optional overlay at a time with
opacity, explicit dates, attribution, coverage, provider metadata/legend and terms.
It works over 2D or angled 3D terrain and on the primary side of aerial comparison.
New manual findings and saved machine suggestions record the selected source and
opacity in their investigation context. Notebook exports contain references, not
copies of provider imagery. Geological and inventory dates are not site dates.

## Architecture for US and European expansion

The first five catalog entries are regional engineering fixtures, not an assertion
of national coverage. Source definitions are separate from providers and UI:

- `src/lost_landscapes/context-sources.json` is a versioned, packaged registry.
  Operators can replace it using an absolute `CONTEXT_SOURCES_PATH` and restart.
- Each entry declares a stable ID, revision, category, country/region, WGS84
  coverage, date semantics, verification date, scale/zoom limits, attribution,
  source/legend/terms links and an adapter specification. Names and countries do
  not affect rendering. Split antimeridian-crossing coverage into separate entries.
- `context_sources.py` validates entries and translates tile coordinates using
  adapters for ArcGIS MapServer exports, explicitly locked ImageServer rasters,
  XYZ tiles, and WMS 1.3.0 GetMap with EPSG:3857. WMS sources must advertise that
  output CRS; their native CRS may differ. No UTM zone or country is assumed.
- `/api/landscape/context` supplies public metadata and local tile templates.
  The UI consumes the same contract for every provider. Adding a dataset on an
  existing protocol needs a catalog entry, not a frontend change. New protocols
  require an adapter and contract tests, not scattered map-specific conditionals.
- The tile gateway accepts only registered IDs, never arbitrary browser-provided
  service URLs. Requests have a six-second total deadline including queue wait,
  four upstream slots and a two-MB/256px response bound. Out-of-coverage requests
  are transparent without contacting providers. Upstream failures return an
  overlay-specific error; no imagery is substituted for missing evidence.
- No persistent upstream imagery mirror or bulk export is created. A short private
  viewing cache limits repeated requests. Provider terms remain attached to sources.

For nationwide US expansion, add **discovery adapters** separately from rendering:
query USGS historical sheet footprints by the current map envelope, return a
paginated list of dated assets, and select individual locked sheet IDs. Keep map,
survey, photo-revision and imprint years separate. Apply the same collection/asset
pattern to state historical aerial indexes and European national catalogs. A photo
footprint is not a georeferenced image. Discovery should use viewport filtering,
cached metadata, explicit pagination and source health rather than fetching every
asset on startup. No global asset discovery or European catalog coverage is claimed
in this first implementation.

European WMS support has a geographic/axis-order contract test. Providers that only
serve other CRSs, WMTS tile matrices, authenticated catalogs, or non-georeferenced
scans need their own adapters before they can be enabled. Do not silently reinterpret
a service's axis order, dates, licensing, or geographic coverage.

## Initial verified sources

| Source | Date semantics | Scope and limitations |
|---|---|---|
| USGS Pittsburgh quadrangle, raster 135419 | 1904 map/survey; 1957 imprint | 1:62,500; one explicitly locked sheet, not a mixed-date mosaic. |
| Pittsburgh aerial photographs | Flight completed May 1939 | Regional georeferenced Penn Pilot imagery hosted by Esri; alignment varies. |
| Allegheny County color orthophotos | 2010 publication; flight date unspecified | One-foot imagery; county coverage. Layer 1 is imagery; layer 0 is an index. |
| Pennsylvania bedrock geology | 1980 source map; 2001 digital revisions | 1:250,000 regional geology, not site-scale contacts or comprehensive soils. |
| DEP abandoned mine inventory | Live service; metadata checked October 2026 | Problem-area boundaries, not underground mine outlines. Inventory is incomplete. |

Research verified metadata, rendered PNG responses and CORS on October 8, 2026.
Source references:

- [USGS topoView](https://www.usgs.gov/tools/topoview) and
  [historical ImageServer](https://historical1.arcgis.com/arcgis/rest/services/USGS_Historical_Topographic_Maps/ImageServer).
  Dated sheet queries expose `Date_On_Map`, `Survey_Year`, `Imprint_Year`,
  `Photo_Revision_Year`, `Aerial_Photo_Year`, `Map_Scale` and `Citation`.
- [Pittsburgh 1939 imagery item](https://www.arcgis.com/home/item.html?id=eeee01ca1f4244d6948e24f323fb5334)
  credits USDA AAA, Abrams Aerial Survey, Penn Pilot and Esri. The item references
  [Esri terms](https://links.esri.com/agol_tou); tile-package export is disabled.
- [Allegheny 2010 dataset](https://www.pasda.psu.edu/uci/DataSummary.aspx?dataset=1209)
  and [full metadata/use constraints](https://www.pasda.psu.edu/uci/FullMetadataDisplay.aspx?file=AlleghenyCountyImagery2010_TileIndex.xml).
  Publication year must not be presented as a verified acquisition year.
- [DCNR bedrock publication](https://maps.dcnr.pa.gov/publications/Default.aspx?id=712)
  and [accuracy metadata](https://www.pasda.psu.edu/uci/FullMetadataDisplay.aspx?file=dcnr_bedrockgeology2001.xml).
  The DCNR DataSharing service layer 7 has the formation renderer; PASDA DCNR2
  layer 11 currently has transparent fills and zero-width outlines.
- [DEP inventory layer](https://mapservices.pasda.psu.edu/server/rest/services/pasda/DEP/MapServer/2).
  It omits active mines, comprehensive underground coverage and permitted mines
  closed after 1982. Empty polygons do not demonstrate absence of mining.
- [Penn Pilot Imagery Navigator](https://maps.psiee.psu.edu/ImageryNavigator/)
  is a future archival discovery source; its photo indexes are not seamless imagery.

## Bounded verification

Offline contract tests: `pytest tests/unit/test_context_sources.py -q`.
Explicit live check: `timeout 15s .venv/bin/python scripts/check_context_sources.py`.
The live check downloads one view tile per catalog entry in parallel, with the same
six-second provider deadline as the application. It is intentionally separate from
normal tests, which use mocked providers and do not wait on external services.

Validation for this delivery: the full local suite passed with 342 tests and 72
native/optional skips in 9.04 seconds; four additional stream-validation cases
also passed in the focused 20-test context suite. Five frontend persistence/source
contract tests passed, as did Ruff, zero-warning ESLint, TypeScript and the build.
A fixture-based browser check passed source switching, metadata/opacity, saved
geographic/date provenance, simulated outage/retry, 3D comparison and mobile layout.
The earlier configuration-path CI regression was fixed independently and passed
native GitHub CI before this overlay delivery.
