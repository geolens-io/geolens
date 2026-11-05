import { useState } from 'react';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { dashboardPayload } from '@/components/builder/dashboard-draft';
import { render } from '@/test/test-utils';
import { indicatorWidget, type IndicatorConfig } from '../indicator/definition';
import IndicatorEditor from '../indicator/IndicatorEditor';
import { IndicatorFallback } from '../indicator/IndicatorFallback';
import IndicatorRenderer from '../indicator/IndicatorRenderer';
import { indicatorDifference } from '../indicator/indicator-value';
import { dashboardReadableTypes, parseStoredWidget } from '../registry';

const id = '6f1c3a52-8d1e-4a57-9b1f-2c4e7a9d0b11';
const layerId = '0b7d2f4e-3c1a-4e8b-9f6d-5a2c7e1b9d34';
const countOf = (count: number) => ({ op: 'count', approximate: false, cached: false, result: { count } });
const base: IndicatorConfig = { stat: 'count', column: null };

describe('indicator reference config', () => {
  const parse = (config: unknown, v: number) => indicatorWidget.parseConfig(config, v);

  it('reads the reference options from version 2 only', () => {
    const config = { stat: 'count', reference: 100, reference_label: 'Target', higher_is_better: false, comparison: 'percent' };
    expect(parse(config, 2)).toEqual({ ...config, column: null });
    expect(parse(config, 1)).toBeNull();
    expect(parse({ stat: 'count', reference: 0 }, 2)).toEqual({ ...base, reference: 0 });
  });

  it('refuses what the server refuses', () => {
    for (const bad of [
      { stat: 'count', reference_label: 'Target' },
      { stat: 'count', reference: '5' },
      { stat: 'count', reference: Number.NaN },
      { stat: 'count', reference: 1, reference_label: '' },
      { stat: 'count', reference: 1, reference_label: 'x'.repeat(41) },
      { stat: 'count', reference: 1, comparison: 'ratio' },
      { stat: 'count', reference: 1, higher_is_better: 'yes' },
    ]) {
      expect(parse(bad, 2)).toBeNull();
    }
    expect(parse({ stat: 'count', reference: 1, reference_label: 'x'.repeat(40) }, 2)).not.toBeNull();
  });

  it('is stored as version 2 only when a reference option is set', () => {
    expect(indicatorWidget.storedVersion?.(base)).toBe(1);
    expect(indicatorWidget.storedVersion?.({ ...base, reference: 0 })).toBe(2);
    const draft = (config: IndicatorConfig) => ({
      panel: 'right' as const,
      widgets: [{ id, type: 'indicator', v: 2, layer_id: layerId, scope: 'layer' as const, config }],
    });
    const versionOf = (config: IndicatorConfig) => {
      const widgets = dashboardPayload(draft(config), [layer()], { panel: 'right' })?.widgets ?? [];
      return (widgets[0] as unknown as { v: number }).v;
    };
    expect(versionOf(base)).toBe(1);
    expect(versionOf({ ...base, reference: 5 })).toBe(2);
  });

  it('is read at both versions and registers both for the server', () => {
    expect(dashboardReadableTypes()).toEqual(expect.arrayContaining(['indicator:1', 'indicator:2']));
    const instance = (v: number, config: unknown) => ({ id, type: 'indicator', v, layer_id: layerId, config });
    expect(parseStoredWidget(instance(1, { stat: 'count' }), 'dashboard').ok).toBe(true);
    expect(parseStoredWidget(instance(2, { stat: 'count', reference: 3 }), 'dashboard').ok).toBe(true);
    expect(parseStoredWidget(instance(1, { stat: 'count', reference: 3 }), 'dashboard')).toEqual({
      ok: false,
      reason: 'invalid_config',
    });
  });
});

function layer() {
  return {
    id: layerId,
    dataset_id: 'd',
    dataset_name: 'Parcels',
    display_name: null,
    sort_order: 0,
    dataset_geometry_type: 'Point',
    dataset_format: 'geojson',
    dataset_record_type: 'dataset',
  } as unknown as Parameters<typeof dashboardPayload>[1][number];
}

describe('indicator difference', () => {
  it('measures the value against the reference', () => {
    expect(indicatorDifference(125, { ...base, reference: 100 })).toMatchObject({
      amount: 25,
      percent: 0.25,
      direction: 'above',
      tone: 'good',
    });
    expect(indicatorDifference(75, { ...base, reference: 100 })).toMatchObject({
      amount: -25,
      percent: -0.25,
      direction: 'below',
      tone: 'bad',
    });
    expect(indicatorDifference(100, { ...base, reference: 100 })).toMatchObject({ direction: 'same', tone: 'neutral' });
  });

  it('has no percent change from a reference of 0', () => {
    expect(indicatorDifference(8, { ...base, reference: 0 })).toEqual({
      amount: 8,
      percent: null,
      direction: 'above',
      tone: 'good',
    });
  });

  it('takes a negative reference as its size', () => {
    expect(indicatorDifference(-5, { ...base, reference: -10 })?.percent).toBe(0.5);
  });

  it('swaps good and bad when lower is better', () => {
    const lower = { ...base, reference: 100, higher_is_better: false };
    expect(indicatorDifference(125, lower)?.tone).toBe('bad');
    expect(indicatorDifference(75, lower)?.tone).toBe('good');
  });

  it('compares an exact value past 2^53 without rounding it', () => {
    expect(indicatorDifference('9007199254740993', { ...base, reference: 9007199254740992 })).toMatchObject({
      amount: 1n,
      direction: 'above',
      tone: 'good',
    });
    expect(indicatorDifference('-9007199254740993', { ...base, reference: -9007199254740992 })?.direction).toBe(
      'below',
    );
    expect(indicatorDifference('9007199254740993', { ...base, reference: 1.5 })).toMatchObject({
      direction: 'above',
    });
  });

  it('compares a decimal text exactly, below and past 2^53', () => {
    for (const [text, reference] of [
      ['9007199254740991.1', 9007199254740991],
      ['9007199254740992.1', 9007199254740992],
    ] as const) {
      expect(indicatorDifference(text, { ...base, reference })).toMatchObject({
        amount: '0.1',
        direction: 'above',
        tone: 'good',
      });
    }
    expect(indicatorDifference('0.30000000000000004', { ...base, reference: 0.3 })?.direction).toBe('above');
    expect(indicatorDifference('-1.5', { ...base, reference: -1.5 })?.direction).toBe('same');
  });

  it('reads a decimal text in exponent form', () => {
    expect(indicatorDifference('1.00000000000000000001E-8', { ...base, reference: 0 })).toMatchObject({
      direction: 'above',
    });
  });

  it('keeps the percent when the subtraction overflows, and has none to show for a value-only comparison', () => {
    const config = { ...base, reference: -1e308 };
    expect(indicatorDifference(1e308, config)).toMatchObject({ amount: null, percent: 2 });
    expect(indicatorDifference(1e308, { ...config, comparison: 'value' })).toBeNull();
  });

  it('writes an exact difference past 2^53 without rounding it', () => {
    const data = { op: 'stats', approximate: false, cached: false, result: { sum: '9223372036854775807' } };
    render(<IndicatorRenderer config={{ stat: 'sum', column: 'id', reference: 0, comparison: 'value' }} data={data} />);
    expect(screen.getByText(/^\+9,223,372,036,854,775,807 above Reference/)).toBeInTheDocument();
  });

  it('displays an exact fractional difference without rounding it through a number', () => {
    const data = { op: 'stats', approximate: false, cached: false, result: { sum: '9007199254740991.1' } };
    render(<IndicatorRenderer config={{ stat: 'sum', column: 'id', reference: 0, comparison: 'value' }} data={data} />);
    expect(screen.getByText(/^\+9,007,199,254,740,991\.1 above Reference/)).toBeInTheDocument();
  });

  it('keeps the difference when the scaled value would overflow a number', () => {
    const config = { ...base, reference: 1e-300 };
    expect(indicatorDifference('9007199254740993', config)).toMatchObject({
      amount: expect.stringMatching(/^9007199254740992\.9999/),
      percent: null,
      direction: 'above',
    });
    const data = { op: 'stats', approximate: false, cached: false, result: { sum: '9007199254740993' } };
    render(<IndicatorRenderer config={{ stat: 'sum', column: 'id', reference: 1e-300 }} data={data} />);
    expect(screen.queryByText(/∞/)).not.toBeInTheDocument();
    expect(screen.getByText(/^\+9,007,199,254,740,993 above Reference/)).toBeInTheDocument();
  });

  it('shows a tie only when the exact value equals the reference', () => {
    const data = { op: 'stats', approximate: false, cached: false, result: { sum: '9007199254740991.1' } };
    render(<IndicatorRenderer config={{ stat: 'sum', column: 'id', reference: 9007199254740991 }} data={data} />);
    expect(screen.queryByText(/Same as/)).not.toBeInTheDocument();
    expect(screen.getByText(/above Reference, favorable$/)).toBeInTheDocument();
  });

  it('reads an exact value sent as text, and has none without a number', () => {
    expect(indicatorDifference('9007199254740993', { ...base, reference: 0 })?.direction).toBe('above');
    expect(indicatorDifference(null, { ...base, reference: 1 })).toBeNull();
    expect(indicatorDifference(undefined, { ...base, reference: 1 })).toBeNull();
    expect(indicatorDifference(5, base)).toBeNull();
  });
});

describe('indicator reference display', () => {
  it('shows the reference line and the difference with an arrow and text', () => {
    const { container } = render(
      <IndicatorRenderer config={{ ...base, reference: 100, reference_label: 'Target' }} data={countOf(125)} />,
    );
    expect(screen.getByText('Target: 100')).toBeInTheDocument();
    const difference = screen.getByText('+25 (+25%) above Target, favorable');
    expect(difference).toHaveClass('text-success');
    expect(container.querySelector('[aria-hidden="true"]')).toHaveTextContent('▲');
  });

  it('colours a shortfall as bad, or as good when lower is better', () => {
    const { rerender } = render(
      <IndicatorRenderer config={{ ...base, reference: 100 }} data={countOf(80)} />,
    );
    expect(screen.getByText('-20 (-20%) below Reference, unfavorable')).toHaveClass('text-destructive');
    rerender(<IndicatorRenderer config={{ ...base, reference: 100, higher_is_better: false }} data={countOf(80)} />);
    expect(screen.getByText('-20 (-20%) below Reference, favorable')).toHaveClass('text-success');
  });

  it('shows the chosen form of the difference, and no percent for a reference of 0', () => {
    const show = (config: IndicatorConfig, count: number) =>
      render(<IndicatorRenderer config={config} data={countOf(count)} />);
    show({ ...base, reference: 50, comparison: 'value' }, 60);
    expect(screen.getByText('+10 above Reference, favorable')).toBeInTheDocument();
    show({ ...base, reference: 50, comparison: 'percent' }, 60);
    expect(screen.getByText('+20% above Reference, favorable')).toBeInTheDocument();
    show({ ...base, reference: 0, comparison: 'percent' }, 7);
    expect(screen.getByText('+7 above Reference, favorable')).toBeInTheDocument();
    show({ ...base, reference: 7 }, 7);
    expect(screen.getByText('Same as Reference')).toBeInTheDocument();
  });

  it('looks as it did without a reference', () => {
    const { container } = render(<IndicatorRenderer config={base} data={countOf(3)} />);
    expect(container.querySelectorAll('p')).toHaveLength(2);
  });

  it('puts the reference and the difference in the table alternative', () => {
    render(
      <IndicatorFallback config={{ ...base, reference: 100, reference_label: 'Target' }} data={countOf(125)} />,
    );
    const table = screen.getByRole('table');
    expect(within(table).getByRole('row', { name: /^Count 125$/ })).toBeInTheDocument();
    expect(within(table).getByRole('row', { name: /^Target 100$/ })).toBeInTheDocument();
    expect(within(table).getByRole('row', { name: /^Difference \+25 \(\+25%\) above Target, favorable$/ })).toBeInTheDocument();
  });

  it('keeps the one-line alternative without a reference', () => {
    render(<IndicatorFallback config={base} data={countOf(3)} />);
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.getByText('Count: 3')).toBeInTheDocument();
  });
});

describe('IndicatorEditor reference fields', () => {
  const columns = [{ name: 'area', type: 'double precision' }];

  it('offers the options only once a reference is entered, and drops them when it is cleared', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const full: IndicatorConfig = { ...base, reference: 12.5, reference_label: 'Goal', higher_is_better: false, comparison: 'value' };
    function Harness({ start }: { start: IndicatorConfig }) {
      const [config, setConfig] = useState(start);
      return (
        <IndicatorEditor
          config={config}
          onChange={(next) => {
            onChange(next);
            setConfig(next);
          }}
          columns={columns}
          idPrefix="w"
        />
      );
    }
    const { unmount } = render(<Harness start={base} />);
    expect(screen.queryByLabelText('Reference label')).not.toBeInTheDocument();
    await user.type(screen.getByRole('spinbutton', { name: 'Reference value' }), '12.5');
    expect(onChange).toHaveBeenLastCalledWith({ ...base, reference: 12.5 });
    unmount();

    render(<Harness start={full} />);
    await user.clear(screen.getByRole('spinbutton', { name: 'Reference value' }));
    expect(onChange).toHaveBeenLastCalledWith(base);
  });

  it('keeps a label of 40 characters that is more than 40 code units', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const config: IndicatorConfig = { ...base, reference: 10 };
    render(<IndicatorEditor config={config} onChange={onChange} columns={columns} idPrefix="w" />);
    await user.click(screen.getByLabelText('Reference label'));
    await user.paste('😀'.repeat(45));
    expect([...(onChange.mock.lastCall?.[0].reference_label ?? '')]).toHaveLength(40);
  });

  it('writes only the options that differ from their defaults', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const config: IndicatorConfig = { ...base, reference: 10 };
    render(<IndicatorEditor config={config} onChange={onChange} columns={columns} idPrefix="w" />);
    await user.type(screen.getByLabelText('Reference label'), 'T');
    expect(onChange).toHaveBeenLastCalledWith({ ...config, reference_label: 'T' });
    await user.click(screen.getByRole('checkbox', { name: 'A higher value is better' }));
    expect(onChange).toHaveBeenLastCalledWith({ ...config, higher_is_better: false });
  });
});
