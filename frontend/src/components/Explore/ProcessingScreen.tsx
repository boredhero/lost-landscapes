import { useState, useEffect } from 'react';
import { Loader2, AlertCircle } from 'lucide-react';

const STAGES = [
  { key: 'discovering', label: 'Finding available LiDAR tiles...' },
  { key: 'downloading', label: 'Downloading terrain data...' },
  { key: 'analyzing', label: 'Detecting underground features...' },
  { key: 'finishing', label: 'Finalizing results...' },
];

const FUN_FACTS = [
  // LiDAR technology
  'LiDAR stands for Light Detection and Ranging — it uses laser pulses to map the Earth',
  'LiDAR can see through tree canopy to reveal hidden terrain features',
  'Airborne LiDAR fires up to 500,000 laser pulses per second at the ground',
  'A single LiDAR tile can contain over 28 million elevation points',
  'LiDAR resolution is typically 1-2 meters — roughly the size of a dining table',
  'USGS 3DEP is mapping the entire US in high-resolution LiDAR, free and open to the public',
  'The "multi-return" capability of LiDAR means a single pulse can bounce off a tree AND the ground below it',
  'LiDAR was originally used in the 1960s to measure clouds from aircraft',
  'The first archaeological LiDAR discovery was a massive Maya city hidden under Guatemalan jungle in 2018',
  'Point cloud density matters: more returns per square meter = better chance of detecting small features',
  'PDAL (Point Data Abstraction Library) processes raw LiDAR point clouds into usable DEMs',
  'Ground classification algorithms like SMRF separate ground returns from vegetation and buildings',
  'LiDAR-derived DEMs can reveal features invisible in satellite imagery, aerial photos, and even on foot',

  // Cave facts
  'The deepest cave in the US is Lechuguilla Cave in New Mexico — 1,604 feet deep',
  'The longest cave system in the world is Mammoth Cave in Kentucky at 426 miles',
  'Pennsylvania has over 1,000 documented caves — most in limestone karst',
  'Cave entrances often show up in LiDAR as sharp depressions with high local relief',
  'The Local Relief Model (LRM) is considered the gold standard for detecting cave entrances in LiDAR',
  'Caves form when slightly acidic groundwater dissolves carbonate rock over millions of years',
  'Speleothems (stalactites and stalagmites) grow about 0.1mm per year on average',
  'The largest cave chamber in the world is Sarawak Chamber in Malaysia — big enough to hold 40 Boeing 747s',
  'Cave-adapted species (troglobites) are often eyeless and unpigmented',
  'Wind Cave in South Dakota has over 160 miles of explored passages and is still being mapped',
  'Caves can act as natural time capsules, preserving climate data going back hundreds of thousands of years',
  'The study of caves is called speleology',
  'Some caves contain rare mineral formations called "cave popcorn" — knobby calcite growths',
  'Laurel Caverns in Pennsylvania is the largest cave in the state at over 4,500 feet of passages',

  // Sinkhole facts
  'Sinkholes form when underground limestone dissolves over thousands of years',
  'Some sinkholes open suddenly and can swallow entire buildings',
  'The largest sinkhole in the world is Xiaozhai Tiankeng in China — 2,172 feet deep',
  'Florida has more sinkholes than any other US state due to its porous limestone bedrock',
  'Sinkholes are detected in LiDAR using "fill-difference" analysis — subtracting the original terrain from a depression-filled version',
  'A single fill-difference pass can achieve 93% recall for known sinkholes',
  'Circular sinkholes have high "circularity" values (close to 1.0) while irregular collapses are closer to 0',
  'The Bayou Corne sinkhole in Louisiana swallowed 40 acres of land starting in 2012',
  'Salt dome collapse sinkholes form when underground salt deposits dissolve, creating massive voids',
  'Cover-collapse sinkholes are the most dangerous type — the surface gives way suddenly with no warning',
  'Cover-subsidence sinkholes form gradually as soil slowly filters into underground voids',
  'Sinkhole depth and area are key morphometric measurements for classification',
  'The "k-parameter" measures how bowl-shaped vs funnel-shaped a depression is',
  'Karst terrain covers about 20% of the Earth\'s land surface',
  'About 25% of the world\'s population relies on water from karst aquifer systems',

  // Mine facts
  'Abandoned mine portals can be detected by their distinctive terrain signatures in LiDAR',
  'Pennsylvania has over 250,000 acres of abandoned mine land — the most in the US',
  'Mine portal openings typically show up as rectangular depressions with steep walls in LiDAR data',
  'The anthracite coal region of eastern PA contains thousands of unmapped mine openings',
  'Acid mine drainage from abandoned mines is one of the biggest water pollution problems in the eastern US',
  'The Centralia mine fire in Pennsylvania has been burning underground since 1962',
  'West Virginia\'s coal mining history left over 4,000 miles of underground workings',
  'Mine subsidence occurs when the roof of an underground mine collapses years or decades after mining stopped',
  'The California Gold Rush (1848-1855) left thousands of abandoned mines across the Sierra Nevada',
  'The USGS Mineral Resources Data System tracks over 300,000 mine and mineral sites across the US',
  'Mine portals often have lower "circularity" values than natural sinkholes due to their rectangular shape',
  'Strip mining creates terraced landscapes visible in LiDAR even decades after reclamation',

  // Detection algorithms
  'DBSCAN clustering merges overlapping detections from multiple passes into single features',
  'The morphometric filter computes 8 measurements: depth, area, perimeter, circularity, volume, k-parameter, elongation, and wall slope',
  'Sky-view factor analysis measures how "enclosed" a point is by surrounding terrain',
  'Topographic Position Index (TPI) compares a point\'s elevation to the average of its neighbors at multiple scales',
  'Profile curvature measures the rate of change of slope — concave areas are potential depressions',
  'Point density analysis finds voids where laser returns are missing — a sign of cave or mine openings',
  'Multi-return ratio analysis detects areas where LiDAR pulses penetrate below the ground surface',
  'WhiteboxTools computes sky-view factor and local relief models using compiled Rust code',
  'Detection confidence scores range from 0 to 1, combining depth, morphology, and multi-pass agreement',
  'Elongation ratio distinguishes natural circular depressions from elongated mine trenches',
  'Wall slope angle helps differentiate steep-walled collapse features from gentle depressions',
  'Random forest classifiers can distinguish sinkholes from other terrain features using 10 morphometric features',
  'GDAL (Geospatial Data Abstraction Library) computes hillshade, slope, and roughness from DEMs',

  // Geology
  'Karst landscapes form in soluble rock like limestone, dolomite, and gypsum',
  'The Great Valley of Pennsylvania sits on a band of dissolved limestone 450 million years old',
  'Lava tubes form when the outer surface of a lava flow solidifies while molten rock continues flowing inside',
  'Lava Beds National Monument in California has over 800 lava tube caves',
  'The Greenbrier limestone in West Virginia is one of the most cave-rich formations in the eastern US',
  'Dolomite (calcium magnesium carbonate) dissolves more slowly than limestone, forming broader caves',
  'The Niagara Escarpment in New York exposes Lockport dolomite, a prime cave-forming rock',
  'Marble is metamorphosed limestone — it can still dissolve and form caves',
  'The Berkshire Hills of Massachusetts have marble caves formed in Precambrian rock over 1 billion years old',
  'Epikarst is the weathered zone at the top of karst bedrock — it stores and funnels water into cave systems',
  'Spring resurgences mark where underground water returns to the surface, often near cave entrances',
  'Phreatic caves form below the water table; vadose caves form above it',
  'Tectonic fractures in bedrock control where caves and sinkholes preferentially develop',

  // Geography & regions
  'The Allegheny Plateau in western PA is both a karst region and a historic coal mining area',
  'West Virginia\'s Greenbrier County has over 1,500 known caves',
  'The Hagerstown Valley in Maryland sits on heavily karstified Cambrian and Ordovician limestone',
  'North Carolina\'s Blue Ridge has karst features in marble and limestone pockets',
  'The Spruce Pine mining district in NC produced most of the world\'s high-purity quartz',
  'South Louisiana\'s salt dome collapses create some of the most dramatic sinkholes in the US',
  'The Modoc Plateau in northern California is one of the most lava-tube-rich areas in the world',
  'Eastern Ohio\'s Lockport Formation contains both karst features and abandoned coal mines',
  'Upstate New York\'s Niagara Escarpment is a UNESCO-recognized geological feature',
  'The Sierra Nevada foothills contain thousands of historic gold and silver mines from the 1850s',

  // Processing & tech
  'Hole Finder processes 11 derivative rasters in parallel from each DEM using native C++ and Rust tools',
  'A filled DEM is created by simulating water filling all depressions — the difference reveals sinkhole depth',
  'Hillshade rendering simulates sunlight hitting terrain to make features visible to the human eye',
  'PostGIS ST_AsMVT generates vector tiles on-the-fly for rendering 100,000+ detections without lag',
  'Each LiDAR tile processes in under 2 seconds for derivatives, plus about 60 seconds for detection passes',
  'Detection polygons are extracted by vectorizing labeled raster regions using rasterio',
  'The affine transform converts between pixel coordinates and real-world geographic coordinates',
  'UTM (Universal Transverse Mercator) projections minimize distance distortion for local-area analysis',
  'WGS84 (EPSG:4326) is the global coordinate system used by GPS — all detections are stored in it',
  'Raster resolution directly affects detection quality — 1m LiDAR finds features that 10m DEMs miss entirely',

  // Fun / surprising
  'Ancient Romans used sinkholes and cave springs as water sources for their aqueducts',
  'Bats use caves as hibernacula — a single cave can host thousands of bats in winter',
  'The deepest known cave on Earth is Veryovkina Cave in Georgia (the country) at 7,257 feet',
  'Some caves have their own weather systems, with temperature and humidity differences creating internal winds',
  'Cave pearls are smooth, round calcite formations that grow in shallow cave pools',
  'The "Swiss cheese model" describes how karst aquifers have irregular voids throughout the rock',
  'Cenotes in Mexico\'s Yucatan are sinkholes that expose the groundwater table — the Maya used them as sacred wells',
  'Mine canaries were used until 1986 to detect carbon monoxide and methane in coal mines',
  'The Lechuguilla Cave system was discovered in 1986 when cavers dug through rubble following a strong airflow',
  'Pseudokarst features look like karst but form in non-soluble rock through erosion, piping, or lava tube collapse',
  'A "swallet" or "swallow hole" is where a surface stream disappears underground into a cave system',
  'Some cave systems are so extensive they cross under state and international boundaries',
];

function getStageIndex(stage: string | null, progress: number): number {
  if (!stage) {
    if (progress < 10) return 0;
    if (progress < 40) return 1;
    if (progress < 90) return 2;
    return 3;
  }
  const idx = STAGES.findIndex((s) => s.key === stage);
  return idx >= 0 ? idx : 0;
}

interface ProcessingScreenProps {
  progress: number;
  stage: string | null;
  source: string | null;
  downloadMb: number | null;
  tilesDone: number | null;
  tilesTotal: number | null;
  detectionsSoFar: number | null;
  error: string | null;
  onRetry: () => void;
}

export default function ProcessingScreen({ progress, stage, source, downloadMb, tilesDone, tilesTotal, detectionsSoFar, error, onRetry }: ProcessingScreenProps) {
  const [factIndex, setFactIndex] = useState(() => Math.floor(Math.random() * FUN_FACTS.length));
  const [, setSeenIndices] = useState<Set<number>>(() => new Set());
  const [factVisible, setFactVisible] = useState(true);

  // Rotate fun facts every 8 seconds — random, no repeats until all seen
  useEffect(() => {
    const interval = setInterval(() => {
      setFactVisible(false);
      setTimeout(() => {
        setSeenIndices((seen) => {
          const updated = new Set(seen);
          updated.add(factIndex);
          // Reset if we've seen everything
          const pool = updated.size >= FUN_FACTS.length ? new Set<number>() : updated;
          let next: number;
          do {
            next = Math.floor(Math.random() * FUN_FACTS.length);
          } while (pool.has(next) && pool.size < FUN_FACTS.length);
          setFactIndex(next);
          return pool;
        });
        setFactVisible(true);
      }, 400);
    }, 8000);
    return () => clearInterval(interval);
  }, [factIndex]);

  if (error) {
    return (
      <div className="fixed inset-0 z-50 bg-slate-950 flex items-center justify-center">
        <div className="text-center px-8 max-w-md">
          <AlertCircle size={48} className="text-red-400 mx-auto mb-4" />
          <h2 className="text-xl font-bold text-white mb-2">Something went wrong</h2>
          <p className="text-slate-400 mb-6">{error}</p>
          <button
            onClick={onRetry}
            className="bg-cherry-500 hover:bg-cherry-400 text-white font-medium px-6 py-3 rounded transition-colors"
          >
            Try again
          </button>
        </div>
      </div>
    );
  }

  const currentStageIdx = getStageIndex(stage, progress);
  const currentLabel = STAGES[currentStageIdx]?.label || 'Scanning your area...';

  return (
    <div className="fixed inset-0 z-50 bg-slate-950 flex items-center justify-center">
      <div className="text-center px-8 max-w-lg w-full">
        {/* Spinning icon */}
        <Loader2 size={40} className="animate-spin text-hotpink-400 mx-auto mb-6" />

        {/* Stage label */}
        <h2 className="text-xl font-bold text-white mb-2">{currentLabel}</h2>
        {source && (
          <p className="text-sm text-slate-400 mb-6">Source: {source}</p>
        )}
        {!source && <div className="mb-6" />}

        {/* Progress bar */}
        <div className="w-full h-3 bg-slate-800 rounded overflow-hidden mb-3">
          <div
            className="h-full bg-hotpink-500 rounded transition-all duration-700 ease-out"
            style={{ width: `${Math.max(progress, 2)}%` }}
          />
        </div>
        <div className="flex items-center justify-between text-sm text-slate-400 font-mono mb-2">
          <span>{Math.round(progress)}%</span>
          {downloadMb != null && <span>{downloadMb.toLocaleString()} MB downloaded</span>}
        </div>
        <div className="flex items-center justify-between text-sm font-mono mb-8" style={{ minHeight: '1.25rem' }}>
          {tilesDone != null && tilesTotal != null && tilesTotal > 0 ? (
            <span className="text-slate-400">Tile {tilesDone} of {tilesTotal}</span>
          ) : (
            <span />
          )}
          {detectionsSoFar != null && detectionsSoFar > 0 ? (
            <span className="text-hotpink-400 font-semibold">{detectionsSoFar.toLocaleString()} detection{detectionsSoFar !== 1 ? 's' : ''} found</span>
          ) : (
            <span />
          )}
        </div>

        {/* Fun fact */}
        <div className="h-16 flex items-center justify-center">
          <p
            className={`text-sm text-slate-500 italic max-w-sm transition-opacity duration-300 ${
              factVisible ? 'opacity-100' : 'opacity-0'
            }`}
          >
            {FUN_FACTS[factIndex]}
          </p>
        </div>
      </div>
    </div>
  );
}
