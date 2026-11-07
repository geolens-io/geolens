import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '@/test/test-utils';
import type { PieChartConfig } from '../pie-chart/definition';
import PieChartEditor from '../pie-chart/PieChartEditor';

const columns = [{ name: 'kind', type: 'text' }];
const config: PieChartConfig = { column: 'kind', stat: 'count', stat_column: null, limit: 10, use_layer_colors: true };

describe('PieChartEditor', () => {
  it('switches layer colours off and on, keeping the rest of the config', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(<PieChartEditor config={config} onChange={onChange} columns={columns} idPrefix="p" />);
    await user.click(screen.getByRole('checkbox', { name: "Use the layer's colours" }));
    expect(onChange).toHaveBeenLastCalledWith({ ...config, use_layer_colors: false });

    rerender(<PieChartEditor config={{ ...config, use_layer_colors: false }} onChange={onChange} columns={columns} idPrefix="p" />);
    await user.click(screen.getByRole('checkbox', { name: "Use the layer's colours" }));
    expect(onChange).toHaveBeenLastCalledWith(config);
  });

  it('sets how many slices show before the rest merge into Other', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<PieChartEditor config={config} onChange={onChange} columns={columns} idPrefix="p" />);
    const slices = screen.getByRole('spinbutton', { name: 'Slices' });
    await user.clear(slices);
    await user.type(slices, '6');
    expect(onChange).toHaveBeenLastCalledWith({ ...config, limit: 6 });
  });
});
