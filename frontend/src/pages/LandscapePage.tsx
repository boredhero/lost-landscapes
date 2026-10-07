import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpRight,
  Check,
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
import LandscapeMap from "../components/Landscape/LandscapeMap";
import type {
  Bounds,
  CameraTarget,
  MapMode,
} from "../components/Landscape/LandscapeMap";
import { createJob, geocodeZip, getDetections, getJob } from "../api/client";
import type { Detection, Job } from "../types";
import { FEATURE_LABELS } from "../types";
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
  const [is3D, set3D] = useState(true);
  const [exaggeration, setExaggeration] = useState(1.25);
  const [split, setSplit] = useState(50);
  const [panel, setPanel] = useState<"explore" | "terrain" | null>("explore");
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
  const [saved, setSaved] = useState<Detection[]>(() => {
    try {
      return JSON.parse(localStorage.getItem("landscape-saved") || "[]");
    } catch {
      return [];
    }
  });
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
    if (job?.status !== "COMPLETED") return;
    void client.invalidateQueries({ queryKey: ["landscape-catalog"] });
    void client.invalidateQueries({ queryKey: ["landscape-detections"] });
    setNotice(
      "Analysis complete. Select a candidate on the map to inspect it.",
    );
    sessionStorage.removeItem("landscape-job");
    setJobId(null);
  }, [job?.status, client]);
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
    const next = saved.some((d) => d.id === detection.id)
      ? saved.filter((d) => d.id !== detection.id)
      : [...saved, detection];
    setSaved(next);
    localStorage.setItem("landscape-saved", JSON.stringify(next));
  }
  function toggle3D() {
    set3D(!is3D);
    move({ pitch: is3D ? 0 : 55 });
  }
  return (
    <main className="landscape-app">
      <LandscapeMap
        mode={mode}
        revision={catalog.revision}
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
          {saved.length > 0 && (
            <div className="saved-places">
              <div className="section-label">SAVED ON THIS DEVICE</div>
              {saved.map((d) => (
                <button
                  key={d.id}
                  onClick={() => {
                    setSelected(d);
                    move({ longitude: d.lon, latitude: d.lat, zoom: 17 });
                  }}
                >
                  <MapPin size={14} />
                  {FEATURE_LABELS[d.feature_type] ?? "Terrain candidate"}
                  <ChevronRight size={14} />
                </button>
              ))}
            </div>
          )}
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
            {saved.some((d) => d.id === selected.id) ? (
              <Check size={16} />
            ) : (
              <MapPin size={16} />
            )}{" "}
            {saved.some((d) => d.id === selected.id)
              ? "Saved · remove"
              : "Save this place"}
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
      <nav className="map-tools" aria-label="Map controls">
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
            terrain.
          </p>
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
          <span className={`status-dot ${insideCoverage ? "" : "muted-dot"}`} />
          <div>
            <strong>
              {loadingTiles
                ? "Loading terrain…"
                : insideCoverage
                  ? "LiDAR terrain"
                  : "Regional terrain"}
            </strong>
            <small>
              {insideCoverage
                ? (activeArea?.source ?? "Imported elevation data")
                : "Zoom to a study area for fine ground detail"}
            </small>
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
                  : "Analyzing this landscape"}
            </strong>
            <button
              className="icon-button"
              aria-label="Dismiss analysis status"
              onClick={() => {
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
