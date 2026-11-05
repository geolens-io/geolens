import type { Map as MaplibreMap } from 'maplibre-gl';
import { useEffect } from 'react';
import { render } from '@/test/test-utils';
import type { DashboardConfig } from '@/types/api';
import { ViewerWithDashboard } from '../ViewerWithDashboard';

const seen = vi.hoisted(() => ({ maps: [] as unknown[] }));

vi.mock('../DashboardPanel', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../DashboardPanel')>()),
  DashboardPanel: ({ map }: { map: unknown }) => {
    seen.maps.push(map);
    return null;
  },
}));

const config = (mapHidden: boolean) =>
  ({
    version: 1,
    ...(mapHidden ? { map_hidden: true } : {}),
    widgets: [{ id: 'w1', type: 'indicator', v: 1, layer_id: 'l1', scope: 'view', config: { stat: 'count' } }],
  }) as DashboardConfig;

function ReportsMap({ onMapReady, map }: { onMapReady: (map: MaplibreMap) => void; map?: MaplibreMap }) {
  useEffect(() => {
    if (map) onMapReady(map);
  }, [map, onMapReady]);
  return <div />;
}

describe('ViewerWithDashboard map hand-off', () => {
  it('forgets the old map while the map is hidden, until the new map reports itself', () => {
    const oldMap = { id: 'old' } as unknown as MaplibreMap;
    const tree = (mapHidden: boolean, map?: MaplibreMap) => (
      <ViewerWithDashboard config={config(mapHidden)} layers={[]}>
        {({ onMapReady }) => <ReportsMap onMapReady={onMapReady} map={map} />}
      </ViewerWithDashboard>
    );
    const view = render(tree(false, oldMap));
    expect(seen.maps.at(-1)).toBe(oldMap);

    view.rerender(tree(true));
    view.rerender(tree(false));

    expect(seen.maps.at(-1)).toBeNull();
  });
});
