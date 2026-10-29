import { useState } from 'react';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '@/test/test-utils';
import { fetchAggregate } from '@/api/aggregate';
import type { MapLayerResponse } from '@/types/api';
import { DashboardEditorPanel } from '../DashboardEditorPanel';
import type { DashboardDraft } from '../dashboard-draft';

vi.mock('@/api/aggregate', () => ({ fetchAggregate: vi.fn() }));

// Radix Select reads these, and jsdom doesn't implement them.
Element.prototype.hasPointerCapture = vi.fn(() => false);
Element.prototype.releasePointerCapture = vi.fn();
Element.prototype.scrollIntoView = vi.fn();

const fetchMock = vi.mocked(fetchAggregate);

function layer(overrides: Partial<MapLayerResponse>): MapLayerResponse {
  return {
    dataset_id: 'dataset-1',
    sort_order: 0,
    visible: true,
    opacity: 1,
    paint: {},
    layout: {},
    layer_type: 'vector_geolens',
    dataset_record_type: 'vector_dataset',
    display_name: null,
    show_in_legend: true,
    ...overrides,
  } as MapLayerResponse;
}

const raster = layer({
  id: 'b1c2d3e4-0000-4000-8000-000000000001',
  dataset_name: 'Imagery',
  layer_type: 'raster_geolens',
  dataset_record_type: 'raster_dataset',
});
const parcels = layer({
  id: 'b1c2d3e4-0000-4000-8000-000000000002',
  dataset_name: 'Parcels',
  dataset_geometry_type: 'POLYGON',
  dataset_column_info: [
    { name: 'parcel_id', type: 'integer' },
    { name: 'land_use', type: 'text' },
    { name: 'area', type: 'double precision' },
    // Contains "int", but the aggregate endpoint can't sum it.
    { name: 'lease', type: 'interval' },
  ],
});
const permits = layer({
  id: 'b1c2d3e4-0000-4000-8000-000000000003',
  dataset_name: 'Permits table',
  dataset_record_type: 'table',
  dataset_geometry_type: null,
  dataset_column_info: [{ name: 'status', type: 'text' }],
});

function Harness({
  layers = [raster, parcels],
  initial = { panel: 'right', widgets: [] },
  onChange,
}: {
  layers?: MapLayerResponse[];
  initial?: DashboardDraft;
  onChange: (draft: DashboardDraft) => void;
}) {
  const [draft, setDraft] = useState(initial);
  return (
    <DashboardEditorPanel
      draft={draft}
      layers={layers}
      map={null}
      onChange={(next) => {
        setDraft(next);
        onChange(next);
      }}
    />
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockResolvedValue({
    op: 'count',
    approximate: false,
    cached: false,
    result: { count: 42 },
  } as never);
});

const lastDraft = (spy: ReturnType<typeof vi.fn>) => spy.mock.calls.at(-1)?.[0] as DashboardDraft;

describe('DashboardEditorPanel', () => {
  it('adds a widget on the first layer with rows and previews it', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    await user.click(screen.getByRole('button', { name: 'Add Indicator' }));

    expect(lastDraft(onChange).widgets).toEqual([
      expect.objectContaining({ type: 'indicator', layer_id: parcels.id, scope: 'layer' }),
    ]);
    expect(screen.getByRole('combobox', { name: 'Layer' })).toHaveTextContent('Parcels');
    const preview = screen.getByRole('region', { name: 'Preview' });
    expect(await within(preview).findByText('42')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith('dataset-1', { op: 'count' }, expect.anything());
  });

  it('offers only numeric columns for a statistic other than count', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await user.click(screen.getByRole('button', { name: 'Add Indicator' }));

    await user.click(await screen.findByRole('combobox', { name: 'Statistic' }));
    await user.click(await screen.findByRole('option', { name: 'Sum' }));

    expect(lastDraft(onChange).widgets[0].config).toEqual({ stat: 'sum', column: 'parcel_id' });
    await user.click(await screen.findByRole('combobox', { name: 'Column' }));
    const options = await screen.findAllByRole('option');
    expect(options.map((option) => option.textContent)).toEqual(['parcel_id', 'area']);
    await user.keyboard('{Escape}');

    // Back to count, which reads no column.
    await user.click(screen.getByRole('combobox', { name: 'Statistic' }));
    await user.click(await screen.findByRole('option', { name: 'Count' }));
    expect(lastDraft(onChange).widgets[0].config).toEqual({ stat: 'count', column: null });
  });

  it('starts a bar chart on the layer\'s first text column', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await user.click(screen.getByRole('button', { name: 'Add Bar chart' }));
    expect(lastDraft(onChange).widgets[0].config).toMatchObject({ column: 'land_use', stat: 'count' });
    expect(screen.queryByText(/Pick another before saving/)).not.toBeInTheDocument();
  });

  it('starts each new widget on a column that suits it, using the layer\'s sampled values', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const quakes = layer({
      ...parcels,
      dataset_column_info: [
        { name: 'place', type: 'text' },
        { name: 'mag_type', type: 'text' },
        { name: 'mag', type: 'double precision' },
      ],
      dataset_sample_values: {
        place: Array.from({ length: 10 }, (_, index) => `place ${index}`),
        mag_type: ['md', 'ml'],
      },
    });
    render(<Harness layers={[quakes]} onChange={onChange} />);
    await user.click(screen.getByRole('button', { name: 'Add Bar chart' }));
    await user.click(screen.getByRole('button', { name: 'Add Histogram' }));
    await user.click(screen.getByRole('button', { name: 'Add Category selector' }));
    expect(lastDraft(onChange).widgets.map((widget) => [widget.type, widget.config])).toEqual([
      ['bar_chart', { column: 'mag_type', stat: 'count', stat_column: null, limit: 10 }],
      ['histogram', { column: 'mag', bins: 20 }],
      ['category_selector', { column: 'mag_type', multiple: true }],
    ]);
    expect(screen.queryByText(/Pick another before saving/)).not.toBeInTheDocument();
  });

  it('holds a bar chart on a column its layer lacks until another is picked', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const stale = {
      id: '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11',
      type: 'bar_chart',
      v: 1,
      layer_id: parcels.id,
      scope: 'layer' as const,
      config: { column: 'name', stat: 'count', stat_column: null, limit: 10 },
    };
    render(<Harness initial={{ panel: 'right', widgets: [stale] }} onChange={onChange} />);

    expect(
      screen.getByText('The layer has no column “name”. Pick another before saving.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Preview' })).not.toBeInTheDocument();

    await user.click(await screen.findByRole('combobox', { name: 'Group by' }));
    await user.click(await screen.findByRole('option', { name: 'land_use' }));

    expect(screen.queryByText(/Pick another before saving/)).not.toBeInTheDocument();
    expect(await screen.findByRole('region', { name: 'Preview' })).toBeInTheDocument();
    expect(lastDraft(onChange).widgets[0].config).toMatchObject({ column: 'land_use' });
  });

  it('asks for preview data once the config rests, not on every keystroke', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const chart = {
      id: '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11',
      type: 'bar_chart',
      v: 1,
      layer_id: parcels.id,
      scope: 'layer' as const,
      config: { column: 'land_use', stat: 'count', stat_column: null, limit: 10 },
    };
    render(<Harness initial={{ panel: 'right', widgets: [chart] }} onChange={onChange} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    const bars = await screen.findByRole('spinbutton', { name: 'Bars' });
    await user.clear(bars);
    await user.type(bars, '25');
    expect(lastDraft(onChange).widgets[0].config).toMatchObject({ limit: 25 });

    await waitFor(() =>
      expect(fetchMock).toHaveBeenLastCalledWith(
        'dataset-1',
        { op: 'value_counts', column: 'land_use', limit: 25 },
        expect.anything(),
      ),
    );
    const limits = fetchMock.mock.calls.map(([, body]) => (body as { limit?: number }).limit);
    expect(limits).toEqual([10, 25]);
  });

  it('sets the panel position and orders and removes widgets', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    await user.click(screen.getByRole('combobox', { name: 'Panel position' }));
    await user.click(await screen.findByRole('option', { name: 'Below the map' }));
    expect(lastDraft(onChange).panel).toBe('bottom');

    await user.click(screen.getByRole('button', { name: 'Add Indicator' }));
    await user.click(screen.getByRole('button', { name: 'Add Bar chart' }));
    const [first, second] = lastDraft(onChange).widgets.map((widget) => widget.type);
    expect([first, second]).toEqual(['indicator', 'bar_chart']);

    await user.click(screen.getByRole('button', { name: 'Move Bar chart up' }));
    expect(lastDraft(onChange).widgets.map((widget) => widget.type)).toEqual(['bar_chart', 'indicator']);

    await user.click(screen.getByRole('button', { name: 'Remove Bar chart' }));
    expect(lastDraft(onChange).widgets.map((widget) => widget.type)).toEqual(['indicator']);
  });

  it('offers the map view only on layers with geometry', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<Harness layers={[parcels, permits]} onChange={onChange} />);
    await user.click(screen.getByRole('button', { name: 'Add Indicator' }));

    await user.click(screen.getByRole('combobox', { name: 'Covers' }));
    await user.click(await screen.findByRole('option', { name: "What's in the map view" }));
    expect(lastDraft(onChange).widgets[0].scope).toBe('view');

    // A table can't be bounded by a view, so moving there covers the whole layer.
    await user.click(screen.getByRole('combobox', { name: 'Layer' }));
    await user.click(await screen.findByRole('option', { name: 'Permits table' }));
    expect(lastDraft(onChange).widgets[0]).toMatchObject({ layer_id: permits.id, scope: 'layer' });
    await user.click(screen.getByRole('combobox', { name: 'Covers' }));
    expect((await screen.findAllByRole('option')).map((option) => option.textContent)).toEqual([
      'The whole layer',
    ]);
  });

  it('flags a stored view-scoped widget on a layer without geometry', () => {
    const stored = {
      id: '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11',
      type: 'indicator',
      v: 1,
      layer_id: permits.id,
      scope: 'view' as const,
      config: { stat: 'count', column: null },
    };
    render(<Harness layers={[permits]} initial={{ panel: 'right', widgets: [stored] }} onChange={vi.fn()} />);
    expect(screen.getByText(/can't follow the map view/)).toBeInTheDocument();
  });

  it('stops adding widgets at the dashboard limit', () => {
    const widgets = Array.from({ length: 50 }, (_, index) => ({
      id: `6f1c3a52-8d1e-4a57-9b1f-${String(index).padStart(12, '0')}`,
      type: 'indicator',
      v: 1,
      layer_id: parcels.id,
      scope: 'layer' as const,
      config: { stat: 'count', column: null },
    }));
    render(<Harness initial={{ panel: 'right', widgets }} onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Add Indicator' })).toBeDisabled();
    expect(screen.getByText('A dashboard holds at most 50 widgets.')).toBeInTheDocument();
  });

  it('keeps the preview widget\'s heading under its card\'s', async () => {
    const user = userEvent.setup();
    render(<Harness onChange={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: 'Add Indicator' }));
    const preview = await screen.findByRole('region', { name: 'Preview' });
    expect(within(preview).getByRole('heading', { level: 4 })).toBeInTheDocument();
    expect(within(preview).queryByRole('heading', { level: 3 })).not.toBeInTheDocument();
  });

  it('asks for a layer with rows before offering widgets', async () => {
    render(<Harness layers={[raster]} onChange={vi.fn()} />);
    expect(
      screen.getByText('Add a vector or table layer to the map to give it widgets.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Add / })).not.toBeInTheDocument();
    await waitFor(() => expect(fetchMock).not.toHaveBeenCalled());
  });
});
