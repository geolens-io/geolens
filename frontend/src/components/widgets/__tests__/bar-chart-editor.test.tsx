import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '@/test/test-utils';
import BarChartEditor from '../bar-chart/BarChartEditor';
import type { BarChartConfig } from '../bar-chart/definition';

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
