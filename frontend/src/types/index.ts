export type FeatureType = 'sinkhole' | 'cave_entrance' | 'mine_portal' | 'depression' | 'collapse_pit' | 'spring' | 'lava_tube' | 'salt_dome_collapse' | 'mound' | 'platform' | 'linear_bank' | 'linear_ditch' | 'enclosure' | 'repeated_pattern' | 'ridge' | 'hollow' | 'scarp' | 'unknown';

export interface Detection {
  outline?: GeoJSON.Polygon;
  id: string;
  lat: number;
  lon: number;
  feature_type: FeatureType;
  confidence: number;
  depth_m?: number;
  area_m2?: number;
  circularity?: number;
  wall_slope_deg?: number;
  source_passes?: Record<string, unknown>;
  morphometrics?: Record<string, unknown>;
  validated?: boolean;
  validation_notes?: string;
}

export interface GroundTruthSite {
  id: string;
  name: string;
  lat: number;
  lon: number;
  feature_type: FeatureType;
  source: string;
}

export interface Job {
  id: string;
  job_type: string;
  status: string;
  progress: number;
  result_summary?: Record<string, unknown>;
  error_message?: string;
  created_at?: string;
}

export interface DetectionFilters {
  featureTypes: FeatureType[];
  confidenceRange: [number, number];
  validated?: boolean | null;
}

export type Basemap = 'satellite' | 'topo' | 'dark' | 'relief';

export const FEATURE_COLORS: Record<FeatureType, string> = {
  cave_entrance: '#ef4444',
  mine_portal: '#f97316',
  sinkhole: '#3b82f6',
  depression: '#8b5cf6',
  collapse_pit: '#eab308',
  spring: '#06b6d4',
  lava_tube: '#a855f7',
  salt_dome_collapse: '#dc2626',
  mound: '#d3aa62',
  platform: '#e6c783',
  linear_bank: '#bead68',
  linear_ditch: '#66aabc',
  enclosure: '#d493b8',
  repeated_pattern: '#b590d9',
  ridge: '#8ca664',
  hollow: '#698ca6',
  scarp: '#ce8565',
  unknown: '#6b7280',
};

export const FEATURE_LABELS: Record<FeatureType, string> = {
  cave_entrance: 'Cave Entrance',
  mine_portal: 'Mine Portal',
  sinkhole: 'Sinkhole',
  depression: 'Depression',
  collapse_pit: 'Collapse Pit',
  spring: 'Spring',
  lava_tube: 'Lava Tube',
  salt_dome_collapse: 'Salt Dome Collapse',
  mound: 'Mound-like feature',
  platform: 'Platform-like feature',
  linear_bank: 'Raised linear feature / possible bank or road',
  linear_ditch: 'Ditch-like linear feature',
  enclosure: 'Enclosure-like boundary',
  repeated_pattern: 'Repeated terrain pattern',
  ridge: 'Ridge-like feature',
  hollow: 'Hollow-like feature',
  scarp: 'Scarp-like steep face',
  unknown: 'Unknown',
};
