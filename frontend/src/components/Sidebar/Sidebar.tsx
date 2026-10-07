import { useQuery } from '@tanstack/react-query';
import { useStore } from '../../store';
import { useDetections as useDetectionsHook } from '../../hooks/useDetections';
import FilterPanel from './FilterPanel';
import DetailPanel from './DetailPanel';
import JobPanel from './JobPanel';
import { FEATURE_COLORS } from '../../types';
import { Filter, List, Briefcase, Info, X, Menu } from 'lucide-react';

const TABS = [
  { id: 'filters' as const, icon: Filter, label: 'Filters' },
  { id: 'detections' as const, icon: List, label: 'Detections' },
  { id: 'jobs' as const, icon: Briefcase, label: 'Jobs' },
  { id: 'detail' as const, icon: Info, label: 'Detail' },
];

export default function Sidebar() {
  const sidebarOpen = useStore((s) => s.sidebarOpen);
  const setSidebarOpen = useStore((s) => s.setSidebarOpen);
  const activePanel = useStore((s) => s.activePanel);
  const setActivePanel = useStore((s) => s.setActivePanel);
  const selectedDetection = useStore((s) => s.selectedDetection);

  return (
    <>
      {/* Mobile toggle button */}
      {!sidebarOpen && (
        <button onClick={() => setSidebarOpen(true)}
          className="fixed top-4 left-4 z-50 bg-slate-800/90 backdrop-blur p-3 rounded shadow-lg md:hidden">
          <Menu size={22} className="text-white" />
        </button>
      )}

      {/* Sidebar panel */}
      <div className={`
        fixed z-40 bg-slate-900/95 backdrop-blur-lg border-r border-slate-700
        transition-transform duration-300 ease-in-out
        flex flex-col
        /* Mobile: bottom sheet */
        inset-x-0 bottom-0 h-[60vh] rounded-t border-t border-r-0
        md:inset-y-0 md:left-0 md:w-[var(--sidebar-width)] md:h-full md:rounded-none md:border-r md:border-t-0
        ${sidebarOpen ? 'translate-y-0 md:translate-x-0' : 'translate-y-full md:-translate-x-full'}
      `}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-slate-700 flex-shrink-0">
          <div className="flex items-baseline gap-3">
            <h2 className="text-lg font-bold text-white tracking-wide">LOST LANDSCAPES</h2>
            <VersionTag />
          </div>
          <button onClick={() => setSidebarOpen(false)} className="text-slate-400 hover:text-white md:hidden">
            <X size={22} />
          </button>
        </div>

        {/* Tab bar */}
        <div className="flex border-b border-slate-700 flex-shrink-0">
          {TABS.map(tab => {
            const isActive = activePanel === tab.id;
            const hasNotification = tab.id === 'detail' && selectedDetection;
            return (
              <button key={tab.id} onClick={() => setActivePanel(tab.id)}
                className={`flex-1 flex flex-col items-center gap-1 py-3 text-sm transition-colors relative
                  ${isActive ? 'text-bordeaux-400 border-b-2 border-bordeaux-400' : 'text-slate-500 hover:text-slate-300'}`}>
                <tab.icon size={18} />
                <span>{tab.label}</span>
                {hasNotification && <span className="absolute top-2 right-1/4 w-2 h-2 bg-hotpink-400 rounded-full" />}
              </button>
            );
          })}
        </div>

        {/* Panel content */}
        <div className="flex-1 overflow-y-auto">
          {activePanel === 'filters' && <FilterPanel />}
          {activePanel === 'detections' && <DetectionList />}
          {activePanel === 'jobs' && <JobPanel />}
          {activePanel === 'detail' && <DetailPanel />}
        </div>
      </div>
    </>
  );
}

/** Simple detection list */
function DetectionList() {
  const { data: detections = [] } = useDetectionsHook();
  const setSelectedDetection = useStore((s) => s.setSelectedDetection);

  return (
    <div className="p-5">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-3">
        {detections.length} detections in view
      </h3>
      <div className="flex flex-col gap-1.5 max-h-[50vh] overflow-y-auto">
        {detections.slice(0, 100).map((d: any) => (
          <button key={d.id} onClick={() => setSelectedDetection(d)}
            className="flex items-center gap-3 p-3 rounded bg-slate-800 hover:bg-slate-700 text-left transition-colors">
            <span className="w-3 h-3 rounded-full flex-shrink-0"
              style={{ backgroundColor: FEATURE_COLORS[d.feature_type as keyof typeof FEATURE_COLORS] || '#6b7280' }} />
            <span className="text-sm text-slate-200 truncate flex-1">
              {d.feature_type?.replace(/_/g, ' ') || 'unknown'}
            </span>
            <span className="text-sm text-slate-400 font-mono">
              {(d.confidence * 100).toFixed(0)}%
            </span>
          </button>
        ))}
        {detections.length > 100 && (
          <p className="text-sm text-slate-500 text-center py-3">+{detections.length - 100} more</p>
        )}
      </div>
    </div>
  );
}

function VersionTag() {
  const { data } = useQuery({
    queryKey: ['info'],
    queryFn: async () => {
      const res = await fetch('/api/info');
      return res.json();
    },
    staleTime: 300_000,
  });
  if (!data) return null;
  return <span className="text-base text-slate-500">v{data.version}</span>;
}
