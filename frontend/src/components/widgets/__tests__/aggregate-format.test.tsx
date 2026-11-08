import { render } from '@/test/test-utils';
import { formatAggregateValue } from '../aggregate';
import BarChartRenderer from '../bar-chart/BarChartRenderer';

describe('formatAggregateValue', () => {
  it('drops decimals from 1,000 up and keeps two below', () => {
    expect(formatAggregateValue(60094702.55)).toBe('60,094,703');
    expect(formatAggregateValue(-1408.38)).toBe('-1,408');
    expect(formatAggregateValue(999.456)).toBe('999.46');
    expect(formatAggregateValue(0.5)).toBe('0.5');
  });
});

describe('bar value labels', () => {
  it('leave room for the longest value inside the chart', () => {
    const data = {
      op: 'group_by',
      approximate: false,
      cached: false,
      result: { groups: [{ key: 'R', value: 60094702.55 }, { key: 'C', value: 1000 }] },
    };
    const { container } = render(
      <BarChartRenderer
        config={{ column: 'zone', stat: 'sum', stat_column: 'area', limit: 5 } as never}
        data={data}
      />,
    );
    const label = [...container.querySelectorAll('svg text')].find((node) => node.textContent === '60,094,703')!;
    const start = Number(label.getAttribute('x'));
    expect(start + '60,094,703'.length * 6.4).toBeLessThanOrEqual(320);
  });
});

describe('an oversized exact value', () => {
  it('is clipped on the chart and leaves the bars their room', () => {
    const exact = '1000.12345678901234567890123456789';
    const data = {
      op: 'group_by',
      approximate: false,
      cached: false,
      result: { groups: [{ key: 'R', value: exact }, { key: 'C', value: 500 }] },
    };
    const { container } = render(
      <BarChartRenderer
        config={{ column: 'zone', stat: 'sum', stat_column: 'area', limit: 5 } as never}
        data={data}
      />,
    );
    const widths = [...container.querySelectorAll('svg rect')].map((rect) => Number(rect.getAttribute('width')));
    expect(widths[0]).toBeGreaterThan(50);
    expect(widths[0]).toBeGreaterThan(widths[1]);
    expect([...container.querySelectorAll('svg text')].some((node) => node.textContent?.endsWith('…'))).toBe(true);
    expect(container.querySelector('svg title')?.textContent).toContain(exact);
  });
});
