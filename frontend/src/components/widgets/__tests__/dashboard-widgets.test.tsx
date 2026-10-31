import { fireEvent, render, screen, within } from '@testing-library/react';
import BarChartRenderer from '../bar-chart/BarChartRenderer';
import { BarChartFallback } from '../bar-chart/BarChartFallback';
import { barChartWidget } from '../bar-chart/definition';
import type { BarChartConfig } from '../bar-chart/definition';
import IndicatorRenderer from '../indicator/IndicatorRenderer';
import { indicatorWidget } from '../indicator/definition';
import { parseStoredWidget } from '../registry';

const id = '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11';
const layerId = '0b7d2f4e-3c1a-4e8b-9f6d-5a2c7e1b9d34';

describe('dashboard widget instances', () => {
  const instance = { id, type: 'indicator', v: 1, layer_id: layerId, config: { stat: 'count' } };

  it('need a layer id and default to the whole layer', () => {
    expect(parseStoredWidget(instance, 'dashboard')).toMatchObject({
      ok: true,
      instance: { layer_id: layerId, scope: 'layer', config: { stat: 'count', column: null } },
    });
    const { layer_id: _layer, ...withoutLayer } = instance;
    expect(parseStoredWidget(withoutLayer, 'dashboard')).toEqual({ ok: false, reason: 'malformed' });
    expect(parseStoredWidget({ ...instance, layer_id: 'layer-1' }, 'dashboard')).toEqual({
      ok: false,
      reason: 'malformed',
    });
  });

  it('accept the view scope and refuse any other', () => {
    expect(parseStoredWidget({ ...instance, scope: 'view' }, 'dashboard')).toMatchObject({
      ok: true,
      instance: { scope: 'view' },
    });
    expect(parseStoredWidget({ ...instance, scope: 'map' }, 'dashboard')).toEqual({
      ok: false,
      reason: 'malformed',
    });
  });

  it('are not story blocks', () => {
    expect(parseStoredWidget(instance, 'story')).toEqual({ ok: false, reason: 'malformed' });
    const { layer_id: _layer, ...block } = instance;
    expect(parseStoredWidget(block, 'story')).toEqual({ ok: false, reason: 'unknown_type' });
  });
});

describe('indicator widget', () => {
  it('parses configs as the server does', () => {
    const parse = (config: unknown) => indicatorWidget.parseConfig(config, 1);
    expect(parse({ stat: 'count', column: null })).toEqual({ stat: 'count', column: null });
    expect(parse({ stat: 'max', column: 'height' })).toEqual({ stat: 'max', column: 'height' });
    expect(parse({ stat: 'max', column: 'x'.repeat(63) })).not.toBeNull();
    for (const bad of [
      { stat: 'count', column: 'height' },
      { stat: 'sum' },
      { stat: 'sum', column: '' },
      { stat: 'sum', column: 'x'.repeat(64) },
      { stat: 'median', column: 'height' },
      { stat: 'count', extra: 1 },
    ]) {
      expect(parse(bad)).toBeNull();
    }
  });

  it('asks the aggregate endpoint for a count or one statistic', () => {
    const request = indicatorWidget.dataRequest!;
    expect(request({ stat: 'count', column: null })).toEqual({ op: 'count' });
    expect(request({ stat: 'mean', column: 'height' })).toEqual({
      op: 'stats',
      column: 'height',
      stats: ['avg'],
    });
  });

  it('shows the value in the reader’s locale with its label', () => {
    const { rerender } = render(
      <IndicatorRenderer
        config={{ stat: 'count', column: null }}
        data={{ op: 'count', approximate: false, cached: false, result: { count: 12345 } }}
      />,
    );
    expect(screen.getByText('12,345')).toBeInTheDocument();
    expect(screen.getByText('Count')).toBeInTheDocument();

    rerender(
      <IndicatorRenderer
        config={{ stat: 'mean', column: 'height' }}
        data={{ op: 'stats', approximate: false, cached: false, result: { avg: 2.5 } }}
      />,
    );
    expect(screen.getByText('2.5')).toBeInTheDocument();
    expect(screen.getByText('Average of height')).toBeInTheDocument();

    rerender(
      <IndicatorRenderer
        config={{ stat: 'sum', column: 'id' }}
        data={{ op: 'stats', approximate: false, cached: false, result: { sum: '9007199254740993' } }}
      />,
    );
    expect(screen.getByText('9,007,199,254,740,993')).toBeInTheDocument();
  });

  it('says there is no data before the host fetches it', () => {
    render(<IndicatorRenderer config={{ stat: 'count', column: null }} />);
    expect(screen.getByText('No data yet')).toBeInTheDocument();
  });
});

const chart: BarChartConfig = { column: 'land_use', stat: 'count', stat_column: null, limit: 3 };
const counts = {
  op: 'value_counts',
  approximate: false,
  cached: false,
  result: {
    values: [
      { value: 'Residential', count: 40 },
      { value: 'Commercial', count: 25 },
      { value: null, count: 5 },
    ],
    other_count: 7,
  },
};

describe('bar chart widget', () => {
  it('starts a new chart on a text column that is not an identifier', () => {
    const initial = barChartWidget.initialConfig!;
    const columns = [
      { name: 'objectid', type: 'integer' },
      { name: 'ID', type: 'character varying' },
      { name: 'GlobalID', type: 'character varying' },
      { name: 'event_id', type: 'text' },
      { name: 'magtype', type: 'character varying' },
    ];
    expect(initial(columns)).toEqual({ column: 'magtype' });
    // Only identifiers left: the first text column still beats a number.
    expect(initial(columns.slice(0, 4))).toEqual({ column: 'ID' });
  });

  it('prefers a text column whose sample shows few categories', () => {
    const initial = barChartWidget.initialConfig!;
    const tenPlaces = Array.from({ length: 10 }, (_, index) => `${index} km N of Somewhere`);
    const columns = [
      { name: 'place', type: 'text', samples: tenPlaces },
      // One value makes no chart.
      { name: 'status', type: 'text', samples: ['reviewed'] },
      { name: 'magType', type: 'text', samples: ['md', 'ml', 'mb'] },
    ];
    // The sample holds at most ten values, so ten tells nothing.
    expect(initial(columns)).toEqual({ column: 'magType' });
    // Without samples, the first text column that isn't an identifier.
    expect(initial(columns.map(({ samples: _samples, ...column }) => column))).toEqual({ column: 'place' });
    expect(initial(columns.slice(0, 1))).toEqual({ column: 'place' });
  });

  it('parses configs as the server does', () => {
    const parse = (config: unknown) => barChartWidget.parseConfig(config, 1);
    expect(parse({ column: 'kind' })).toEqual({ column: 'kind', stat: 'count', stat_column: null, limit: 10 });
    for (const bad of [
      {},
      { column: 'kind', stat: 'count', stat_column: 'area' },
      { column: 'kind', stat: 'sum' },
      { column: 'kind', limit: 0 },
      { column: 'kind', limit: 51 },
      { column: 'kind', limit: 2.5 },
      { column: 'kind', colour: 'red' },
    ]) {
      expect(parse(bad)).toBeNull();
    }
  });

  it('asks for value counts, or a statistic grouped by the column', () => {
    const request = barChartWidget.dataRequest!;
    expect(request(chart)).toEqual({ op: 'value_counts', column: 'land_use', limit: 3 });
    expect(request({ ...chart, stat: 'mean', stat_column: 'area' })).toEqual({
      op: 'group_by',
      group_column: 'land_use',
      stat: 'avg',
      column: 'area',
      limit: 3,
    });
  });

  it('is one tab stop, and arrow keys, Home and End move between bars', () => {
    render(<BarChartRenderer config={chart} data={counts} />);
    const svg = screen.getByRole('group', { name: 'Count by land_use' });
    expect(svg).toHaveAttribute('aria-roledescription', 'bar chart');
    expect(svg).toHaveAttribute('tabindex', '0');
    expect(svg).toHaveAccessibleDescription('Use the arrow keys to move between bars.');
    expect(document.querySelectorAll('[tabindex]')).toHaveLength(1);

    fireEvent.focus(svg);
    expect(screen.getByText('Residential: 40', { selector: 'figcaption span' })).toBeInTheDocument();
    fireEvent.keyDown(svg, { key: 'ArrowRight' });
    expect(screen.getByText('Commercial: 25', { selector: 'figcaption span' })).toBeInTheDocument();
    fireEvent.keyDown(svg, { key: 'End' });
    expect(screen.getByText('(no value): 5', { selector: 'figcaption span' })).toBeInTheDocument();
    fireEvent.keyDown(svg, { key: 'ArrowDown' });
    expect(screen.getByText('(no value): 5', { selector: 'figcaption span' })).toBeInTheDocument();
    fireEvent.keyDown(svg, { key: 'Home' });
    expect(screen.getByText('Residential: 40', { selector: 'figcaption span' })).toBeInTheDocument();
  });

  it('draws bars in theme colours, scaled to the largest, with an outline on the active one', () => {
    const { container } = render(<BarChartRenderer config={chart} data={counts} />);
    const bars = [...container.querySelectorAll('svg rect')];
    expect(bars).toHaveLength(3);
    expect(bars.every((bar) => bar.getAttribute('class')?.includes('fill-primary'))).toBe(true);
    const widths = bars.map((bar) => Number(bar.getAttribute('width')));
    expect(widths[0]).toBeGreaterThan(widths[1]);
    expect(widths[1]).toBeGreaterThan(widths[2]);

    fireEvent.focus(screen.getByRole('group', { name: 'Count by land_use' }));
    expect(bars[0]).toHaveAttribute('stroke-width', '2');
    expect(bars[1]).toHaveAttribute('stroke-width', '0');
  });

  it('draws negative values left of a zero baseline, scaled by magnitude', () => {
    const grouped = { ...chart, stat: 'sum' as const, stat_column: 'change' };
    const result = (values: number[]) => ({
      op: 'group_by',
      approximate: false,
      cached: false,
      result: { groups: values.map((value, i) => ({ key: `k${i}`, value })) },
    });
    const bars = (values: number[]) => {
      const { container, unmount } = render(<BarChartRenderer config={grouped} data={result(values)} />);
      const rects = [...container.querySelectorAll('svg rect')].map((rect) => ({
        x: Number(rect.getAttribute('x')),
        width: Number(rect.getAttribute('width')),
      }));
      const line = container.querySelector('svg line');
      const zero = line === null ? null : Number(line.getAttribute('x1'));
      unmount();
      return { rects, zero };
    };

    const mixed = bars([50, -5, -100]);
    expect(mixed.zero).not.toBeNull();
    const [positive, small, large] = mixed.rects;
    expect(positive.x).toBeCloseTo(mixed.zero!);
    expect(small.x + small.width).toBeCloseTo(mixed.zero!);
    expect(large.x + large.width).toBeCloseTo(mixed.zero!);
    expect(large.width).toBeGreaterThan(positive.width);
    expect(positive.width).toBeGreaterThan(small.width);
    expect(large.width / small.width).toBeCloseTo(20);

    const negative = bars([-5, -100]);
    expect(negative.rects[1].width / negative.rects[0].width).toBeCloseTo(20);
    for (const rect of negative.rects) expect(rect.x + rect.width).toBeCloseTo(negative.zero!);

    expect(bars([40, 25]).zero).toBeNull();
  });

  it('shows a clipped label in full on hover', () => {
    const long = {
      ...counts,
      result: {
        values: [
          { value: 'Mixed use residential north', count: 40 },
          { value: 'Mixed use residential south', count: 25 },
        ],
        other_count: 0,
      },
    };
    const { container } = render(<BarChartRenderer config={chart} data={long} />);
    const labels = [...container.querySelectorAll('svg g > text')].map((node) => node.textContent);
    expect(labels).toContain('Mixed use resid…');
    const titles = [...container.querySelectorAll('svg g > title')].map((node) => node.textContent);
    expect(titles).toEqual(['Mixed use residential north: 40', 'Mixed use residential south: 25']);
  });

  it('offers the data as a table, with the rows the top N leaves out', () => {
    render(<BarChartFallback config={chart} data={counts} />);
    const table = screen.getByRole('table', { name: 'Count by land_use' });
    expect(within(table).getByRole('columnheader', { name: 'land_use' })).toBeInTheDocument();
    expect(within(table).getByRole('columnheader', { name: 'Count' })).toBeInTheDocument();
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows.map((row) => row.textContent)).toEqual([
      'Residential40',
      'Commercial25',
      '(no value)5',
      'Other7',
    ]);
  });

  it('reads grouped statistics and shows no data before the host fetches it', () => {
    const grouped = { ...chart, stat: 'sum' as const, stat_column: 'area' };
    render(
      <BarChartFallback
        config={grouped}
        data={{
          op: 'group_by',
          approximate: false,
          cached: false,
          result: { groups: [{ key: 2024, value: 1500.25 }] },
        }}
      />,
    );
    expect(screen.getByRole('table', { name: 'Sum of area by land_use' })).toBeInTheDocument();
    expect(screen.getByRole('row', { name: '2024 1,500.25' })).toBeInTheDocument();

    render(<BarChartRenderer config={chart} />);
    expect(screen.getByText('No data yet')).toBeInTheDocument();
  });

  it('picks a bar with Enter or a click, marks it, and clears it when picked again', () => {
    const onSelect = vi.fn();
    const { container, rerender } = render(<BarChartRenderer config={chart} data={counts} onSelect={onSelect} />);
    const svg = screen.getByRole('group', { name: 'Count by land_use' });
    expect(svg).toHaveAccessibleDescription(/Press Enter to filter the map by a bar/);

    fireEvent.focus(svg);
    fireEvent.keyDown(svg, { key: 'ArrowDown' });
    fireEvent.keyDown(svg, { key: 'Enter' });
    expect(onSelect).toHaveBeenLastCalledWith({ column: 'land_use', label: 'Commercial', values: ['Commercial'] });
    fireEvent.click(container.querySelectorAll('svg g[aria-hidden="true"]')[2]);
    expect(onSelect).toHaveBeenLastCalledWith({ column: 'land_use', label: '(no value)', values: [null] });

    const picked = { column: 'land_use', label: 'Commercial', values: ['Commercial'] };
    rerender(<BarChartRenderer config={chart} data={counts} selection={picked} onSelect={onSelect} />);
    const bars = [...container.querySelectorAll('svg rect')];
    expect(bars[1].getAttribute('class')).not.toContain('opacity-75');
    expect(bars[0].getAttribute('class')).toContain('opacity-75');
    expect(container.querySelector('[data-picked]')).toHaveTextContent(/✓Commercial/);
    expect(screen.getByRole('rowheader', { name: /Commercial/ })).toHaveTextContent('Commercial✓ (picked)');
    fireEvent.keyDown(svg, { key: 'Home' });
    fireEvent.keyDown(svg, { key: 'ArrowDown' });
    fireEvent.keyDown(svg, { key: ' ' });
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it('ignores Enter where the host does not link widgets', () => {
    const { container } = render(<BarChartRenderer config={chart} data={counts} />);
    const svg = screen.getByRole('group', { name: 'Count by land_use' });
    fireEvent.focus(svg);
    fireEvent.keyDown(svg, { key: 'Enter' });
    expect(container.querySelector('[data-picked]')).toBeNull();
    expect(container.querySelector('svg g.cursor-pointer')).toBeNull();
  });

  it('says there is no data when the result has no rows', () => {
    const empty = { ...counts, result: { values: [], other_count: 0 } };
    render(<BarChartRenderer config={chart} data={empty} />);
    expect(screen.getByText('No data')).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Count by land_use' })).toBeNull();
    expect(screen.queryByRole('table')).toBeNull();
  });
});
