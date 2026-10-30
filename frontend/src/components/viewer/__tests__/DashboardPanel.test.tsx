import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { render } from '@/test/test-utils';
import { fetchAggregate, type AggregateRequest } from '@/api/aggregate';
import { storageKeys } from '@/lib/storage';
import type { DashboardConfig, SharedLayerResponse } from '@/types/api';
import { DashboardPanel } from '../DashboardPanel';
import { VIEW_REFETCH_DEBOUNCE_MS } from '../hooks/use-dashboard-data';

vi.mock('@/api/aggregate', () => ({ fetchAggregate: vi.fn() }));

const fetchMock = vi.mocked(fetchAggregate);

const layerId = '0b7d2f4e-3c1a-4e8b-9f6d-5a2c7e1b9d34';
const datasetId = 'a7d1c2e3-0000-4000-8000-000000000001';
const countId = '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11';
const chartId = '9a2b4c6d-1e3f-4a5b-8c7d-0e1f2a3b4c5d';

function layer(overrides: Partial<SharedLayerResponse> = {}): SharedLayerResponse {
  return {
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
    column_info: [{ name: 'land_use', type: 'text' }],
    ...overrides,
  } as SharedLayerResponse;
}

function dashboard(widgets: unknown[]): DashboardConfig {
  return { version: 1, widgets } as DashboardConfig;
}

const countWidget = {
  id: countId,
  type: 'indicator',
  v: 1,
  title: 'Parcels counted',
  layer_id: layerId,
  scope: 'layer',
  config: { stat: 'count', column: null },
};
const chartWidget = {
  id: chartId,
  type: 'bar_chart',
  v: 1,
  layer_id: layerId,
  scope: 'layer',
  config: { column: 'land_use', stat: 'count', stat_column: null, limit: 5 },
};

function respond(body: AggregateRequest) {
  if (body.op === 'count') {
    return { op: 'count', approximate: false, cached: false, result: { count: 1234 } };
  }
  return {
    op: 'value_counts',
    approximate: false,
    cached: false,
    result: { values: [{ value: 'Residential', count: 40 }], other_count: 0 },
  };
}

type Bounds = [number, number, number, number];

/** A map whose view the test moves; `moveend` fires once per move. */
function movableMap(initial: Bounds) {
  let current = initial;
  const listeners = new Set<() => void>();
  const map = {
    getBounds: () => ({
      getWest: () => current[0],
      getSouth: () => current[1],
      getEast: () => current[2],
      getNorth: () => current[3],
    }),
    on: (_event: string, listener: () => void) => listeners.add(listener),
    off: (_event: string, listener: () => void) => listeners.delete(listener),
  } as unknown as MaplibreMap;
  return {
    map,
    move(next: Bounds) {
      current = next;
      listeners.forEach((listener) => listener());
    },
  };
}

/**
 * Lets `ms` pass with React free to render and run timers, as it is inside
 * `waitFor`; an `act` around a sleep would hold the updates until it ends.
 */
function rest(ms: number) {
  const until = Date.now() + ms;
  return waitFor(() => expect(Date.now()).toBeGreaterThanOrEqual(until), { timeout: ms + 1000 });
}

function requestedBodies(): AggregateRequest[] {
  return fetchMock.mock.calls.map(([, body]) => body);
}

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (_dataset, body) => respond(body) as never);
  localStorage.clear();
});

describe('DashboardPanel', () => {
  it('renders the widgets in order and asks for each with the layer filter', async () => {
    render(
      <DashboardPanel
        config={dashboard([countWidget, chartWidget])}
        layers={[layer({ filter: ['==', ['get', 'land_use'], 'Residential'] })]}
        map={null}
        embedToken="embed-abc"
        mapId="map-1"
      />,
    );

    const panel = screen.getByRole('region', { name: 'Dashboard' });
    const headings = within(panel).getAllByRole('heading', { level: 3 });
    expect(headings.map((h) => h.textContent)).toEqual(['Parcels counted', 'Count by land_use']);
    expect(await within(panel).findByText('1,234')).toBeInTheDocument();

    const filter = { op: '=', args: [{ property: 'land_use' }, 'Residential'] };
    expect(fetchMock).toHaveBeenCalledWith(
      datasetId,
      { op: 'count', filter },
      expect.objectContaining({ embedToken: 'embed-abc' }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      datasetId,
      { op: 'value_counts', column: 'land_use', limit: 5, filter },
      expect.objectContaining({ embedToken: 'embed-abc' }),
    );
    expect(screen.queryByText(/layer's filter can't be applied/)).not.toBeInTheDocument();
  });

  it('names an untitled widget from its config, with the layer as the subline', () => {
    const widget = (id: string, type: string, config: unknown) => ({
      id,
      type,
      v: 1,
      layer_id: layerId,
      scope: 'layer',
      config,
    });
    const ids = [
      '1a1a1a1a-1111-4111-8111-111111111111',
      '2b2b2b2b-2222-4222-8222-222222222222',
      '3c3c3c3c-3333-4333-8333-333333333333',
      '4d4d4d4d-4444-4444-8444-444444444444',
    ];
    render(
      <DashboardPanel
        config={dashboard([
          widget(ids[0], 'indicator', { stat: 'sum', column: 'score' }),
          widget(ids[1], 'histogram', { column: 'score', bins: 10 }),
          widget(ids[2], 'category_selector', { column: 'land_use', multiple: true }),
          { ...chartWidget, id: ids[3], config: { ...chartWidget.config, column: 'land_use' } },
        ])}
        layers={[
          layer({
            column_info: [
              { name: 'land_use', type: 'text', title: 'Land use' },
              { name: 'score', type: 'integer' },
            ],
          }),
        ]}
        map={null}
      />,
    );

    const panel = screen.getByRole('region', { name: 'Dashboard' });
    const headings = within(panel).getAllByRole('heading', { level: 3 });
    expect(headings.map((h) => h.textContent)).toEqual([
      'Sum of score',
      'Distribution of score',
      'Filter by Land use',
      'Count by Land use',
    ]);
    expect(within(panel).getAllByText('City parcels')).toHaveLength(4);
    expect(within(panel).getByRole('article', { name: 'Sum of score City parcels' })).toBeInTheDocument();
  });

  it('collapses and reopens, remembering the choice for the map', async () => {
    const user = userEvent.setup();
    const props = {
      config: dashboard([countWidget]),
      layers: [layer()],
      map: null,
      mapId: 'map-1',
    };
    const { unmount } = render(<DashboardPanel {...props} />);
    expect(await screen.findByText('1,234')).toBeInTheDocument();

    const hide = screen.getByRole('button', { name: 'Hide dashboard' });
    expect(hide).toHaveAttribute('aria-expanded', 'true');
    await user.click(hide);

    expect(screen.queryByText('Parcels counted')).not.toBeInTheDocument();
    const open = screen.getByRole('button', { name: 'Open dashboard' });
    expect(open).toHaveAttribute('aria-expanded', 'false');
    expect(open).toHaveFocus();
    expect(localStorage.getItem(storageKeys.dashboardCollapsed('map-1'))).toBe('1');

    unmount();
    fetchMock.mockClear();
    render(<DashboardPanel {...props} />);
    expect(screen.getByRole('button', { name: 'Open dashboard' })).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Open dashboard' }));
    expect(await screen.findByText('1,234')).toBeInTheDocument();
    expect(localStorage.getItem(storageKeys.dashboardCollapsed('map-1'))).toBeNull();
  });

  it('keeps a share link reader’s choice out of storage', async () => {
    const user = userEvent.setup();
    render(<DashboardPanel config={dashboard([countWidget])} layers={[layer()]} map={null} />);
    await user.click(screen.getByRole('button', { name: 'Hide dashboard' }));
    expect(screen.getByRole('button', { name: 'Open dashboard' })).toBeInTheDocument();
    expect(localStorage.length).toBe(0);
  });

  it('refetches view-scoped widgets with the map view once the map rests', async () => {
    const { map, move } = movableMap([-10, -5, 10, 5]);
    render(
      <DashboardPanel
        config={dashboard([{ ...countWidget, scope: 'view' }, chartWidget])}
        layers={[layer()]}
        map={map}
        mapId="map-1"
      />,
    );
    // Until the view has rested there is nothing to show yet.
    const viewWidget = screen.getByRole('article', { name: 'Parcels counted' });
    expect(within(viewWidget).getByText('Loading...')).toBeInTheDocument();
    expect(within(viewWidget).queryByText('No data yet')).not.toBeInTheDocument();

    // The map leaves its first view at once, as a fit on load does.
    move([-20, -10, 20, 10]);
    await waitFor(() =>
      expect(requestedBodies()).toContainEqual({ op: 'count', bbox: [-20, -10, 20, 10] }),
    );
    const viewCounts = () => requestedBodies().filter((body) => body.op === 'count');
    expect(viewCounts()).toHaveLength(1);

    move([0, 0, 20, 10]);
    // Nothing is asked until the map has rested.
    await rest(VIEW_REFETCH_DEBOUNCE_MS / 2);
    expect(viewCounts()).toHaveLength(1);
    move([170, 0, 190, 10]);

    // The last view crosses the antimeridian and is sent wrapped.
    await waitFor(() =>
      expect(requestedBodies()).toContainEqual({ op: 'count', bbox: [170, 0, -170, 10] }),
    );
    expect(viewCounts()).toHaveLength(2);
    expect(viewCounts()).not.toContainEqual({ op: 'count', bbox: [0, 0, 20, 10] });

    // A sub-pixel move rounds to the same view and asks for nothing new.
    move([170.000001, 0, 190.000001, 10]);
    await rest(VIEW_REFETCH_DEBOUNCE_MS * 2);
    expect(viewCounts()).toHaveLength(2);

    // A widget that covers the whole layer doesn't follow the view.
    expect(requestedBodies().filter((body) => body.op === 'value_counts')).toEqual([
      { op: 'value_counts', column: 'land_use', limit: 5 },
    ]);
  });

  it('says when a widget ignores a layer filter the endpoint cannot take', async () => {
    render(
      <DashboardPanel
        config={dashboard([countWidget])}
        layers={[layer({ filter: ['==', ['get', 'a'], ['get', 'b']] as never })]}
        map={null}
        mapId="map-1"
      />,
    );

    expect(
      await screen.findByText(
        "Shows all features: the layer's filter can't be applied to these numbers.",
      ),
    ).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(requestedBodies()).toEqual([{ op: 'count' }]);
  });

  it('asks the reader to zoom in when the view holds too many rows', async () => {
    const { ApiError } = await import('@/api/client');
    fetchMock.mockRejectedValue(
      new ApiError('too wide', 422, { code: 'too_wide', message: 'too wide' }),
    );
    render(
      <DashboardPanel
        config={dashboard([countWidget])}
        layers={[layer()]}
        map={null}
        mapId="map-1"
      />,
    );
    expect(
      await screen.findByText('Too many features in view. Zoom in to see these numbers.'),
    ).toBeInTheDocument();
  });

  it('says a refused column is unavailable, with no retry, and keeps retry for other failures', async () => {
    const { ApiError } = await import('@/api/client');
    fetchMock.mockRejectedValue(
      new ApiError('refused', 422, { code: 'invalid_column', message: 'Unknown column' }),
    );
    const { unmount } = render(
      <DashboardPanel config={dashboard([countWidget])} layers={[layer()]} map={null} mapId="map-1" />,
    );
    expect(await screen.findByText("This widget's column isn't available here.")).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    unmount();

    fetchMock.mockReset();
    fetchMock.mockRejectedValue(new Error('network down'));
    render(<DashboardPanel config={dashboard([countWidget])} layers={[layer()]} map={null} mapId="map-1" />);
    expect(await screen.findByText("These numbers couldn't be loaded.")).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('says a refused filter cannot be applied, with no retry', async () => {
    const { ApiError } = await import('@/api/client');
    fetchMock.mockRejectedValue(new ApiError('refused', 422, { code: 'invalid_filter', message: 'Filter too deep' }));
    render(<DashboardPanel config={dashboard([countWidget])} layers={[layer()]} map={null} mapId="map-1" />);
    expect(await screen.findByText("This widget's filter can't be applied here.")).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
  });

  it('leaves out widgets whose layer the reader turns off, and keeps those on layers saved hidden', async () => {
    // A reference layer saved hidden can still drive the numbers.
    const otherLayer = layer({ id: '2d9f4a6b-5e3c-4a0d-9b8f-7c4e9a3d1f56', display_name: 'Roads', visible: false });
    const roadsWidget = { ...countWidget, id: chartId, title: 'Roads counted', layer_id: otherLayer.id };
    const props = {
      config: dashboard([countWidget, roadsWidget]),
      layers: [layer(), otherLayer],
      map: null,
      mapId: 'map-1',
    };
    const { rerender } = render(<DashboardPanel {...props} hiddenLayers={new Set()} />);
    expect(screen.getByRole('heading', { name: 'Roads counted' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Parcels counted' })).toBeInTheDocument();

    rerender(<DashboardPanel {...props} hiddenLayers={new Set([layerId])} />);
    expect(screen.getByRole('heading', { name: 'Roads counted' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Parcels counted' })).not.toBeInTheDocument();

    rerender(<DashboardPanel {...props} hiddenLayers={new Set([layerId, otherLayer.id])} />);
    expect(screen.queryByRole('heading', { level: 3 })).not.toBeInTheDocument();
    expect(screen.getByText(/Show one in the legend to see its widgets/)).toBeInTheDocument();
  });

  it('dims the last numbers while a pan\'s new ones load', async () => {
    const { map, move } = movableMap([-10, -5, 10, 5]);
    render(
      <DashboardPanel
        config={dashboard([{ ...countWidget, scope: 'view' }])}
        layers={[layer()]}
        map={map}
        mapId="map-1"
      />,
    );
    const value = await screen.findByText('1,234');
    expect(value.closest('.transition-opacity')).not.toHaveClass('opacity-50');

    fetchMock.mockImplementation(() => new Promise(() => {}));
    move([0, 0, 20, 10]);
    await waitFor(() => expect(screen.getByText('1,234').closest('.transition-opacity')).toHaveClass('opacity-50'));
  });

  it('asks again once the dataset\'s contents change', async () => {
    const props = { config: dashboard([countWidget]), map: null, mapId: 'map-1' };
    const { rerender } = render(<DashboardPanel {...props} layers={[layer({ tile_version: 1 })]} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    rerender(<DashboardPanel {...props} layers={[layer({ tile_version: 1 })]} />);
    rerender(<DashboardPanel {...props} layers={[layer({ tile_version: 2 })]} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it('can start collapsed, as an embed asks, and still opens', async () => {
    const user = userEvent.setup();
    render(
      <DashboardPanel config={dashboard([countWidget])} layers={[layer()]} map={null} startCollapsed />,
    );
    expect(fetchMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Open dashboard' }));
    expect(await screen.findByText('1,234')).toBeInTheDocument();
  });

  it('announces failures once for the panel and offers a retry on each widget', async () => {
    const user = userEvent.setup();
    const { ApiError } = await import('@/api/client');
    fetchMock.mockRejectedValue(new ApiError('down', 503));
    render(
      <DashboardPanel config={dashboard([countWidget, chartWidget])} layers={[layer()]} map={null} mapId="map-1" />,
    );

    await waitFor(() =>
      expect(screen.getByText("Some widgets couldn't load their numbers.")).toBeInTheDocument(),
    );
    expect(screen.getAllByRole('status')).toHaveLength(1);
    const retries = screen.getAllByRole('button', { name: 'Retry' });
    expect(retries).toHaveLength(2);

    fetchMock.mockImplementation(async (_dataset, body) => respond(body) as never);
    await user.click(retries[0]);
    expect(await screen.findByText('1,234')).toBeInTheDocument();
  });

  it('lets a table layer\'s widget cover the whole layer instead of a view it has no geometry for', async () => {
    const table = layer({ geometry_type: null });
    render(
      <DashboardPanel
        config={dashboard([{ ...countWidget, scope: 'view' }])}
        layers={[table]}
        map={null}
        mapId="map-1"
      />,
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(datasetId, { op: 'count' }, expect.anything()));
    expect(screen.queryByText('Follows the map view')).not.toBeInTheDocument();
  });

  it('keeps the open button labelled when a bottom panel is collapsed', async () => {
    const user = userEvent.setup();
    render(
      <DashboardPanel
        config={{ ...dashboard([countWidget]), panel: 'bottom' }}
        layers={[layer()]}
        map={null}
        mapId="map-1"
      />,
    );
    await user.click(screen.getByRole('button', { name: 'Hide dashboard' }));
    // A right panel collapses to an icon rail on wide screens; a bottom one stays a labelled bar.
    expect(screen.getByText('Open dashboard')).not.toHaveClass('md:sr-only');
  });

  it('renders nothing for a map without widgets', () => {
    const { container } = render(
      <DashboardPanel config={dashboard([])} layers={[layer()]} map={null} mapId="map-1" />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
