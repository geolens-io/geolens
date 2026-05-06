import { fireEvent, render, screen } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import {
  LineGradientControls,
  DEFAULT_GRADIENT_STOPS,
  stopsToLineGradientExpression,
  lineGradientExpressionToStops,
} from '../LineGradientControls';
import type { StyleConfig } from '@/types/api';

// Radix popover used by StyleColorPicker
(globalThis as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
  class { observe(){} unobserve(){} disconnect(){} } as unknown as typeof ResizeObserver;
Element.prototype.hasPointerCapture = vi.fn(() => false);
Element.prototype.releasePointerCapture = vi.fn();
Element.prototype.scrollIntoView = vi.fn();

const t = (key: string) => key; // identity translator

describe('LineGradientControls — round-trip parser', () => {
  it('parser: stopsToLineGradientExpression emits canonical interpolate-linear-line-progress for line-gradient', () => {
    const expr = stopsToLineGradientExpression([
      { position: 0, color: '#0066cc' },
      { position: 1, color: '#cc3300' },
    ]);
    expect(expr).toEqual(['interpolate', ['linear'], ['line-progress'], 0, '#0066cc', 1, '#cc3300']);
  });

  it('parser: lineGradientExpressionToStops accepts a canonical 3-stop line-gradient expression', () => {
    const stops = lineGradientExpressionToStops([
      'interpolate', ['linear'], ['line-progress'],
      0.0, '#000', 0.5, '#888', 1.0, '#fff',
    ]);
    expect(stops).toEqual([
      { position: 0.0, color: '#000' },
      { position: 0.5, color: '#888' },
      { position: 1.0, color: '#fff' },
    ]);
  });

  it('parser: lineGradientExpressionToStops rejects step expressions (non-gradient interpolation)', () => {
    expect(lineGradientExpressionToStops(['step', ['line-progress'], '#000', 0.5, '#fff'])).toBeNull();
  });

  it('parser: lineGradientExpressionToStops rejects non-linear gradient interpolation', () => {
    expect(lineGradientExpressionToStops(['interpolate', ['exponential', 2], ['line-progress'], 0, '#000', 1, '#fff'])).toBeNull();
  });

  it('parser: lineGradientExpressionToStops rejects non-line-progress input on a gradient', () => {
    expect(lineGradientExpressionToStops(['interpolate', ['linear'], ['zoom'], 0, '#000', 1, '#fff'])).toBeNull();
  });

  it('parser: lineGradientExpressionToStops rejects odd-arity stops in a gradient expression', () => {
    expect(lineGradientExpressionToStops(['interpolate', ['linear'], ['line-progress'], 0, '#000', 1])).toBeNull();
  });

  it('parser: stops -> line-gradient expression -> stops round-trips bit-for-bit', () => {
    const stops = [
      { position: 0, color: '#0066cc' },
      { position: 0.33, color: '#88aa00' },
      { position: 1, color: '#cc3300' },
    ];
    expect(lineGradientExpressionToStops(stopsToLineGradientExpression(stops))).toEqual(stops);
  });
});

describe('LineGradientControls — UI', () => {
  it('ui: line-gradient mode toggle defaults to Solid when paint has no gradient', () => {
    render(<LineGradientControls paint={{}} styleConfig={null} onPaintProp={vi.fn()} onBuilderChange={vi.fn()} t={t} />);
    expect(screen.getByRole('button', { name: 'style.lineGradient.solid' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'style.lineGradient.gradient' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('ui: line-gradient mode toggle defaults to Gradient when paint has a canonical expression', () => {
    const expr = stopsToLineGradientExpression(DEFAULT_GRADIENT_STOPS);
    render(<LineGradientControls paint={{ 'line-gradient': expr }} styleConfig={null} onPaintProp={vi.fn()} onBuilderChange={vi.fn()} t={t} />);
    expect(screen.getByRole('button', { name: 'style.lineGradient.gradient' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('ui: clicking Gradient commits a default 2-stop line-gradient to BOTH paint and builder', async () => {
    const onPaintProp = vi.fn();
    const onBuilderChange = vi.fn();
    const user = userEvent.setup();
    render(<LineGradientControls paint={{ 'line-color': '#abcdef' }} styleConfig={null} onPaintProp={onPaintProp} onBuilderChange={onBuilderChange} t={t} />);
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.gradient' }));
    expect(onPaintProp).toHaveBeenCalledWith('line-gradient', stopsToLineGradientExpression([...DEFAULT_GRADIENT_STOPS]));
    expect(onBuilderChange).toHaveBeenCalledWith({ lineGradient: { stops: [...DEFAULT_GRADIENT_STOPS] } });
  });

  it('ui: clicking Solid clears paint line-gradient and builder.lineGradient', async () => {
    const onPaintProp = vi.fn();
    const onBuilderChange = vi.fn();
    const user = userEvent.setup();
    const expr = stopsToLineGradientExpression(DEFAULT_GRADIENT_STOPS);
    render(<LineGradientControls paint={{ 'line-color': '#abcdef', 'line-gradient': expr }} styleConfig={{ builder: { lineGradient: { stops: [...DEFAULT_GRADIENT_STOPS] } } } as unknown as StyleConfig} onPaintProp={onPaintProp} onBuilderChange={onBuilderChange} t={t} />);
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.solid' }));
    expect(onPaintProp).toHaveBeenCalledWith('line-gradient', undefined);
    expect(onBuilderChange).toHaveBeenCalledWith({ lineGradient: undefined });
  });

  it('ui: Add stop appends a new line-gradient stop at the midpoint of the last two positions', async () => {
    const onPaintProp = vi.fn();
    const user = userEvent.setup();
    const expr = stopsToLineGradientExpression([{ position: 0, color: '#000' }, { position: 1, color: '#fff' }]);
    render(<LineGradientControls paint={{ 'line-gradient': expr }} styleConfig={{ builder: { lineGradient: { stops: [{ position: 0, color: '#000' }, { position: 1, color: '#fff' }] } } } as unknown as StyleConfig} onPaintProp={onPaintProp} onBuilderChange={vi.fn()} t={t} />);
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.addStop' }));
    const calls = onPaintProp.mock.calls.filter((c: unknown[]) => c[0] === 'line-gradient');
    const lastExpr = calls[calls.length - 1][1] as unknown[];
    expect(lastExpr.length).toBe(3 + 6); // [interpolate, [linear], [line-progress], p1, c1, p2, c2, p3, c3]
    expect(lastExpr[3]).toBe(0);
    expect(lastExpr[5]).toBe(0.5); // midpoint of 0 and 1
    expect(lastExpr[7]).toBe(1);
  });

  it('ui: line-gradient remove buttons are disabled at the minimum of 2 stops', () => {
    const expr = stopsToLineGradientExpression([{ position: 0, color: '#000' }, { position: 1, color: '#fff' }]);
    render(<LineGradientControls paint={{ 'line-gradient': expr }} styleConfig={{ builder: { lineGradient: { stops: [{ position: 0, color: '#000' }, { position: 1, color: '#fff' }] } } } as unknown as StyleConfig} onPaintProp={vi.fn()} onBuilderChange={vi.fn()} t={t} />);
    const removes = screen.getAllByRole('button', { name: 'style.lineGradient.removeStop' });
    expect(removes).toHaveLength(2);
    for (const btn of removes) expect(btn).toBeDisabled();
  });

  it('ui: line-gradient position input surfaces invalidPosition error for value > 1', () => {
    const expr = stopsToLineGradientExpression([{ position: 0, color: '#000' }, { position: 1, color: '#fff' }]);
    render(<LineGradientControls paint={{ 'line-gradient': expr }} styleConfig={{ builder: { lineGradient: { stops: [{ position: 0, color: '#000' }, { position: 1, color: '#fff' }] } } } as unknown as StyleConfig} onPaintProp={vi.fn()} onBuilderChange={vi.fn()} t={t} />);
    const positionInputs = screen.getAllByRole('spinbutton', { name: 'style.lineGradient.position' });
    fireEvent.change(positionInputs[1], { target: { value: '1.5' } });
    expect(screen.getByText('style.lineGradient.invalidPosition')).toBeInTheDocument();
  });

  it('ui: non-canonical line-gradient paint expression renders customExpression hint instead of stops', () => {
    render(<LineGradientControls paint={{ 'line-gradient': ['step', ['line-progress'], '#000', 0.5, '#fff'] }} styleConfig={null} onPaintProp={vi.fn()} onBuilderChange={vi.fn()} t={t} />);
    expect(screen.getByText('style.lineGradient.customExpression')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'style.lineGradient.addStop' })).not.toBeInTheDocument();
  });
});
