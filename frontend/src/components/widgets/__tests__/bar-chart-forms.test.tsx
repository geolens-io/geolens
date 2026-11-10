import { fireEvent, render, screen, within } from '@testing-library/react';
import BarChartRenderer from '../bar-chart/BarChartRenderer';
import { BarChartFallback } from '../bar-chart/BarChartFallback';
import type { BarChartConfig } from '../bar-chart/definition';
import { LayerColorsProvider } from '../layer-colors';

const envelope = { approximate: false, cached: false };
const colors = {
  column: 'kind',
  colorOf: (key: unknown) => ({ park: '#00aa00', road: '#aa0000' })[String(key) as 'park' | 'road'],
};

const category: BarChartConfig = { column: 'kind', stat: 'count', stat_column: null, limit: 10 };
const categoryData = {
  ...envelope,
  op: 'value_counts',
  result: {
    values: [
      { value: 'park', count: 5 },
      { value: 'road', count: 3 },
      { value: 'lot', count: 1 },
    ],
    other_count: 0,
  },
};
const bars = (container: HTMLElement) => [...container.querySelectorAll('svg rect')] as SVGElement[];

describe('layer colours on a category bar chart', () => {
  it("draws each bar in the layer's colour for its value, theme colour where it has none", () => {
    const { container } = render(
      <LayerColorsProvider value={colors}>
        <BarChartRenderer config={category} data={categoryData} />
      </LayerColorsProvider>,
    );
    const drawn = bars(container);
    expect(drawn.map((bar) => bar.style.fill)).toEqual(['rgb(0, 170, 0)', 'rgb(170, 0, 0)', '']);
    expect(drawn[2].getAttribute('class')).toContain('fill-primary');
    expect(drawn[0].getAttribute('class')).not.toContain('fill-primary');
  });

  it('keeps theme colours when the chart groups by another column than the style column', () => {
    const { container } = render(
      <LayerColorsProvider value={colors}>
        <BarChartRenderer config={{ ...category, column: 'zone' }} data={categoryData} />
      </LayerColorsProvider>,
    );
    expect(bars(container).map((bar) => bar.style.fill)).toEqual(['', '', '']);
  });

  it('keeps theme colours when the author switched layer colours off', () => {
    const { container } = render(
      <LayerColorsProvider value={colors}>
        <BarChartRenderer config={{ ...category, use_layer_colors: false }} data={categoryData} />
      </LayerColorsProvider>,
    );
    expect(bars(container).map((bar) => bar.style.fill)).toEqual(['', '', '']);
  });
});

describe('bar chart by feature', () => {
  const config: BarChartConfig = {
    mode: 'by_feature',
    label_column: 'name',
    value_column: 'height',
    sort: 'desc',
    limit: 3,
  };
  const row = (gid: number, name: string, height: number | null) => ({ gid, values: { name, height } });
  const data = (hasMore: boolean) => ({
    ...envelope,
    op: 'rows',
    result: { rows: [row(1, 'Tower', 300), row(2, 'Hall', 40), row(3, 'Shed', null)], next_cursor: null, has_more: hasMore },
  });

  it('draws one bar per feature, labelled by the label field', () => {
    render(<BarChartRenderer config={config} data={data(false)} />);
    const chart = screen.getByRole('group', { name: 'height by name' });
    fireEvent.focus(chart);
    const readout = { selector: 'figcaption span' };
    expect(screen.getByText('Tower: 300', readout)).toBeInTheDocument();
    fireEvent.keyDown(chart, { key: 'End' });
    expect(screen.getByText('Shed: N/A', readout)).toBeInTheDocument();
  });

  it('says when the layer has more features than the bars show', () => {
    const { rerender } = render(<BarChartRenderer config={config} data={data(false)} />);
    expect(screen.queryByText(/The layer has more/)).toBeNull();
    rerender(<BarChartRenderer config={config} data={data(true)} />);
    expect(screen.getByText('Showing 3 features. The layer has more.')).toBeInTheDocument();
  });

  it('picks the feature label, and lists the features in its table', () => {
    const onSelect = vi.fn();
    render(<BarChartRenderer config={config} data={data(false)} onSelect={onSelect} />);
    const chart = screen.getByRole('group', { name: 'height by name' });
    fireEvent.focus(chart);
    fireEvent.keyDown(chart, { key: 'Enter' });
    expect(onSelect).toHaveBeenCalledWith({ column: 'name', label: 'Tower', values: ['Tower'] });
    const table = screen.getByRole('table', { name: 'height by name' });
    expect(within(table).getAllByRole('row').slice(1).map((r) => r.textContent)).toEqual(['Tower300', 'Hall40', 'ShedN/A']);
  });

  it('draws no more bars than its limit when a shared request holds more rows, and says there are more', () => {
    const shared = {
      ...envelope,
      op: 'rows',
      result: {
        rows: [row(1, 'Tower', 300), row(2, 'Hall', 40), row(3, 'Shed', 9), row(4, 'Barn', 8)],
        next_cursor: null,
        has_more: false,
      },
    };
    const { container } = render(<BarChartRenderer config={{ ...config, limit: 2 }} data={shared} />);
    expect(container.querySelectorAll('svg rect')).toHaveLength(2);
    expect(screen.getByText('Showing 2 features. The layer has more.')).toBeInTheDocument();
  });

  it('says so in the table alternative when there are more features', () => {
    render(<BarChartFallback config={config} data={data(true)} />);
    expect(screen.getByText('Showing 3 features. The layer has more.')).toBeInTheDocument();
  });
});

describe('bar chart by field', () => {
  const config: BarChartConfig = { mode: 'by_fields', fields: ['height', 'area'], stat: 'sum' };
  const data = {
    ...envelope,
    op: 'stats_by_fields',
    result: {
      fields: [
        { column: 'height', stats: { sum: 340 } },
        { column: 'area', stats: { sum: 1200 } },
      ],
    },
  };

  it('draws one bar per field with the statistic as its value, and lists them in a table', () => {
    render(<BarChartRenderer config={config} data={data} columnLabel={(c) => (c === 'area' ? 'Area (m²)' : c)} />);
    const table = screen.getByRole('table', { name: 'Sum by field' });
    expect(within(table).getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual(['Field', 'Sum']);
    expect(within(table).getAllByRole('row').slice(1).map((r) => r.textContent)).toEqual(['height340', 'Area (m²)1,200']);
  });

  it('is read-only: its bars are not values to pick', () => {
    const onSelect = vi.fn();
    render(<BarChartRenderer config={config} data={data} onSelect={onSelect} />);
    const chart = screen.getByRole('group', { name: 'Sum by field' });
    expect(chart).toHaveAccessibleDescription('Use the arrow keys to move between bars.');
    fireEvent.focus(chart);
    fireEvent.keyDown(chart, { key: 'Enter' });
    expect(onSelect).not.toHaveBeenCalled();
  });
});

describe('bar chart by date', () => {
  const config: BarChartConfig = { mode: 'date', column: 'built', date_bucket: 'month', stat: 'count', stat_column: null, limit: 3 };
  const group = (key: string | null, value: number) => ({ key, value });
  const data = (truncated = false) => ({
    ...envelope,
    op: 'group_by',
    result: {
      groups: [group('2026-02-01T00:00:00Z', 4), group('2026-03-01T00:00:00Z', 7), group(null, 1)],
      truncated,
    },
  });

  it('labels each bucket by its UTC start and says the axis is in UTC', () => {
    render(<BarChartRenderer config={config} data={data()} />);
    const table = screen.getByRole('table', { name: 'Count by month (UTC)' });
    expect(within(table).getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual(['built', 'Count']);
    // 2026-03-01T00:00Z is still March 1 for a reader west of UTC.
    expect(within(table).getAllByRole('row').slice(1).map((r) => r.textContent)).toEqual([
      'Feb 20264',
      'Mar 20267',
      '(no value)1',
    ]);
  });

  it('names a week by its first day', () => {
    const weekly: BarChartConfig = { ...config, date_bucket: 'week' } as BarChartConfig;
    render(
      <BarChartFallback
        config={weekly}
        data={{ ...data(), result: { groups: [group('2026-03-02T00:00:00Z', 2)], truncated: false } }}
      />,
    );
    expect(screen.getByText('Mar 2, 2026')).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Count by week (UTC)' })).toBeInTheDocument();
  });

  it('says UTC once even when the column label already does', () => {
    render(<BarChartRenderer config={config} data={data()} columnLabel={() => 'Time (UTC)'} />);
    const table = screen.getByRole('table', { name: 'Count by month (UTC)' });
    expect(within(table).getAllByRole('columnheader')[0]).toHaveTextContent(/^Time \(UTC\)$/);
  });

  it('says when the layer has more periods', () => {
    render(<BarChartRenderer config={config} data={data(true)} />);
    expect(screen.getByText('Showing the first 3 periods. The layer has more.')).toBeInTheDocument();
  });
});
