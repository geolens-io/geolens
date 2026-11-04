import { barChartWidget } from '../bar-chart/definition';

describe('bar chart config', () => {
  it('reads a stored category chart that carries the layer colour option', () => {
    const config = { column: 'kind', stat: 'count', stat_column: null, limit: 10, use_layer_colors: false };
    expect(barChartWidget.parseConfig({ ...config, mode: 'category' }, 1)).toEqual(config);
  });

  it('reads the legacy shape without adding keys', () => {
    const config = { column: 'kind', stat: 'count', stat_column: null, limit: 10 };
    expect(barChartWidget.parseConfig(config, 1)).toEqual(config);
  });

  it('leaves chart forms it does not draw unread', () => {
    expect(
      barChartWidget.parseConfig({ mode: 'date', column: 'built', date_bucket: 'month' }, 1),
    ).toBeNull();
  });
});
