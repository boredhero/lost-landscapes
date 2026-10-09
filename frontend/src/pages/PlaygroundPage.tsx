import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import MapView from '../components/Map/MapView';
import Sidebar from '../components/Sidebar/Sidebar';
import { useStore } from '../store';
import { useJobProgress } from '../hooks/useJobProgress';
import { startConsumerScan } from '../api/client';
import { ArrowLeft, Search, Loader2, X, CheckCircle, AlertCircle } from 'lucide-react';

export default function PlaygroundPage() {
  const setTerrainReady = useStore((s) => s.setTerrainReady);
  const bbox = useStore((s) => s.bbox);
  const searchStale = useStore((s) => s.searchStale);
  const setSearchStale = useStore((s) => s.setSearchStale);
  const bumpTileVersion = useStore((s) => s.bumpTileVersion);
  const activeJobId = useStore((s) => s.activeJobId);
  const setActiveJobId = useStore((s) => s.setActiveJobId);
  const [scanStatus, setScanStatus] = useState<'idle' | 'scanning' | 'done' | 'failed'>('idle');
  const [scanError, setScanError] = useState<string | null>(null);
  const jobProgress = useJobProgress(scanStatus === 'scanning' ? activeJobId : null);
  const completionHandled = useRef(false);
  useEffect(() => { setTerrainReady(true); }, [setTerrainReady]);
  // Handle scan completion
  useEffect(() => {
    if (scanStatus !== 'scanning') { completionHandled.current = false; return; }
    if (completionHandled.current) return;
    if (jobProgress.status === 'COMPLETED') {
      completionHandled.current = true;
      // eslint-disable-next-line react-hooks/set-state-in-effect -- Reflect external job completion.
      setScanStatus('done');
      setActiveJobId(null);
      setSearchStale(true);
      bumpTileVersion();
      // Auto-dismiss after 4s
      setTimeout(() => setScanStatus('idle'), 4000);
    } else if (jobProgress.status === 'FAILED' || jobProgress.status === 'CANCELLED') {
      completionHandled.current = true;
      setScanError(jobProgress.error || 'Processing failed');
      setScanStatus('failed');
      setActiveJobId(null);
    }
  }, [scanStatus, jobProgress.status, jobProgress.error, setActiveJobId, setSearchStale, bumpTileVersion]);
  const handleScan = useCallback(async () => {
    if (!bbox) return;
    const lat = (bbox[1] + bbox[3]) / 2;
    const lon = (bbox[0] + bbox[2]) / 2;
    // Derive radius from viewport — what you see is what gets scanned
    const latSpanKm = (bbox[3] - bbox[1]) * 111.32;
    const lonSpanKm = (bbox[2] - bbox[0]) * 111.32 * Math.cos(lat * Math.PI / 180);
    const radiusKm = Math.min(latSpanKm, lonSpanKm) / 2;
    // If viewport is too wide, ask user to zoom in
    if (radiusKm > 2) {
      setScanError('Zoom in a bit — the visible area is too large to scan. Choose an area under 4 km across.');
      setScanStatus('failed');
      setTimeout(() => setScanStatus('idle'), 5000);
      return;
    }
    setScanStatus('scanning');
    setScanError(null);
    try {
      const { job_id } = await startConsumerScan(lat, lon, Math.max(0.5, radiusKm));
      setActiveJobId(job_id);
    } catch (err: any) {
      setScanError(err?.message || 'Failed to start scan');
      setScanStatus('failed');
    }
  }, [bbox, setActiveJobId]);
  const handleDismissBanner = useCallback(() => {
    setScanStatus('idle');
    setScanError(null);
  }, []);
  return (
    <div className="relative h-full w-full">
      <div className="absolute inset-0">
        <MapView />
      </div>
      <Sidebar />
      {/* Search this area button */}
      {searchStale && bbox && scanStatus === 'idle' && (
        <button
          onClick={handleScan}
          className="fixed top-16 left-1/2 -translate-x-1/2 z-30 bg-cherry-500 hover:bg-cherry-400 text-white font-medium text-sm px-6 py-3 rounded shadow-lg flex items-center gap-2 transition-all"
        >
          <Search size={16} />
          Search this area
        </button>
      )}
      {/* Processing banner */}
      {scanStatus === 'scanning' && (
        <div className="fixed top-16 left-1/2 -translate-x-1/2 z-30 bg-slate-800/95 backdrop-blur text-white text-sm px-6 py-3 rounded shadow-lg flex items-center gap-3">
          <Loader2 size={16} className="animate-spin text-cherry-400" />
          <span>
            {jobProgress.stage === 'downloading' ? 'Downloading LiDAR data' : jobProgress.stage === 'analyzing' ? 'Analyzing terrain' : jobProgress.stage === 'finishing' ? 'Finishing up' : 'Processing'}
            {jobProgress.downloadMb != null && jobProgress.stage === 'downloading' && <span className="text-slate-400 ml-1">({jobProgress.downloadMb} MB)</span>}
            {jobProgress.stage !== 'downloading' && jobProgress.progress > 0 && <span className="text-slate-400 ml-1">({Math.round(jobProgress.progress)}%)</span>}
          </span>
        </div>
      )}
      {/* Done banner */}
      {scanStatus === 'done' && (
        <div className="fixed top-16 left-1/2 -translate-x-1/2 z-30 bg-emerald-900/90 backdrop-blur text-emerald-200 text-sm px-6 py-3 rounded shadow-lg flex items-center gap-3">
          <CheckCircle size={16} />
          <span>Scan complete{jobProgress.totalDetections != null ? ` — ${jobProgress.totalDetections} detections` : ''}</span>
          <button onClick={handleDismissBanner} className="text-emerald-400 hover:text-white ml-1"><X size={14} /></button>
        </div>
      )}
      {/* Error banner */}
      {scanStatus === 'failed' && (
        <div className="fixed top-16 left-1/2 -translate-x-1/2 z-30 bg-red-900/90 backdrop-blur text-red-200 text-sm px-6 py-3 rounded shadow-lg flex items-center gap-3">
          <AlertCircle size={16} />
          <span>{scanError || 'Scan failed'}</span>
          <button onClick={handleDismissBanner} className="text-red-400 hover:text-white ml-1"><X size={14} /></button>
        </div>
      )}
      <Link
        to="/"
        className="fixed top-4 right-4 z-50 bg-slate-800/90 backdrop-blur px-5 py-3 rounded shadow-lg text-sm text-slate-300 hover:text-white flex items-center gap-2 transition-colors"
      >
        <ArrowLeft size={16} />
        Back to Explore
      </Link>
    </div>
  );
}
