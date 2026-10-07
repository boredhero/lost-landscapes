import { useEffect, useRef, useCallback } from 'react';
import { useMap } from 'react-map-gl/maplibre';
import {
  TerraDraw,
  TerraDrawPolygonMode,
  TerraDrawSelectMode,
  TerraDrawRenderMode,
} from 'terra-draw';
import { TerraDrawMapLibreGLAdapter } from 'terra-draw-maplibre-gl-adapter';

interface DrawControlProps {
  active: boolean;
  onDrawCreate: (geometry: GeoJSON.Geometry) => void;
  onDrawDelete: () => void;
}

export default function DrawControl({ active, onDrawCreate, onDrawDelete }: DrawControlProps) {
  const { current: mapRef } = useMap();
  const drawRef = useRef<TerraDraw | null>(null);
  const onDrawCreateRef = useRef(onDrawCreate);
  useEffect(() => { onDrawCreateRef.current = onDrawCreate; }, [onDrawCreate]);

  const startDraw = useCallback(() => {
    const map = mapRef?.getMap();
    if (!map || !map.isStyleLoaded()) return;

    // Clean up existing instance
    if (drawRef.current?.enabled) {
      try { drawRef.current.stop(); } catch {}
      drawRef.current = null;
    }

    const draw = new TerraDraw({
      adapter: new TerraDrawMapLibreGLAdapter({ map }),
      modes: [
        new TerraDrawPolygonMode(),
        new TerraDrawSelectMode({
          flags: {
            polygon: {
              feature: {
                draggable: true,
                coordinates: { midpoints: { draggable: true }, draggable: true, deletable: true },
              },
            },
          },
        }),
        new TerraDrawRenderMode({ modeName: 'static' } as any),
      ],
    });

    draw.start();
    draw.setMode('polygon');

    draw.on('finish', (id) => {
      const snapshot = draw.getSnapshot();
      const feature = snapshot.find((f) => f.id === id);
      if (feature?.geometry) {
        onDrawCreateRef.current(feature.geometry);
      }
    });

    drawRef.current = draw;
  }, [mapRef]);

  const stopDraw = useCallback(() => {
    if (drawRef.current?.enabled) {
      try { drawRef.current.stop(); } catch {}
      drawRef.current = null;
    }
    onDrawDelete();
  }, [onDrawDelete]);

  useEffect(() => {
    if (active) {
      const map = mapRef?.getMap();
      if (map?.isStyleLoaded()) {
        startDraw();
      } else {
        map?.once('style.load', startDraw);
      }
    } else {
      stopDraw();
    }

    return () => {
      if (drawRef.current?.enabled) {
        try { drawRef.current.stop(); } catch {}
        drawRef.current = null;
      }
    };
  }, [active, startDraw, stopDraw, mapRef]);

  return null;
}
