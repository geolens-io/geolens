import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { render } from '@/test/test-utils';
import { fetchAggregate, type AggregateRequest } from '@/api/aggregate';
import type { DashboardConfig, SharedLayerResponse } from '@/types/api';
import { DashboardPanel } from '../DashboardPanel';
import type { LinkedPick } from '../linked-filters';

vi.mock('@/api/aggregate', () => ({ fetchAggregate: vi.fn() }));

const zoom = vi.hoisted(() => vi.fn());
vi.mock('../hooks/use-feature-zoom', () => ({ useFeatureZoom: () => zoom }));

const fetchMock = vi.mocked(fetchAggregate);

const layerId = '0b7d2f4e-3c1a-4e8b-9f6d-5a2c7e1b9d34';
const datasetId = 'a7d1c2e3-0000-4000-8000-000000000001';
const listId = '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11';
const chartId = '9a2b4c6d-1e3f-4a5b-8c7d-0e1f2a3b4c5d';

const layer = {
  id: layerId,
  dataset_id: datasetId,
  dataset_name: 'Parcels',
  display_name: 'City parcels',
  table_name: 'parcels',
  geometry_type: 'POLYGON',
  sort_order: 0,
  visible: true,
  opacity: 1,
  paint: {},
  layout: {},
  show_in_legend: true,
  tile_url: '',
  filter: ['==', ['get', 'kind'], 'park'],
  column_info: [
    { name: 'name', type: 'text' },
    { name: 'kind', type: 'text' },
  ],
} as unknown as SharedLayerResponse;

const listWidget = {
  id: listId,
  type: 'feature_list',
  v: 1,
  layer_id: layerId,
  scope: 'layer',
  config: { title_column: 'name', subtitle_column: null, sort_column: 'name', sort: 'asc', page_size: 10 },
};

const dashboard = (widgets: unknown[]) => ({ version: 1, widgets }) as DashboardConfig;

function page(names: string[], next: string | null) {
  return {
    op: 'rows',
    approximate: false,
    cached: false,
    result: {
      rows: names.map((name, index) => ({
        gid: index + (next ? 0 : 100),
        values: { name },
        bbox: [-74, 40, -73.9, 40.1],
      })),
      next_cursor: next,
      has_more: next !== null,
    },
  };
}

function requested(): AggregateRequest[] {
  return fetchMock.mock.calls.map(([, body]) => body);
}

beforeEach(() => {
  fetchMock.mockReset();
  zoom.mockReset();
  fetchMock.mockImplementation(async (_dataset, body) =>
    ((body as { cursor?: string }).cursor ? page(['Third', 'Fourth'], null) : page(['First', 'Second'], 'c1')) as never,
  );
});

const filter = { op: '=', args: [{ property: 'kind' }, 'park'] };

describe('feature list on a dashboard', () => {
  it('asks for a page of rows with the layer filter and the map view', async () => {
    const bounds = [-10, -5, 10, 5];
    const map = {
      getBounds: () => ({
        getWest: () => bounds[0],
        getSouth: () => bounds[1],
        getEast: () => bounds[2],
        getNorth: () => bounds[3],
      }),
      on: () => undefined,
      off: () => undefined,
    } as unknown as MaplibreMap;
    render(
      <DashboardPanel
        config={dashboard([{ ...listWidget, scope: 'view' }])}
        layers={[layer]}
        map={map}
        mapId="map-1"
      />,
    );
    await screen.findByText('First');
    expect(requested()).toEqual([
      { op: 'rows', columns: ['name'], sort_column: 'name', sort: 'asc', limit: 10, filter, bbox: bounds },
    ]);
  });

  it('adds the picks made on the layer’s other widgets to its request', async () => {
    const pick: LinkedPick = {
      widgetId: chartId,
      layerId,
      selection: { column: 'kind', label: 'park', values: ['park'] },
      cql2: { op: '=', args: [{ property: 'kind' }, 'park'] },
    };
    const other = { op: '=', args: [{ property: 'name' }, 'Elm'] };
    render(
      <DashboardPanel
        config={dashboard([listWidget])}
        layers={[{ ...layer, filter: undefined } as SharedLayerResponse]}
        map={null}
        mapId="map-1"
        picks={[pick, { ...pick, widgetId: 'other', cql2: other as never }]}
      />,
    );
    await screen.findByText('First');
    expect(requested()[0]).toMatchObject({ op: 'rows', filter: { op: 'and', args: [pick.cql2, other] } });
  });

  it('appends the next cursor page under the first when Load more is pressed', async () => {
    render(<DashboardPanel config={dashboard([listWidget])} layers={[layer]} map={null} mapId="map-1" />);
    await screen.findByText('First');
    await userEvent.click(screen.getByRole('button', { name: 'Load more' }));
    await screen.findByText('Fourth');

    expect(requested()[1]).toMatchObject({ op: 'rows', cursor: 'c1' });
    expect(requested()[0]).not.toHaveProperty('cursor');
    const names = within(screen.getByRole('list', { name: 'Features' }))
      .getAllByRole('listitem')
      .map((item) => item.textContent);
    expect(names).toEqual(['First', 'Second', 'Third', 'Fourth']);
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });

  it('zooms the map to a clicked feature when the dashboard has one', async () => {
    const map = { getBounds: () => undefined, on: () => undefined, off: () => undefined } as unknown as MaplibreMap;
    render(<DashboardPanel config={dashboard([listWidget])} layers={[layer]} map={map} mapId="map-1" />);
    await userEvent.click(await screen.findByRole('button', { name: /First/ }));
    await waitFor(() => expect(zoom).toHaveBeenCalledWith(layer, { id: 0, bbox: [-74, 40, -73.9, 40.1] }));
  });

  it('does not offer a zoom where the dashboard hides its map', async () => {
    render(
      <DashboardPanel
        config={{ ...dashboard([listWidget]), map_hidden: true } as DashboardConfig}
        layers={[layer]}
        map={null}
        mapId="map-1"
      />,
    );
    await screen.findByText('First');
    expect(screen.queryByRole('button', { name: /First/ })).not.toBeInTheDocument();
    expect(zoom).not.toHaveBeenCalled();
  });

  it('stops asking for a page that failed until the reader presses the button', async () => {
    vi.stubGlobal(
      'IntersectionObserver',
      class {
        callback: IntersectionObserverCallback;
        constructor(callback: IntersectionObserverCallback) {
          this.callback = callback;
        }
        observe(target: Element) {
          queueMicrotask(() =>
            this.callback([{ isIntersecting: true, target } as IntersectionObserverEntry], this as never),
          );
        }
        disconnect() {}
      },
    );
    try {
      let failing = true;
      fetchMock.mockImplementation(async (_dataset, body) => {
        if (!(body as { cursor?: string }).cursor) return page(['First', 'Second'], 'c1') as never;
        if (failing) throw new Error('down');
        return page(['Third'], null) as never;
      });
      render(<DashboardPanel config={dashboard([listWidget])} layers={[layer]} map={null} mapId="map-1" />);

      expect(await screen.findByRole('alert')).toHaveTextContent("Couldn't load more");
      await new Promise((resolve) => setTimeout(resolve, 100));
      expect(fetchMock).toHaveBeenCalledTimes(2);

      failing = false;
      await userEvent.click(screen.getByRole('button', { name: 'Try again' }));
      await screen.findByText('Third');
      expect(fetchMock).toHaveBeenCalledTimes(3);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('keeps rows plain where the map is not the viewer’s, as in the Builder’s preview', async () => {
    const map = { getBounds: () => undefined, on: () => undefined, off: () => undefined } as unknown as MaplibreMap;
    render(<DashboardPanel config={dashboard([listWidget])} layers={[layer]} map={map} mapId="map-1" canZoom={false} />);
    await screen.findByText('First');
    expect(screen.queryByRole('button', { name: /First/ })).not.toBeInTheDocument();
  });
});
