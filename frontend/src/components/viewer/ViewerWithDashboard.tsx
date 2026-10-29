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
  const [storedPicks, setPicks] = useState<readonly LinkedPick[]>([]);
  // A refreshed map can drop a picked widget or its layer; its pick goes too,
  // since no chip would be left to clear it.
  const picks = useMemo(() => {
    const live = storedPicks.filter(
      (pick) =>
        panel.config?.widgets.some((widget) => widget.id === pick.widgetId && widget.layer_id === pick.layerId) &&
        panel.layers.some((layer) => layer.id === pick.layerId),
    );
    return live.length === storedPicks.length ? storedPicks : live;
  }, [storedPicks, panel.config, panel.layers]);
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
