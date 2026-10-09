import { useEffect, useState } from 'react';
import { useStore } from '../store';
import { getJob } from '../api/client';

interface JobProgress {
  progress: number;
  stage: string | null;
  source: string | null;
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED' | null;
  totalDetections: number | null;
  downloadMb: number | null;
  tilesDone: number | null;
  tilesTotal: number | null;
  detectionsSoFar: number | null;
  error: string | null;
}

/** Poll one job, including terminal states and reconnects, without global socket races. */
export function useJobProgress(jobId: string | null): JobProgress {
  const setProcessingProgress = useStore(s => s.setProcessingProgress);
  const setProcessingStage = useStore(s => s.setProcessingStage);
  const [state, setState] = useState<JobProgress>(empty);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function poll() {
      if (!jobId || disposed) return;
      let terminal = false;
      try {
        const job = await getJob(jobId);
        if (disposed) return;
        const summary = job.result_summary ?? {};
        const next: JobProgress = {
          progress: job.progress, status: job.status as JobProgress['status'],
          stage: typeof summary.stage === 'string' ? summary.stage : null,
          source: typeof summary.source === 'string' ? summary.source : null,
          totalDetections: typeof summary.total_detections === 'number' ? summary.total_detections : null,
          downloadMb: typeof summary.download_mb === 'number' ? summary.download_mb : null,
          tilesDone: typeof summary.tiles_done === 'number' ? summary.tiles_done : null,
          tilesTotal: typeof summary.tiles_total === 'number' ? summary.tiles_total : null,
          detectionsSoFar: typeof summary.detections_so_far === 'number' ? summary.detections_so_far : null,
          error: job.error_message ?? null,
        };
        setState(next); setProcessingProgress(next.progress); setProcessingStage(next.stage);
        terminal = ['COMPLETED', 'FAILED', 'CANCELLED'].includes(job.status);
      } catch { if (!disposed) setState(s => ({ ...s, error: 'Connection lost; reconnecting to scan…' })); }
      if (!disposed && !terminal) timer = setTimeout(() => void poll(), 2500);
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Reset when subscribing to another job.
    setState(empty);
    void poll();
    return () => { disposed = true; clearTimeout(timer); };
  }, [jobId, setProcessingProgress, setProcessingStage]);
  return state;
}
const empty: JobProgress = { progress: 0, stage: null, source: null, status: null, totalDetections: null, downloadMb: null, tilesDone: null, tilesTotal: null, detectionsSoFar: null, error: null };
