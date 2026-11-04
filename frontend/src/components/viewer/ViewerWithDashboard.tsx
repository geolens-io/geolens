import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { DashboardConfig, SharedLayerResponse } from '@/types/api';
import { widgetLayerId } from '@/components/widgets/registry';
import { readerLogoUrl, readerThemeStyle, type ReaderTheme } from '@/lib/reader-theme';
import { useForcedTheme, useTheme } from '@/components/theme-provider';
import { cn } from '@/lib/utils';
import { DashboardPanel, dashboardLayout } from './DashboardPanel';
import { linkMapLayers, type LinkedPick } from './linked-filters';

interface ViewerWithDashboardProps {
  config: DashboardConfig | null | undefined;
  layers: readonly SharedLayerResponse[];
  /**
   * Ids of the layers the reader turned off; see `DashboardPanel`. Their picks
   * leave the chips and filters until the layer is turned back on.
   */
  hiddenLayers?: ReadonlySet<string>;
  embedToken?: string;
  /** Remembers the reader's collapsed choice; see `DashboardPanel`. */
  mapId?: string;
  startCollapsed?: boolean;
  /** Set where the page has no main landmark of its own, which the map's viewport otherwise supplies. */
  mainLandmark?: boolean;
  /** A branding extension's accent, font and logo for the viewer and its dashboard. */
  readerTheme?: ReaderTheme | null;
  /**
   * Renders the map viewport, passing `onMapReady` on to the viewer's map and
   * `mapLayers` to it as its layers: `layers` with the reader's dashboard picks
   * added to their filters.
   */
  children: (map: { onMapReady: (map: MaplibreMap) => void; mapLayers: SharedLayerResponse[] }) => ReactNode;
}

/**
 * A viewer's map with its dashboard to the right or below, and always below on
 * narrow screens. When the dashboard hides its map, the map is not mounted and
 * the dashboard fills the page. A pick on a widget filters its layer on the map until the
 * reader clears it; the saved map is unchanged.
 */
export function ViewerWithDashboard({ children, readerTheme, mainLandmark, ...panel }: ViewerWithDashboardProps) {
  useForcedTheme(panel.config?.theme);
  const [map, setMap] = useState<MaplibreMap | null>(null);
  const { resolvedTheme } = useTheme();
  const [storedPicks, setPicks] = useState<readonly LinkedPick[]>([]);
  const { hiddenLayers } = panel;
  // A refreshed map can drop a picked widget or its layer; its pick goes too,
  // since no chip would be left to clear it.
  const picks = useMemo(() => {
    const live = storedPicks.filter(
      (pick) =>
        !hiddenLayers?.has(pick.layerId) &&
        panel.config?.widgets.some((widget) => widget.id === pick.widgetId && widgetLayerId(widget) === pick.layerId) &&
        panel.layers.some((layer) => layer.id === pick.layerId),
    );
    return live.length === storedPicks.length ? storedPicks : live;
  }, [storedPicks, hiddenLayers, panel.config, panel.layers]);
  // The panel changes only the picks it shows, so the hidden layers' picks are kept.
  const changePicks = useCallback(
    (next: readonly LinkedPick[]) =>
      setPicks((stored) => [...stored.filter((pick) => hiddenLayers?.has(pick.layerId)), ...next]),
    [hiddenLayers],
  );
  const layout = dashboardLayout(panel.config);
  // The saved layers still feed the widgets; only the map itself stays unmounted.
  const mapHidden = layout === 'page';
  const mapLayers = useMemo(
    () => (mapHidden ? [] : linkMapLayers(panel.layers, picks)),
    [mapHidden, panel.layers, picks],
  );
  // The unmounted map must not outlive its removal: a later map reports itself through onMapReady.
  useEffect(() => {
    if (mapHidden) setMap(null);
  }, [mapHidden]);
  const dashboard = (
    <DashboardPanel
      {...panel}
      map={map}
      picks={picks}
      onPicksChange={changePicks}
      logoUrl={readerLogoUrl(readerTheme)}
    />
  );
  return (
    <div
      className={cn(
        'flex w-full min-h-0 flex-1 flex-col',
        layout === 'right' && 'md:flex-row',
      )}
      style={readerThemeStyle(readerTheme, resolvedTheme)}
    >
      {!mapHidden && children({ onMapReady: setMap, mapLayers })}
      {mapHidden && mainLandmark ? <main className="flex min-h-0 w-full flex-1 flex-col">{dashboard}</main> : dashboard}
    </div>
  );
}
