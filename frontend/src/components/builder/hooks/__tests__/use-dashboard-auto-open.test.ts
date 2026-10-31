import { act, renderHook } from '@testing-library/react';
import { useState } from 'react';
import type { RailPanel } from '@/components/builder/BuilderRail';
import { storageKeys } from '@/lib/storage';
import { useDashboardAutoOpen } from '../use-dashboard-auto-open';

type Props = { mapId: string; ready?: boolean; hasWidgets?: boolean; sheetLayout?: boolean };

function setup(initial: Props) {
  return renderHook(
    (props: Props) => {
      const [railPanel, setRailPanel] = useState<RailPanel>(null);
      useDashboardAutoOpen({
        ready: true,
        hasWidgets: true,
        sheetLayout: false,
        ...props,
        railPanel,
        setRailPanel,
      });
      return { railPanel, setRailPanel };
    },
    { initialProps: initial },
  );
}

beforeEach(() => localStorage.clear());

describe('useDashboardAutoOpen', () => {
  it('opens the dashboard panel once the map is ready with widgets', () => {
    const { result, rerender } = setup({ mapId: 'a', ready: false });
    expect(result.current.railPanel).toBeNull();
    rerender({ mapId: 'a', ready: true });
    expect(result.current.railPanel).toBe('dashboard');
  });

  it('leaves the rail closed for a map without widgets', () => {
    const { result } = setup({ mapId: 'a', hasWidgets: false });
    expect(result.current.railPanel).toBeNull();
  });

  it('opens only once per map, so a later close stays closed through edits', () => {
    const { result, rerender } = setup({ mapId: 'a' });
    act(() => result.current.setRailPanel(null));
    rerender({ mapId: 'a', hasWidgets: false });
    rerender({ mapId: 'a', hasWidgets: true });
    expect(result.current.railPanel).toBeNull();
  });

  it('stays closed on a map the author closed it on, but opens another map', () => {
    const first = setup({ mapId: 'a' });
    act(() => first.result.current.setRailPanel('history'));
    expect(localStorage.getItem(storageKeys.dashboardRailClosed('a'))).toBe('1');
    first.unmount();

    expect(setup({ mapId: 'a' }).result.current.railPanel).toBeNull();
    expect(setup({ mapId: 'b' }).result.current.railPanel).toBe('dashboard');
  });

  it('forgets the closure when the author opens the panel again', () => {
    localStorage.setItem(storageKeys.dashboardRailClosed('a'), '1');
    const { result } = setup({ mapId: 'a' });
    act(() => result.current.setRailPanel('dashboard'));
    expect(localStorage.getItem(storageKeys.dashboardRailClosed('a'))).toBeNull();
  });

  it('does not open where panels open as a sheet', () => {
    const { result } = setup({ mapId: 'a', sheetLayout: true });
    expect(result.current.railPanel).toBeNull();
  });

  it('opens when storage throws', () => {
    const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied');
    });
    const { result } = setup({ mapId: 'a' });
    spy.mockRestore();
    expect(result.current.railPanel).toBe('dashboard');
  });
});
