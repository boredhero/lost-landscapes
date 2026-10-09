import type { Detection } from '../types';

export type Geometry = GeoJSON.Point | GeoJSON.LineString | GeoJSON.Polygon;
export type Review = 'unreviewed' | 'interesting' | 'dismissed' | 'uncertain';
export interface Measurement {
  method: string;
  revision: string;
  length_m: number;
  area_m2: number | null;
  samples: { distance_m: number; lon: number; lat: number; elevation_m: number | null; source: string | null }[];
  sources: { id: string; vertical_datum: string | null; elevation_units: string; resolution_m: number[] }[];
}
export interface Finding {
  id: string;
  title: string;
  geometry: Geometry;
  notes: string;
  evidence: string;
  review: Review;
  createdAt: string;
  updatedAt: string;
  context: Record<string, unknown>;
  detection?: Detection;
  measurement?: Measurement;
}
export interface Investigation {
  id: string;
  name: string;
  findings: Finding[];
}
export interface Notebook { version: 1; investigations: Investigation[] }
export const STORAGE_KEY = 'landscape-investigations-v1';
export function newInvestigation(name = 'My investigation'): Investigation {
  return { id: crypto.randomUUID(), name, findings: [] };
}
export function newFinding(geometry: Geometry, context: Record<string, unknown>): Finding {
  const now = new Date().toISOString();
  return { id: crypto.randomUUID(), title: 'Terrain observation', geometry, notes: '', evidence: '', review: 'unreviewed', createdAt: now, updatedAt: now, context };
}
export function fromDetection(detection: Detection): Finding {
  return { ...newFinding({ type: 'Point', coordinates: [detection.lon, detection.lat] }, { origin: 'automatic suggestion', job_id: detection.source_passes?.job_id ?? null, pass_config: detection.source_passes?.pass_config ?? null }), title: typeof detection.feature_type === 'string' ? detection.feature_type.replaceAll('_', ' ') : 'Terrain candidate', detection };
}
export function validateNotebook(value: unknown): Notebook {
  if (!value || typeof value !== 'object') throw Error('Invalid investigation file');
  const book = value as Notebook;
  if (book.version !== 1 || !Array.isArray(book.investigations) || book.investigations.length < 1 || book.investigations.length > 100) throw Error('Unsupported investigation version or too many investigations');
  const ids = new Set<string>();
  for (const group of book.investigations) {
    if (typeof group.id !== 'string' || ids.has(group.id) || typeof group.name !== 'string' || !Array.isArray(group.findings) || group.findings.length > 1000) throw Error('Invalid investigation');
    ids.add(group.id);
    const findingIds = new Set<string>();
    for (const item of group.findings) {
      if (!item || typeof item.id !== 'string' || findingIds.has(item.id)) throw Error('Invalid or duplicate finding');
      findingIds.add(item.id);
      for (const key of ['title', 'notes', 'evidence', 'createdAt', 'updatedAt'] as const) if (typeof item[key] !== 'string' || item[key].length > 100000) throw Error('Invalid finding text');
      if (!['unreviewed', 'interesting', 'dismissed', 'uncertain'].includes(item.review)) throw Error('Invalid review state');
      const g = item.geometry;
      if (!g || !['Point', 'LineString', 'Polygon'].includes(g.type)) throw Error('Unsupported geometry');
      const points = g.type === 'Point' ? [g.coordinates] : g.type === 'Polygon' ? g.coordinates[0] : g.coordinates;
      const minimum = g.type === 'Point' ? 1 : g.type === 'Polygon' ? 4 : 2;
      if (!Array.isArray(points) || points.length < minimum || points.length > 500 || (g.type === 'Polygon' && g.coordinates.length !== 1)) throw Error('Invalid vertices');
      for (const p of points) if (!Array.isArray(p) || p.length !== 2 || !p.every(Number.isFinite) || Math.abs(p[0]) > 180 || Math.abs(p[1]) > 85) throw Error('Invalid coordinates');
      if (g.type === 'Polygon' && JSON.stringify(points[0]) !== JSON.stringify(points.at(-1))) throw Error('Polygon must be closed');
      if (item.measurement) {
        const m = item.measurement;
        if (typeof m.method !== 'string' || typeof m.revision !== 'string' || !Number.isFinite(m.length_m) || (m.area_m2 !== null && !Number.isFinite(m.area_m2)) || !Array.isArray(m.samples) || m.samples.length > 201 || !Array.isArray(m.sources) || m.sources.length > 32) throw Error('Invalid measurement');
        for (const sample of m.samples) if (![sample.distance_m, sample.lon, sample.lat].every(Number.isFinite) || (sample.elevation_m !== null && !Number.isFinite(sample.elevation_m)) || (sample.source !== null && typeof sample.source !== 'string')) throw Error('Invalid profile sample');
        for (const source of m.sources) if (typeof source.id !== 'string' || typeof source.elevation_units !== 'string' || (source.vertical_datum !== null && typeof source.vertical_datum !== 'string') || !Array.isArray(source.resolution_m) || !source.resolution_m.every(Number.isFinite)) throw Error('Invalid profile source');
      }
      if (item.detection && (typeof item.detection.id !== 'string' || !Number.isFinite(item.detection.lon) || !Number.isFinite(item.detection.lat))) throw Error('Invalid detection provenance');
    }
  }
  return book;
}
export function loadNotebook(): { book: Notebook; error: string } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { book: validateNotebook(JSON.parse(raw)), error: '' };
    const group = newInvestigation();
    const legacy = JSON.parse(localStorage.getItem('landscape-saved') || '[]');
    if (Array.isArray(legacy)) group.findings = legacy.filter(d => typeof d.id === 'string' && Number.isFinite(d.lon) && Number.isFinite(d.lat)).map(fromDetection);
    return { book: { version: 1, investigations: [group] }, error: '' };
  } catch {
    return { book: { version: 1, investigations: [newInvestigation()] }, error: 'Saved investigations could not be read. Your stored copy has been preserved. Export any new work before leaving.' };
  }
}
export function exportNotebook(book: Notebook) {
  return {
    type: 'FeatureCollection',
    investigation_version: 1,
    investigations: book.investigations.map(({ id, name }) => ({ id, name })),
    features: book.investigations.flatMap(group => group.findings.map(({ geometry, ...properties }) => ({ type: 'Feature', id: properties.id, geometry, properties: { ...properties, investigationId: group.id } }))),
  };
}
export function importNotebook(text: string): Notebook {
  if (text.length > 5_000_000) throw Error('Import must be smaller than 5 MB');
  const data = JSON.parse(text);
  if (data.type !== 'FeatureCollection' || data.investigation_version !== 1 || !Array.isArray(data.investigations) || !Array.isArray(data.features) || data.features.length > 10000) throw Error('Choose a Lost Landscapes GeoJSON export');
  const groups: Investigation[] = data.investigations.map((g: { id: string; name: string }) => ({ ...g, findings: [] }));
  for (const feature of data.features) {
    const group = groups.find(g => g.id === feature.properties?.investigationId);
    if (!group) throw Error('Finding has no investigation');
    group.findings.push({ ...feature.properties, geometry: feature.geometry });
  }
  return validateNotebook({ version: 1, investigations: groups });
}
export function download(name: string, content: string, type = 'application/geo+json') {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement('a');
  link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
