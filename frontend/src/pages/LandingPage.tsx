import { useState, useCallback, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import MapView from '../components/Map/MapView';
import TopBar from '../components/Explore/TopBar';
import SettingsPanel from '../components/Explore/SettingsPanel';
import ProcessingScreen from '../components/Explore/ProcessingScreen';
import ResultsSplash from '../components/Explore/ResultsSplash';
import SwipeCard from '../components/Explore/SwipeCard';
import { useJobProgress } from '../hooks/useJobProgress';
import { useStore } from '../store';
import { geocodeZip, getDetections, startConsumerScan, warmTerrainCache } from '../api/client';
import { Locate, Search, Settings2, Loader2, AlertCircle, MapPin } from 'lucide-react';
import type { Detection } from '../types';

type Phase = 'splash' | 'processing' | 'results' | 'tour' | 'explore';

export default function LandingPage() {
  const [phase, setPhase] = useState<Phase>('splash');
  const [geoLoading, setGeoLoading] = useState(false);
  const [geoError, setGeoError] = useState<string | null>(null);
  const [zipCode, setZipCode] = useState('');
  const [zipLoading, setZipLoading] = useState(false);
  const [zipError, setZipError] = useState<string | null>(null);
  const [showZipInput, setShowZipInput] = useState(false);
  const [swipeDirection, setSwipeDirection] = useState(1);
  const setTargetViewState = useStore((s) => s.setTargetViewState);
  const setUserLocation = useStore((s) => s.setUserLocation);
  const setSearchStale = useStore((s) => s.setSearchStale);
  const bumpTileVersion = useStore((s) => s.bumpTileVersion);
  const setTerrainReady = useStore((s) => s.setTerrainReady);
  const userLocation = useStore((s) => s.userLocation);
  const activeJobId = useStore((s) => s.activeJobId);
  const setActiveJobId = useStore((s) => s.setActiveJobId);
  const tourDetections = useStore((s) => s.tourDetections);
  const setTourDetections = useStore((s) => s.setTourDetections);
  const tourIndex = useStore((s) => s.tourIndex);
  const setTourIndex = useStore((s) => s.setTourIndex);
  const scanCenter = useRef<{ lat: number; lon: number } | null>(null);
  const jobProgress = useJobProgress(phase === 'processing' ? activeJobId : null);
  // Shared flow after getting a location (from geo or zip)
  const handleLocationAcquired = useCallback(async (lat: number, lon: number) => {
    console.log('[lostlandscapes] Location acquired:', lat, lon);
    scanCenter.current = { lat, lon };
    setUserLocation({ lat, lon });
    setTerrainReady(false);
    setTargetViewState({ longitude: lon, latitude: lat, zoom: 14, pitch: 45, bearing: -15 });
    try {
      const { job_id } = await startConsumerScan(lat, lon, 1.5);
      console.log('[lostlandscapes] Scan started, job:', job_id);
      setActiveJobId(job_id);
      setPhase('processing');
    } catch (err) {
      console.error('[lostlandscapes] Scan failed:', err);
      setSearchStale(true);
      setPhase('explore');
    }
  }, [setUserLocation, setTargetViewState, setActiveJobId, setSearchStale, setTerrainReady]);
  const handleFindNearMe = useCallback(() => {
    if (!navigator.geolocation) {
      setGeoError("Your browser doesn't support geolocation.");
      return;
    }
    setGeoLoading(true);
    setGeoError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setGeoLoading(false);
        handleLocationAcquired(pos.coords.latitude, pos.coords.longitude);
      },
      (err) => {
        setGeoLoading(false);
        const messages: Record<number, string> = {
          1: "Location permission denied. Allow location access in your browser settings, or enter your zip code below.",
          2: "Location unavailable. Try entering your zip code instead.",
          3: "Location request timed out. Try entering your zip code instead.",
        };
        setGeoError(messages[err.code] ?? `Geolocation error (code ${err.code}): ${err.message}`);
        setShowZipInput(true);
      },
      { timeout: 10000 },
    );
  }, [handleLocationAcquired]);
  const handleZipSubmit = useCallback(async () => {
    if (!/^\d{5}$/.test(zipCode)) {
      setZipError('Enter a valid 5-digit zip code');
      return;
    }
    setZipLoading(true);
    setZipError(null);
    try {
      const { lat, lon } = await geocodeZip(zipCode);
      setZipLoading(false);
      handleLocationAcquired(lat, lon);
    } catch {
      setZipLoading(false);
      setZipError('Invalid or unrecognized zip code');
    }
  }, [zipCode, handleLocationAcquired]);
  // Watch for job completion
  const completionHandled = useRef(false);
  useEffect(() => {
    if (phase !== 'processing') { completionHandled.current = false; return; }
    if (completionHandled.current) return;
    const status = jobProgress.status;
    if (status !== 'COMPLETED' && status !== 'FAILED') return;
    completionHandled.current = true;
    console.log('[lostlandscapes] Job finished:', status);
    bumpTileVersion();
    if (status === 'FAILED') return;
    const center = scanCenter.current;
    if (!center) {
      console.error('[lostlandscapes] No scan center — going to explore');
      setSearchStale(true);
      // eslint-disable-next-line react-hooks/set-state-in-effect -- Recover from an external job without a scan center.
      setPhase('explore');
      return;
    }
    const rLat = 10 / 111.32;
    const rLon = 10 / (111.32 * Math.cos(center.lat * Math.PI / 180));
    const west = center.lon - rLon, south = center.lat - rLat;
    const east = center.lon + rLon, north = center.lat + rLat;
    const warmPromise = warmTerrainCache(west, south, east, north)
      .then((res) => { console.log('[lostlandscapes] Terrain cache warmed:', res); setTerrainReady(true); })
      .catch((err) => { console.warn('[lostlandscapes] Terrain warm failed (non-fatal):', err); setTerrainReady(true); });
    const detectPromise = getDetections({ west, south, east, north, min_confidence: 0.5, limit: 50 });
    Promise.all([warmPromise, detectPromise]).then(([, data]) => {
      const dets: Detection[] = (data.features || []).map((f: any) => ({
        id: f.id,
        lon: f.geometry.coordinates[0],
        lat: f.geometry.coordinates[1],
        ...f.properties,
      }));
      dets.sort((a, b) => {
        const aIsDepression = a.feature_type === 'depression' ? 1 : 0;
        const bIsDepression = b.feature_type === 'depression' ? 1 : 0;
        if (aIsDepression !== bIsDepression) return aIsDepression - bIsDepression;
        return b.confidence - a.confidence;
      });
      console.log('[lostlandscapes] Fetched', dets.length, 'detections for tour');
      setTourDetections(dets);
      setTourIndex(0);
      setActiveJobId(null);
      if (dets.length > 0) {
        setPhase('results');
      } else {
        setSearchStale(true);
        setPhase('explore');
      }
    }).catch((err) => {
      console.error('[lostlandscapes] Failed to fetch detections:', err);
      setSearchStale(true);
      setPhase('explore');
    });
  }, [phase, jobProgress.status, setTourDetections, setTourIndex, setActiveJobId, setSearchStale, setTargetViewState, bumpTileVersion, setTerrainReady]);
  // Tour navigation
  const handleTourNext = useCallback(() => {
    if (tourIndex < tourDetections.length - 1) {
      const next = tourIndex + 1;
      setTourIndex(next);
      setSwipeDirection(1);
      const d = tourDetections[next];
      setTargetViewState({ longitude: d.lon, latitude: d.lat, zoom: 15, pitch: 45, bearing: -15 });
    }
  }, [tourIndex, tourDetections, setTourIndex, setTargetViewState]);
  const handleTourPrev = useCallback(() => {
    if (tourIndex > 0) {
      const prev = tourIndex - 1;
      setTourIndex(prev);
      setSwipeDirection(-1);
      const d = tourDetections[prev];
      setTargetViewState({ longitude: d.lon, latitude: d.lat, zoom: 15, pitch: 45, bearing: -15 });
    }
  }, [tourIndex, tourDetections, setTourIndex, setTargetViewState]);
  const handleTourExit = useCallback(() => {
    setSearchStale(true);
    setPhase('explore');
  }, [setSearchStale]);
  const handleSwiperDismiss = useCallback(() => {
    setTourDetections([]);
    setTourIndex(0);
  }, [setTourDetections, setTourIndex]);
  // --- RENDER ---
  const isMapPhase = phase === 'processing' || phase === 'results' || phase === 'tour' || phase === 'explore';
  const filters = useStore((s) => s.filters);
  if (isMapPhase) {
    const filteredTour = tourDetections.filter((d) => d.confidence >= filters.confidenceRange[0]);
    const tourDetection = filteredTour[tourIndex];
    return (
      <div className="relative h-full w-full">
        <div className="absolute inset-0">
          <MapView />
        </div>
        {phase === 'processing' && (
          <div className="absolute inset-0 z-20 bg-slate-950">
            <ProcessingScreen
              progress={jobProgress.progress}
              stage={jobProgress.stage}
              source={jobProgress.source}
              downloadMb={jobProgress.downloadMb}
              tilesDone={jobProgress.tilesDone}
              tilesTotal={jobProgress.tilesTotal}
              detectionsSoFar={jobProgress.detectionsSoFar}
              error={jobProgress.status === 'FAILED' || jobProgress.status === 'CANCELLED' ? (jobProgress.error || 'Processing failed') : null}
              onRetry={() => {
                setActiveJobId(null);
                setPhase('splash');
              }}
            />
          </div>
        )}
        {phase === 'results' && (
          <ResultsSplash
            detections={tourDetections}
            onDismiss={() => {
              if (tourDetections.length > 0) {
                const best = tourDetections[0];
                setTargetViewState({ longitude: best.lon, latitude: best.lat, zoom: 15, pitch: 45, bearing: -15 });
                setPhase('tour');
              } else {
                setSearchStale(true);
                setPhase('explore');
              }
            }}
          />
        )}
        {(phase === 'tour' || phase === 'explore') && (
          <>
            <TopBar />
            <SettingsPanel />
            <ExploreSearchButton onScan={handleLocationAcquired} />
            {tourDetection && (
              <SwipeCard
                detection={tourDetection}
                userLocation={userLocation}
                currentIndex={tourIndex}
                totalCount={filteredTour.length}
                direction={swipeDirection}
                onNext={handleTourNext}
                onPrev={handleTourPrev}
                onExit={phase === 'tour' ? handleTourExit : handleSwiperDismiss}
              />
            )}
          </>
        )}
      </div>
    );
  }
  // Splash
  return (
    <div className="h-full w-full flex items-center justify-center bg-slate-950 relative">
      <Link
        to="/playground"
        className="absolute top-5 right-5 flex items-center gap-2 text-sm text-slate-500 hover:text-slate-300 transition-colors"
      >
        <Settings2 size={16} />
        Advanced
      </Link>
      <div className="text-center px-8 max-w-xl">
        <h1 className="text-6xl md:text-7xl font-black text-white mb-3 tracking-tight">Lost Landscapes</h1>
        <p className="text-slate-400 text-lg md:text-xl mb-10 leading-relaxed">
          Discover caves, mines, sinkholes & more hidden in LiDAR terrain data
        </p>
        {geoError && (
          <div className="flex items-center gap-3 bg-red-900/30 border border-red-700/50 text-red-300 text-base rounded px-5 py-4 mb-6">
            <AlertCircle size={18} className="flex-shrink-0" />
            {geoError}
          </div>
        )}
        <div className="flex flex-col gap-4">
          <button
            onClick={handleFindNearMe}
            disabled={geoLoading}
            className="flex items-center justify-center gap-3 bg-cherry-500 hover:bg-cherry-400 disabled:opacity-60 text-white font-semibold py-4 px-8 rounded text-lg transition-colors"
          >
            {geoLoading ? <Loader2 size={22} className="animate-spin" /> : <Locate size={22} />}
            {geoLoading ? 'Getting location...' : 'Find a Hole Near Me'}
          </button>
          <button
            onClick={() => setShowZipInput(!showZipInput)}
            className="flex items-center justify-center gap-3 bg-slate-800 hover:bg-slate-700 text-slate-200 font-semibold py-4 px-8 rounded text-lg transition-colors"
          >
            <MapPin size={22} />
            Enter Zip Code
          </button>
          {showZipInput && (
            <div className="flex items-stretch gap-4">
              <input
                type="text"
                inputMode="numeric"
                maxLength={5}
                placeholder="Zip code"
                value={zipCode}
                onChange={(e) => { setZipCode(e.target.value.replace(/\D/g, '')); setZipError(null); }}
                onKeyDown={(e) => e.key === 'Enter' && handleZipSubmit()}
                autoFocus
                className="flex-1 min-w-0 bg-slate-800 border-2 border-slate-600 text-white text-xl py-4 px-6 rounded focus:outline-none focus:border-cherry-500 transition-colors placeholder:text-slate-500"
              />
              <button
                onClick={handleZipSubmit}
                disabled={zipLoading || zipCode.length !== 5}
                className="bg-cherry-500 hover:bg-cherry-400 disabled:opacity-50 text-white font-semibold py-4 px-10 rounded text-lg transition-colors flex-shrink-0"
              >
                {zipLoading ? <Loader2 size={22} className="animate-spin" /> : 'Go'}
              </button>
            </div>
          )}
          {zipError && (
            <p className="text-red-400 text-base">{zipError}</p>
          )}
        </div>
        <p className="text-sm text-slate-600 mt-10">
          LiDAR coverage across the US &middot; 36 validation sites
        </p>
      </div>
    </div>
  );
}

/** Floating search button — triggers a full scan for the viewport center */
function ExploreSearchButton({ onScan }: { onScan: (lat: number, lon: number) => void }) {
  const searchStale = useStore((s) => s.searchStale);
  const bbox = useStore((s) => s.bbox);
  if (!searchStale || !bbox) return null;
  const lat = (bbox[1] + bbox[3]) / 2;
  const lon = (bbox[0] + bbox[2]) / 2;
  return (
    <button
      onClick={() => onScan(lat, lon)}
      className="fixed top-16 left-1/2 -translate-x-1/2 z-30 bg-cherry-500 hover:bg-cherry-400 text-white font-medium text-sm px-6 py-3 rounded shadow-lg flex items-center gap-2 transition-all"
    >
      <Search size={16} />
      Search this area
    </button>
  );
}
