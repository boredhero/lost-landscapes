# Lost Landscapes API Documentation

Base URL: `https://lostlandscapes.martinospizza.dev/api`
Interactive docs: `https://lostlandscapes.martinospizza.dev/api/docs`

All responses are JSON unless otherwise noted. All geometry is WGS84 (EPSG:4326).

---

## Health & Info

### `GET /api/health`
Returns service status.
```json
{"status": "ok", "version": "0.1.0"}
```

### `GET /api/info`
Returns version info from info.yml.
```json
{
  "name": "Lost Landscapes",
  "version": "0.1.0",
  "description": "LiDAR-based terrain anomaly detection platform",
  "license": "GPL-3.0-or-later",
  "detection_passes": 11,
  "regions": 5,
  "validation_sites": 23
}
```

---

## Detections

### `GET /api/detections`
Query detections within a bounding box. Returns GeoJSON FeatureCollection.

**Required params:**
- `west`, `south`, `east`, `north` (float) — bounding box in WGS84

**Optional params:**
- `feature_type` (string, repeatable) — filter by type: `SINKHOLE`, `CAVE_ENTRANCE`, `MINE_PORTAL`, `DEPRESSION`, `COLLAPSE_PIT`, `SPRING`, `UNKNOWN`
- `source_pass` (string) — filter by detection pass name (e.g. `fill_difference`, `local_relief_model`)
- `min_confidence` (float 0-1, default 0.0)
- `validated` (bool) — filter by validation status
- `limit` (int, default 10000, max 50000)
- `offset` (int, default 0)

**Response:**
```json
{
  "type": "FeatureCollection",
  "total_count": 798,
  "features": [
    {
      "type": "Feature",
      "id": "uuid",
      "geometry": {"type": "Point", "coordinates": [-79.71, 39.81]},
      "properties": {
        "feature_type": "DEPRESSION",
        "confidence": 0.85,
        "depth_m": 3.2,
        "area_m2": 450,
        "circularity": 0.7,
        "wall_slope_deg": 25.3,
        "source_passes": ["fill_difference", "local_relief_model"],
        "morphometrics": {"k_parameter": 2.1, "elongation": 0.8},
        "validated": null,
        "validation_notes": null
      }
    }
  ]
}
```

### `GET /api/detections/{detection_id}`
Get full detail for one detection including pass results and validation history.

**Response:**
```json
{
  "id": "uuid",
  "feature_type": "DEPRESSION",
  "confidence": 0.85,
  "depth_m": 3.2,
  "area_m2": 450,
  "morphometrics": {...},
  "source_passes": [...],
  "pass_results": [
    {"pass_name": "fill_difference", "raw_score": 0.9, "parameters": {...}}
  ],
  "validation_events": [
    {"verdict": "CONFIRMED", "notes": "Visited in person", "created_at": "..."}
  ]
}
```

---

## Validation

### `POST /api/detections/{detection_id}/validate`
Record a validation verdict.

**Body:**
```json
{"verdict": "confirmed", "notes": "Optional notes"}
```
Verdict must be: `confirmed`, `rejected`, or `uncertain`.

**Response:**
```json
{"status": "ok", "verdict": "CONFIRMED", "detection_id": "uuid"}
```

---

## Comments

### `GET /api/detections/{detection_id}/comments`
List comments on a detection, newest first.

**Response:**
```json
[
  {"id": "uuid", "text": "Looks like a real sinkhole", "author": "Noah", "created_at": "2026-03-23T..."}
]
```

### `POST /api/detections/{detection_id}/comments`
Add a comment.

**Body:**
```json
{"text": "This might be a mine entrance", "author": "Noah"}
```

### `DELETE /api/comments/{comment_id}`
Delete a comment.

---

## Saved Detections

### `GET /api/saved`
List all saved/highlighted detections.

**Response:**
```json
[
  {"id": "uuid", "detection_id": "uuid", "label": "Interesting cave", "color": "#f59e0b", "notes": "...", "created_at": "..."}
]
```

### `POST /api/detections/{detection_id}/save`
Save/highlight a detection.

**Body:**
```json
{"label": "Possible cave", "color": "#ef4444", "notes": "Check on next field trip"}
```

### `DELETE /api/saved/{save_id}`
Remove a saved detection.

---

## Ground Truth

### `GET /api/ground-truth`
List known ground truth sites as GeoJSON.

**Optional params:**
- `west`, `south`, `east`, `north` — bounding box filter
- `limit` (int, default 1000)

**Response:** GeoJSON FeatureCollection with name, feature_type, source.

### `POST /api/ground-truth`
Add a new ground truth site (e.g. from map click in validation UI).

**Body:**
```json
{"name": "New Cave", "feature_type": "cave_entrance", "lat": 39.8, "lon": -79.7, "notes": "Found on hiking trip"}
```

---

## Jobs

### `GET /api/jobs`
List processing jobs, newest first.

**Optional params:**
- `status` — filter by: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`

**Response:**
```json
{
  "jobs": [
    {"id": "uuid", "job_type": "FULL_PIPELINE", "status": "COMPLETED", "progress": 100.0, "created_at": "..."}
  ]
}
```

### `POST /api/jobs`
Submit a new processing job.

**Body:**
```json
{
  "job_type": "full_pipeline",
  "region_name": "western_pa",
  "pass_config": "cave_hunting"
}
```
Or with drawn AOI:
```json
{
  "job_type": "full_pipeline",
  "bbox": {"type": "Polygon", "coordinates": [[[...]]]}
  "pass_config": "sinkhole_survey"
}
```

### `GET /api/jobs/{job_id}`
Get job status and progress.

### `POST /api/jobs/{job_id}/cancel`
Cancel a pending/running job.

---

## Datasets

### `GET /api/datasets`
List ingested LiDAR datasets.

---

## Regions

### `GET /api/regions`
List all target regions with GeoJSON geometries.

**Response:**
```json
{
  "regions": [
    {"name": "western_pa", "description": "Allegheny Plateau karst...", "geometry": {"type": "Polygon", ...}}
  ]
}
```

### `GET /api/regions/{region_name}`
Get a specific region's full GeoJSON.

---

## Exports

### `GET /api/export/geojson`
Download detections as a GeoJSON file.

**Required params:** `west`, `south`, `east`, `north`
**Optional:** `min_confidence`, `feature_type`
**Response:** `application/geo+json` file download.

### `GET /api/export/csv`
Download detections as CSV.

**Required params:** `west`, `south`, `east`, `north`
**Optional:** `min_confidence`
**Response:** `text/csv` file with columns: id, lat, lon, feature_type, confidence, depth_m, area_m2, circularity, validated.

---

## Vector Tiles (MVT)

### `GET /api/tiles/{z}/{x}/{y}.mvt`
Mapbox Vector Tiles for detections. Used by the deck.gl frontend for rendering large datasets.

**Optional:** `min_confidence` (float)

Layer name: `detections`. Properties: id, feature_type, confidence, depth_m, area_m2, validated.

### `GET /api/tiles/ground-truth/{z}/{x}/{y}.mvt`
Vector tiles for ground truth sites.

Layer name: `ground_truth`. Properties: id, name, feature_type, source.

---

## Raster Tiles

### `GET /api/raster/{layer}/{z}/{x}/{y}.png`
Raster tiles for processed DEM derivatives.

Layers: `hillshade`, `slope`, `svf`, `lrm`

Returns cached PNG if available, transparent 1x1 PNG if not.

### `GET /api/raster/terrain-rgb/{z}/{x}/{y}.png`
Terrain-RGB tiles for MapLibre 3D terrain.

---

## WebSocket

### `WS /ws/jobs`
Real-time job progress. Polls DB every 2s, sends updates for active jobs.

**Server → Client:**
```json
{"type": "job_updates", "jobs": [{"id": "...", "status": "RUNNING", "progress": 45.0}]}
```

**Client → Server:**
```json
{"ping": true}
```
