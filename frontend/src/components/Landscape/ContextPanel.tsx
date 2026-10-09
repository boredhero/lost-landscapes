import type { ContextSource } from './contextLayers';

interface Props {
  sources: ContextSource[];
  selected?: ContextSource;
  loading: boolean;
  catalogError: boolean;
  tileError: boolean;
  opacity: number;
  view: { longitude: number; latitude: number; zoom: number };
  onSelect: (id: string) => void;
  onOpacity: (value: number) => void;
  onRetry: () => void;
  onCatalogRetry: () => void;
  onClose: () => void;
  onShowCoverage: (source: ContextSource) => void;
}

export default function ContextPanel(props: Props) {
  const { selected: source, view } = props;
  const outside = source && (view.longitude < source.bounds[0] || view.longitude > source.bounds[2] || view.latitude < source.bounds[1] || view.latitude > source.bounds[3]);
  return <aside className="landscape-panel notebook-panel context-panel" aria-label="Historical evidence settings">
    <div className="panel-eyebrow"><span>LANDSCAPE CONTEXT</span><button aria-label="Close historical evidence" onClick={props.onClose}>×</button></div>
    <h2>Look back in time.</h2>
    <p className="muted">Compare maps, photographs and recorded geology or mining with the terrain. Dates describe each source, not the age of a feature you find.</p>
    <p className="muted">Availability varies by region. This catalog is a starting collection, not complete national coverage.</p>
    {props.loading && <p role="status">Loading evidence sources…</p>}
    {props.catalogError && <p role="alert">Evidence sources could not be loaded. <button onClick={props.onCatalogRetry}>Retry sources</button></p>}
    <label>Evidence overlay<select aria-label="Evidence overlay" value={source?.id ?? ''} onChange={event => props.onSelect(event.target.value)}>
      <option value="">None</option>
      {props.sources.map(item => <option key={item.id} value={item.id}>{item.name} — {item.date_label}</option>)}
    </select></label>
    {!props.loading && !props.catalogError && !props.sources.length && <p>No evidence sources are configured.</p>}
    {source && <>
      <label>Overlay opacity: {Math.round(props.opacity * 100)}%<input aria-label="Overlay opacity" type="range" min="0" max="1" step="0.05" value={props.opacity} onChange={event => props.onOpacity(Number(event.target.value))} /></label>
      <p><strong>{source.date_label}</strong></p>
      <p>{source.region}{source.country ? ` (${source.country})` : ""}</p>
      <button onClick={() => props.onShowCoverage(source)}>Show source coverage</button>
      <p>{source.description}</p>
      <p className="muted">{source.limitations}</p>
      {source.verified_at && <p className="muted">Metadata checked: {source.verified_at}</p>}
      <p className="muted">Credit: {source.attribution}</p>
      <p className="context-links"><a href={source.source_url} target="_blank" rel="noreferrer">Source and metadata ↗</a>{source.legend_url && <a href={source.legend_url} target="_blank" rel="noreferrer">Legend ↗</a>}{source.terms_url && <a href={source.terms_url} target="_blank" rel="noreferrer">Terms ↗</a>}</p>
      {outside && <p role="status">Map center is outside this source’s coverage. The overlay only appears within its published bounds.</p>}
      {view.zoom < source.min_zoom && <p role="status">Zoom in to level {source.min_zoom} to see this source.</p>}
      {view.zoom > source.max_zoom && <p className="muted">Enlarged beyond the source’s native zoom; no additional detail is available.</p>}
      {props.tileError && <p role="alert">Some evidence tiles could not load. <button onClick={props.onRetry}>Retry overlay</button></p>}
      <button onClick={() => props.onSelect('')}>Remove overlay</button>
      <p className="muted">In comparison mode, evidence is shown on the primary map only. New findings retain the selected source, date and opacity in their exported context.</p>
    </>}
  </aside>;
}
