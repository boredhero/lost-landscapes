import { useEffect, useMemo, useRef, useState } from "react";
import Map, {
  Layer,
  Source,
  ScaleControl,
  AttributionControl,
} from "react-map-gl/maplibre";
import type {
  MapRef,
  MapLayerMouseEvent,
  ViewState,
} from "react-map-gl/maplibre";
import type { StyleSpecification } from "maplibre-gl";
import type { Detection } from "../../types";
import type { ReliefRadius, TerrainLayer } from "./terrainLayers";
import { terrainMinZoom, usesTerrainRadius } from "./terrainLayers";
import "maplibre-gl/dist/maplibre-gl.css";

export type MapMode = "lidar" | "aerial" | "compare";
export type Bounds = [number, number, number, number];
export interface CameraTarget {
  longitude: number;
  latitude: number;
  zoom: number;
  pitch: number;
  bearing: number;
  id: number;
}
interface Props {
  mode: MapMode;
  revision: string;
  terrainLayer: TerrainLayer;
  reliefRadius: ReliefRadius;
  lightAzimuth: number;
  is3D: boolean;
  exaggeration: number;
  split: number;
  target: CameraTarget | null;
  detections: Detection[];
  coverage: Bounds[];
  showCoverage: boolean;
  selected: string | null;
  onSelect: (d: Detection) => void;
  onView: (view: ViewState, bbox: Bounds) => void;
  onTerrainError: () => void;
  onLoading: (loading: boolean) => void;
}
const initial = {
  longitude: -79.986,
  latitude: 40.499,
  zoom: 14.4,
  pitch: 55,
  bearing: -25,
};

function style(
  aerial: boolean, revision: string, terrainLayer: TerrainLayer = "relief",
  reliefRadius: ReliefRadius = 25, lightAzimuth = 315,
): StyleSpecification {
  const suffix = `?v=${encodeURIComponent(revision)}`;
  const derivative = terrainLayer !== "relief";
  const parameters = usesTerrainRadius(terrainLayer) ? `&radius_m=${reliefRadius}`
    : terrainLayer === "hillshade" ? `&azimuth=${lightAzimuth}` : "";
  return {
    version: 8,
    sources: {
      terrain: {
        type: "raster-dem",
        tiles: [`/api/landscape/tiles/terrain/{z}/{x}/{y}.png${suffix}`],
        tileSize: 512,
        encoding: "terrarium",
        maxzoom: 18,
        attribution: "Terrain: USGS 3DEP / AWS Open Data",
      },
      relief: {
        type: "raster",
        tiles: [`/api/landscape/tiles/${terrainLayer}/{z}/{x}/{y}.png${suffix}${parameters}`],
        tileSize: 512,
        minzoom: derivative ? terrainMinZoom(terrainLayer) : 0,
        maxzoom: 18,
      },
      aerial: {
        type: "raster",
        tiles: [
          "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        ],
        tileSize: 256,
        maxzoom: 19,
        attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
      },
    },
    layers: [
      {
        id: "background",
        type: "background",
        paint: { "background-color": "#899486" },
      },
      ...(aerial
        ? [
            {
              id: "aerial",
              type: "raster" as const,
              source: "aerial",
              paint: {
                "raster-saturation": -0.18,
                "raster-fade-duration": 160,
              },
            },
          ]
        : [
            ...(!derivative ? [{
              id: "context-shade",
              type: "hillshade" as const,
              source: "terrain",
              paint: {
                "hillshade-exaggeration": 0.35,
                "hillshade-shadow-color": "#263d32",
                "hillshade-highlight-color": "#e0e5cf",
                "hillshade-illumination-anchor": "map" as const,
              },
            }] : []),
            {
              id: "relief",
              type: "raster" as const,
              source: "relief",
              paint: {
                "raster-fade-duration": 180,
                "raster-resampling": "linear" as const,
              },
            },
          ]),
    ],
  };
}

export default function LandscapeMap(props: Props) {
  const {
    mode,
    revision,
    terrainLayer,
    reliefRadius,
    lightAzimuth,
    is3D,
    exaggeration,
    split,
    target,
    detections,
    coverage,
    showCoverage,
    selected,
    onSelect,
    onView,
    onTerrainError,
    onLoading,
  } = props;
  const map = useRef<MapRef>(null);
  const [camera, setCamera] = useState(initial);
  const baseStyle = useMemo(
    () => style(mode === "aerial", revision, terrainLayer, reliefRadius, lightAzimuth),
    [mode, revision, terrainLayer, reliefRadius, lightAzimuth],
  );
  const aerialStyle = useMemo(() => style(true, revision), [revision]);
  const terrain = useMemo(
    () => (is3D ? { source: "terrain", exaggeration } : undefined),
    [is3D, exaggeration],
  );
  const geojson = useMemo<GeoJSON.FeatureCollection>(
    () => ({
      type: "FeatureCollection",
      features: detections.map((d) => ({
        type: "Feature",
        id: d.id,
        geometry: { type: "Point", coordinates: [d.lon, d.lat] },
        properties: { id: d.id, selected: d.id === selected },
      })),
    }),
    [detections, selected],
  );
  const footprints = useMemo<GeoJSON.FeatureCollection>(
    () => ({
      type: "FeatureCollection",
      features: coverage.map(([w, s, e, n]) => ({
        type: "Feature",
        properties: {},
        geometry: {
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
      })),
    }),
    [coverage],
  );

  useEffect(() => {
    if (target)
      map.current?.flyTo({
        center: [target.longitude, target.latitude],
        zoom: target.zoom,
        pitch: target.pitch,
        bearing: target.bearing,
        duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? 0
          : 900,
      });
  }, [target]);

  function reportView() {
    const current = map.current;
    if (!current) return;
    const center = current.getCenter();
    const b = current.getBounds();
    onView(
      {
        longitude: center.lng,
        latitude: center.lat,
        zoom: current.getZoom(),
        pitch: current.getPitch(),
        bearing: current.getBearing(),
        padding: { top: 0, bottom: 0, left: 0, right: 0 },
      },
      [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()],
    );
  }
  function click(event: MapLayerMouseEvent) {
    const id = event.features?.[0]?.properties?.id;
    const detection = detections.find((d) => d.id === id);
    if (detection) onSelect(detection);
  }
  return (
    <div className="landscape-map" aria-label="Interactive LiDAR terrain map">
      <Map
        ref={map}
        initialViewState={initial}
        mapStyle={baseStyle}
        terrain={terrain}
        maxPitch={75}
        maxZoom={19}
        attributionControl={false}
        onLoad={reportView}
        onData={() => onLoading(!(map.current?.areTilesLoaded() ?? false))}
        onIdle={() => onLoading(false)}
        onMove={(event) => setCamera(event.viewState)}
        onMoveEnd={reportView}
        onClick={click}
        interactiveLayerIds={["candidates"]}
        onError={onTerrainError}
      >
        <Source id="candidate-data" type="geojson" data={geojson}>
          <Layer
            id="candidate-halo"
            type="circle"
            paint={{
              "circle-radius": ["case", ["get", "selected"], 13, 9],
              "circle-color": "#e9b765",
              "circle-opacity": 0.25,
            }}
          />
          <Layer
            id="candidates"
            type="circle"
            paint={{
              "circle-radius": ["case", ["get", "selected"], 6, 4],
              "circle-color": "#e9b765",
              "circle-stroke-color": "#243a2c",
              "circle-stroke-width": 2,
            }}
          />
        </Source>
        {showCoverage && (
          <Source id="coverage" type="geojson" data={footprints}>
            <Layer
              id="coverage-outline"
              type="line"
              paint={{
                "line-color": "#e2efcc",
                "line-width": 1.5,
                "line-dasharray": [4, 3],
                "line-opacity": 0.8,
              }}
            />
          </Source>
        )}
        <ScaleControl position="bottom-left" unit="metric" />
        <AttributionControl position="bottom-right" compact />
      </Map>
      {mode === "compare" && (
        <>
          <div
            className="comparison-map"
            style={{ clipPath: `inset(0 0 0 ${split}%)` }}
            aria-hidden="true"
          >
            <Map
              {...camera}
              mapStyle={aerialStyle}
              terrain={terrain}
              interactive={false}
              attributionControl={false}
              maxPitch={75}
              maxZoom={19}
            />
          </div>
          <div className="comparison-line" style={{ left: `${split}%` }}>
            <span>↔</span>
          </div>
          <div className="comparison-caption">
            <span>Bare earth</span>
            <span>Aerial imagery</span>
          </div>
        </>
      )}
    </div>
  );
}
