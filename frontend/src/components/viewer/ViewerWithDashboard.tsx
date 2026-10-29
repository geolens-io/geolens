import { useState, type ReactNode } from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { DashboardConfig, SharedLayerResponse } from '@/types/api';
import { cn } from '@/lib/utils';
import { DashboardPanel, dashboardPanelPosition } from './DashboardPanel';

interface ViewerWithDashboardProps {
  config: DashboardConfig | null | undefined;
  layers: readonly SharedLayerResponse[];
  /** Ids of the layers the reader turned off; see `DashboardPanel`. */
  hiddenLayers?: ReadonlySet<string>;
  embedToken?: string;
  /** Remembers the reader's collapsed choice; see `DashboardPanel`. */
  mapId?: string;
  startCollapsed?: boolean;
  /** Renders the map viewport, passing `onMapReady` on to the viewer's map. */
  children: (onMapReady: (map: MaplibreMap) => void) => ReactNode;
}

/** A viewer's map with its dashboard to the right or below, and always below on narrow screens. */
export function ViewerWithDashboard({ children, ...panel }: ViewerWithDashboardProps) {
  const [map, setMap] = useState<MaplibreMap | null>(null);
  return (
    <div
      className={cn(
        'flex w-full min-h-0 flex-1 flex-col',
        dashboardPanelPosition(panel.config) === 'right' && 'md:flex-row',
      )}
    >
      {children(setMap)}
      <DashboardPanel {...panel} map={map} />
    </div>
  );
}
