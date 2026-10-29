import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import CategorySelectorEditor from '../category-selector/CategorySelectorEditor';
import { CategorySelectorFallback } from '../category-selector/CategorySelectorFallback';
import CategorySelectorRenderer from '../category-selector/CategorySelectorRenderer';
import {
  categorySelectorWidget,
  SELECTOR_OPTIONS,
  type CategorySelectorConfig,
} from '../category-selector/definition';

// Radix Select reads these, and jsdom doesn't implement them.
Element.prototype.hasPointerCapture = vi.fn(() => false);
Element.prototype.releasePointerCapture = vi.fn();
Element.prototype.scrollIntoView = vi.fn();

const config: CategorySelectorConfig = { column: 'land_use', multiple: true };
const data = {
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

describe('category selector widget', () => {
  it('parses configs as the server does', () => {
    const parse = (raw: unknown) => categorySelectorWidget.parseConfig(raw, 1);
    expect(parse({ column: 'land_use' })).toEqual({ column: 'land_use', multiple: true });
    expect(parse({ column: 'land_use', multiple: false })).toEqual({ column: 'land_use', multiple: false });
    for (const bad of [{}, { column: 'land_use', multiple: 'yes' }, { column: 'land_use', limit: 5 }]) {
      expect(parse(bad)).toBeNull();
    }
  });

  it('asks for the most frequent values of its column', () => {
    expect(categorySelectorWidget.dataRequest!(config)).toEqual({
      op: 'value_counts',
      column: 'land_use',
      limit: SELECTOR_OPTIONS,
    });
    expect(categorySelectorWidget.readsColumns!(config)).toEqual([{ name: 'land_use', numeric: false }]);
  });

  it('offers checkboxes with counts and picks several values', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const { rerender } = render(<CategorySelectorRenderer config={config} data={data} onSelect={onSelect} />);
    const group = screen.getByRole('group', { name: 'Filter by land_use' });
    expect(within(group).getAllByRole('checkbox')).toHaveLength(3);
    expect(within(group).getByText('40')).toBeInTheDocument();
    expect(within(group).getByText('Other values: 7')).toBeInTheDocument();

    await user.click(screen.getByRole('checkbox', { name: /Residential/ }));
    expect(onSelect).toHaveBeenLastCalledWith({ column: 'land_use', label: 'Residential', values: ['Residential'] });

    const picked = { column: 'land_use', label: 'Residential', values: ['Residential'] };
    rerender(<CategorySelectorRenderer config={config} data={data} selection={picked} onSelect={onSelect} />);
    expect(screen.getByRole('checkbox', { name: /Residential/ })).toBeChecked();
    // Keyboard: Tab to the next box and Space ticks it.
    await user.tab();
    await user.keyboard(' ');
    expect(onSelect).toHaveBeenLastCalledWith({
      column: 'land_use',
      label: 'Residential, Commercial',
      values: ['Residential', 'Commercial'],
    });
    await user.click(screen.getByRole('checkbox', { name: /no value/ }));
    expect(onSelect).toHaveBeenLastCalledWith({
      column: 'land_use',
      label: 'Residential, (no value)',
      values: ['Residential', null],
    });
    await user.click(screen.getByRole('checkbox', { name: /Residential/ }));
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it('offers radio buttons headed by All when the reader picks one value', async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    const single = { ...config, multiple: false };
    const picked = { column: 'land_use', label: 'Commercial', values: ['Commercial'] };
    render(<CategorySelectorRenderer config={single} data={data} selection={picked} onSelect={onSelect} />);
    const radios = screen.getAllByRole('radio');
    expect(radios.map((radio) => radio.closest('li')?.textContent)).toEqual([
      'All',
      'Residential40',
      'Commercial25',
      '(no value)5',
    ]);
    expect(screen.getByRole('radio', { name: /Commercial/ })).toBeChecked();

    await user.click(screen.getByRole('radio', { name: /Residential/ }));
    expect(onSelect).toHaveBeenLastCalledWith({ column: 'land_use', label: 'Residential', values: ['Residential'] });
    await user.click(screen.getByRole('radio', { name: 'All' }));
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it('keeps a picked value the current numbers no longer list, so it can be cleared', () => {
    const picked = { column: 'land_use', label: 'Industrial', values: ['Industrial'] };
    render(<CategorySelectorRenderer config={config} data={data} selection={picked} onSelect={vi.fn()} />);
    expect(screen.getByRole('checkbox', { name: 'Industrial' })).toBeChecked();
  });

  it('shows the same options, disabled, where the host does not link widgets', async () => {
    const user = userEvent.setup();
    const picked = { column: 'land_use', label: 'Commercial', values: ['Commercial'] };
    const { rerender } = render(<CategorySelectorRenderer config={config} data={data} selection={picked} />);
    const boxes = screen.getAllByRole('checkbox');
    expect(boxes).toHaveLength(3);
    for (const box of boxes) expect(box).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: 'Commercial' })).toBeChecked();
    await user.click(screen.getByRole('checkbox', { name: 'Residential' }));
    expect(screen.getByRole('checkbox', { name: 'Residential' })).not.toBeChecked();

    rerender(<CategorySelectorRenderer config={{ ...config, multiple: false }} data={data} />);
    for (const radio of screen.getAllByRole('radio')) expect(radio).toBeDisabled();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('offers the same table as its text alternative', () => {
    render(<CategorySelectorFallback config={config} data={data} />);
    const rows = within(screen.getByRole('table')).getAllByRole('row').slice(1);
    expect(rows.map((row) => row.textContent)).toEqual(['Residential40', 'Commercial25', '(no value)5', 'Other7']);
  });

  it('edits the column and whether readers pick more than one value', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <CategorySelectorEditor
        config={config}
        onChange={onChange}
        columns={[
          { name: 'land_use', type: 'text' },
          { name: 'zone', type: 'text' },
        ]}
        idPrefix="s"
      />,
    );
    await user.click(screen.getByRole('combobox', { name: 'Column' }));
    await user.click(screen.getByRole('option', { name: 'zone' }));
    expect(onChange).toHaveBeenLastCalledWith({ ...config, column: 'zone' });
    const multiple = screen.getByRole('checkbox', { name: 'Readers can pick more than one value' });
    expect(multiple).toBeChecked();
    await user.click(multiple);
    expect(onChange).toHaveBeenLastCalledWith({ ...config, multiple: false });
  });
});
