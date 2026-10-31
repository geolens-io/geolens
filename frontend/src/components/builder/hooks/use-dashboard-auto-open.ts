import { useEffect, useRef } from 'react';
import type { RailPanel } from '@/components/builder/BuilderRail';
import { readStorage, removeStorage, storageKeys, writeStorage } from '@/lib/storage';

/**
 * Opens the Dashboard rail panel once per map when its saved dashboard has
 * widgets, so the dashboard isn't missed. Closing it, or switching to another
 * panel, is remembered per map and stops the auto-open; opening it again clears
 * that. Where the rail panels open as a sheet it stays closed. A panel this
 * hook opened, and the author left open, closes on a switch to a map that
 * doesn't open it.
 */
export function useDashboardAutoOpen({
  mapId,
  ready,
  hasWidgets,
  sheetLayout,
  railPanel,
  setRailPanel,
}: {
  mapId: string | undefined;
  /** The map and its layers have loaded. */
  ready: boolean;
  hasWidgets: boolean;
  sheetLayout: boolean;
  railPanel: RailPanel;
  setRailPanel: (panel: RailPanel) => void;
}) {
  const handledFor = useRef<string | null>(null);
  // The panel this hook last set, until the author picks another.
  const autoPanel = useRef<RailPanel | undefined>(undefined);
  useEffect(() => {
    if (!mapId || !ready || handledFor.current === mapId) return;
    handledFor.current = mapId;
    const open = hasWidgets && !sheetLayout && readStorage(storageKeys.dashboardRailClosed(mapId)) !== '1';
    const next = open ? 'dashboard' : autoPanel.current === 'dashboard' && railPanel === 'dashboard' ? null : undefined;
    if (next === undefined) return;
    autoPanel.current = next;
    setRailPanel(next);
  }, [mapId, ready, hasWidgets, sheetLayout, railPanel, setRailPanel]);

  const previous = useRef({ mapId, railPanel });
  useEffect(() => {
    const before = previous.current;
    previous.current = { mapId, railPanel };
    // Another map's panel state carried over, or this hook's own change, is not this author's choice.
    if (!mapId || before.mapId !== mapId || before.railPanel === railPanel || autoPanel.current === railPanel) return;
    autoPanel.current = undefined;
    if (railPanel === 'dashboard') removeStorage(storageKeys.dashboardRailClosed(mapId));
    else if (before.railPanel === 'dashboard') writeStorage(storageKeys.dashboardRailClosed(mapId), '1');
  }, [mapId, railPanel]);
}
