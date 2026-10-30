import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { FilterSpecification } from 'maplibre-gl';
import { render } from '@/test/test-utils';
import { fetchAggregate, type AggregateRequest } from '@/api/aggregate';
import { getTileConfig, type TileConfig } from '@/api/settings';
import type { DashboardConfig, SharedLayerResponse } from '@/types/api';
import { ViewerWithDashboard } from '../ViewerWithDashboard';

vi.mock('@/api/aggregate', () => ({ fetchAggregate: vi.fn() }));
vi.mock('@/api/settings', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/settings')>()),
  getTileConfig: vi.fn(),
}));

const TILE_CONFIG: TileConfig = {
  cdn_base_url: null,
  public_app_url: null,
  public_api_url: null,
  public_base_url: null,
  mvt_source_layer_prefix: 'data',
};

const fetchMock = vi.mocked(fetchAggregate);

const parcelsId = '0b7d2f4e-3c1a-4e8b-9f6d-5a2c7e1b9d34';
const roadsId = '1c8e3a5f-4d2b-4f9c-8a7e-6b3d8f2c0e45';
const chartId = '9a2b4c6d-1e3f-4a5b-8c7d-0e1f2a3b4c5d';
const countId = '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11';
const roadsCountId = '7a2d4b63-9e2f-4b68-8c2a-3d5f8b0a1c22';

function layer(id: string, name: string, filter: FilterSpecification | null = null): SharedLayerResponse {
  return {
    id,
    dataset_id: `dataset-${name}`,
    dataset_name: name,
    display_name: name,
    table_name: name,
    geometry_type: 'POLYGON',
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    show_in_legend: true,
    tile_url: '',
    filter,
    column_info: [
      { name: 'land_use', type: 'text' },
      { name: 'zone', type: 'text' },
      { name: 'opened', type: 'timestamp with time zone' },
      { name: 'price', type: 'money' },
      { name: 'lease', type: 'interval' },
    ],
  } as SharedLayerResponse;
}

const dashboard = (chartColumn = 'land_use'): DashboardConfig =>
  ({
    version: 1,
    widgets: [
      {
        id: chartId,
        type: 'bar_chart',
        v: 1,
        title: 'Land use',
        layer_id: parcelsId,
        config: { column: chartColumn, stat: 'count', stat_column: null, limit: 5 },
      },
      { id: countId, type: 'indicator', v: 1, title: 'Parcels', layer_id: parcelsId, config: { stat: 'count' } },
      { id: roadsCountId, type: 'indicator', v: 1, title: 'Roads', layer_id: roadsId, config: { stat: 'count' } },
    ],
  }) as DashboardConfig;

// A filtered count is the number of Residential parcels; the bars answer the same whatever the filter.
function respond(body: AggregateRequest) {
  if (body.op === 'count') {
    return { op: 'count', approximate: false, cached: false, result: { count: body.filter ? 40 : 1234 } };
  }
  return {
    op: 'value_counts',
    approximate: false,
    cached: false,
    result: {
      values: [
        { value: 'Residential', count: 40 },
        { value: 'Commercial', count: 25 },
        // Timestamps don't compare in SQL as the map writes them, so this one can't filter.
        { value: '2024-03-01 17:00:00+00', count: 3 },
      ],
      other_count: 0,
    },
  };
}

function renderViewer(layers: SharedLayerResponse[], config = dashboard()) {
  const mapLayers = vi.fn();
  render(
    <ViewerWithDashboard config={config} layers={layers} embedToken="embed-abc">
      {({ mapLayers: linked }) => {
        mapLayers(linked);
        return <div data-testid="viewport" />;
      }}
    </ViewerWithDashboard>,
  );
  return { latestMapLayers: () => mapLayers.mock.calls.at(-1)![0] as SharedLayerResponse[] };
}

const residential = { op: 'in', args: [{ property: 'land_use' }, ['Residential']] };
const bodiesFor = (op: string) => fetchMock.mock.calls.map(([, body]) => body).filter((body) => body.op === op);

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (_dataset, body) => respond(body) as never);
  vi.mocked(getTileConfig).mockReset();
  vi.mocked(getTileConfig).mockResolvedValue(TILE_CONFIG);
});

async function clickBar(name: string) {
  const chart = await screen.findByRole('group', { name: 'Count by land_use' });
  const bar = [...chart.querySelectorAll('g[aria-hidden="true"]')].find((g) => g.textContent?.includes(name));
  fireEvent.click(bar!);
}

describe('dashboard linking', () => {
  it('filters the map layer and its other widgets by a clicked bar, and the chip clears it', async () => {
    const user = userEvent.setup();
    const parcels = layer(parcelsId, 'Parcels');
    const roads = layer(roadsId, 'Roads');
    const { latestMapLayers } = renderViewer([parcels, roads]);
    const panel = screen.getByRole('region', { name: 'Dashboard' });
    const parcelsCount = within(panel).getByRole('article', { name: 'Parcels' });
    expect(await within(parcelsCount).findByText('1,234')).toBeInTheDocument();

    await clickBar('Residential');

    expect(await within(parcelsCount).findByText('40')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      'dataset-Parcels',
      { op: 'count', filter: residential },
      expect.objectContaining({ embedToken: 'embed-abc' }),
    );
    // The chart keeps its own full distribution; a layer without picks is untouched.
    expect(bodiesFor('value_counts').every((body) => body.filter === undefined)).toBe(true);
    expect(within(within(panel).getByRole('article', { name: 'Roads' })).getByText('1,234')).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith('dataset-Roads', expect.objectContaining({ filter: expect.anything() }), expect.anything());

    const [mapParcels, mapRoads] = latestMapLayers();
    expect(mapParcels.filter).toEqual(['in', ['get', 'land_use'], ['literal', ['Residential']]]);
    expect(mapRoads).toBe(roads);
    expect(parcels.filter).toBeNull();

    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('Filtered Parcels to land_use: Residential.'),
    );
    const chip = within(screen.getByRole('group', { name: 'Filters' })).getByRole('button', {
      name: 'Remove filter land_use: Residential on Parcels',
    });
    expect(chip).toHaveTextContent('land_use: Residential');

    await user.click(chip);
    expect(await within(parcelsCount).findByText('1,234')).toBeInTheDocument();
    expect(latestMapLayers()[0]).toBe(parcels);
    expect(screen.queryByRole('group', { name: 'Filters' })).not.toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('Removed filter land_use: Residential on Parcels.'),
    );
    // The last chip leaves, so focus goes to the panel's toggle beside the chips.
    expect(document.activeElement).toBe(within(panel).getByRole('button', { name: 'Hide dashboard' }));
  });

  it('drops a pick whose widget or dashboard a refreshed map no longer has', async () => {
    const parcels = layer(parcelsId, 'Parcels');
    const layers = [parcels, layer(roadsId, 'Roads')];
    const mapLayers = vi.fn();
    const viewer = (config: DashboardConfig | null) => (
      <ViewerWithDashboard config={config} layers={layers}>
        {({ mapLayers: linked }) => {
          mapLayers(linked);
          return <div />;
        }}
      </ViewerWithDashboard>
    );
    const latest = () => (mapLayers.mock.calls.at(-1)![0] as SharedLayerResponse[])[0];
    const { rerender } = render(viewer(dashboard()));
    await clickBar('Residential');
    expect(latest().filter).not.toBeNull();
    expect(screen.getByRole('group', { name: 'Filters' })).toBeInTheDocument();

    // The author removed the chart that made the pick.
    const withoutChart = { ...dashboard(), widgets: dashboard().widgets.filter((widget) => widget.id !== chartId) };
    rerender(viewer(withoutChart));
    expect(latest()).toBe(parcels);
    expect(screen.queryByRole('group', { name: 'Filters' })).not.toBeInTheDocument();

    // Picked again, then the whole dashboard goes.
    rerender(viewer(dashboard()));
    await clickBar('Commercial');
    expect(latest().filter).not.toBeNull();
    rerender(viewer(null));
    expect(latest()).toBe(parcels);
  });

  it('refuses a pick that would push a server-clustered layer\'s filter past the cluster route\'s limits', async () => {
    const user = userEvent.setup();
    const long = (letter: string) => letter.repeat(1500);
    fetchMock.mockImplementation(async () => ({
      op: 'value_counts',
      approximate: false,
      cached: false,
      result: { values: ['a', 'b', 'c'].map((letter) => ({ value: long(letter), count: 1 })), other_count: 0 },
    }) as never);
    const clustered = {
      ...layer(parcelsId, 'Parcels'),
      geometry_type: 'POINT',
      feature_count: 20_000,
      style_config: { render_mode: 'cluster' },
    } as SharedLayerResponse;
    const selector = {
      version: 1,
      widgets: [
        { id: chartId, type: 'category_selector', v: 1, title: 'Land use', layer_id: parcelsId, config: { column: 'land_use', multiple: true } },
      ],
    } as DashboardConfig;
    const { latestMapLayers } = renderViewer([clustered, layer(roadsId, 'Roads')], selector);
    const boxes = await screen.findAllByRole('checkbox');

    await user.click(boxes[0]);
    await user.click(boxes[1]);
    const filtered = latestMapLayers()[0].filter;
    expect(filtered).toEqual(['in', ['get', 'land_use'], ['literal', [long('a'), long('b')]]]);

    // A third value takes the filter past 4096 characters.
    await user.click(boxes[2]);
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent("Too many values to filter this layer's clusters. Pick fewer."),
    );
    expect(latestMapLayers()[0].filter).toEqual(filtered);
    expect(boxes[2]).not.toBeChecked();
  });

  it('refuses a pick on a server-clustered layer whose saved filter its cluster tiles can\'t take', async () => {
    const opaque: FilterSpecification = ['>', ['length', ['get', 'zone']], 3];
    const clustered = {
      ...layer(parcelsId, 'Parcels', opaque),
      geometry_type: 'POINT',
      feature_count: 20_000,
      style_config: { render_mode: 'cluster' },
    } as SharedLayerResponse;
    const { latestMapLayers } = renderViewer([clustered, layer(roadsId, 'Roads')]);
    await clickBar('Residential');

    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent("This filter can't be applied to this layer's clusters on the map."),
    );
    expect(latestMapLayers()[0]).toBe(clustered);
    expect(screen.queryByRole('group', { name: 'Filters' })).not.toBeInTheDocument();
  });

  it('refuses a pick that would make the widgets\' requests longer than the server takes', async () => {
    const user = userEvent.setup();
    const long = (letter: string) => letter.repeat(2600);
    fetchMock.mockImplementation(async (_dataset, body) =>
      (body.op === 'value_counts'
        ? {
            op: 'value_counts',
            approximate: false,
            cached: false,
            result: { values: ['a', 'b', 'c', 'd'].map((letter) => ({ value: long(letter), count: 1 })), other_count: 0 },
          }
        : respond(body)) as never,
    );
    const selector = {
      version: 1,
      widgets: [
        { id: chartId, type: 'category_selector', v: 1, title: 'Land use', layer_id: parcelsId, config: { column: 'land_use', multiple: true } },
        { id: countId, type: 'indicator', v: 1, title: 'Parcels', layer_id: parcelsId, config: { stat: 'count' } },
      ],
    } as DashboardConfig;
    const { latestMapLayers } = renderViewer([layer(parcelsId, 'Parcels'), layer(roadsId, 'Roads')], selector);
    const boxes = await screen.findAllByRole('checkbox');

    for (const box of boxes.slice(0, 3)) await user.click(box);
    const filtered = latestMapLayers()[0].filter;
    expect(filtered).toEqual(['in', ['get', 'land_use'], ['literal', [long('a'), long('b'), long('c')]]]);

    // A fourth value takes the indicator's filter past the 10,000 characters the server reads.
    await user.click(boxes[3]);
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Too many values to filter by. Pick fewer.'));
    expect(latestMapLayers()[0].filter).toEqual(filtered);
    expect(boxes[3]).not.toBeChecked();
    expect(bodiesFor('count').every((body) => JSON.stringify(body.filter ?? null).length <= 10_000)).toBe(true);
  });

  it('refuses a pick whose cluster tile URL would overflow a request line with the columns it also carries', async () => {
    const user = userEvent.setup();
    const long = (letter: string) => letter.repeat(1200);
    fetchMock.mockImplementation(async () => ({
      op: 'value_counts',
      approximate: false,
      cached: false,
      result: { values: ['a', 'b', 'c'].map((letter) => ({ value: long(letter), count: 1 })), other_count: 0 },
    }) as never);
    // The popup's fields ride along in the tile URL's cols=.
    const fields = Array.from({ length: 120 }, (_, i) => `a_rather_long_attribute_column_name_${i}`);
    const clustered = {
      ...layer(parcelsId, 'Parcels'),
      geometry_type: 'POINT',
      feature_count: 20_000,
      style_config: { render_mode: 'cluster' },
      popup_config: { enabled: true, visible_fields: fields },
    } as SharedLayerResponse;
    const selector = {
      version: 1,
      widgets: [
        { id: chartId, type: 'category_selector', v: 1, title: 'Land use', layer_id: parcelsId, config: { column: 'land_use', multiple: true } },
      ],
    } as DashboardConfig;
    const { latestMapLayers } = renderViewer([clustered, layer(roadsId, 'Roads')], selector);
    const boxes = await screen.findAllByRole('checkbox');

    await user.click(boxes[0]);
    await user.click(boxes[1]);
    const filtered = latestMapLayers()[0].filter;
    expect(filtered).toEqual(['in', ['get', 'land_use'], ['literal', [long('a'), long('b')]]]);

    // Three values are about 3,700 characters of CQL2, within the route's 4,096,
    // but the URL with the columns no longer fits nginx's 8 KiB request line.
    await user.click(boxes[2]);
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent("Too many values to filter this layer's clusters. Pick fewer."),
    );
    expect(latestMapLayers()[0].filter).toEqual(filtered);
    expect(boxes[2]).not.toBeChecked();
  });

  it('offers picks on a server-clustered layer only once the map\'s tile config has loaded', async () => {
    let loadTileConfig: (config: TileConfig) => void = () => {};
    vi.mocked(getTileConfig).mockReturnValue(new Promise((resolve) => (loadTileConfig = resolve)));
    const clustered = {
      ...layer(parcelsId, 'Parcels'),
      geometry_type: 'POINT',
      feature_count: 20_000,
      style_config: { render_mode: 'cluster' },
    } as SharedLayerResponse;
    renderViewer([clustered, layer(roadsId, 'Roads')]);
    const chart = await screen.findByRole('group', { name: 'Count by land_use' });
    expect(chart).toHaveAccessibleDescription('Use the arrow keys to move between bars.');

    loadTileConfig(TILE_CONFIG);
    await waitFor(() => expect(chart).toHaveAccessibleDescription(/Press Enter to filter the map by a bar/));
  });

  it('applies a pick with Enter on the focused bar', async () => {
    renderViewer([layer(parcelsId, 'Parcels'), layer(roadsId, 'Roads')]);
    const chart = await screen.findByRole('group', { name: 'Count by land_use' });
    fireEvent.focus(chart);
    fireEvent.keyDown(chart, { key: 'Enter' });
    await waitFor(() => expect(bodiesFor('count')).toContainEqual({ op: 'count', filter: residential }));
  });

  it('combines a pick with the layer’s saved filter, on the map and in the numbers', async () => {
    const saved: FilterSpecification = ['==', ['get', 'zone'], 'A'];
    const { latestMapLayers } = renderViewer([layer(parcelsId, 'Parcels', saved), layer(roadsId, 'Roads')]);
    await clickBar('Residential');

    await waitFor(() =>
      expect(bodiesFor('count')).toContainEqual({
        op: 'count',
        filter: { op: 'and', args: [{ op: '=', args: [{ property: 'zone' }, 'A'] }, residential] },
      }),
    );
    // The chart reads the saved filter alone.
    expect(bodiesFor('value_counts').at(-1)).toMatchObject({ filter: { op: '=', args: [{ property: 'zone' }, 'A'] } });
    expect(latestMapLayers()[0].filter).toEqual(['all', saved, ['in', ['get', 'land_use'], ['literal', ['Residential']]]]);
  });

  it('still filters by the pick when the saved filter is one the numbers can’t use', async () => {
    const opaque: FilterSpecification = ['>', ['length', ['get', 'zone']], 3];
    const { latestMapLayers } = renderViewer([layer(parcelsId, 'Parcels', opaque), layer(roadsId, 'Roads')]);
    await clickBar('Residential');

    await waitFor(() => expect(bodiesFor('count')).toContainEqual({ op: 'count', filter: residential }));
    const parcelsCount = screen.getByRole('article', { name: 'Parcels' });
    expect(within(parcelsCount).getByText("Applies your filters, but not the layer's own filter, which can't be applied to these numbers.")).toBeInTheDocument();
    // The chart that made the pick isn't filtered by it, so it still shows all features.
    const chartCard = screen.getByRole('article', { name: 'Land use' });
    expect(within(chartCard).getByText(/^Shows all features/)).toBeInTheDocument();
    expect(latestMapLayers()[0].filter).toEqual(['all', opaque, ['in', ['get', 'land_use'], ['literal', ['Residential']]]]);
  });

  it('refuses a pick the server can’t filter on and says so', async () => {
    const { latestMapLayers } = renderViewer(
      [layer(parcelsId, 'Parcels'), layer(roadsId, 'Roads')],
      dashboard('opened'),
    );
    const chart = await screen.findByRole('group', { name: 'Count by opened' });
    const bar = [...chart.querySelectorAll('g[aria-hidden="true"]')].find((g) => g.textContent?.includes('2024'));
    fireEvent.click(bar!);

    const status = screen.getByRole('status');
    await waitFor(() => expect(status).toHaveTextContent('“2024-03-01 17:00:00+00” can\'t be used as a filter.'));
    expect(screen.queryByRole('group', { name: 'Filters' })).not.toBeInTheDocument();
    expect(latestMapLayers()[0].filter).toBeNull();

    // The same refusal again is spoken again: the region empties and refills.
    const writes: string[] = [];
    const observer = new MutationObserver(() => writes.push(status.textContent ?? ''));
    observer.observe(status, { childList: true, characterData: true, subtree: true });
    fireEvent.click(bar!);
    await waitFor(() => expect(writes.at(-1)).toContain("can't be used as a filter"));
    observer.disconnect();
    expect(writes).toContain('');
  });

  it('offers picks only on columns the map\'s features carry', async () => {
    const pickHint = /Press Enter to filter the map by a bar/;
    const chartFor = async (changes: Partial<SharedLayerResponse>) => {
      const view = render(
        <ViewerWithDashboard config={dashboard()} layers={[{ ...layer(parcelsId, 'Parcels'), ...changes }, layer(roadsId, 'Roads')]}>
          {() => <div />}
        </ViewerWithDashboard>,
      );
      const chart = await screen.findByRole('group', { name: 'Count by land_use' });
      const description = chart.getAttribute('aria-describedby');
      const hint = document.getElementById(description ?? '')?.textContent ?? '';
      view.unmount();
      return pickHint.test(hint);
    };

    // The tiles carry only the allowlist, so a pick on another column would hide every feature.
    expect(await chartFor({ dataset_tile_columns: ['zone'] })).toBe(false);
    expect(await chartFor({ dataset_tile_columns: ['zone', 'land_use'] })).toBe(true);
    expect(await chartFor({ dataset_tile_columns: null })).toBe(true);
    // A small clustered point layer loads every property as GeoJSON, whatever the allowlist.
    expect(
      await chartFor({
        dataset_tile_columns: [],
        geometry_type: 'POINT',
        feature_count: 100,
        style_config: { render_mode: 'cluster' },
      }),
    ).toBe(true);
  });

  it('offers no picks on a column the server can’t filter on', async () => {
    const config = {
      version: 1,
      widgets: [
        {
          id: chartId,
          type: 'histogram',
          v: 1,
          title: 'Price',
          layer_id: parcelsId,
          config: { column: 'price', bins: 5 },
        },
        {
          id: countId,
          type: 'category_selector',
          v: 1,
          title: 'Lease',
          layer_id: parcelsId,
          config: { column: 'lease', multiple: true },
        },
      ],
    } as DashboardConfig;
    fetchMock.mockImplementation(async (_dataset, body) =>
      (body.op === 'histogram'
        ? { op: 'histogram', approximate: false, cached: false, result: { bins: [{ lower: 0, upper: 1, count: 2 }] } }
        : { op: 'value_counts', approximate: false, cached: false, result: { values: [{ value: '1 year', count: 2 }], other_count: 0 } }) as never,
    );
    renderViewer([layer(parcelsId, 'Parcels'), layer(roadsId, 'Roads')], config);

    const histogram = await screen.findByRole('group', { name: 'Distribution of price' });
    expect(histogram).toHaveAccessibleDescription('Use the arrow keys to move between bins.');
    expect(await screen.findByRole('checkbox', { name: '1 year' })).toBeDisabled();
  });

  it('keeps picks while the right panel is collapsed and counts them on its toggle', async () => {
    const user = userEvent.setup();
    const parcels = layer(parcelsId, 'Parcels');
    const { latestMapLayers } = renderViewer([parcels, layer(roadsId, 'Roads')]);
    await clickBar('Commercial');
    const filtered = latestMapLayers()[0];
    expect(filtered).not.toBe(parcels);

    await user.click(screen.getByRole('button', { name: 'Hide dashboard' }));
    expect(screen.queryByRole('article')).not.toBeInTheDocument();
    expect(latestMapLayers()[0].filter).toEqual(filtered.filter);
    // The rail stays narrow: no chips, a count on the toggle instead.
    expect(screen.queryByRole('group', { name: 'Filters' })).not.toBeInTheDocument();
    const toggle = screen.getByRole('button', { name: 'Open dashboard, 1 filter applied' });
    expect(within(toggle).getByText('1', { exact: true })).toHaveAttribute('aria-hidden', 'true');

    await user.click(toggle);
    const chip = screen.getByRole('button', { name: 'Remove filter land_use: Commercial on Parcels' });
    await user.click(chip);
    expect(latestMapLayers()[0]).toBe(parcels);
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Hide dashboard' }));
  });

  it('keeps the chips in the header row of a collapsed bottom panel', async () => {
    const user = userEvent.setup();
    const parcels = layer(parcelsId, 'Parcels');
    const { latestMapLayers } = renderViewer([parcels, layer(roadsId, 'Roads')], { ...dashboard(), panel: 'bottom' });
    await clickBar('Commercial');

    await user.click(screen.getByRole('button', { name: 'Hide dashboard' }));
    expect(screen.getByRole('button', { name: 'Open dashboard' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Remove filter land_use: Commercial on Parcels' }));
    expect(latestMapLayers()[0]).toBe(parcels);
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Open dashboard' }));
  });
});
