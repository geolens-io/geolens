import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '@/i18n/i18n';
import { changeTestLanguage } from '@/test/i18n';
import { tableWidget, type TableConfig } from '../table/definition';
import TableEditor from '../table/TableEditor';
import { TableFallback } from '../table/TableFallback';
import TableRenderer from '../table/TableRenderer';

// Radix Select reads these, and jsdom doesn't implement them.
Element.prototype.hasPointerCapture = vi.fn(() => false);
Element.prototype.releasePointerCapture = vi.fn();
Element.prototype.scrollIntoView = vi.fn();

const config: TableConfig = {
  group_column: 'land_use',
  stats: [
    { stat: 'count', column: null },
    { stat: 'mean', column: 'area' },
  ],
  sort_by: 1,
  sort: 'desc',
  limit: 2,
};

function groupBy(groups: { key: string | null; values: (number | string | null)[] }[], truncated = false) {
  return {
    op: 'group_by',
    approximate: false,
    cached: false,
    result: { truncated, groups: groups.map((g) => ({ key: g.key, value: g.values[0], values: g.values })) },
  };
}

const data = groupBy([
  { key: 'Park', values: [1234567, 8.5] },
  { key: null, values: [3, null] },
]);

describe('table widget', () => {
  const parse = (raw: unknown) => tableWidget.parseConfig(raw, 1);
  const base = { group_column: 'land_use', stats: [{ stat: 'count' }] };

  it('parses configs as the server does and fills its defaults', () => {
    expect(parse(base)).toEqual({
      group_column: 'land_use',
      stats: [{ stat: 'count', column: null }],
      sort_by: null,
      sort: 'desc',
      limit: 10,
    });
    expect(parse(config)).toEqual(config);
  });

  it('keeps the statistics list to one to five, each matching its column', () => {
    const sum = { stat: 'sum', column: 'area' };
    expect(parse({ ...base, stats: [] })).toBeNull();
    expect(parse({ ...base, stats: Array(5).fill(sum) })).not.toBeNull();
    expect(parse({ ...base, stats: Array(6).fill(sum) })).toBeNull();
    expect(parse({ ...base, stats: [{ stat: 'sum' }] })).toBeNull();
    expect(parse({ ...base, stats: [{ stat: 'count', column: 'area' }] })).toBeNull();
    expect(parse({ ...base, stats: [{ stat: 'median', column: 'area' }] })).toBeNull();
  });

  it('holds the sort index, direction, limit and keys to the server rules', () => {
    for (const bad of [
      { sort_by: 1 },
      { sort_by: -1 },
      { sort_by: 0.5 },
      { sort: 'up' },
      { limit: 0 },
      { limit: 51 },
      { colour: 'red' },
    ]) {
      expect(parse({ ...base, ...bad })).toBeNull();
    }
    expect(parse({ ...base, sort_by: 0, limit: 50 })).not.toBeNull();
  });

  it('asks for every statistic, ordered by the chosen one', () => {
    expect(tableWidget.dataRequest!(config)).toEqual({
      op: 'group_by',
      group_column: 'land_use',
      stats: [{ stat: 'count' }, { stat: 'avg', column: 'area' }],
      sort_by: 1,
      sort: 'desc',
      limit: 2,
      blank_text_as_null: true,
    });
    expect(tableWidget.dataRequest!({ ...config, sort_by: null, sort: 'asc' })).toMatchObject({
      sort_by: 'group',
      sort: 'asc',
    });
    expect(tableWidget.readsColumns!(config)).toEqual([
      { name: 'land_use', numeric: false },
      { name: 'area', numeric: true },
    ]);
    expect(tableWidget.picksColumn!(config)).toBe('land_use');
  });

  it('starts on a category column', () => {
    expect(tableWidget.initialConfig!([{ name: 'kind', type: 'text', samples: ['a', 'b'] }])).toEqual({
      group_column: 'kind',
    });
  });

  it('draws a table with a caption, named column headers and a row per group', () => {
    render(<TableRenderer config={config} data={data} />);
    const table = screen.getByRole('table', { name: 'Statistics by land_use' });
    const headers = within(table).getAllByRole('columnheader').map((header) => header.textContent);
    expect(headers).toEqual(['land_use', 'Count', 'Average of area']);
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByRole('rowheader')).toHaveTextContent('Park');
    expect(within(rows[0]).getAllByRole('cell').map((cell) => cell.textContent)).toEqual(['1,234,567', '8.5']);
    expect(within(rows[1]).getByRole('rowheader')).toHaveTextContent('(no value)');
  });

  it('scrolls a wide table inside its own container', () => {
    const { container } = render(<TableRenderer config={config} data={data} />);
    const wrapper = container.querySelector('table')!.parentElement!;
    expect(wrapper).toHaveClass('overflow-x-auto');
  });

  it('is read-only without onSelect', () => {
    render(<TableRenderer config={config} data={data} />);
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('picks a row\'s group, as a bar does, and clears it when picked again', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const { rerender } = render(<TableRenderer config={config} data={data} onSelect={onSelect} />);
    await user.click(screen.getByRole('cell', { name: '1,234,567' }));
    expect(onSelect).toHaveBeenLastCalledWith({ column: 'land_use', label: 'Park', values: ['Park'] });

    rerender(
      <TableRenderer
        config={config}
        data={data}
        onSelect={onSelect}
        selection={{ column: 'land_use', label: 'Park', values: ['Park'] }}
      />,
    );
    const picked = screen.getByRole('button', { name: /Park/ });
    expect(picked).toHaveAttribute('aria-pressed', 'true');
    expect(picked.closest('tr')).toHaveAttribute('aria-selected', 'true');
    await user.click(picked);
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it('picks from the keyboard', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(<TableRenderer config={config} data={data} onSelect={onSelect} />);
    await user.tab();
    await user.keyboard('{Enter}');
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenLastCalledWith({ column: 'land_use', label: 'Park', values: ['Park'] });
  });

  it('says when groups were cut off at the limit', () => {
    const { rerender } = render(<TableRenderer config={config} data={data} />);
    expect(screen.queryByText(/not listed/)).toBeNull();
    rerender(<TableRenderer config={config} data={{ ...data, result: { ...data.result, truncated: true } }} />);
    expect(screen.getByText('Showing the first 2 values. More values are not listed.')).toBeInTheDocument();
  });

  it('reads a single-statistic result that carries no values list', () => {
    const single = { ...data, result: { truncated: false, groups: [{ key: 'Park', value: 7 }] } };
    render(<TableRenderer config={{ ...config, stats: [config.stats[0]] }} data={single} />);
    expect(screen.getByRole('cell', { name: '7' })).toBeInTheDocument();
  });

  it('shows exact decimals as text unchanged', () => {
    const exact = groupBy([{ key: 'Park', values: ['0.1000000000000000055', '9007199254740993'] }]);
    render(<TableRenderer config={config} data={exact} />);
    expect(screen.getByRole('cell', { name: '0.1000000000000000055' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: '9,007,199,254,740,993' })).toBeInTheDocument();
  });

  describe('in the reader\'s locale', () => {
    afterEach(async () => {
      await i18n.changeLanguage('en');
    });

    it('formats numbers and headers for the language', async () => {
      await changeTestLanguage('de');
      render(<TableRenderer config={config} data={data} />);
      expect(screen.getByRole('cell', { name: '1.234.567' })).toBeInTheDocument();
      expect(screen.getByRole('cell', { name: '8,5' })).toBeInTheDocument();
      expect(screen.getByRole('columnheader', { name: 'Mittelwert von area' })).toBeInTheDocument();
    });
  });

  it('shows the same table, without picks, as its fallback', () => {
    render(<TableFallback config={config} data={data} onSelect={vi.fn()} />);
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('says when there is no data or no groups', () => {
    const { rerender } = render(<TableRenderer config={config} />);
    expect(screen.getByText('No data yet')).toBeInTheDocument();
    rerender(<TableRenderer config={config} data={groupBy([])} />);
    expect(screen.getByText('No data')).toBeInTheDocument();
  });
});

describe('TableEditor', () => {
  const columns = [
    { name: 'land_use', type: 'text' },
    { name: 'area', type: 'double precision' },
  ];

  it('adds a statistic up to five and removes one, keeping the sort on the same statistic', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(<TableEditor config={config} onChange={onChange} columns={columns} idPrefix="w" />);
    await user.click(screen.getByRole('button', { name: 'Add a statistic' }));
    expect(onChange).toHaveBeenLastCalledWith({
      ...config,
      stats: [...config.stats, { stat: 'count', column: null }],
    });

    await user.click(screen.getByRole('button', { name: 'Remove statistic 1' }));
    expect(onChange).toHaveBeenLastCalledWith({ ...config, stats: [config.stats[1]], sort_by: 0 });
    await user.click(screen.getByRole('button', { name: 'Remove statistic 2' }));
    expect(onChange).toHaveBeenLastCalledWith({ ...config, stats: [config.stats[0]], sort_by: null });

    const five = { ...config, stats: Array(5).fill(config.stats[0]) as TableConfig['stats'] };
    rerender(<TableEditor config={five} onChange={onChange} columns={columns} idPrefix="w" />);
    expect(screen.queryByRole('button', { name: 'Add a statistic' })).toBeNull();
  });

  it('shows a limit set from outside', () => {
    const { rerender } = render(<TableEditor config={config} onChange={vi.fn()} columns={columns} idPrefix="w" />);
    rerender(<TableEditor config={{ ...config, limit: 30 }} onChange={vi.fn()} columns={columns} idPrefix="w" />);
    expect(screen.getByRole('spinbutton', { name: 'Rows' })).toHaveValue(30);
  });
});

describe('table value labels', () => {
  const coded = groupBy([{ key: '1', values: [4, 2] }, { key: '2', values: [3, 1] }]);
  const valueLabel = (column: string, value: unknown) =>
    column === 'land_use' && value === '1' ? 'City' : undefined;

  it('shows the label, picks the stored value, and adds the code in the fallback', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const { unmount } = render(<TableRenderer config={config} data={coded} valueLabel={valueLabel} onSelect={onSelect} />);
    await user.click(screen.getByRole('button', { name: 'City' }));
    expect(onSelect).toHaveBeenLastCalledWith({ column: 'land_use', label: 'City', values: ['1'] });
    expect(screen.getByRole('button', { name: '2' })).toBeInTheDocument();
    unmount();

    render(<TableFallback config={config} data={coded} valueLabel={valueLabel} />);
    expect(screen.getAllByRole('rowheader').map((header) => header.textContent)).toEqual(['City (1)', '2']);
  });
});
