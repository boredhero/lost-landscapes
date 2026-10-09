import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  Compass,
  Crosshair,
  Layers2,
  LoaderCircle,
  MapPin,
  Mountain,
  Search,
  SlidersHorizontal,
  Sparkles,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import type { ViewState } from "react-map-gl/maplibre";
import ContextPanel from "../components/Landscape/ContextPanel";
import { contextSnapshot } from "../components/Landscape/contextLayers";
import type { ContextSource } from "../components/Landscape/contextLayers";
import LoadingNotice from "../components/Landscape/LoadingNotice";
import LandscapeMap from "../components/Landscape/LandscapeMap";
import { isHorizonLayer, lightDirections, terrainLayers, terrainLegend, terrainMinZoom, usesTerrainRadius } from "../components/Landscape/terrainLayers";
import type { ReliefRadius, TerrainLayer } from "../components/Landscape/terrainLayers";
import type {
  Bounds,
  CameraTarget,
  MapMode,
} from "../components/Landscape/LandscapeMap";
import { cancelJob, createJob, geocodeZip, getDetections, getJob } from "../api/client";
import type { Detection, Job } from "../types";
import { FEATURE_LABELS } from "../types";
import NotebookPanel from '../investigations/NotebookPanel';
import { fromDetection, loadNotebook, newFinding, STORAGE_KEY } from '../investigations/model';
import type { Finding, Geometry, Notebook } from '../investigations/model';
import "./landscape.css";

interface Area {
  id: string;
  name: string;
  description: string;
  bounds: Bounds;
  source: string;
  resolution_m: number;
}
interface Catalog {
  revision: string;
  areas: Area[];
  tile_count: number;
  coverage: Bounds[];
  analysis_enabled: boolean;
  visualizations?: {
    algorithm_version: string;
    sources: {
      id: string;
      geographic_bounds: Bounds;
      eligible: boolean;
      reason: string | null;
      crs: string | null;
      resolution_m: [number, number] | null;
      elevation_units: string;
      survey_id?: string | null;
      vertical_datum?: string | null;
      mosaic_eligible?: boolean;
      mosaic_reason?: string | null;
      horizon_radius_presets_m?: number[];
    }[];
  };
}
const emptyCatalog: Catalog = {
  revision: "",
  areas: [],
  tile_count: 0,
  coverage: [],
  analysis_enabled: false,
};
const defaultView = {
  longitude: -79.986,
  latitude: 40.499,
  zoom: 14.4,
  pitch: 55,
  bearing: -25,
};
const modes: { id: MapMode; label: string; detail: string }[] = [
  { id: "lidar", label: "LiDAR", detail: "See beneath the canopy" },
  { id: "aerial", label: "Aerial", detail: "See the landscape today" },
  { id: "compare", label: "Compare", detail: "Compare ground and imagery" },
];
function message(error: unknown) {
  return error instanceof Error
    ? error.message
    : "Something went wrong. Please try again.";
}

export default function LandscapePage() {
  const client = useQueryClient();
  const [mode, setMode] = useState<MapMode>("lidar");
  const [terrainLayer, setTerrainLayer] = useState<TerrainLayer>("relief");
  const [reliefRadius, setReliefRadius] = useState<ReliefRadius>(25);
  const [lightAzimuth, setLightAzimuth] = useState(315);
  const [is3D, set3D] = useState(true);
  const [exaggeration, setExaggeration] = useState(1.25);
  const [split, setSplit] = useState(50);
  const [panel, setPanel] = useState<"explore" | "terrain" | "notebook" | "shortlist" | "context" | null>("explore");
  const [contextId, setContextId] = useState('');
  const [contextOpacity, setContextOpacity] = useState(0.55);
  const [contextError, setContextError] = useState(false);
  const [contextAttempt, setContextAttempt] = useState(0);
  const contextQuery = useQuery<{ sources: ContextSource[] }>({
    queryKey: ['landscape-context'],
    enabled: panel === 'context' || !!contextId,
    queryFn: async () => {
      const response = await fetch('/api/landscape/context', { signal: AbortSignal.timeout(12_000) });
      if (!response.ok) throw Error('Evidence sources unavailable');
      return response.json();
    },
    staleTime: 300_000,
    retry: false,
  });
  const contextSource = contextQuery.data?.sources.find(source => source.id === contextId);
  const [coverage, setCoverage] = useState(false);
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [notice, setNotice] = useState("");
  const [terrainError, setTerrainError] = useState(false);
  const [loadingTiles, setLoadingTiles] = useState(true);
  const [selected, setSelected] = useState<Detection | null>(null);
  const [activeArea, setActiveArea] = useState<Area | null>(null);
  const [target, setTarget] = useState<CameraTarget | null>(null);
  const [view, setView] = useState(defaultView);
  const [bbox, setBbox] = useState<Bounds | null>(null);
  const [jobId, setJobId] = useState<string | null>(() =>
    sessionStorage.getItem("landscape-job"),
  );
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [initialNotebook] = useState(loadNotebook);
  const [book, setBook] = useState(initialNotebook.book);
  const [storageError, setStorageError] = useState(initialNotebook.error);
  const [groupId, setGroupId] = useState(initialNotebook.book.investigations[0]?.id);
  const [findingId, setFindingId] = useState<string | null>(null);
  const [drawing, setDrawing] = useState<Geometry['type'] | null>(null);
  const [vertices, setVertices] = useState<number[][]>([]);
  const was3D = useRef(false);
  const group = book.investigations.find(g => g.id === groupId) ?? book.investigations[0];
  const finding = group.findings.find(f => f.id === findingId);
  function updateBook(next: Notebook) {
    setBook(next);
    if (initialNotebook.error) return;
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(next)); setStorageError(''); }
    catch { setStorageError('Could not save on this device. Export your findings before leaving.'); }
  }
  function updateFinding(next: Finding) {
    setBook(current => {
      const updated = { ...current, investigations: current.investigations.map(g => ({ ...g, findings: g.findings.map(f => f.id === next.id ? { ...(next.measurement && next.measurement !== f.measurement ? { ...f, measurement: next.measurement } : next), updatedAt: new Date().toISOString() } : f) })) };
      if (!initialNotebook.error) {
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(updated)); }
        catch { setStorageError('Could not save on this device. Export your findings before leaving.'); }
      }
      return updated;
    });
  }
  function endDrawing() {
    setDrawing(null); setVertices([]);
    if (was3D.current) { set3D(true); setTarget({ ...view, pitch: 55, id: Date.now() }); }
  }
  function startDrawing(type: Geometry['type'] | null) {
    if (!type) { endDrawing(); return; }
    if (!drawing) was3D.current = is3D;
    setDrawing(type); setVertices([]); setSelected(null);
    setMode('lidar'); set3D(false); setTarget({ ...view, pitch: 0, id: Date.now() });
  }
  function addGeometry(geometry: Geometry) {
    const item = newFinding(geometry, { revision: catalog.revision, terrainLayer, radius_m: reliefRadius, azimuth: lightAzimuth, evidence_overlay: contextSnapshot(contextSource, contextOpacity) });
    updateBook({ ...book, investigations: book.investigations.map(g => g.id === group.id ? { ...g, findings: [...g.findings, item] } : g) });
    setFindingId(item.id); endDrawing(); setPanel('notebook');
  }
  function finishDrawing() {
    if (drawing === 'LineString' && vertices.length >= 2) addGeometry({ type: 'LineString', coordinates: vertices });
    if (drawing === 'Polygon' && vertices.length >= 3) addGeometry({ type: 'Polygon', coordinates: [[...vertices, vertices[0]]] });
  }
  function drawPoint(point: number[]) {
    if (drawing === 'Point') addGeometry({ type: 'Point', coordinates: point });
    else if (vertices.length < 499) setVertices([...vertices, point]);
  }
  const investigationFeatures: GeoJSON.FeatureCollection = {
    type: 'FeatureCollection', features: [
      ...group.findings.map(f => ({ type: 'Feature' as const, geometry: f.geometry, properties: { findingId: f.id, selected: f.id === findingId } })),
      ...(vertices.length ? [{ type: 'Feature' as const, geometry: vertices.length === 1 ? { type: 'Point' as const, coordinates: vertices[0] } : { type: 'LineString' as const, coordinates: vertices }, properties: { draft: true } }] : []),
    ],
  };
  const bootstrapped = useRef(false);
  const catalogQuery = useQuery<Catalog>({
    queryKey: ["landscape-catalog"],
    queryFn: async () => {
      const response = await fetch("/api/landscape/catalog");
      if (!response.ok) throw new Error("Terrain service is unavailable.");
      return response.json();
    },
    staleTime: 15_000,
  });
  const catalog = catalogQuery.data ?? emptyCatalog;
  const detectionsQuery = useQuery<Detection[]>({
    queryKey: ["landscape-detections", bbox],
    enabled: !!bbox && catalog.analysis_enabled,
    queryFn: async () => {
      const [west, south, east, north] = bbox!;
      const response = await getDetections({
        west,
        south,
        east,
        north,
        limit: 100,
        min_confidence: 0.4,
      });
      return response.features.map(
        (f: {
          id: string;
          geometry: { coordinates: number[] };
          properties: object;
        }) => ({
          id: f.id,
          lon: f.geometry.coordinates[0],
          lat: f.geometry.coordinates[1],
          ...f.properties,
        }),
      );
    },
    staleTime: 30_000,
  });
  const jobQuery = useQuery<Job>({
    queryKey: ["landscape-job", jobId],
    enabled: !!jobId,
    queryFn: () => getJob(jobId!),
    refetchInterval: (query) =>
      ["COMPLETED", "FAILED", "CANCELLED"].includes(
        query.state.data?.status ?? "",
      )
        ? false
        : 2500,
  });
  const job = jobQuery.data;
  const busy =
    submitting ||
    (!!jobId &&
      !["COMPLETED", "FAILED", "CANCELLED"].includes(job?.status ?? ""));
  const detections = detectionsQuery.data ?? [];
  const insideCoverage = catalog.coverage.some(
    ([w, s, e, n]) =>
      view.longitude >= w &&
      view.longitude <= e &&
      view.latitude >= s &&
      view.latitude <= n,
  );
  const layerInfo = terrainLayers.find((layer) => layer.id === terrainLayer)!;
  const inspectingTerrain = terrainLayer !== "relief" && mode !== "aerial";
  const minimumZoom = terrainMinZoom(terrainLayer);
  const currentArea = catalog.areas.find(({ bounds: [w, s, e, n] }) =>
    view.longitude >= w && view.longitude <= e && view.latitude >= s && view.latitude <= n,
  );
  const currentSources = (catalog.visualizations?.sources ?? []).filter(({ geographic_bounds }) => {
    if (!geographic_bounds) return false;
    const [w, s, e, n] = geographic_bounds;
    return view.longitude >= w && view.longitude <= e && view.latitude >= s && view.latitude <= n;
  });
  const shownAreas = catalog.areas.filter((area) =>
    `${area.name} ${area.description}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  const move = useCallback(
    (next: Partial<typeof defaultView>) => {
      setTarget({ ...view, ...next, id: Date.now() });
    },
    [view],
  );
  const visit = useCallback(
    (area: Area) => {
      const [w, s, e, n] = area.bounds;
      const span = Math.max(e - w, (n - s) * 1.5);
      setActiveArea(area);
      setTarget({
        longitude: (w + e) / 2,
        latitude: (s + n) / 2,
        zoom: Math.min(
          15.6,
          Math.max(10, Math.log2(360 / Math.max(span, 0.001)) + 1.0),
        ),
        pitch: is3D ? 55 : 0,
        bearing: -25,
        id: Date.now(),
      });
      setSelected(null);
      setTerrainError(false);
      if (window.innerWidth < 700) setPanel(null);
    },
    [is3D],
  );
  useEffect(() => {
    if (bootstrapped.current || !catalog.areas.length) return;
    bootstrapped.current = true;
    visit(catalog.areas[0]);
  }, [catalog.areas, visit]);
  useEffect(() => {
    if (!job || !["COMPLETED", "FAILED", "CANCELLED"].includes(job.status)) return;
    void client.invalidateQueries({ queryKey: ["landscape-catalog"] });
    void client.invalidateQueries({ queryKey: ["landscape-detections"] });
    setNotice(
      job.status === "COMPLETED" ? `Analysis complete. ${job.result_summary?.tiles_failed ? "Some tiles failed; coverage is partial. " : ""}Open the shortlist to review candidates.` : job.status === "CANCELLED" ? "Scan cancelled. A native processing phase already in progress may take time to stop. Earlier results are preserved." : job.error_message || "Analysis failed. Earlier results are preserved.",
    );
    sessionStorage.removeItem("landscape-job");
    setJobId(null);
  }, [job, client]);
  const onView = useCallback((next: ViewState, bounds: Bounds) => {
    setView(next);
    setBbox(bounds);
  }, []);
  const onTerrainError = useCallback(() => setTerrainError(true), []);

  async function search(event: FormEvent) {
    event.preventDefault();
    setNotice("");
    const input = query.trim();
    if (!input) return;
    const coordinates = input.match(
      /^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$/,
    );
    if (coordinates) {
      const latitude = Number(coordinates[1]),
        longitude = Number(coordinates[2]);
      if (Math.abs(latitude) > 85 || Math.abs(longitude) > 180) {
        setNotice(
          "Use latitude between −85 and 85, then longitude between −180 and 180.",
        );
        return;
      }
      move({ latitude, longitude, zoom: 15 });
      setPanel(null);
      return;
    }
    if (/^\d{5}$/.test(input)) {
      setSearching(true);
      try {
        const location = await geocodeZip(input);
        move({ latitude: location.lat, longitude: location.lon, zoom: 14 });
        setNotice(`${location.city}, ${location.state}`);
        setPanel(null);
      } catch {
        setNotice(
          "Could not find that ZIP code. Try coordinates or a study area.",
        );
      } finally {
        setSearching(false);
      }
      return;
    }
    if (shownAreas.length) visit(shownAreas[0]);
    else
      setNotice(
        "No matching study area. You can also enter a US ZIP code or latitude, longitude.",
      );
  }
  async function analyze() {
    if (!bbox || busy) return;
    const [w, s, e, n] = bbox;
    const width = (e - w) * 111.32 * Math.cos((view.latitude * Math.PI) / 180),
      height = (n - s) * 111.32;
    if (width > 4 || height > 4) {
      setNotice("Zoom in to analyze an area less than 4 km across.");
      return;
    }
    setSubmitting(true);
    setNotice("");
    try {
      const result = await createJob({
        job_type: "full_pipeline",
        pass_config: "sinkhole_survey",
        bbox: {
          type: "Polygon",
          coordinates: [
            [
              [w, s],
              [e, s],
              [e, n],
              [w, n],
              [w, s],
            ],
          ],
        },
      });
      if (result.status === "FAILED")
        throw new Error(result.error_message || "Analysis could not start.");
      setJobId(result.id);
      sessionStorage.setItem("landscape-job", result.id);
    } catch (error) {
      setNotice(message(error));
    } finally {
      setSubmitting(false);
    }
  }
  function locate() {
    if (!navigator.geolocation) {
      setNotice("Location is unavailable in this browser. Use search instead.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) =>
        move({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          zoom: 15,
        }),
      () =>
        setNotice(
          "Location could not be accessed. Search for a ZIP code or coordinates instead.",
        ),
      { timeout: 10000 },
    );
  }
  function save(detection: Detection) {
    const existing = group.findings.find(f => f.detection?.id === detection.id);
    const item = existing ?? fromDetection(detection);
    if (!existing) item.context = { ...item.context, evidence_overlay: contextSnapshot(contextSource, contextOpacity) };
    if (!existing && group.findings.length >= 1000) { setNotice("This investigation has 1,000 findings. Create another investigation first."); return; }
    if (!existing) updateBook({ ...book, investigations: book.investigations.map(g => g.id === group.id ? { ...g, findings: [...g.findings, item] } : g) });
    setFindingId(item.id); setSelected(null); setPanel('notebook');
  }
  async function cancelScan() {
    if (!jobId || cancelling) return;
    setCancelling(true);
    try { await cancelJob(jobId); await jobQuery.refetch(); }
    catch (error) { setNotice(message(error)); }
    finally { setCancelling(false); }
  }
  function toggle3D() {
    set3D(!is3D);
    move({ pitch: is3D ? 0 : 55 });
  }
  return (
    <main className="landscape-app">
      <LandscapeMap
        contextSource={contextSource}
        contextOpacity={contextOpacity}
        contextAttempt={contextAttempt}
        onContextError={() => setContextError(true)}
        findings={investigationFeatures}
        drawing={!!drawing}
        onDrawPoint={drawPoint}
        onFinding={(id) => { setFindingId(id); setSelected(null); setPanel('notebook'); }}
        mode={mode}
        revision={catalog.revision}
        terrainLayer={terrainLayer}
        reliefRadius={reliefRadius}
        lightAzimuth={lightAzimuth}
        is3D={is3D}
        exaggeration={exaggeration}
        split={split}
        target={target}
        detections={detections}
        coverage={catalog.coverage}
        showCoverage={coverage}
        selected={selected?.id ?? null}
        onSelect={(d) => {
          setSelected(d);
          setPanel(null);
        }}
        onView={onView}
        onTerrainError={onTerrainError}
        onLoading={setLoadingTiles}
      />
      <div className="request-loading-notices">
        {catalogQuery.isFetching && <LoadingNotice label="Loading study areas…" />}
        {searching && <LoadingNotice label="Finding location…" />}
        {contextQuery.isFetching && <LoadingNotice label="Loading evidence sources…" />}
      </div>
      <header className="landscape-header">
        <a
          className="landscape-brand"
          href="/"
          aria-label="Lost Landscapes home"
        >
          <Mountain size={26} strokeWidth={1.3} />
          <span>
            LOST<span className="brand-second">LANDSCAPES</span>
          </span>
          <span className="edition">FIELD NOTES / 01</span>
        </a>
        <form className="landscape-search" onSubmit={search} role="search">
          <Search size={17} />
          <input
            aria-label="Search study areas, ZIP code, or coordinates"
            placeholder="Study area, ZIP, or coordinates"
            value={query}
            onFocus={() => setPanel("explore")}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button aria-label="Search" type="submit" disabled={searching}>
            {searching ? (
              <LoaderCircle className="spin" size={17} />
            ) : (
              <ArrowUpRight size={18} />
            )}
          </button>
        </form>
        <button
          className={`header-explore ${panel === "explore" ? "active" : ""}`}
          onClick={() => {
            setSelected(null);
            setPanel(panel === "explore" ? null : "explore");
          }}
        >
          <Compass size={17} /> Explore
        </button>
      </header>
      <div className="map-mode-switch" aria-label="Map appearance">
        {modes.map((m) => (
          <button
            key={m.id}
            aria-pressed={mode === m.id}
            title={m.detail}
            onClick={() => setMode(m.id)}
          >
            {m.id === "lidar" ? (
              <Mountain size={15} />
            ) : m.id === "compare" ? (
              <Layers2 size={15} />
            ) : null}
            {m.label}
          </button>
        ))}
      </div>
      {panel === "explore" && !selected && (
        <aside
          className="landscape-panel explore-panel"
          aria-label="Explore study areas"
        >
          <div className="panel-eyebrow">
            <span>THE GROUND TELLS A STORY</span>
            <button
              className="icon-button"
              aria-label="Close explore panel"
              onClick={() => setPanel(null)}
            >
              <X size={17} />
            </button>
          </div>
          <h1>
            Beneath
            <br />
            the canopy.
          </h1>
          <p className="panel-intro">
            Look past the trees. Read the ridges, old paths, and subtle shapes
            of the land.
          </p>
          <div className="panel-divider" />
          <div className="section-label">
            <span>EXPLORE A LANDSCAPE</span>
            <span>{String(catalog.areas.length).padStart(2, "0")}</span>
          </div>
          {catalogQuery.isPending && (
            <p className="muted loading-row">
              <LoaderCircle size={16} className="spin" /> Finding available
              LiDAR…
            </p>
          )}
          {catalogQuery.isError && (
            <div className="inline-error">
              Terrain service is unavailable.
              <button onClick={() => void catalogQuery.refetch()}>
                Try again
              </button>
            </div>
          )}
          {!catalogQuery.isPending &&
            !catalogQuery.isError &&
            !catalog.areas.length && (
              <p className="muted">
                No LiDAR study areas have been imported yet. Aerial and regional
                terrain are available to explore.
              </p>
            )}
          {shownAreas.map((area, i) => (
            <button
              className={`area-card ${activeArea?.id === area.id ? "selected" : ""}`}
              key={area.id}
              onClick={() => visit(area)}
            >
              <span className="area-number">
                {String(i + 1).padStart(2, "0")}
              </span>
              <span>
                <strong>{area.name}</strong>
                <small>{area.resolution_m} m LiDAR · Ready to explore</small>
              </span>
              <ArrowUpRight size={18} />
            </button>
          ))}
          {!!query && !shownAreas.length && !!catalog.areas.length && (
            <p className="muted">
              No matching study area. Press Enter to search a ZIP code or
              coordinates.
            </p>
          )}
          {activeArea && (
            <p className="area-description">{activeArea.description}</p>
          )}
          <div className="field-tip">
            <span className="tip-symbol">↗</span>
            <p>
              <strong>Start with the shape.</strong>
              <br />
              Tilt the terrain, then compare it with aerial imagery. Straight
              lines and sharp corners can be worth a closer look.
            </p>
          </div>
          <button className="primary-button" onClick={() => setPanel('notebook')}>Open investigations · {group.findings.length} findings</button>
          <button className="text-button" onClick={() => setPanel('shortlist')}>Review automatic suggestions</button>
          <div className="panel-footer">
            <span className="status-dot" /> REAL TERRAIN. NEW PERSPECTIVES.
          </div>
        </aside>
      )}
      {selected && (
        <aside
          className="landscape-panel inspector"
          aria-label="Candidate details"
        >
          <div className="panel-eyebrow">
            <span>TERRAIN CANDIDATE</span>
            <button
              className="icon-button"
              aria-label="Close candidate"
              onClick={() => setSelected(null)}
            >
              <X size={17} />
            </button>
          </div>
          <h2>{FEATURE_LABELS[selected.feature_type] ?? "Terrain feature"}</h2>
          <p className="panel-intro">
            A shape identified by terrain analysis. This is not a verified ruin
            or archaeological site.
          </p>
          <dl>
            <div>
              <dt>Detection score</dt>
              <dd>{Math.round(selected.confidence * 100)} / 100</dd>
            </div>
            <div>
              <dt>Depth</dt>
              <dd>{selected.depth_m?.toFixed(1) ?? "—"} m</dd>
            </div>
            <div>
              <dt>Area</dt>
              <dd>{selected.area_m2?.toFixed(0) ?? "—"} m²</dd>
            </div>
            <div>
              <dt>Coordinates</dt>
              <dd>
                {selected.lat.toFixed(5)}, {selected.lon.toFixed(5)}
              </dd>
            </div>
          </dl>
          <button className="primary-button" onClick={() => save(selected)}>
            <MapPin size={16} /> {group.findings.some(f => f.detection?.id === selected.id) ? 'Open saved finding' : 'Save to investigation'}
          </button>
          <button
            className="text-button"
            onClick={() => {
              setMode("compare");
              move({
                longitude: selected.lon,
                latitude: selected.lat,
                zoom: 17,
              });
            }}
          >
            Compare with aerial imagery <ArrowUpRight size={15} />
          </button>
        </aside>
      )}
      {panel === 'shortlist' && <aside className="landscape-panel notebook-panel" aria-label="Automatic shortlist">
        <div className="panel-eyebrow"><span>AUTOMATIC SUGGESTIONS</span><button aria-label="Close shortlist" onClick={() => setPanel(null)}>×</button></div>
        <h2>Review the shapes.</h2>
        <p className="muted">Highest scoring candidates in the current map view (up to 100, score ≥ 0.4). Current scanning is tuned for depressions; these are not verified sites.</p>
        <p>Save into: {group.name}</p>
        {!catalog.analysis_enabled && <p>Analysis is not enabled on this deployment. Saved findings remain available in investigations.</p>}
        {detectionsQuery.isPending && catalog.analysis_enabled && <p>Loading suggestions…</p>}
        {detectionsQuery.isError && <button onClick={() => void detectionsQuery.refetch()}>Could not load suggestions — retry</button>}
        {!detections.length && !detectionsQuery.isPending && !detectionsQuery.isError && <p>No candidates in this map view.</p>}
        {detections.map(d => { const saved = group.findings.find(f => f.detection?.id === d.id); return <div className="shortlist-item" key={d.id}><strong>{FEATURE_LABELS[d.feature_type] ?? 'Terrain candidate'}</strong><p>Score {Math.round(d.confidence * 100)} / 100{saved ? ` · ${saved.review}` : ' · unreviewed'}</p><div className="notebook-actions"><button onClick={() => { setSelected(d); setPanel(null); move({ longitude: d.lon, latitude: d.lat, zoom: 17 }); }}>Inspect</button><button onClick={() => save(d)}>{saved ? 'Open saved finding' : 'Save to investigation'}</button></div></div>; })}
      </aside>}
      {panel === 'notebook' && <NotebookPanel book={book} group={group} selected={finding} drawing={drawing} vertices={vertices.length} error={storageError}
        onBook={updateBook} onGroup={(id) => { setGroupId(id); setFindingId(null); }} onSelect={setFindingId} onUpdate={updateFinding}
        onDraw={startDrawing} onFinish={finishDrawing} onUndo={() => setVertices(vertices.slice(0, -1))} onClose={() => setPanel(null)}
        onLocate={(f) => { const p = f.geometry.type === 'Point' ? f.geometry.coordinates : f.geometry.type === 'Polygon' ? f.geometry.coordinates[0][0] : f.geometry.coordinates[0]; move({ longitude: p[0], latitude: p[1], zoom: 17 }); }} />}
      {drawing && panel !== 'notebook' && <div className="drawing-bar"><span>Click map to place vertices ({vertices.length})</span><button onClick={() => setVertices(vertices.slice(0, -1))}>Undo</button><button onClick={finishDrawing}>Finish drawing</button><button onClick={endDrawing}>Cancel drawing</button></div>}
      {panel === 'context' && <ContextPanel sources={contextQuery.data?.sources ?? []} selected={contextSource}
        loading={contextQuery.isFetching} catalogError={contextQuery.isError} tileError={contextError}
        opacity={contextOpacity} view={view} onOpacity={setContextOpacity}
        onSelect={id => { setContextId(id); setContextError(false); }}
        onRetry={() => { setContextError(false); setContextAttempt(value => value + 1); }}
        onShowCoverage={source => {
          const [w, s, e, n] = source.bounds;
          move({ longitude: (w + e) / 2, latitude: (s + n) / 2, zoom: Math.min(16, Math.max(source.min_zoom, Math.log2(360 / Math.max(e - w, (n - s) * 1.5)) + 0.5)) });
        }}
        onCatalogRetry={() => void contextQuery.refetch()} onClose={() => setPanel(null)} />}
      <nav className="map-tools" aria-label="Map controls">
        <button aria-label="Historical evidence" title="Historical evidence" className={panel === 'context' ? 'active' : ''} onClick={() => { setSelected(null); setPanel(panel === 'context' ? null : 'context'); }}><Layers2 size={18} /></button>
        <button aria-label="Open automatic shortlist" title="Automatic shortlist" onClick={() => { setSelected(null); setPanel(panel === "shortlist" ? null : "shortlist"); }}><Sparkles size={18} /></button>
        <button aria-label="Open investigations" title="Investigations" onClick={() => { setSelected(null); setPanel(panel === 'notebook' ? null : 'notebook'); }}>✎</button>
        <button
          aria-label="Zoom in"
          title="Zoom in"
          onClick={() => move({ zoom: Math.min(19, view.zoom + 1) })}
        >
          <ZoomIn size={19} />
        </button>
        <button
          aria-label="Zoom out"
          title="Zoom out"
          onClick={() => move({ zoom: Math.max(3, view.zoom - 1) })}
        >
          <ZoomOut size={19} />
        </button>
        <span className="tool-divider" />
        <button
          aria-label="Reset north and tilt"
          title="Reset north and tilt"
          onClick={() => move({ bearing: 0, pitch: is3D ? 55 : 0 })}
        >
          <Compass
            size={20}
            style={{ transform: `rotate(${-view.bearing}deg)` }}
          />
        </button>
        <button
          aria-label="Find my location"
          title="Find my location"
          onClick={locate}
        >
          <Crosshair size={19} />
        </button>
        <span className="tool-divider" />
        <button
          className={is3D ? "active" : ""}
          aria-pressed={is3D}
          aria-label={is3D ? "Switch to 2D" : "Switch to 3D"}
          onClick={toggle3D}
        >
          {is3D ? "3D" : "2D"}
        </button>
        <button
          className={panel === "terrain" ? "active" : ""}
          aria-label="Terrain controls"
          title="Terrain controls"
          onClick={() => {
            setSelected(null);
            setPanel(panel === "terrain" ? null : "terrain");
          }}
        >
          <SlidersHorizontal size={18} />
        </button>
      </nav>
      {panel === "terrain" && (
        <aside
          className="landscape-panel terrain-panel"
          aria-label="Terrain settings"
        >
          <div className="panel-eyebrow">
            <span>YOUR VANTAGE POINT</span>
            <button
              className="icon-button"
              aria-label="Close terrain settings"
              onClick={() => setPanel(null)}
            >
              <X size={17} />
            </button>
          </div>
          <h2>Read the relief.</h2>
          <fieldset className="terrain-layer-picker">
            <legend>Terrain view</legend>
            {terrainLayers.map((layer) => (
              <label key={layer.id}>
                <input type="radio" name="terrain-layer" value={layer.id}
                  checked={terrainLayer === layer.id}
                  onChange={() => {
                    setTerrainLayer(layer.id);
                    setTerrainError(false);
                    if (mode === "aerial") setMode("lidar");
                  }} />
                {layer.label}
              </label>
            ))}
          </fieldset>
          <p className="muted">{layerInfo.description}</p>
          {terrainLayer === "vat" && <p className="muted">General-terrain VAT: hillshade lit from northwest at 35°, inverted slope 0–50° at 50%, positive openness 68–93° overlay at 50%, and SVF 0.7–1 multiply at 25%. The selected search radius applies to both horizon components.</p>}
          {usesTerrainRadius(terrainLayer) && (
            <label className="terrain-select">
              {isHorizonLayer(terrainLayer) ? "Search radius" : "Neighborhood half-width"}
              <select value={reliefRadius} onChange={(event) => {
                setReliefRadius(Number(event.target.value) as ReliefRadius);
                setTerrainError(false);
              }}>
                {[10, 25, 50].map((radius) => <option key={radius} value={radius}>{radius} m</option>)}
              </select>
              <span className="muted">{isHorizonLayer(terrainLayer)
                ? "16 directions on the source grid. Radius rounds up to native spacing; sampled cell centers can extend slightly beyond it. Complete surrounding data is required."
                : "A square neighborhood extends this far in each direction, rounded up to whole source cells."}</span>
            </label>
          )}
          {terrainLayer === "hillshade" && (
            <label className="terrain-select">
              Light from
              <select value={lightAzimuth} onChange={(event) => {
                setLightAzimuth(Number(event.target.value));
                setTerrainError(false);
              }}>
                {lightDirections.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
              </select>
              <span className="muted">Light is 45° above the horizon.</span>
            </label>
          )}
          {terrainLayer !== "relief" && (
            <p className="muted">Calculated on the source grid. Blank areas lack supported data or complete neighborhoods, or exceed the processing limit. Zoom {minimumZoom} or closer is required.</p>
          )}
          {terrainLayer !== "relief" && view.zoom < minimumZoom && (
            <button className="primary-button" onClick={() => move({ zoom: minimumZoom + 1 })}>Zoom to detail</button>
          )}
          <div className="panel-divider" />
          <label className="range-label">
            Elevation exaggeration <output>{exaggeration.toFixed(2)}×</output>
            <input
              aria-label="Elevation exaggeration"
              type="range"
              min="1"
              max="2.5"
              step=".05"
              value={exaggeration}
              disabled={!is3D}
              onChange={(e) => setExaggeration(Number(e.target.value))}
            />
          </label>
          <p className="muted">
            1× shows true proportions. A little exaggeration makes gentle
            terrain easier to read.
          </p>
          <div className="tilt-controls">
            <span>Tilt</span>
            <button
              aria-label="Look down"
              disabled={!is3D}
              onClick={() => move({ pitch: Math.max(0, view.pitch - 10) })}
            >
              <ArrowDown size={16} />
            </button>
            <span>{Math.round(view.pitch)}°</span>
            <button
              aria-label="Tilt toward horizon"
              disabled={!is3D}
              onClick={() => move({ pitch: Math.min(75, view.pitch + 10) })}
            >
              <ArrowUp size={16} />
            </button>
          </div>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={coverage}
              onChange={(e) => setCoverage(e.target.checked)}
            />{" "}
            Show LiDAR coverage
          </label>
          <p className="muted">
            Beyond LiDAR coverage, the map uses lower-resolution regional
            terrain for 3D shape and the Landscape view. Inspection layers use local data only.
          </p>
          <details className="terrain-provenance">
            <summary>About the data here</summary>
            <p>{currentArea?.source ?? "No named study area at the map center."}</p>
            {currentArea && <p>Catalog resolution: {currentArea.resolution_m} m. Zooming in does not add ground detail.</p>}
            {currentSources.map((source) => (
              <div className="terrain-source" key={source.id}>
                <strong>{source.id}</strong>
                <p>{source.crs ?? "CRS unknown"} · Elevation: {source.elevation_units}</p>
                {source.resolution_m && <p>Native spacing: {source.resolution_m.map((value) => Number(value.toFixed(3))).join(" × ")} m</p>}
                <p>Declared survey: {source.survey_id ?? "Unknown"} · Vertical datum: {source.vertical_datum ?? "Unknown"}</p>
                {source.mosaic_eligible !== undefined && <p>{source.mosaic_eligible
                  ? "Neighbor joining available when projection, spacing and pixel alignment match."
                  : `Neighbor joining unavailable: ${source.mosaic_reason}`}</p>}
                {source.resolution_m && terrainLayer === "local-relief" && <p>Effective half-width: {source.resolution_m.map((value) => Number((Math.ceil(reliefRadius / value) * value).toFixed(3))).join(" × ")} m</p>}
                {isHorizonLayer(terrainLayer) && <p>Supported horizon radii: {source.horizon_radius_presets_m?.join(", ") || "None"} m. Searches are capped at 128 native cells.</p>}
                {!source.eligible && <p>Inspection unavailable: {source.reason}</p>}
              </div>
            ))}
            {!currentSources.length && <p>No local source at the map center.</p>}
            <p>Survey metadata is declared by the data provider or importer, not independently verified by this viewer. Missing elevation units are assumed to be metres for individual sources; joining requires declared metre units.</p>
            <p>Coverage outlines show file extents; holes and incomplete edge neighborhoods may remain inside them. Exaggeration changes the 3D display, not calculated slope or local relief.</p>
            {catalog.visualizations && <p>Visualization method: {catalog.visualizations.algorithm_version}</p>}
          </details>
        </aside>
      )}
      {mode === "compare" && (
        <div className="comparison-control">
          <span>LiDAR</span>
          <input
            aria-label="Compare LiDAR and aerial imagery"
            type="range"
            min="5"
            max="95"
            value={split}
            onChange={(e) => setSplit(Number(e.target.value))}
          />
          <span>Aerial</span>
        </div>
      )}
      <div className="map-bottom">
        <div className="terrain-status">
          <span className={`status-dot ${insideCoverage && !inspectingTerrain ? "" : "muted-dot"}`} />
          <div>
            <strong>
              {loadingTiles
                ? "Loading terrain…"
                : inspectingTerrain
                  ? view.zoom < minimumZoom ? "Zoom in for terrain detail" : layerInfo.label
                : insideCoverage
                  ? "LiDAR terrain"
                  : "Regional terrain"}
            </strong>
            <small>
              {inspectingTerrain && !currentSources.some((source) => source.eligible && (!isHorizonLayer(terrainLayer) || source.horizon_radius_presets_m?.includes(reliefRadius)))
                ? "No supported local source at map center"
                : insideCoverage
                ? (currentArea?.source ?? "Imported elevation data")
                : "Zoom to a study area for fine ground detail"}
            </small>
            {inspectingTerrain && (
              <div className={`terrain-legend legend-${terrainLayer}`} aria-label={`${layerInfo.label} legend`}>
                <span className="legend-ramp" />
                <span>{terrainLegend[terrainLayer]?.[0]}</span>
                <span>{terrainLegend[terrainLayer]?.[1]}</span>
              </div>
            )}
          </div>
        </div>
        <button
          className="analyze-button"
          onClick={analyze}
          disabled={busy || !catalog.analysis_enabled || !bbox}
          title={
            !catalog.analysis_enabled
              ? "Terrain preview — analysis worker is not enabled"
              : undefined
          }
        >
          {busy ? (
            <LoaderCircle size={17} className="spin" />
          ) : (
            <Sparkles size={17} />
          )}
          <span>
            {busy
              ? "Analyzing…"
              : catalog.analysis_enabled
                ? "Analyze this area"
                : "Terrain preview"}
          </span>
        </button>
      </div>
      {(busy || job?.status === "FAILED" || jobQuery.isError) && (
        <div className="analysis-progress" role="status">
          <div>
            <strong>
              {jobQuery.isError
                ? "Could not reach analysis service"
                : job?.status === "FAILED"
                  ? "Analysis could not finish"
                  : job?.status === "PENDING" ? "Scan queued" : "Analyzing this landscape"}
            </strong>
            <button
              className="icon-button"
              aria-label="Forget scan tracking"
              disabled={busy && !jobQuery.isError}
              title="Only forget an unreachable scan if you no longer need to track it"
              onClick={() => {
                if (busy && !window.confirm("This only forgets tracking; the scan may still be running. Continue?")) return;
                setJobId(null);
                sessionStorage.removeItem("landscape-job");
              }}
            >
              <X size={15} />
            </button>
          </div>
          <p>
            {jobQuery.isError
              ? "Your scan may still be running. Refresh to reconnect."
              : job?.error_message ||
                String(
                  job?.result_summary?.stage ??
                    "Preparing terrain. You can keep exploring.",
                )}
          </p>
          {jobQuery.isError && <button onClick={() => void jobQuery.refetch()}>Reconnect to scan</button>}
          {!!jobId && busy && <button onClick={() => void cancelScan()} disabled={cancelling}>{cancelling ? 'Cancelling…' : 'Cancel scan'}</button>}
          {!jobQuery.isError && job?.status !== "FAILED" && (
            <progress max="100" value={job?.progress ?? 0} />
          )}
        </div>
      )}
      {(notice || terrainError) && (
        <div className="landscape-notice" role="status">
          <span>
            {notice ||
              "Some terrain tiles could not load. Pan or zoom to retry; aerial imagery is also available."}
          </span>
          <button
            className="icon-button"
            aria-label="Dismiss message"
            onClick={() => {
              setNotice("");
              setTerrainError(false);
            }}
          >
            <X size={16} />
          </button>
        </div>
      )}
      <div className="map-hint">
        <ChevronLeft size={12} />
        <span>Drag to explore · Right-drag to tilt & rotate</span>
        <ChevronRight size={12} />
      </div>
    </main>
  );
}
