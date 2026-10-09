export interface ContextSource {
  id: string;
  name: string;
  region?: string;
  country?: string;
  date_kind?: string;
  revision?: string;
  verified_at?: string;
  provider?: string;
  category: 'historical-map' | 'historical-aerial' | 'geology' | 'mining';
  date_label: string;
  attribution: string;
  source_url: string;
  legend_url: string | null;
  terms_url?: string;
  description: string;
  limitations: string;
  bounds: [number, number, number, number];
  min_zoom: number;
  max_zoom: number;
  tile_url: string;
}

export function contextSnapshot(source: ContextSource | undefined, opacity: number) {
  return source ? { id: source.id, name: source.name, date_label: source.date_label, opacity, source_url: source.source_url, attribution: source.attribution, region: source.region, country: source.country, date_kind: source.date_kind, revision: source.revision, verified_at: source.verified_at, provider: source.provider, terms_url: source.terms_url, bounds: source.bounds } : null;
}
