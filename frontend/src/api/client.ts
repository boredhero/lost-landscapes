import type { Job } from '../types';
const BASE = '/api';
function normalizeJob(job: Job): Job { return { ...job, status: job.status.toUpperCase() }; }

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function getDetections(params: {
  west: number; south: number; east: number; north: number;
  min_confidence?: number; feature_type?: string[];
  limit?: number;
}) {
  const sp = new URLSearchParams();
  sp.set('west', String(params.west));
  sp.set('south', String(params.south));
  sp.set('east', String(params.east));
  sp.set('north', String(params.north));
  if (params.min_confidence) sp.set('min_confidence', String(params.min_confidence));
  params.feature_type?.forEach(ft => sp.append('feature_type', ft));
  if (params.limit) sp.set('limit', String(params.limit));
  return fetchJson<any>(`/detections?${sp}`);
}

export async function getDetectionDetail(id: string) {
  return fetchJson<any>(`/detections/${id}`);
}

export async function validateDetection(id: string, verdict: string, notes?: string) {
  return fetchJson<any>(`/detections/${id}/validate`, {
    method: 'POST',
    body: JSON.stringify({ verdict, notes }),
  });
}

export async function getJobs() {
  const result = await fetchJson<{ jobs: Job[] }>('/jobs');
  return { ...result, jobs: result.jobs.map(normalizeJob) };
}

export async function createJob(body: { job_type: string; bbox?: any; pass_config?: string }) {
  return normalizeJob(await fetchJson<Job>('/jobs', { method: 'POST', body: JSON.stringify(body) }));
}

export async function cancelJob(id: string) {
  return fetchJson<any>(`/jobs/${id}/cancel`, { method: 'POST' });
}

export async function getGroundTruth(params?: {
  west?: number; south?: number; east?: number; north?: number;
}) {
  const sp = new URLSearchParams();
  if (params?.west != null) {
    sp.set('west', String(params.west));
    sp.set('south', String(params.south));
    sp.set('east', String(params.east));
    sp.set('north', String(params.north));
  }
  return fetchJson<any>(`/ground-truth?${sp}`);
}

export async function addGroundTruth(body: { name: string; feature_type: string; lat: number; lon: number; notes?: string }) {
  return fetchJson<any>('/ground-truth', { method: 'POST', body: JSON.stringify(body) });
}

export async function getHealth() {
  return fetchJson<any>('/health');
}

export async function geocodeZip(zip: string) {
  return fetchJson<{ lat: number; lon: number; city: string; state: string }>(`/geocode?zip=${zip}`);
}

export async function getDetectionCount(lat: number, lon: number, radiusKm: number) {
  return fetchJson<{ count: number }>(`/detections/count?lat=${lat}&lon=${lon}&radius_km=${radiusKm}`);
}

export async function startConsumerScan(lat: number, lon: number, radiusKm: number) {
  return fetchJson<{ job_id: string; estimated_minutes: number }>('/explore/scan', {
    method: 'POST',
    body: JSON.stringify({ lat, lon, radius_km: radiusKm }),
  });
}

export async function getJob(id: string) {
  return normalizeJob(await fetchJson<Job>(`/jobs/${id}`));
}

export async function getTileCoverage(west: number, south: number, east: number, north: number, z: number) {
  return fetchJson<GeoJSON.FeatureCollection>(`/raster/terrain/coverage?west=${west}&south=${south}&east=${east}&north=${north}&z=${z}`);
}

export async function warmTerrainCache(west: number, south: number, east: number, north: number) {
  return fetchJson<{ cached: number; rendered: number; proxied: number }>(
    `/raster/terrain/warm?west=${west}&south=${south}&east=${east}&north=${north}`,
    { method: 'POST' },
  );
}
