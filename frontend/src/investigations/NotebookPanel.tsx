import { useEffect, useState } from 'react';
import type { Finding, Geometry, Investigation, Measurement, Notebook, Review } from './model';
import { download, exportNotebook, importNotebook, newInvestigation } from './model';

interface Props {
  book: Notebook; group: Investigation; selected: Finding | undefined;
  drawing: Geometry['type'] | null; vertices: number; error: string;
  onBook: (book: Notebook) => void; onGroup: (id: string) => void;
  onSelect: (id: string) => void; onUpdate: (finding: Finding) => void;
  onDraw: (type: Geometry['type'] | null) => void; onFinish: () => void;
  onUndo: () => void; onClose: () => void; onLocate: (finding: Finding) => void;
}
function Profile({ data }: { data: Measurement }) {
  const heights = data.samples.flatMap(s => s.elevation_m === null ? [] : [s.elevation_m]);
  if (!heights.length) return <p>No supported local elevation data along this geometry.</p>;
  const low = Math.min(...heights), high = Math.max(...heights);
  let path = '', connected = false, previousSource: string | null = null;
  for (const s of data.samples) {
    if (s.elevation_m === null) { connected = false; continue; }
    const x = 10 + 280 * s.distance_m / (data.length_m || 1), y = 100 - 80 * (s.elevation_m - low) / (high - low || 1);
    path += `${connected && s.source === previousSource ? 'L' : 'M'}${x},${y} `;
    connected = true; previousSource = s.source;
  }
  return <div className="elevation-profile">
    {data.samples.length > 1 ? <svg viewBox="0 0 300 120" role="img" aria-label={`Elevation profile from ${low.toFixed(1)} to ${high.toFixed(1)} metres`}><path d={path} fill="none" stroke="currentColor" strokeWidth="2" /></svg> : null}
    <p>{low.toFixed(1)}–{high.toFixed(1)} m elevation · {data.samples.filter(s => s.elevation_m === null).length} missing samples</p>
    <p className="muted">Native cell elevations, without 3D exaggeration. Gaps and source boundaries break the profile. Datums are not harmonized.</p>
    {data.sources.map(s => <p className="muted" key={s.id}>{s.id} · {s.resolution_m.join(' × ')} m · {s.vertical_datum ?? 'Unknown vertical datum'} · {s.elevation_units}</p>)}
    <button onClick={() => download('elevation-profile.csv', 'distance_m,longitude,latitude,elevation_m,source\n' + data.samples.map(s => [s.distance_m, s.lon, s.lat, s.elevation_m ?? '', JSON.stringify(s.source ?? '')].join(',')).join('\n'), 'text/csv')}>Export profile CSV</button>
  </div>;
}
export default function NotebookPanel(props: Props) {
  const { book, group, selected, drawing, vertices, error, onBook, onGroup, onSelect, onUpdate, onDraw, onFinish, onUndo, onClose, onLocate } = props;
  const [requestError, setRequestError] = useState('');
  const [measuring, setMeasuring] = useState(false);
  const [importError, setImportError] = useState('');
  const selectedId = selected?.id;
  useEffect(() => { setRequestError(''); }, [selectedId]);
  async function measure() {
    if (!selected) return;
    setMeasuring(true); setRequestError('');
    try {
      const response = await fetch('/api/landscape/measure', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(selected.geometry) });
      const data = await response.json();
      if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'Unsupported geometry. Use a valid shape under 10 km.');
      onUpdate({ ...selected, measurement: data });
    } catch (e) { setRequestError(e instanceof Error ? e.message : 'Measurement failed'); }
    finally { setMeasuring(false); }
  }
  return <aside className="landscape-panel notebook-panel" aria-label="Investigations">
    <div className="panel-eyebrow"><span>FIELD NOTEBOOK</span><button onClick={onClose} aria-label="Close investigations">×</button></div>
    <h2>Investigations</h2>
    <p className="muted">Saved in this browser on this device. Export a backup to keep or share your findings.</p>
    {error && <p role="alert">{error}</p>}
    <label>Investigation<select aria-label="Investigation" value={group.id} onChange={e => onGroup(e.target.value)}>{book.investigations.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}</select></label>
    <label>Name<input value={group.name} maxLength={120} onChange={e => onBook({ ...book, investigations: book.investigations.map(g => g.id === group.id ? { ...g, name: e.target.value } : g) })} /></label>
    <div className="notebook-actions"><button onClick={() => { const g = newInvestigation('New investigation'); onBook({ ...book, investigations: [...book.investigations, g] }); onGroup(g.id); }}>New investigation</button><button onClick={() => download('lost-landscapes.geojson', JSON.stringify(exportNotebook(book), null, 2))}>Export GeoJSON</button></div>
    <label>Import GeoJSON<input type="file" accept=".geojson,.json,application/geo+json" onChange={async e => {
      const file = e.target.files?.[0]; if (!file) return;
      try {
        if (file.size > 5_000_000) throw Error('Import must be smaller than 5 MB');
        const imported = importNotebook(await file.text());
        // Import as copies, never overwrite existing investigations.
        const groups = imported.investigations.map(g => ({ ...g, id: crypto.randomUUID(), findings: g.findings.map(f => ({ ...f, id: crypto.randomUUID() })) }));
        if (book.investigations.length + groups.length > 100) throw Error('At most 100 investigations');
        onBook({ ...book, investigations: [...book.investigations, ...groups] });
        if (groups[0]) onGroup(groups[0].id);
        setImportError('');
      } catch (e) { setImportError(e instanceof Error ? e.message : 'Import failed'); }
    }} /></label>
    {importError && <p role="alert">{importError}</p>}
    <div className="notebook-actions">{(['Point', 'LineString', 'Polygon'] as const).map((type, i) => <button key={type} aria-pressed={drawing === type} onClick={() => onDraw(type)}>{['Mark point', 'Draw line', 'Draw area'][i]}</button>)}</div>
    {drawing && <div role="status"><p>Click the map to place {drawing === 'Point' ? 'a point' : 'vertices'}. {vertices} placed. Close this panel for more room; drawing controls remain available.</p><div className="notebook-actions"><button onClick={onUndo} disabled={!vertices}>Undo vertex</button><button onClick={onFinish} disabled={vertices < (drawing === 'Polygon' ? 3 : drawing === 'LineString' ? 2 : 1)}>Finish drawing</button><button onClick={() => onDraw(null)}>Cancel drawing</button></div></div>}
    <div className="panel-divider" />
    <p>{group.findings.length} findings</p>
    <div className="finding-list">{group.findings.map(f => <button key={f.id} aria-pressed={selectedId === f.id} onClick={() => onSelect(f.id)}>{f.title || 'Untitled'} · {f.review}</button>)}</div>
    {selected && <div className="finding-editor" key={selected.id}>
      <label>Finding title<input aria-label="Finding title" value={selected.title} maxLength={200} onChange={e => onUpdate({ ...selected, title: e.target.value })} /></label>
      <label>Review<select aria-label="Review" value={selected.review} onChange={e => onUpdate({ ...selected, review: e.target.value as Review })}>{(['unreviewed', 'interesting', 'uncertain', 'dismissed'] as const).map(v => <option key={v}>{v}</option>)}</select></label>
      <label>Notes<textarea aria-label="Notes" value={selected.notes} maxLength={20000} onChange={e => onUpdate({ ...selected, notes: e.target.value })} /></label>
      <label>Evidence references<textarea aria-label="Evidence references" placeholder="Map references, URLs, field observations…" value={selected.evidence} maxLength={20000} onChange={e => onUpdate({ ...selected, evidence: e.target.value })} /></label>
      {selected.detection && <p className="muted">Automatic suggestion · score {selected.detection.confidence} · {selected.detection.feature_type}. Review status is your assessment, not a verified site classification.</p>}
      <div className="notebook-actions"><button onClick={() => onLocate(selected)}>Show on map</button><button disabled={measuring} onClick={() => void measure()}>{measuring ? 'Measuring…' : 'Measure / elevation profile'}</button><button onClick={() => { if (window.confirm('Delete this finding?')) onBook({ ...book, investigations: book.investigations.map(g => g.id === group.id ? { ...g, findings: g.findings.filter(f => f.id !== selected.id) } : g) }); }}>Delete finding</button></div>
      {requestError && <p role="alert">{requestError}</p>}
      {selected.measurement && <><p>{selected.geometry.type !== 'Point' && `${selected.measurement.length_m.toFixed(1)} m ${selected.geometry.type === 'Polygon' ? 'perimeter' : 'length'}`}{selected.measurement.area_m2 !== null && ` · ${selected.measurement.area_m2.toFixed(1)} m²`}</p>{selected.geometry.type !== 'Polygon' && <Profile data={selected.measurement} />}</>}
    </div>}
  </aside>;
}
