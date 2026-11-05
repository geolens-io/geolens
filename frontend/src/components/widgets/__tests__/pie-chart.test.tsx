import { fireEvent, render, screen, within } from '@testing-library/react';
import { LayerColorsProvider } from '../layer-colors';
import { pieChartWidget, type PieChartConfig } from '../pie-chart/definition';
import { PieChartFallback } from '../pie-chart/PieChartFallback';
import { arcPath, pieArcs } from '../pie-chart/pie-geometry';
import PieChartRenderer from '../pie-chart/PieChartRenderer';

const config: PieChartConfig = { column: 'kind', stat: 'count', stat_column: null, limit: 2, use_layer_colors: true };
const data = {
  op: 'value_counts',
  approximate: false,
  cached: false,
  result: {
    values: [
      { value: 'park', count: 50 },
      { value: 'road', count: 30 },
    ],
    other_count: 20,
  },
};

describe('pie chart config', () => {
  const parse = (raw: unknown) => pieChartWidget.parseConfig(raw, 1);

  it('reads configs as the server stores them, filling its defaults', () => {
    expect(parse({ column: 'kind' })).toEqual({ column: 'kind', stat: 'count', stat_column: null, limit: 10, use_layer_colors: true });
    expect(parse({ ...config, stat: 'sum', stat_column: 'area', use_layer_colors: false })).toMatchObject({
      stat: 'sum',
      stat_column: 'area',
      use_layer_colors: false,
    });
    for (const bad of [
      {},
      { ...config, limit: 0 },
      { ...config, limit: 51 },
      { ...config, stat: 'sum' },
      { ...config, stat_column: 'area' },
      { ...config, use_layer_colors: 'yes' },
      { ...config, mode: 'donut' },
    ]) {
      expect(parse(bad)).toBeNull();
    }
  });

  it('asks for the top values with counts, or a statistic grouped by the column', () => {
    expect(pieChartWidget.dataRequest!(config)).toEqual({ op: 'value_counts', column: 'kind', limit: 2 });
    expect(pieChartWidget.dataRequest!({ ...config, stat: 'mean', stat_column: 'area' })).toEqual({
      op: 'group_by',
      group_column: 'kind',
      stat: 'avg',
      column: 'area',
      limit: 2,
    });
    expect(pieChartWidget.picksColumn!(config)).toBe('kind');
  });
});

describe('pie geometry', () => {
  it('divides the circle by value and gives a non-positive value no room', () => {
    const arcs = pieArcs([1, 3, 0, -2, Number.NaN]);
    expect(arcs.map((arc) => arc.share)).toEqual([0.25, 0.75, 0, 0, 0]);
    expect(arcs[1].end).toBeCloseTo(Math.PI * 2);
    expect(arcPath(60, 60, 50, arcs[2])).toBe('');
  });

  it('draws a lone slice as a whole disc', () => {
    const [only] = pieArcs([7]);
    expect(arcPath(60, 60, 50, only).match(/A/g)).toHaveLength(2);
  });
});

describe('PieChartRenderer', () => {
  it('draws a slice per value and an Other slice for the rest, each named with its value and share', () => {
    const { container } = render(<PieChartRenderer config={config} data={data} />);
    expect(container.querySelectorAll('svg[role="group"] path')).toHaveLength(3);
    const legend = screen.getAllByRole('listitem').map((item) => item.textContent);
    expect(legend).toEqual(['park5050%', 'road3030%', 'Other2020%']);
  });

  it('is one tab stop whose arrow keys read out each slice', () => {
    render(<PieChartRenderer config={config} data={data} />);
    const chart = screen.getByRole('group', { name: 'Count by kind' });
    expect(chart).toHaveAttribute('aria-roledescription', 'pie chart');
    expect(chart).toHaveAccessibleDescription('Use the arrow keys to move between slices.');
    expect(document.querySelectorAll('[tabindex]')).toHaveLength(1);
    fireEvent.focus(chart);
    const readout = { selector: 'figcaption span' };
    expect(screen.getByText('park: 50 (50%)', readout)).toBeInTheDocument();
    fireEvent.keyDown(chart, { key: 'End' });
    expect(screen.getByText('Other: 20 (20%)', readout)).toBeInTheDocument();
  });

  it('picks a slice with Enter or a click, and clears the pick when picked again', () => {
    const onSelect = vi.fn();
    const { container, rerender } = render(<PieChartRenderer config={config} data={data} onSelect={onSelect} />);
    const chart = screen.getByRole('group', { name: 'Count by kind' });
    fireEvent.focus(chart);
    fireEvent.keyDown(chart, { key: 'ArrowRight' });
    fireEvent.keyDown(chart, { key: 'Enter' });
    expect(onSelect).toHaveBeenLastCalledWith({ column: 'kind', label: 'road', values: ['road'] });

    fireEvent.click(container.querySelectorAll('svg[role="group"] g')[0]);
    expect(onSelect).toHaveBeenLastCalledWith({ column: 'kind', label: 'park', values: ['park'] });

    const picked = { column: 'kind', label: 'park', values: ['park'] };
    rerender(<PieChartRenderer config={config} data={data} selection={picked} onSelect={onSelect} />);
    const paths = [...container.querySelectorAll('svg[role="group"] path')];
    expect(paths[0].getAttribute('class')).not.toContain('opacity-75');
    expect(paths[1].getAttribute('class')).toContain('opacity-75');
    fireEvent.keyDown(chart, { key: 'Home' });
    fireEvent.keyDown(chart, { key: ' ' });
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it('does not pick Other, which stands for no one value', () => {
    const onSelect = vi.fn();
    const { container } = render(<PieChartRenderer config={config} data={data} onSelect={onSelect} />);
    const chart = screen.getByRole('group', { name: 'Count by kind' });
    fireEvent.focus(chart);
    fireEvent.keyDown(chart, { key: 'End' });
    fireEvent.keyDown(chart, { key: 'Enter' });
    expect(onSelect).not.toHaveBeenCalled();
    expect(container.querySelectorAll('svg[role="group"] g.cursor-pointer')).toHaveLength(2);
  });

  it('marks a picked value in the legend and the table as well as on the slice', () => {
    const picked = { column: 'kind', label: 'park', values: ['park'] };
    render(<PieChartRenderer config={config} data={data} selection={picked} onSelect={vi.fn()} />);
    expect(screen.getAllByRole('listitem')[0]).toHaveTextContent('park');
    expect(screen.getAllByRole('listitem')[0]).toHaveTextContent('(picked)');
    expect(screen.getAllByRole('listitem')[1]).not.toHaveTextContent('(picked)');
  });

  it('leaves out the Other slice when a statistic is grouped, which has no total for it', () => {
    const grouped = {
      op: 'group_by',
      approximate: false,
      cached: false,
      result: { groups: [{ key: 'park', value: 4 }, { key: 'road', value: 4 }], truncated: true },
    };
    const { container } = render(
      <PieChartRenderer config={{ ...config, stat: 'sum', stat_column: 'area' }} data={grouped} />,
    );
    expect(container.querySelectorAll('svg[role="group"] path')).toHaveLength(2);
    expect(screen.queryByText('Other')).toBeNull();
    // The two groups shown are not the whole, so no share is claimed for them.
    expect(screen.getByText(/Showing the top 2 values/)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/%/);
    fireEvent.focus(screen.getByRole('group', { name: /Sum of area by kind/ }));
    expect(screen.getByText('park: 4', { selector: 'figcaption span' })).toBeInTheDocument();
  });

  describe('layer colours', () => {
    const colors = { column: 'kind', colorOf: (key: unknown) => (key === 'park' ? '#00aa00' : undefined) };
    const fills = (config: PieChartConfig, column = 'kind') => {
      const { container } = render(
        <LayerColorsProvider value={{ ...colors, column }}>
          <PieChartRenderer config={config} data={data} />
        </LayerColorsProvider>,
      );
      return [...container.querySelectorAll('svg[role="group"] path')].map((path) => (path as SVGElement).style.fill);
    };

    it("fills a slice with the layer's colour for its value, in the chart and its legend", () => {
      const { container } = render(
        <LayerColorsProvider value={colors}>
          <PieChartRenderer config={config} data={data} />
        </LayerColorsProvider>,
      );
      expect([...container.querySelectorAll('path')].map((path) => (path as SVGElement).style.fill)).toEqual([
        'rgb(0, 170, 0)',
        '',
        '',
      ]);
      expect(container.querySelector('ul rect')).toHaveStyle({ fill: 'rgb(0, 170, 0)' });
    });

    it('uses theme colours for another column, or with the switch off', () => {
      expect(fills(config, 'zone')).toEqual(['', '', '']);
      expect(fills({ ...config, use_layer_colors: false })).toEqual(['', '', '']);
    });
  });

  it('offers a table with Other as its last row', () => {
    render(<PieChartFallback config={config} data={data} />);
    const table = screen.getByRole('table', { name: 'Count by kind' });
    expect(within(table).getAllByRole('row').slice(1).map((row) => row.textContent)).toEqual(['park50', 'road30', 'Other20']);
  });
});
