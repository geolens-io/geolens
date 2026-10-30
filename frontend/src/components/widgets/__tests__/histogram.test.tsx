import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { histogramWidget, type HistogramConfig } from '../histogram/definition';
import HistogramEditor from '../histogram/HistogramEditor';
import { HistogramFallback } from '../histogram/HistogramFallback';
import HistogramRenderer from '../histogram/HistogramRenderer';
import { selectionCql2 } from '@/components/viewer/linked-filters';
import type { SharedLayerResponse } from '@/types/api';

// Radix Select reads these, and jsdom doesn't implement them.
Element.prototype.hasPointerCapture = vi.fn(() => false);
Element.prototype.releasePointerCapture = vi.fn();
Element.prototype.scrollIntoView = vi.fn();

const config: HistogramConfig = { column: 'height', bins: 3 };
const data = {
  op: 'histogram',
  approximate: false,
  cached: false,
  result: {
    bins: [
      { lower: 0, upper: 10, count: 4 },
      { lower: 10, upper: 20, count: 12 },
      { lower: 20, upper: 30, count: 1 },
    ],
  },
};

describe('histogram widget', () => {
  it('parses configs as the server does', () => {
    const parse = (raw: unknown) => histogramWidget.parseConfig(raw, 1);
    expect(parse({ column: 'height' })).toEqual({ column: 'height', bins: 20 });
    expect(parse({ column: 'height', bins: 50 })).toEqual({ column: 'height', bins: 50 });
    for (const bad of [{}, { column: 'height', bins: 1 }, { column: 'height', bins: 51 }, { column: 'height', bins: 2.5 }, { column: 'height', colour: 'red' }]) {
      expect(parse(bad)).toBeNull();
    }
  });

  it('asks for binned counts of its numeric column', () => {
    expect(histogramWidget.dataRequest!(config)).toEqual({ op: 'histogram', column: 'height', bins: 3 });
    expect(histogramWidget.readsColumns!(config)).toEqual([{ name: 'height', numeric: true }]);
  });

  it('starts on a numeric column that is not an identifier', () => {
    const columns = [
      { name: 'objectid', type: 'integer' },
      { name: 'name', type: 'text' },
      { name: 'mag', type: 'double precision' },
    ];
    expect(histogramWidget.initialConfig!(columns)).toEqual({ column: 'mag' });
    expect(histogramWidget.initialConfig!(columns.slice(0, 2))).toEqual({ column: 'objectid' });
  });

  it('draws a column per bin from a zero baseline, scaled to the largest', () => {
    const { container } = render(<HistogramRenderer config={config} data={data} />);
    const columns = [...container.querySelectorAll('svg rect.fill-primary')];
    expect(columns).toHaveLength(3);
    const heights = columns.map((column) => Number(column.getAttribute('height')));
    expect(heights[1]).toBe(100);
    expect(heights[0]).toBeCloseTo(100 / 3);
    // The axis names the lowest and highest values.
    const axis = [...container.querySelectorAll('svg text')].map((label) => label.textContent);
    expect(axis).toEqual(['0', '30']);
  });

  it('is one tab stop, and arrow keys, Home and End move between bins', () => {
    render(<HistogramRenderer config={config} data={data} />);
    const chart = screen.getByRole('group', { name: 'Distribution of height' });
    expect(chart).toHaveAttribute('aria-roledescription', 'histogram');
    expect(chart).toHaveAccessibleDescription('Use the arrow keys to move between bins.');
    expect(document.querySelectorAll('[tabindex]')).toHaveLength(1);

    fireEvent.focus(chart);
    expect(screen.getByText('0 – 10: 4')).toBeInTheDocument();
    fireEvent.keyDown(chart, { key: 'ArrowRight' });
    expect(screen.getByText('10 – 20: 12')).toBeInTheDocument();
    fireEvent.keyDown(chart, { key: 'End' });
    expect(screen.getByText('20 – 30: 1')).toBeInTheDocument();
    fireEvent.keyDown(chart, { key: 'ArrowLeft' });
    expect(screen.getByText('10 – 20: 12')).toBeInTheDocument();
    fireEvent.keyDown(chart, { key: 'Home' });
    expect(screen.getByText('0 – 10: 4')).toBeInTheDocument();
  });

  it('picks a bin with Enter or a click, and clears it when picked again', () => {
    const onSelect = vi.fn();
    const { container, rerender } = render(<HistogramRenderer config={config} data={data} onSelect={onSelect} />);
    const chart = screen.getByRole('group', { name: 'Distribution of height' });
    expect(chart).toHaveAccessibleDescription(/Press Enter to filter the map to a bin/);

    fireEvent.focus(chart);
    fireEvent.keyDown(chart, { key: 'End' });
    fireEvent.keyDown(chart, { key: 'Enter' });
    // The last bin holds the maximum.
    expect(onSelect).toHaveBeenLastCalledWith({
      column: 'height',
      label: '20 – 30',
      range: { lower: 20, upper: 30, includeUpper: true },
    });

    fireEvent.click(container.querySelectorAll('svg g[aria-hidden="true"]')[0]);
    expect(onSelect).toHaveBeenLastCalledWith({
      column: 'height',
      label: '0 – 10',
      range: { lower: 0, upper: 10, includeUpper: false },
    });

    const picked = { column: 'height', label: '0 – 10', range: { lower: 0, upper: 10, includeUpper: false } };
    rerender(<HistogramRenderer config={config} data={data} selection={picked} onSelect={onSelect} />);
    const columns = [...container.querySelectorAll('svg rect.fill-primary')];
    expect(columns[0].getAttribute('class')).not.toContain('opacity-35');
    expect(columns[1].getAttribute('class')).toContain('opacity-35');
    expect(container.querySelector('[data-picked]')).toHaveTextContent('✓');
    fireEvent.keyDown(chart, { key: 'Home' });
    fireEvent.keyDown(chart, { key: ' ' });
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it('marks every bin a pick made on other bins reaches, after another widget re-bins it', () => {
    const onSelect = vi.fn();
    const marked = (lower: number, upper: number, includeUpper = false) => {
      const selection = { column: 'height', label: 'x', range: { lower, upper, includeUpper } };
      const { container, unmount } = render(
        <HistogramRenderer config={config} data={data} selection={selection} onSelect={onSelect} />,
      );
      const columns = [...container.querySelectorAll('svg g[aria-hidden="true"]')].slice(0, 3);
      const result = columns.map((column) => column.hasAttribute('data-picked'));
      unmount();
      return result;
    };
    expect(marked(2.71, 2.98)).toEqual([true, false, false]);
    expect(marked(8, 12)).toEqual([true, true, false]);
    // A range that stops where a bin starts doesn't reach it, unless it holds its upper edge.
    expect(marked(10, 20)).toEqual([false, true, false]);
    expect(marked(10, 20, true)).toEqual([false, true, true]);
    expect(marked(30, 30, true)).toEqual([false, false, true]);

    // Clicking a marked bin clears the pick.
    const selection = { column: 'height', label: 'x', range: { lower: 2.71, upper: 2.98, includeUpper: false } };
    const { container } = render(<HistogramRenderer config={config} data={data} selection={selection} onSelect={onSelect} />);
    fireEvent.click(container.querySelectorAll('svg g[aria-hidden="true"]')[0]);
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it('ignores Enter and clicks where the host does not link widgets', () => {
    const { container } = render(<HistogramRenderer config={config} data={data} />);
    const chart = screen.getByRole('group', { name: 'Distribution of height' });
    fireEvent.focus(chart);
    fireEvent.keyDown(chart, { key: 'Enter' });
    fireEvent.click(container.querySelectorAll('svg g[aria-hidden="true"]')[0]);
    expect(container.querySelector('[data-picked]')).toBeNull();
    expect(container.querySelector('svg g.cursor-pointer')).toBeNull();
  });

  it('offers its bins as a table with the picked one marked', () => {
    const picked = { column: 'height', label: '10 – 20', range: { lower: 10, upper: 20, includeUpper: false } };
    render(<HistogramFallback config={config} data={data} selection={picked} />);
    const table = screen.getByRole('table', { name: 'Distribution of height' });
    expect(within(table).getAllByRole('columnheader').map((cell) => cell.textContent)).toEqual(['Range', 'Count']);
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows.map((row) => row.textContent)).toEqual(['0 – 104', '10 – 20✓ (picked)12', '20 – 301']);
  });

  it('labels narrow bins with enough decimals to tell them apart', () => {
    const narrow = {
      ...data,
      result: { bins: [{ lower: 0.1, upper: 0.125, count: 2 }, { lower: 0.125, upper: 0.15, count: 3 }] },
    };
    render(<HistogramFallback config={config} data={narrow} />);
    expect(screen.getByText('0.1 – 0.125')).toBeInTheDocument();
    expect(screen.getByText('0.125 – 0.15')).toBeInTheDocument();
  });

  describe('with whole-number bins', () => {
    const visits: HistogramConfig = { column: 'visits', bins: 20 };
    // The server's whole-number bins: [a, a + w) holds a to a + w - 1.
    const bins = (width: number, count: number) => ({
      ...data,
      result: {
        bins: Array.from({ length: count }, (_, index) => ({
          lower: index * width,
          upper: (index + 1) * width,
          count: index + 1,
        })),
        whole_numbers: true,
      },
    });

    it('labels a bin of one whole number by that number', () => {
      render(<HistogramFallback config={visits} data={bins(1, 3)} />);
      expect(screen.getAllByRole('rowheader').map((header) => header.textContent)).toEqual(['0', '1', '2']);
    });

    it('labels a wider bin by the whole numbers it holds', () => {
      render(<HistogramFallback config={visits} data={bins(50, 2)} />);
      expect(screen.getByText('0 – 49')).toBeInTheDocument();
      expect(screen.getByText('50 – 99')).toBeInTheDocument();
    });

    it('labels the axis with the lowest and highest whole numbers', () => {
      const { container } = render(<HistogramRenderer config={visits} data={bins(50, 2)} />);
      const axis = [...container.querySelectorAll('svg text')].map((label) => label.textContent);
      expect(axis).toEqual(['0', '99']);
    });

    it('picks the whole numbers the bin holds', () => {
      const onSelect = vi.fn();
      render(<HistogramRenderer config={visits} data={bins(50, 2)} onSelect={onSelect} />);
      const chart = screen.getByRole('group', { name: 'Distribution of visits' });
      fireEvent.focus(chart);
      fireEvent.keyDown(chart, { key: 'Enter' });
      expect(onSelect).toHaveBeenLastCalledWith({
        column: 'visits',
        label: '0 – 49',
        range: { lower: 0, upper: 49, includeUpper: true },
      });
    });

    it('closes the last whole-number bin at its last value, and a single-value bin at its value', () => {
      const onSelect = vi.fn();
      const { unmount } = render(<HistogramRenderer config={visits} data={bins(50, 2)} onSelect={onSelect} />);
      const chart = screen.getByRole('group', { name: 'Distribution of visits' });
      fireEvent.focus(chart);
      fireEvent.keyDown(chart, { key: 'End' });
      fireEvent.keyDown(chart, { key: 'Enter' });
      expect(onSelect).toHaveBeenLastCalledWith(
        expect.objectContaining({ range: { lower: 50, upper: 99, includeUpper: true } }),
      );
      unmount();

      const single = { ...data, result: { bins: [{ lower: 7, upper: 8, count: 3 }], whole_numbers: true } };
      render(<HistogramRenderer config={visits} data={single} onSelect={onSelect} />);
      const lone = screen.getByRole('group', { name: 'Distribution of visits' });
      fireEvent.focus(lone);
      fireEvent.keyDown(lone, { key: 'Enter' });
      expect(onSelect).toHaveBeenLastCalledWith({
        column: 'visits',
        label: '7',
        range: { lower: 7, upper: 7, includeUpper: true },
      });
    });

    it('still filters when the last bin reaches the column type\'s maximum', () => {
      const onSelect = vi.fn();
      const small = [{ name: 'visits', type: 'smallint' }];
      const top = { ...data, result: { bins: [{ lower: 32700, upper: 32768, count: 2 }], whole_numbers: true } };
      render(<HistogramRenderer config={visits} data={top} onSelect={onSelect} />);
      const chart = screen.getByRole('group', { name: 'Distribution of visits' });
      fireEvent.focus(chart);
      fireEvent.keyDown(chart, { key: 'Enter' });

      const layer = { id: 'a', dataset_id: 'ds', filter: null, column_info: small } as unknown as SharedLayerResponse;
      expect(selectionCql2(layer, onSelect.mock.lastCall![0])).not.toBeNull();
    });
  });

  it('reads bins without the whole-number flag as half-open, the last holding the maximum', () => {
    const visits: HistogramConfig = { column: 'visits', bins: 2 };
    const older = { ...data, result: { bins: [{ lower: 10, upper: 45, count: 4 }, { lower: 45, upper: 80, count: 4 }] } };
    const onSelect = vi.fn();
    render(<HistogramRenderer config={visits} data={older} onSelect={onSelect} />);
    expect(screen.getAllByRole('rowheader').map((header) => header.textContent)).toEqual(['10 – 45', '45 – 80']);

    const chart = screen.getByRole('group', { name: 'Distribution of visits' });
    fireEvent.focus(chart);
    fireEvent.keyDown(chart, { key: 'Enter' });
    expect(onSelect).toHaveBeenLastCalledWith(
      expect.objectContaining({ range: { lower: 10, upper: 45, includeUpper: false } }),
    );
    fireEvent.keyDown(chart, { key: 'End' });
    fireEvent.keyDown(chart, { key: 'Enter' });
    expect(onSelect).toHaveBeenLastCalledWith(
      expect.objectContaining({ range: { lower: 45, upper: 80, includeUpper: true } }),
    );
  });

  it('says there is no data before the host fetches it, and when there are no values', () => {
    const { rerender } = render(<HistogramRenderer config={config} />);
    expect(screen.getByText('No data yet')).toBeInTheDocument();
    rerender(<HistogramRenderer config={config} data={{ ...data, result: { bins: [] } }} />);
    expect(screen.getByText('No data')).toBeInTheDocument();
  });

  it('edits the column, offering only numeric ones, and the number of bins', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <HistogramEditor
        config={config}
        onChange={onChange}
        columns={[
          { name: 'height', type: 'double precision' },
          { name: 'land_use', type: 'text' },
          { name: 'floors', type: 'integer' },
        ]}
        idPrefix="h"
      />,
    );
    await user.click(screen.getByRole('combobox', { name: 'Column' }));
    expect(screen.getAllByRole('option').map((option) => option.textContent)).toEqual(['height', 'floors']);
    await user.click(screen.getByRole('option', { name: 'floors' }));
    expect(onChange).toHaveBeenLastCalledWith({ ...config, column: 'floors' });

    const bins = screen.getByRole('spinbutton', { name: 'Bins' });
    await user.clear(bins);
    await user.type(bins, '1');
    expect(onChange).not.toHaveBeenCalledWith({ ...config, bins: 1 });
    await user.type(bins, '5');
    expect(onChange).toHaveBeenLastCalledWith({ ...config, bins: 15 });
  });
});
