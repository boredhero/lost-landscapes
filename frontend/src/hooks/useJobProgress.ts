import { useEffect, useRef, useState, useCallback } from 'react';
import { useStore } from '../store';
import { getJob } from '../api/client';

interface JobProgress {
  progress: number;
  stage: string | null;
  source: string | null;
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | null;
  totalDetections: number | null;
  downloadMb: number | null;
  tilesDone: number | null;
  tilesTotal: number | null;
  detectionsSoFar: number | null;
  error: string | null;
}

/**
 * WebSocket hook for real-time job progress.
 * Connects to /ws/jobs when jobId is provided, falls back to polling on disconnect.
 */
export function useJobProgress(jobId: string | null): JobProgress {
  const setProcessingProgress = useStore((s) => s.setProcessingProgress);
  const setProcessingStage = useStore((s) => s.setProcessingStage);
  const wsRef = useRef<WebSocket | null>(null);
  const retriesRef = useRef(0);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [state, setState] = useState<JobProgress>({
    progress: 0,
    stage: null,
    source: null,
    status: null,
    totalDetections: null,
    downloadMb: null,
    tilesDone: null,
    tilesTotal: null,
    detectionsSoFar: null,
    error: null,
  });

  const handleJobUpdate = useCallback((job: any) => {
    const newState: JobProgress = {
      progress: job.progress || 0,
      stage: job.stage || null,
      source: job.source || null,
      status: job.status?.toUpperCase() || null,
      totalDetections: job.total_detections ?? null,
      downloadMb: job.download_mb ?? null,
      tilesDone: job.tiles_done ?? null,
      tilesTotal: job.tiles_total ?? null,
      detectionsSoFar: job.detections_so_far ?? null,
      error: job.error_message || null,
    };
    setState(newState);
    setProcessingProgress(newState.progress);
    setProcessingStage(newState.stage);
  }, [setProcessingProgress, setProcessingStage]);

  // Polling fallback
  const startPolling = useCallback(() => {
    if (pollingRef.current || !jobId) return;
    pollingRef.current = setInterval(async () => {
      try {
        const job = await getJob(jobId);
        handleJobUpdate(job);
        if (job.status === 'COMPLETED' || job.status === 'FAILED') {
          if (pollingRef.current) clearInterval(pollingRef.current);
          pollingRef.current = null;
        }
      } catch {
        // ignore polling errors
      }
    }, 3000);
  }, [jobId, handleJobUpdate]);

  useEffect(() => {
    if (!jobId) {
      setState({ progress: 0, stage: null, source: null, status: null, totalDetections: null, downloadMb: null, tilesDone: null, tilesTotal: null, detectionsSoFar: null, error: null });
      return;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/jobs`;

    function connect() {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        retriesRef.current = 0;
        // Stop polling if it was running as fallback
        if (pollingRef.current) {
          clearInterval(pollingRef.current);
          pollingRef.current = null;
        }
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'job_updates' && Array.isArray(data.jobs)) {
            const match = data.jobs.find((j: any) => j.id === jobId);
            if (match) {
              handleJobUpdate(match);
            }
          }
        } catch {
          // ignore parse errors
        }
      };

      ws.onclose = () => {
        wsRef.current = null;
        if (retriesRef.current < 3) {
          retriesRef.current++;
          setTimeout(connect, 2000);
        } else {
          // Fall back to polling
          startPolling();
        }
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [jobId, handleJobUpdate, startPolling]);

  return state;
}
