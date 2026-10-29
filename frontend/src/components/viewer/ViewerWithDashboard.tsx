import { useMemo, useState, type ReactNode } from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { DashboardConfig, SharedLayerResponse } from '@/types/api';
import { cn } from '@/lib/utils';
import { DashboardPanel, dashboardPanelPosition } from './DashboardPanel';
import { linkMapLayers, type LinkedPick } from './linked-filters';

interface ViewerWithDashboardProps {
  config: DashboardConfig | null | undefined;
  layers: readonly SharedLayerResponse[];
  /** Ids of the layers the reader turned off; see `DashboardPanel`. */
  hiddenLayers?: ReadonlySet<string>;
  embedToken?: string;
  /** Remembers the reader's collapsed choice; see `DashboardPanel`. */
  mapId?: string;
  startCollapsed?: boolean;
  /**
   * Renders the map viewport, passing `onMapReady` on to the viewer's map and
   * `mapLayers` to it as its layers: `layers` with the reader's dashboard picks
   * added to their filters.
   */
  children: (map: { onMapReady: (map: MaplibreMap) => void; mapLayers: SharedLayerResponse[] }) => ReactNode;
}

/**
 * A viewer's map with its dashboard to the right or below, and always below on
 * narrow screens. A pick on a widget filters its layer on the map until the
 * reader clears it; the saved map is unchanged.
 */
export function ViewerWithDashboard({ children, ...panel }: ViewerWithDashboardProps) {
  const [map, setMap] = useState<MaplibreMap | null>(null);
  const [picks, setPicks] = useState<readonly LinkedPick[]>([]);
  const mapLayers = useMemo(() => linkMapLayers(panel.layers, picks), [panel.layers, picks]);
  return (
    <div
      className={cn(
        'flex w-full min-h-0 flex-1 flex-col',
        dashboardPanelPosition(panel.config) === 'right' && 'md:flex-row',
      )}
    >
      {children({ onMapReady: setMap, mapLayers })}
      <DashboardPanel {...panel} map={map} picks={picks} onPicksChange={setPicks} />
    </div>
  );
}
