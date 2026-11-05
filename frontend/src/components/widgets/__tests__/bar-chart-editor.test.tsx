import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '@/test/test-utils';
import BarChartEditor from '../bar-chart/BarChartEditor';
import type { BarChartConfig } from '../bar-chart/definition';

// Radix Select reads these, and jsdom doesn't implement them.
Element.prototype.hasPointerCapture = vi.fn(() => false);
Element.prototype.releasePointerCapture = vi.fn();
Element.prototype.scrollIntoView = vi.fn();

const columns = [{ name: 'kind', type: 'text' }];
const config: BarChartConfig = { column: 'kind', stat: 'count', stat_column: null, limit: 10 };

describe('BarChartEditor', () => {
  it('shows a limit set from outside, as when a draft is reset', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(
      <BarChartEditor config={config} onChange={onChange} columns={columns} idPrefix="w" />,
    );
    const bars = screen.getByRole('spinbutton', { name: 'Bars' });
    await user.clear(bars);
    await user.type(bars, '7');
    expect(onChange).toHaveBeenLastCalledWith({ ...config, limit: 7 });

    rerender(<BarChartEditor config={{ ...config, limit: 25 }} onChange={onChange} columns={columns} idPrefix="w" />);
    expect(bars).toHaveValue(25);
  });
});

describe('BarChartEditor forms', () => {
  const layerColumns = [
    { name: 'kind', type: 'text' },
    { name: 'height', type: 'double precision' },
    { name: 'area', type: 'integer' },
    { name: 'built', type: 'date' },
  ];

  async function chooseMode(label: string, current: BarChartConfig = config) {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<BarChartEditor config={current} onChange={onChange} columns={layerColumns} idPrefix="w" />);
    await user.click(screen.getByRole('combobox', { name: 'Bars show' }));
    await user.click(screen.getByRole('option', { name: label }));
    return onChange;
  }

  it.each([
    [
      'Dates',
      { mode: 'date', column: 'built', date_bucket: 'month', stat: 'count', stat_column: null, limit: 10 },
    ],
    [
      'One bar per feature',
      { mode: 'by_feature', label_column: 'kind', value_column: 'height', sort: 'desc', limit: 10 },
    ],
    ['One bar per field', { mode: 'by_fields', fields: ['height'], stat: 'sum' }],
  ])('starts the %s form on columns the layer has', async (label, expected) => {
    expect(await chooseMode(label)).toHaveBeenLastCalledWith(expected);
  });

  it('offers dates and numeric forms only when the layer has such columns', async () => {
    const user = userEvent.setup();
    render(<BarChartEditor config={config} onChange={vi.fn()} columns={[{ name: 'kind', type: 'text' }]} idPrefix="w" />);
    await user.click(screen.getByRole('combobox', { name: 'Bars show' }));
    expect(screen.getByRole('option', { name: 'Dates' })).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByRole('option', { name: 'One bar per field' })).toHaveAttribute('aria-disabled', 'true');
    expect(screen.getByRole('option', { name: 'Values of a column' })).not.toHaveAttribute('aria-disabled');
  });

  it('stores the layer colours option only when it is off', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(<BarChartEditor config={config} onChange={onChange} columns={layerColumns} idPrefix="w" />);
    const toggle = screen.getByRole('checkbox', { name: "Use the layer's colours" });
    expect(toggle).toBeChecked();
    await user.click(toggle);
    expect(onChange).toHaveBeenLastCalledWith({ ...config, use_layer_colors: false });

    rerender(<BarChartEditor config={{ ...config, use_layer_colors: false }} onChange={onChange} columns={layerColumns} idPrefix="w" />);
    await user.click(screen.getByRole('checkbox', { name: "Use the layer's colours" }));
    expect(onChange).toHaveBeenLastCalledWith(config);
  });

  it('has no layer colours option for forms that are not value charts', () => {
    const date: BarChartConfig = { mode: 'date', column: 'built', date_bucket: 'year', stat: 'count', stat_column: null, limit: 5 };
    render(<BarChartEditor config={date} onChange={vi.fn()} columns={layerColumns} idPrefix="w" />);
    expect(screen.queryByRole('checkbox', { name: "Use the layer's colours" })).toBeNull();
    expect(screen.getByRole('combobox', { name: 'Date column' })).toBeInTheDocument();
  });

  it('keeps at least one field on a by-field chart', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const byFields: BarChartConfig = { mode: 'by_fields', fields: ['height'], stat: 'sum' };
    render(<BarChartEditor config={byFields} onChange={onChange} columns={layerColumns} idPrefix="w" />);
    expect(screen.getByRole('checkbox', { name: 'height' })).toBeDisabled();
    await user.click(screen.getByRole('checkbox', { name: 'area' }));
    expect(onChange).toHaveBeenLastCalledWith({ ...byFields, fields: ['height', 'area'] });
  });
});
