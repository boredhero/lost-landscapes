import { useCallback, useEffect, useRef, useState } from 'react';
import Map, { NavigationControl, ScaleControl, GeolocateControl, useMap } from 'react-map-gl/maplibre';
import { MapboxOverlay } from '@deck.gl/mapbox';
import { HeatmapLayer } from '@deck.gl/aggregation-layers';
import { useControl } from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';

import { useStore } from '../../store';
import { useDetections } from '../../hooks/useDetections';
import { getDetectionDetail, getTileCoverage } from '../../api/client';
import DrawControl from './DrawControl';
import type { Basemap, Detection } from '../../types';
import { FEATURE_COLORS } from '../../types';

const TERRAIN_SOURCE = {
  type: 'raster-dem' as const,
  tiles: ['/api/raster/terrain/{z}/{x}/{y}.png'],
  tileSize: 256,
  encoding: 'terrarium' as const,
  minzoom: 7,
  maxzoom: 15,
};

const MAPLIBRE_GLYPHS = 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf';

// Shared relief hillshade source — available on ALL basemaps where we have LiDAR DEMs.
// Outside coverage, tiles are transparent (RGBA) so the base imagery shows through.
const RELIEF_SOURCE = {
  type: 'raster' as const,
  tiles: ['/api/raster/hillshade/{z}/{x}/{y}.png'],
  tileSize: 256,
  minzoom: 10,
  maxzoom: 18,
};

const SATELLITE_STYLE = {
  version: 8 as const,
  glyphs: MAPLIBRE_GLYPHS,
  sources: {
    'esri-satellite': {
      type: 'raster' as const,
      tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256,
      maxzoom: 18,
      attribution: 'Esri, Maxar, Earthstar Geographics',
    },
    'carto-labels': {
      type: 'raster' as const,
      tiles: ['https://basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}@2x.png'],
      tileSize: 256,
      maxzoom: 18,
      attribution: 'CARTO',
    },
    'relief-hillshade': RELIEF_SOURCE,
    'terrain-source': TERRAIN_SOURCE,
  },
  layers: [
    {
      id: 'satellite',
      type: 'raster' as const,
      source: 'esri-satellite',
    },
    {
      id: 'relief-hillshade',
      type: 'raster' as const,
      source: 'relief-hillshade',
      paint: { 'raster-opacity': 0.55 },
    },
    {
      id: 'labels',
      type: 'raster' as const,
      source: 'carto-labels',
    },
  ],
};

const RELIEF_STYLE = {
  version: 8 as const,
  glyphs: MAPLIBRE_GLYPHS,
  sources: {
    'relief-hillshade': RELIEF_SOURCE,
    'terrain-source': TERRAIN_SOURCE,
  },
  layers: [
    {
      id: 'void-background',
      type: 'background' as const,
      paint: { 'background-color': '#1a1a1e', 'background-opacity': 1 },
    },
    {
      id: 'relief-hillshade',
      type: 'raster' as const,
      source: 'relief-hillshade',
      paint: { 'raster-opacity': 1.0 },
    },
  ],
};

const TOPO_STYLE = {
  version: 8 as const,
  glyphs: MAPLIBRE_GLYPHS,
  sources: {
    'opentopomap': {
      type: 'raster' as const,
      tiles: ['https://tile.opentopomap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 17,
      attribution: 'OpenTopoMap',
    },
    'relief-hillshade': RELIEF_SOURCE,
    'terrain-source': TERRAIN_SOURCE,
  },
  layers: [
    {
      id: 'topo-base',
      type: 'raster' as const,
      source: 'opentopomap',
    },
    {
      id: 'relief-hillshade',
      type: 'raster' as const,
      source: 'relief-hillshade',
      paint: { 'raster-opacity': 0.45 },
    },
  ],
};

const BASEMAP_STYLES: Record<Basemap, string | object> = {
  satellite: SATELLITE_STYLE,
  relief: RELIEF_STYLE,
  topo: TOPO_STYLE,
  dark: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
};

function DeckGLOverlay(props: { layers: any[] }) {
  const overlay = useControl(() => new MapboxOverlay({ interleaved: false }));
  useEffect(() => {
    try {
      overlay.setProps({ layers: props.layers });
    } catch {
      // Ignore during style transitions when GL context is temporarily invalid
    }
  }, [overlay, props.layers]);
  return null;
}

/** Manages 3D terrain via MapLibre native setTerrain() with try-catch.
 *  Re-applies after every basemap style swap (MapLibre destroys terrain on style change).
 *  Debounces exaggeration to prevent NaN crash from rapid slider adjustment. */
function TerrainController() {
  const { current: mapRef } = useMap();
  const show3DTerrain = useStore((s) => s.show3DTerrain);
  const terrainExaggeration = useStore((s) => s.terrainExaggeration);
  const basemap = useStore((s) => s.basemap);
  const exaggerationRef = useRef(terrainExaggeration);
  exaggerationRef.current = terrainExaggeration;
  useEffect(() => {
    const map = mapRef?.getMap();
    if (!map) return;
    const applyTerrain = () => {
      requestAnimationFrame(() => {
        try {
          if (!map.isStyleLoaded()) return;
          if (!map.getSource('terrain-source')) {
            try { map.addSource('terrain-source', TERRAIN_SOURCE); } catch { /* race */ }
          }
          if (!map.getSource('terrain-source')) return;
          // Terrain DEMs are permanent (VRT mosaic of all processed tiles) with a
          // global AWS fallback, so terrain is always servable — render it whenever
          // 3D is enabled instead of gating on a per-session warm flag. MapLibre
          // pulls tiles lazily; areas without data fall back to AWS global terrain.
          if (show3DTerrain) {
            map.setTerrain({ source: 'terrain-source', exaggeration: exaggerationRef.current });
          } else {
            map.setTerrain(null);
          }
        } catch { /* suppress DOMException during style transitions */ }
      });
    };
    applyTerrain();
    map.on('style.load', applyTerrain);
    return () => { map.off('style.load', applyTerrain); };
  }, [mapRef, show3DTerrain, basemap]);
  // Debounced exaggeration updates — prevents NaN crash from rapid slider changes
  useEffect(() => {
    const map = mapRef?.getMap();
    if (!map || !show3DTerrain) return;
    const timer = setTimeout(() => {
      try {
        if (map.isStyleLoaded() && map.getSource('terrain-source')) {
          map.setTerrain({ source: 'terrain-source', exaggeration: terrainExaggeration });
        }
      } catch { /* suppress during transitions */ }
    }, 150);
    return () => clearTimeout(timer);
  }, [terrainExaggeration, mapRef, show3DTerrain]);
  return null;
}

function FlyToHandler() {
  const { current: mapRef } = useMap();
  const targetViewState = useStore((s) => s.targetViewState);
  const clearTargetViewState = useStore((s) => s.clearTargetViewState);

  useEffect(() => {
    if (targetViewState && mapRef) {
      console.log('[HoleFinder] FlyTo:', targetViewState.latitude.toFixed(4), targetViewState.longitude.toFixed(4));
      mapRef.flyTo({
        center: [targetViewState.longitude, targetViewState.latitude],
        zoom: targetViewState.zoom,
        pitch: targetViewState.pitch ?? 45,
        bearing: targetViewState.bearing ?? -15,
        duration: 2000,
      });
      clearTargetViewState();
    }
  }, [targetViewState, mapRef, clearTargetViewState]);

  return null;
}

/** Adds MVT vector tile layers for detections + ground truth. Re-adds after basemap change. */
function MVTLayerManager() {
  const { current: mapRef } = useMap();
  const basemap = useStore((s) => s.basemap);
  const showGroundTruth = useStore((s) => s.showGroundTruth);
  const tileVersion = useStore((s) => s.tileVersion);
  const setSelectedDetection = useStore((s) => s.setSelectedDetection);
  const setDrawerState = useStore((s) => s.setDrawerState);
  const setSidebarOpen = useStore((s) => s.setSidebarOpen);

  const addMVTLayers = useCallback((map: any) => {
    console.log('[MVT] addMVTLayers called, style loaded:', map.isStyleLoaded(), 'existing sources:', Object.keys(map.getStyle()?.sources || {}));
    // Detection tiles
    if (!map.getSource('detections-mvt')) {
      map.addSource('detections-mvt', {
        type: 'vector',
        tiles: [`${window.location.origin}/api/tiles/{z}/{x}/{y}.mvt?min_confidence=0.3`],
        minzoom: 6,
        maxzoom: 16,
      });
      console.log('[MVT] Added detections-mvt source');
    }
    if (!map.getLayer('detections-circles')) {
      map.addLayer({
        id: 'detections-circles',
        type: 'circle',
        source: 'detections-mvt',
        'source-layer': 'detections',
        // Zoom-dependent confidence filter: at low zoom only show high-confidence,
        // progressively reveal lower-confidence detections as user zooms in.
        // More lenient at high zoom so zoomed-in users see everything in their viewport.
        filter: ['>=', ['get', 'confidence'],
          ['step', ['zoom'],
            0.7,      // zoom < 11: only high confidence (wide view)
            11, 0.5,  // zoom 11–13: medium
            13, 0.3,  // zoom 13–15: most detections
            15, 0.15, // zoom 15+: show everything stored
          ],
        ],
        paint: {
          // Radius scales with both zoom AND confidence
          'circle-radius': [
            'interpolate', ['linear'], ['zoom'],
            8, ['interpolate', ['linear'], ['get', 'confidence'], 0.3, 2, 0.7, 4, 1.0, 6],
            12, ['interpolate', ['linear'], ['get', 'confidence'], 0.3, 4, 0.7, 8, 1.0, 12],
            16, ['interpolate', ['linear'], ['get', 'confidence'], 0.3, 8, 0.7, 14, 1.0, 20],
          ],
          'circle-color': ['match', ['get', 'feature_type'],
            'cave_entrance', FEATURE_COLORS.cave_entrance,
            'mine_portal', FEATURE_COLORS.mine_portal,
            'sinkhole', FEATURE_COLORS.sinkhole,
            'depression', FEATURE_COLORS.depression,
            'collapse_pit', FEATURE_COLORS.collapse_pit,
            'spring', FEATURE_COLORS.spring,
            'lava_tube', FEATURE_COLORS.lava_tube,
            'salt_dome_collapse', FEATURE_COLORS.salt_dome_collapse,
            FEATURE_COLORS.unknown,
          ],
          'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 8, 1, 14, 2, 18, 3],
          'circle-stroke-color': 'rgba(255,255,255,0.7)',
          'circle-opacity': [
            'interpolate', ['linear'], ['get', 'confidence'],
            0.3, 0.35,
            0.5, 0.55,
            0.7, 0.75,
            0.9, 0.95,
          ],
        },
      });
    }

    // Detection outline polygons (from same MVT source, 'outlines' layer)
    if (!map.getLayer('detection-outlines-fill')) {
      map.addLayer({
        id: 'detection-outlines-fill',
        type: 'fill',
        source: 'detections-mvt',
        'source-layer': 'outlines',
        paint: {
          'fill-color': '#ff1a4a',
          'fill-opacity': ['interpolate', ['linear'], ['zoom'], 10, 0.15, 13, 0.25, 15, 0.35, 18, 0.5],
        },
      });
    }
    if (!map.getLayer('detection-outlines-stroke')) {
      map.addLayer({
        id: 'detection-outlines-stroke',
        type: 'line',
        source: 'detections-mvt',
        'source-layer': 'outlines',
        paint: {
          'line-color': '#ff0044',
          'line-width': ['interpolate', ['linear'], ['zoom'], 10, 2, 13, 3, 15, 4, 17, 6, 18, 8],
          'line-opacity': 1.0,
        },
      });
    }

    console.log('[MVT] Layers added. Sources:', Object.keys(map.getStyle()?.sources || {}), 'Layers:', map.getStyle()?.layers?.map((l: any) => l.id).filter((id: string) => id.includes('detection') || id.includes('outline') || id.includes('ground')));
    // Log when MVT tiles actually load data
    map.on('sourcedata', (e: any) => {
      if (e.sourceId === 'detections-mvt' && e.isSourceLoaded) {
        const features = map.querySourceFeatures('detections-mvt', { sourceLayer: 'detections' });
        const outlines = map.querySourceFeatures('detections-mvt', { sourceLayer: 'outlines' });
        console.log('[MVT] detections-mvt loaded:', features.length, 'detection features,', outlines.length, 'outline features');
      }
    });
    // Ground truth tiles
    if (!map.getSource('ground-truth-mvt')) {
      map.addSource('ground-truth-mvt', {
        type: 'vector',
        tiles: [`${window.location.origin}/api/tiles/ground-truth/{z}/{x}/{y}.mvt`],
        minzoom: 6,
        maxzoom: 16,
      });
    }
    if (!map.getLayer('ground-truth-circles')) {
      map.addLayer({
        id: 'ground-truth-circles',
        type: 'circle',
        source: 'ground-truth-mvt',
        'source-layer': 'ground_truth',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 8, 5, 14, 10, 18, 16],
          'circle-color': '#ffd700',
          'circle-stroke-width': 2,
          'circle-stroke-color': '#ffffff',
          'circle-opacity': 0.9,
        },
      });
    }
  }, []);

  useEffect(() => {
    const map = mapRef?.getMap();
    if (!map) return;

    const setup = () => {
      addMVTLayers(map);
      console.log('[MVT] setup() complete');

      // Click detection dot → fetch detail → show in drawer/sidebar
      map.on('click', 'detections-circles', async (e: any) => {
        const feature = e.features?.[0];
        if (!feature?.properties?.id) return;
        try {
          const detail = await getDetectionDetail(feature.properties.id);
          const d: Detection = {
            id: detail.id,
            lat: e.lngLat.lat,
            lon: e.lngLat.lng,
            feature_type: detail.feature_type,
            confidence: detail.confidence,
            depth_m: detail.depth_m,
            area_m2: detail.area_m2,
            circularity: detail.circularity,
            wall_slope_deg: detail.wall_slope_deg,
            source_passes: detail.source_passes,
            morphometrics: detail.morphometrics,
            validated: detail.validated,
            validation_notes: detail.validation_notes,
          };
          setSelectedDetection(d);
          setDrawerState('detail');
          setSidebarOpen(true);
        } catch {
          // ignore fetch errors on click
        }
      });

      // Click outline polygon → same detail flow
      map.on('click', 'detection-outlines-fill', async (e: any) => {
        const feature = e.features?.[0];
        if (!feature?.properties?.id) return;
        try {
          const detail = await getDetectionDetail(feature.properties.id);
          const d: Detection = {
            id: detail.id,
            lat: e.lngLat.lat,
            lon: e.lngLat.lng,
            feature_type: detail.feature_type,
            confidence: detail.confidence,
            depth_m: detail.depth_m,
            area_m2: detail.area_m2,
            circularity: detail.circularity,
            wall_slope_deg: detail.wall_slope_deg,
            source_passes: detail.source_passes,
            morphometrics: detail.morphometrics,
            validated: detail.validated,
            validation_notes: detail.validation_notes,
          };
          setSelectedDetection(d);
          setDrawerState('detail');
          setSidebarOpen(true);
        } catch {
          // ignore fetch errors on click
        }
      });

      // Cursor
      map.on('mouseenter', 'detections-circles', () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', 'detections-circles', () => { map.getCanvas().style.cursor = ''; });
      map.on('mouseenter', 'detection-outlines-fill', () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', 'detection-outlines-fill', () => { map.getCanvas().style.cursor = ''; });
    };

    // Try immediately if style already loaded, otherwise wait for ready/style.load
    if (map.isStyleLoaded()) {
      setup();
    } else {
      map.once('style.load', setup);
    }
    // Also listen for our custom ready event (fired from Map onLoad)
    map.on('holefinder:ready', () => {
      if (!map.getSource('detections-mvt')) setup();
    });

    // Re-add layers after basemap change destroys them.
    // rAF delay lets the GL context settle — without it, addSource/addLayer
    // throw DOMException during the style transition.
    map.on('style.load', () => {
      requestAnimationFrame(() => {
        // For external styles (Dark), relief source isn't baked in
        try {
          if (!map.getSource('relief-hillshade')) {
            map.addSource('relief-hillshade', RELIEF_SOURCE);
            map.addLayer({ id: 'relief-hillshade', type: 'raster', source: 'relief-hillshade', paint: { 'raster-opacity': 0.35 } });
          }
        } catch { /* race */ }
        try {
          addMVTLayers(map);
        } catch (e) {
          console.warn('[MVT] Re-add after style change failed:', e);
          requestAnimationFrame(() => { try { addMVTLayers(map); } catch { /* give up */ } });
        }
      });
    });
  }, [mapRef, addMVTLayers, setSelectedDetection, setDrawerState, setSidebarOpen]);

  // Force MVT tile reload when tileVersion bumps (after scan completion)
  useEffect(() => {
    if (tileVersion === 0) return; // skip initial
    const map = mapRef?.getMap();
    if (!map) return;
    const src = map.getSource('detections-mvt') as any;
    if (src) {
      // Update tile URL with cache-busting param and reload
      src.setTiles([`${window.location.origin}/api/tiles/{z}/{x}/{y}.mvt?min_confidence=0.3&v=${tileVersion}`]);
      console.log('[MVT] Tile cache busted, version:', tileVersion);
    }
  }, [tileVersion, mapRef]);

  // Explicit re-add after basemap change. style.load + rAF alone isn't reliable
  // because react-map-gl's internal style reconciliation can run AFTER our rAF
  // callback, wiping out layers we just added. This belt-and-suspenders approach
  // waits 300ms for everything to settle, then forces re-add.
  useEffect(() => {
    const map = mapRef?.getMap();
    if (!map) return;
    const timer = setTimeout(() => {
      try {
        const doAdd = () => {
          if (!map.getSource('relief-hillshade')) {
            try { map.addSource('relief-hillshade', RELIEF_SOURCE); map.addLayer({ id: 'relief-hillshade', type: 'raster', source: 'relief-hillshade', paint: { 'raster-opacity': 0.35 } }); } catch { /* exists */ }
          }
          addMVTLayers(map);
          console.log('[MVT] Re-added after basemap change to:', basemap);
        };
        if (map.isStyleLoaded()) {
          doAdd();
        } else {
          map.once('style.load', doAdd);
        }
      } catch { /* style transition race */ }
    }, 300);
    return () => clearTimeout(timer);
  }, [basemap, mapRef, addMVTLayers]);

  // Toggle ground truth visibility
  useEffect(() => {
    const map = mapRef?.getMap();
    if (!map || !map.getLayer('ground-truth-circles')) return;
    map.setLayoutProperty('ground-truth-circles', 'visibility', showGroundTruth ? 'visible' : 'none');
  }, [showGroundTruth, mapRef]);

  return null;
}

/** Fetches tile coverage GeoJSON and renders fill+line layers showing LiDAR vs AWS source. */
function TileCoverageLayer() {
  const { current: mapRef } = useMap();
  const showTileCoverage = useStore((s) => s.showTileCoverage);
  const bbox = useStore((s) => s.bbox);
  const viewState = useStore((s) => s.viewState);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Idempotent: ensures source+layers exist on the current style. Returns true if ready.
  const ensureLayers = useCallback((map: any): boolean => {
    try {
      if (!map.isStyleLoaded()) return false;
      if (!map.getSource('tile-coverage')) {
        map.addSource('tile-coverage', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      }
      if (!map.getLayer('tile-coverage-fill')) {
        map.addLayer({
          id: 'tile-coverage-fill', type: 'fill', source: 'tile-coverage',
          paint: {
            'fill-color': ['match', ['get', 'source'], 'lidar', '#eab308', '#06b6d4'],
            'fill-opacity': ['match', ['get', 'source'], 'lidar', 0.25, 0.12],
          },
        });
      }
      if (!map.getLayer('tile-coverage-line')) {
        map.addLayer({
          id: 'tile-coverage-line', type: 'line', source: 'tile-coverage',
          paint: {
            'line-color': ['match', ['get', 'source'], 'lidar', '#eab308', '#06b6d4'],
            'line-width': ['match', ['get', 'source'], 'lidar', 2.5, 1],
            'line-opacity': ['match', ['get', 'source'], 'lidar', 0.9, 0.5],
          },
        });
      }
      if (!map.getLayer('tile-coverage-label')) {
        map.addLayer({
          id: 'tile-coverage-label', type: 'symbol', source: 'tile-coverage',
          filter: ['==', ['get', 'source'], 'lidar'],
          layout: { 'text-field': 'LiDAR', 'text-size': 11, 'text-font': ['Open Sans Semibold'], 'text-allow-overlap': false },
          paint: { 'text-color': '#eab308', 'text-halo-color': 'rgba(0,0,0,0.8)', 'text-halo-width': 1.5 },
        });
      }
      const vis = useStore.getState().showTileCoverage ? 'visible' : 'none';
      for (const id of ['tile-coverage-fill', 'tile-coverage-line', 'tile-coverage-label']) {
        if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', vis);
      }
      return true;
    } catch {
      return false;
    }
  }, []);
  // Register for style.load + holefinder:ready so layers survive basemap switches
  useEffect(() => {
    const map = mapRef?.getMap();
    if (!map) return;
    const handler = () => ensureLayers(map);
    if (map.isStyleLoaded()) handler();
    map.on('style.load', handler);
    map.on('holefinder:ready', handler);
    return () => { map.off('style.load', handler); map.off('holefinder:ready', handler); };
  }, [mapRef, ensureLayers]);
  // Toggle visibility
  useEffect(() => {
    const map = mapRef?.getMap();
    if (!map) return;
    const vis = showTileCoverage ? 'visible' : 'none';
    for (const id of ['tile-coverage-fill', 'tile-coverage-line', 'tile-coverage-label']) {
      try { if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', vis); } catch { /* style transition */ }
    }
  }, [showTileCoverage, mapRef]);
  // Fetch coverage data on viewport change (debounced 500ms)
  useEffect(() => {
    if (!showTileCoverage || !bbox || !viewState) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      if (abortRef.current) abortRef.current.abort();
      abortRef.current = new AbortController();
      const z = Math.min(Math.floor(viewState.zoom), 15);
      if (z < 12) {
        // Clear stale coverage when zoomed too far out (z<12 tiles are huge)
        const map = mapRef?.getMap();
        if (map?.getSource('tile-coverage')) (map.getSource('tile-coverage') as any).setData({ type: 'FeatureCollection', features: [] });
        return;
      }
      try {
        const geojson = await getTileCoverage(bbox[0], bbox[1], bbox[2], bbox[3], z);
        const map = mapRef?.getMap();
        if (!map) return;
        ensureLayers(map);
        if (map.getSource('tile-coverage')) {
          (map.getSource('tile-coverage') as any).setData(geojson);
        }
      } catch { /* fetch aborted or failed */ }
    }, 500);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [showTileCoverage, bbox, viewState, mapRef, ensureLayers]);
  return null;
}

/** Right-click (desktop) / long-press (mobile) → copy GPS coordinates to clipboard with toast. */
function CoordinateCopy() {
  const { current: mapRef } = useMap();
  const [toast, setToast] = useState<{ text: string; x: number; y: number } | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    const map = mapRef?.getMap();
    if (!map) return;
    const handler = (e: any) => {
      e.preventDefault();
      const lat = e.lngLat.lat.toFixed(6);
      const lon = e.lngLat.lng.toFixed(6);
      const text = `${lat}, ${lon}`;
      navigator.clipboard.writeText(text).catch(() => {});
      const point = e.point;
      setToast({ text, x: point.x, y: point.y });
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setToast(null), 2000);
    };
    map.on('contextmenu', handler);
    return () => { map.off('contextmenu', handler); };
  }, [mapRef]);
  if (!toast) return null;
  return (
    <div className="absolute z-50 pointer-events-none" style={{ left: toast.x, top: toast.y, transform: 'translate(-50%, -120%)' }}>
      <div className="bg-slate-900/90 text-white text-sm font-mono px-3 py-1.5 rounded shadow-lg border border-slate-600/50 whitespace-nowrap">
        {toast.text} <span className="text-slate-400 ml-1">copied</span>
      </div>
    </div>
  );
}

const DEFAULT_VIEW = { longitude: -79.96, latitude: 40.50, zoom: 10, pitch: 45, bearing: -15 };

export default function MapView() {
  const basemap = useStore((s) => s.basemap);
  const showHeatmap = useStore((s) => s.showHeatmap);
  const setBbox = useStore((s) => s.setBbox);
  const drawingAOI = useStore((s) => s.drawingAOI);
  const setDrawnAOI = useStore((s) => s.setDrawnAOI);
  const storedViewState = useStore((s) => s.viewState);
  const setViewState = useStore((s) => s.setViewState);
  const setSearchStale = useStore((s) => s.setSearchStale);

  // Heatmap still uses deck.gl + useDetections (playground only)
  const { data: detections = [] } = useDetections();

  const heatmapLayers = showHeatmap && detections.length > 0
    ? [new HeatmapLayer({
        id: 'heatmap',
        data: detections,
        getPosition: (d: Detection) => [d.lon, d.lat],
        getWeight: (d: Detection) => d.confidence,
        radiusPixels: 40,
        intensity: 1,
        threshold: 0.1,
        opacity: 0.6,
      })]
    : [];

  const handleMoveEnd = useCallback((evt: any) => {
    const map = evt.target;
    const bounds = map.getBounds();
    setBbox([bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()]);
    const center = map.getCenter();
    setViewState({
      longitude: center.lng,
      latitude: center.lat,
      zoom: map.getZoom(),
      pitch: map.getPitch(),
      bearing: map.getBearing(),
    });
    setSearchStale(true);
  }, [setBbox, setViewState, setSearchStale]);

  return (
    <Map
      initialViewState={storedViewState ?? DEFAULT_VIEW}
      style={{ width: '100%', height: '100%' }}
      mapStyle={BASEMAP_STYLES[basemap] as any}
      dragRotate={true}
      touchZoomRotate={true}
      touchPitch={true}
      pitchWithRotate={true}
      onMoveEnd={handleMoveEnd}
      onLoad={(evt) => {
        const map = evt.target;
        const bounds = map.getBounds();
        setBbox([bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()]);
        // Suppress terrain tile decode errors — non-fatal, map shows flat terrain for failed tiles
        map.on('error', (e: any) => {
          if (e?.error?.message?.includes('usable') || e?.sourceId === 'terrain-source') return;
          console.warn('[MapView] Map error:', e?.error?.message || e);
        });
        // Dispatch custom event so MVTLayerManager knows map is ready
        map.fire('holefinder:ready');
      }}
    >
      {heatmapLayers.length > 0 && <DeckGLOverlay layers={heatmapLayers} />}
      <TerrainController />
      <MVTLayerManager />
      <TileCoverageLayer />
      <CoordinateCopy />
      <FlyToHandler />
      <DrawControl
        active={drawingAOI}
        onDrawCreate={(geom) => setDrawnAOI(geom)}
        onDrawDelete={() => setDrawnAOI(null)}
      />
      <NavigationControl position="bottom-right" />
      <ScaleControl position="bottom-left" />
      <GeolocateControl position="bottom-right" />
    </Map>
  );
}
