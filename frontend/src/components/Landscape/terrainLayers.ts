export type TerrainLayer = "relief" | "slope" | "local-relief" | "hillshade" | "svf" | "openness-positive" | "openness-negative" | "vat";
export type ReliefRadius = 10 | 25 | 50;

export const isHorizonLayer = (layer: TerrainLayer) => ["svf", "openness-positive", "openness-negative", "vat"].includes(layer);
export const terrainMinZoom = (layer: TerrainLayer) => isHorizonLayer(layer) ? 16 : 14;
export const usesTerrainRadius = (layer: TerrainLayer) => layer === "local-relief" || isHorizonLayer(layer);
export const terrainLegend: Partial<Record<TerrainLayer, [string, string]>> = {
  slope: ["0°", "60° or steeper"],
  "local-relief": ["−2 m or lower", "+2 m or higher"],
  hillshade: ["Shadow", "Light"],
  svf: ["0 · closed sky", "1 · open sky"],
  "openness-positive": ["60° or lower", "120° or higher"],
  "openness-negative": ["60° or lower", "120° or higher"],
  vat: ["Darker composite", "Lighter composite"],
};

export const terrainLayers: { id: TerrainLayer; label: string; description: string }[] = [
  { id: "relief", label: "Landscape", description: "Multidirectional shading with regional terrain for context." },
  { id: "slope", label: "Slope", description: "Steepness of the ground. Look for terrace edges, banks, and scarps." },
  { id: "local-relief", label: "Local relief", description: "Height above or below the surrounding mean. Look for subtle raised and sunken features." },
  { id: "hillshade", label: "Directional light", description: "Change the light direction to examine shapes that disappear into shadow." },
  { id: "svf", label: "Sky-view factor", description: "Visible sky estimated from terrain horizons in 16 directions. Depressions and enclosed terrain become darker." },
  { id: "openness-positive", label: "Positive openness", description: "Average zenith angle to the surrounding horizon. Highlights raised features; a flat surface is 90°." },
  { id: "openness-negative", label: "Negative openness", description: "Openness calculated beneath the surface, displayed with inverted shading to emphasize depressions. A flat surface is 90°." },
  { id: "vat", label: "Archaeological topography (VAT)", description: "A fixed blend of hillshade, slope, positive openness and sky-view factor. Combines terrain cues for inspection; brightness is not a physical measurement or detection score." },
];

export const lightDirections = [
  { value: 0, label: "North" }, { value: 45, label: "Northeast" },
  { value: 90, label: "East" }, { value: 135, label: "Southeast" },
  { value: 180, label: "South" }, { value: 225, label: "Southwest" },
  { value: 270, label: "West" }, { value: 315, label: "Northwest" },
];
