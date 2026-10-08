export type TerrainLayer = "relief" | "slope" | "local-relief" | "hillshade";
export type ReliefRadius = 10 | 25 | 50;

export const terrainLayers: { id: TerrainLayer; label: string; description: string }[] = [
  { id: "relief", label: "Landscape", description: "Multidirectional shading with regional terrain for context." },
  { id: "slope", label: "Slope", description: "Steepness of the ground. Look for terrace edges, banks, and scarps." },
  { id: "local-relief", label: "Local relief", description: "Height above or below the surrounding mean. Look for subtle raised and sunken features." },
  { id: "hillshade", label: "Directional light", description: "Change the light direction to examine shapes that disappear into shadow." },
];

export const lightDirections = [
  { value: 0, label: "North" }, { value: 45, label: "Northeast" },
  { value: 90, label: "East" }, { value: 135, label: "Southeast" },
  { value: 180, label: "South" }, { value: 225, label: "Southwest" },
  { value: 270, label: "West" }, { value: 315, label: "Northwest" },
];
