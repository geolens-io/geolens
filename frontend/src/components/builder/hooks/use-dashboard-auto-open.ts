import { useEffect, useRef } from 'react';
import type { RailPanel } from '@/components/builder/BuilderRail';
import { readStorage, removeStorage, storageKeys, writeStorage } from '@/lib/storage';

/**
 * Opens the Dashboard rail panel once per map when its saved dashboard has
 * widgets, so the dashboard isn't missed. Closing it, or switching to another
 * panel, is remembered per map and stops the auto-open; opening it again clears
 * that. Where the rail panels open as a sheet it stays closed.
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
  useEffect(() => {
    if (!mapId || !ready || handledFor.current === mapId) return;
    handledFor.current = mapId;
    if (hasWidgets && !sheetLayout && readStorage(storageKeys.dashboardRailClosed(mapId)) !== '1') {
      setRailPanel('dashboard');
    }
  }, [mapId, ready, hasWidgets, sheetLayout, setRailPanel]);

  const previous = useRef({ mapId, railPanel });
  useEffect(() => {
    const before = previous.current;
    previous.current = { mapId, railPanel };
    // Another map's panel state carried over is not this author's choice.
    if (!mapId || before.mapId !== mapId) return;
    if (railPanel === 'dashboard') removeStorage(storageKeys.dashboardRailClosed(mapId));
    else if (before.railPanel === 'dashboard') writeStorage(storageKeys.dashboardRailClosed(mapId), '1');
  }, [mapId, railPanel]);
}
