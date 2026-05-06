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

  it('ui: clicking Gradient commits a default 2-stop line-gradient to BOTH paint and builder (with next paint)', async () => {
    const onPaintProp = vi.fn();
    const onBuilderChange = vi.fn();
    const user = userEvent.setup();
    render(<LineGradientControls paint={{ 'line-color': '#abcdef' }} styleConfig={null} onPaintProp={onPaintProp} onBuilderChange={onBuilderChange} t={t} />);
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.gradient' }));
    const expr = stopsToLineGradientExpression([...DEFAULT_GRADIENT_STOPS]);
    expect(onPaintProp).toHaveBeenCalledWith('line-gradient', expr);
    // UAT regression-lock: onBuilderChange MUST receive nextPaint that includes
    // the new line-gradient expression, otherwise upstream save reads stale paint
    // (closure capture) and shadows the gradient.
    expect(onBuilderChange).toHaveBeenCalledWith(
      { lineGradient: { stops: [...DEFAULT_GRADIENT_STOPS] } },
      expect.objectContaining({ 'line-gradient': expr, 'line-color': '#abcdef' }),
    );
  });

  it('ui: clicking Solid clears paint line-gradient and builder.lineGradient (with next paint)', async () => {
    const onPaintProp = vi.fn();
    const onBuilderChange = vi.fn();
    const user = userEvent.setup();
    const expr = stopsToLineGradientExpression(DEFAULT_GRADIENT_STOPS);
    render(<LineGradientControls paint={{ 'line-color': '#abcdef', 'line-gradient': expr }} styleConfig={{ builder: { lineGradient: { stops: [...DEFAULT_GRADIENT_STOPS] } } } as unknown as StyleConfig} onPaintProp={onPaintProp} onBuilderChange={onBuilderChange} t={t} />);
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.solid' }));
    expect(onPaintProp).toHaveBeenCalledWith('line-gradient', undefined);
    // UAT regression-lock: nextPaint MUST omit line-gradient (so the upstream save
    // produces a paint without the now-stale gradient).
    const lastCall = onBuilderChange.mock.calls[onBuilderChange.mock.calls.length - 1];
    expect(lastCall[0]).toEqual({ lineGradient: undefined });
    expect(lastCall[1]).not.toHaveProperty('line-gradient');
    expect(lastCall[1]).toEqual(expect.objectContaining({ 'line-color': '#abcdef' }));
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

  it('ui: activateSolid is atomic — single onPaintProp(line-gradient, undefined) + composed onBuilderChange (WR-04)', async () => {
    const onPaintProp = vi.fn();
    const onBuilderChange = vi.fn();
    const user = userEvent.setup();
    const expr = stopsToLineGradientExpression(DEFAULT_GRADIENT_STOPS);
    render(
      <LineGradientControls
        paint={{ 'line-color': '#abcdef', 'line-gradient': expr }}
        styleConfig={{ builder: { lineGradient: { stops: [...DEFAULT_GRADIENT_STOPS] } } } as unknown as StyleConfig}
        onPaintProp={onPaintProp}
        onBuilderChange={onBuilderChange}
        t={t}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.solid' }));
    // Only ONE onPaintProp call should fire — the line-gradient removal.
    // The line-color restore must travel through onBuilderChange's nextPaint
    // payload, NOT through a second onPaintProp call (atomicity).
    expect(onPaintProp).toHaveBeenCalledTimes(1);
    expect(onPaintProp).toHaveBeenCalledWith('line-gradient', undefined);
    // onBuilderChange MUST receive a fully-composed nextPaint with line-color preserved
    // and line-gradient absent.
    expect(onBuilderChange).toHaveBeenCalledTimes(1);
    const [patch, nextPaint] = onBuilderChange.mock.calls[0];
    expect(patch).toEqual({ lineGradient: undefined });
    expect(nextPaint).toEqual(expect.objectContaining({ 'line-color': '#abcdef' }));
    expect(nextPaint).not.toHaveProperty('line-gradient');
  });

  it('ui: Solid -> Gradient toggle restores a previously-preserved non-canonical expression (WR-03)', async () => {
    const onPaintProp = vi.fn();
    const onBuilderChange = vi.fn();
    const user = userEvent.setup();
    const customExpr = ['step', ['line-progress'], '#000', 0.5, '#fff'];
    // Mount with a non-canonical expression: customExpression hint visible, mode=gradient.
    const { rerender } = render(
      <LineGradientControls
        paint={{ 'line-gradient': customExpr }}
        styleConfig={null}
        onPaintProp={onPaintProp}
        onBuilderChange={onBuilderChange}
        t={t}
      />,
    );
    expect(screen.getByText('style.lineGradient.customExpression')).toBeInTheDocument();
    // Toggle to Solid — the non-canonical expression should be saved internally.
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.solid' }));
    // Simulate parent re-render with paint after gradient was dropped (Solid mode active).
    rerender(
      <LineGradientControls
        paint={{ 'line-color': '#0066cc' }}
        styleConfig={null}
        onPaintProp={onPaintProp}
        onBuilderChange={onBuilderChange}
        t={t}
      />,
    );
    onPaintProp.mockClear();
    onBuilderChange.mockClear();
    // Toggle back to Gradient — the custom expression must be restored, NOT a default 2-stop.
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.gradient' }));
    const lineGradientCalls = onPaintProp.mock.calls.filter((c: unknown[]) => c[0] === 'line-gradient');
    expect(lineGradientCalls).toHaveLength(1);
    expect(lineGradientCalls[0][1]).toEqual(customExpr);
    // builder.lineGradient should be cleared because the expression is non-canonical.
    expect(onBuilderChange).toHaveBeenCalledWith({ lineGradient: undefined }, expect.objectContaining({ 'line-gradient': customExpr }));
  });

  it('ui: pendingPositionEdits clears on commitStops so stale invalid positions do not leak across remove/add (WR-02)', async () => {
    const onPaintProp = vi.fn();
    const onBuilderChange = vi.fn();
    const user = userEvent.setup();
    const initialStops = [
      { position: 0, color: '#000' },
      { position: 0.5, color: '#888' },
      { position: 1, color: '#fff' },
    ];
    const expr = stopsToLineGradientExpression(initialStops);
    const { rerender } = render(
      <LineGradientControls
        paint={{ 'line-gradient': expr }}
        styleConfig={{ builder: { lineGradient: { stops: initialStops } } } as unknown as StyleConfig}
        onPaintProp={onPaintProp}
        onBuilderChange={onBuilderChange}
        t={t}
      />,
    );
    // Type an invalid pending position into idx=2.
    const positionInputs = screen.getAllByRole('spinbutton', { name: 'style.lineGradient.position' });
    fireEvent.change(positionInputs[2], { target: { value: '1.5' } });
    expect(screen.getByText('style.lineGradient.invalidPosition')).toBeInTheDocument();
    // Remove idx=0 — commitStops fires with 2 remaining stops; pendingPositionEdits[2] is now orphaned.
    await user.click(screen.getAllByRole('button', { name: 'style.lineGradient.removeStop' })[0]);
    // Simulate parent re-rendering with the committed shorter stops. Pending edits for the new
    // re-rendered indices must be empty — the component must NOT show invalidPosition anymore.
    const remainingStops = [
      { position: 0.5, color: '#888' },
      { position: 1, color: '#fff' },
    ];
    rerender(
      <LineGradientControls
        paint={{ 'line-gradient': stopsToLineGradientExpression(remainingStops) }}
        styleConfig={{ builder: { lineGradient: { stops: remainingStops } } } as unknown as StyleConfig}
        onPaintProp={onPaintProp}
        onBuilderChange={onBuilderChange}
        t={t}
      />,
    );
    expect(screen.queryByText('style.lineGradient.invalidPosition')).not.toBeInTheDocument();
    // Add a stop — neither the new idx=2 nor any other index should re-surface a stale 1.5.
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.addStop' }));
    const addStopsCommitted = onPaintProp.mock.calls
      .filter((c: unknown[]) => c[0] === 'line-gradient')
      .map((c: unknown[]) => c[1])
      .pop() as unknown[];
    // The committed paint must NOT include 1.5 anywhere — assert by rerendering with it.
    rerender(
      <LineGradientControls
        paint={{ 'line-gradient': addStopsCommitted }}
        styleConfig={{ builder: { lineGradient: { stops: lineGradientExpressionToStops(addStopsCommitted)! } } } as unknown as StyleConfig}
        onPaintProp={onPaintProp}
        onBuilderChange={onBuilderChange}
        t={t}
      />,
    );
    expect(screen.queryByText('style.lineGradient.invalidPosition')).not.toBeInTheDocument();
    // No position input shows 1.5 either.
    const finalInputs = screen.getAllByRole('spinbutton', { name: 'style.lineGradient.position' });
    for (const input of finalInputs) {
      expect((input as HTMLInputElement).value).not.toBe('1.5');
    }
  });
});

describe('LineGradientControls — advanced expression editor', () => {
  it('advanced: line-gradient advanced disclosure is collapsed by default', () => {
    render(<LineGradientControls paint={{}} styleConfig={null} onPaintProp={vi.fn()} onBuilderChange={vi.fn()} t={t} />);
    // The disclosure toggle button is visible
    expect(screen.getByRole('button', { name: 'style.lineGradient.advanced' })).toBeInTheDocument();
    // The textarea is NOT yet rendered
    expect(screen.queryByRole('textbox', { name: 'style.lineGradient.advanced' })).not.toBeInTheDocument();
  });

  it('advanced: opening the line-gradient advanced disclosure renders a textarea + Apply + Cancel', async () => {
    const user = userEvent.setup();
    render(<LineGradientControls paint={{}} styleConfig={null} onPaintProp={vi.fn()} onBuilderChange={vi.fn()} t={t} />);
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.advanced' }));
    expect(screen.getByRole('textbox', { name: 'style.lineGradient.advanced' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'style.lineGradient.applyExpression' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'style.lineGradient.cancelExpression' })).toBeInTheDocument();
  });

  it('advanced: typing invalid JSON into the line-gradient advanced editor surfaces parseError inline and does NOT commit', async () => {
    const onPaintProp = vi.fn();
    const user = userEvent.setup();
    render(<LineGradientControls paint={{}} styleConfig={null} onPaintProp={onPaintProp} onBuilderChange={vi.fn()} t={t} />);
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.advanced' }));
    const textbox = screen.getByRole('textbox', { name: 'style.lineGradient.advanced' });
    fireEvent.change(textbox, { target: { value: 'not-json{' } });
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.applyExpression' }));
    expect(screen.getByText('style.lineGradient.parseError')).toBeInTheDocument();
    const lineGradientCalls = onPaintProp.mock.calls.filter((c: unknown[]) => c[0] === 'line-gradient');
    expect(lineGradientCalls).toHaveLength(0);
  });

  it('advanced: typing a non-array structure into the line-gradient advanced editor surfaces structureError', async () => {
    const onPaintProp = vi.fn();
    const user = userEvent.setup();
    render(<LineGradientControls paint={{}} styleConfig={null} onPaintProp={onPaintProp} onBuilderChange={vi.fn()} t={t} />);
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.advanced' }));
    const textbox = screen.getByRole('textbox', { name: 'style.lineGradient.advanced' });
    fireEvent.change(textbox, { target: { value: '{"foo":"bar"}' } });
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.applyExpression' }));
    expect(screen.getByText('style.lineGradient.structureError')).toBeInTheDocument();
    const lineGradientCalls = onPaintProp.mock.calls.filter((c: unknown[]) => c[0] === 'line-gradient');
    expect(lineGradientCalls).toHaveLength(0);
  });

  it('advanced: typing an unknown operator into the line-gradient advanced editor surfaces structureError', async () => {
    const onPaintProp = vi.fn();
    const user = userEvent.setup();
    render(<LineGradientControls paint={{}} styleConfig={null} onPaintProp={onPaintProp} onBuilderChange={vi.fn()} t={t} />);
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.advanced' }));
    const textbox = screen.getByRole('textbox', { name: 'style.lineGradient.advanced' });
    fireEvent.change(textbox, { target: { value: '["unknownop", 1, 2]' } });
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.applyExpression' }));
    expect(screen.getByText('style.lineGradient.structureError')).toBeInTheDocument();
    const lineGradientCalls = onPaintProp.mock.calls.filter((c: unknown[]) => c[0] === 'line-gradient');
    expect(lineGradientCalls).toHaveLength(0);
  });

  it('advanced: applying a canonical line-gradient expression commits to paint and re-hydrates the stops panel', async () => {
    const onPaintProp = vi.fn();
    const onBuilderChange = vi.fn();
    const user = userEvent.setup();
    render(<LineGradientControls paint={{}} styleConfig={null} onPaintProp={onPaintProp} onBuilderChange={onBuilderChange} t={t} />);
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.advanced' }));
    const textbox = screen.getByRole('textbox', { name: 'style.lineGradient.advanced' });
    const canonical = JSON.stringify(['interpolate', ['linear'], ['line-progress'], 0, '#0066cc', 0.5, '#888888', 1, '#cc3300']);
    fireEvent.change(textbox, { target: { value: canonical } });
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.applyExpression' }));
    // paint commit
    const lineGradientCalls = onPaintProp.mock.calls.filter((c: unknown[]) => c[0] === 'line-gradient');
    expect(lineGradientCalls).toHaveLength(1);
    expect(lineGradientCalls[0][1]).toEqual(['interpolate', ['linear'], ['line-progress'], 0, '#0066cc', 0.5, '#888888', 1, '#cc3300']);
    // builder commit with parsed stops
    const builderCalls = onBuilderChange.mock.calls.filter((c: unknown[]) => {
      const patch = c[0] as { lineGradient?: { stops?: unknown[] } };
      return Array.isArray(patch.lineGradient?.stops);
    });
    expect(builderCalls).toHaveLength(1);
  });

  it('advanced: applying a non-canonical line-gradient expression commits to paint and shows the customExpression hint (no silent flatten)', async () => {
    const onPaintProp = vi.fn();
    const onBuilderChange = vi.fn();
    const user = userEvent.setup();
    // Render in gradient mode by mounting with a canonical expression already set, then paste a step expression
    const initial = stopsToLineGradientExpression([{ position: 0, color: '#000' }, { position: 1, color: '#fff' }]);
    const { rerender } = render(<LineGradientControls paint={{ 'line-gradient': initial }} styleConfig={{ builder: { lineGradient: { stops: [{ position: 0, color: '#000' }, { position: 1, color: '#fff' }] } } } as unknown as StyleConfig} onPaintProp={onPaintProp} onBuilderChange={onBuilderChange} t={t} />);
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.advanced' }));
    const textbox = screen.getByRole('textbox', { name: 'style.lineGradient.advanced' });
    const stepExpr = JSON.stringify(['step', ['line-progress'], '#000', 0.5, '#fff']);
    fireEvent.change(textbox, { target: { value: stepExpr } });
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.applyExpression' }));
    // paint should be the step expression
    const lineGradientCalls = onPaintProp.mock.calls.filter((c: unknown[]) => c[0] === 'line-gradient');
    expect(lineGradientCalls).toHaveLength(1);
    expect(lineGradientCalls[0][1]).toEqual(['step', ['line-progress'], '#000', 0.5, '#fff']);
    // builder should be cleared (non-canonical can't be represented as stops)
    const builderCalls = onBuilderChange.mock.calls.filter((c: unknown[]) => {
      const patch = c[0] as { lineGradient?: unknown };
      return patch.lineGradient === undefined;
    });
    expect(builderCalls.length).toBeGreaterThanOrEqual(1);
    // Re-render with the parent's updated paint to simulate the React lifecycle of the commit
    rerender(<LineGradientControls paint={{ 'line-gradient': ['step', ['line-progress'], '#000', 0.5, '#fff'] }} styleConfig={null} onPaintProp={onPaintProp} onBuilderChange={onBuilderChange} t={t} />);
    // customExpression hint visible; stops panel hidden (Add stop button NOT in DOM)
    expect(screen.getByText('style.lineGradient.customExpression')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'style.lineGradient.addStop' })).not.toBeInTheDocument();
  });

  it('advanced: cancelling the line-gradient advanced editor does NOT commit', async () => {
    const onPaintProp = vi.fn();
    const user = userEvent.setup();
    render(<LineGradientControls paint={{}} styleConfig={null} onPaintProp={onPaintProp} onBuilderChange={vi.fn()} t={t} />);
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.advanced' }));
    const textbox = screen.getByRole('textbox', { name: 'style.lineGradient.advanced' });
    const canonical = JSON.stringify(['interpolate', ['linear'], ['line-progress'], 0, '#000', 1, '#fff']);
    fireEvent.change(textbox, { target: { value: canonical } });
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.cancelExpression' }));
    const lineGradientCalls = onPaintProp.mock.calls.filter((c: unknown[]) => c[0] === 'line-gradient');
    expect(lineGradientCalls).toHaveLength(0);
    // textarea closed
    expect(screen.queryByRole('textbox', { name: 'style.lineGradient.advanced' })).not.toBeInTheDocument();
  });
});
