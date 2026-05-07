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
    // Phase 258 POLISH-06: stops now carry id fields (optional); use objectContaining
    // so the assertion accepts the extra `id` field without breaking GRAD-04.
    expect(onBuilderChange).toHaveBeenCalledWith(
      {
        lineGradient: {
          stops: expect.arrayContaining([
            expect.objectContaining({ position: 0, color: '#0066cc' }),
            expect.objectContaining({ position: 1, color: '#cc3300' }),
          ]),
        },
      },
      expect.objectContaining({ 'line-gradient': expr, 'line-color': '#abcdef' }),
    );
    // Stop count must be exactly 2 — guard against accidental stop duplication.
    const builderCall = onBuilderChange.mock.calls[0]?.[0] as { lineGradient: { stops: unknown[] } };
    expect(builderCall.lineGradient.stops).toHaveLength(2);
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

  it('ui: monotonic warning uses displayed (pending) position so it surfaces immediately while typing (IN-03)', () => {
    const stops = [
      { position: 0, color: '#000' },
      { position: 0.5, color: '#888' },
      { position: 1, color: '#fff' },
    ];
    const expr = stopsToLineGradientExpression(stops);
    render(
      <LineGradientControls
        paint={{ 'line-gradient': expr }}
        styleConfig={{ builder: { lineGradient: { stops } } } as unknown as StyleConfig}
        onPaintProp={vi.fn()}
        onBuilderChange={vi.fn()}
        t={t}
      />,
    );
    const positionInputs = screen.getAllByRole('spinbutton', { name: 'style.lineGradient.position' });
    // Type an out-of-range pending value into idx=1 (1.5). Out-of-range values are NOT
    // committed upstream (so they persist in pendingPositionEdits and feed displayedPos).
    // idx=1 will show invalidPosition. The IN-03 fix means idx=2's monotonic check now
    // uses displayed positions: prevDisplayedPos (idx=1) = 1.5, displayedPos (idx=2) = 1
    // (committed) -> 1 > 1.5 is false -> duplicatePosition surfaces immediately on idx=2.
    fireEvent.change(positionInputs[1], { target: { value: '1.5' } });
    expect(screen.getByText('style.lineGradient.invalidPosition')).toBeInTheDocument();
    expect(screen.getByText('style.lineGradient.duplicatePosition')).toBeInTheDocument();
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

  it('advanced: openAdvanced with empty paint renders empty textarea, not literal "null" (IN-02)', async () => {
    const user = userEvent.setup();
    render(<LineGradientControls paint={{}} styleConfig={null} onPaintProp={vi.fn()} onBuilderChange={vi.fn()} t={t} />);
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.advanced' }));
    const textarea = screen.getByRole('textbox', { name: 'style.lineGradient.advanced' }) as HTMLTextAreaElement;
    expect(textarea.value).toBe('');
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

describe('LineGradientControls — UI polish (Phase 258)', () => {
  it('polish-01: gradient preview swatch renders in canonical gradient mode with linear-gradient background', () => {
    const stops = [{ position: 0, color: '#000000' }, { position: 1, color: '#ffffff' }];
    const expr = stopsToLineGradientExpression(stops);
    render(
      <LineGradientControls
        paint={{ 'line-gradient': expr }}
        styleConfig={{ builder: { lineGradient: { stops } } } as unknown as StyleConfig}
        onPaintProp={vi.fn()}
        onBuilderChange={vi.fn()}
        t={t}
      />,
    );
    const swatch = screen.getByTestId('line-gradient-preview-swatch');
    expect(swatch).toBeInTheDocument();
    // jsdom normalizes hex to rgb() in computed style; check the component's background prop
    // by reading the style attribute (raw) or the computed background property.
    const style = swatch.getAttribute('style') ?? '';
    expect(style).toContain('linear-gradient(to right,');
    // jsdom may normalize hex colors to rgb() in the style attribute; accept either form.
    const bg = (swatch as HTMLElement).style.background;
    expect(bg).toContain('0%');
    expect(bg).toContain('100%');
  });

  it('polish-01: gradient preview swatch is NOT rendered in customExpression branch', () => {
    render(
      <LineGradientControls
        paint={{ 'line-gradient': ['step', ['line-progress'], '#000', 0.5, '#fff'] }}
        styleConfig={null}
        onPaintProp={vi.fn()}
        onBuilderChange={vi.fn()}
        t={t}
      />,
    );
    expect(screen.queryByTestId('line-gradient-preview-swatch')).not.toBeInTheDocument();
    expect(screen.getByText('style.lineGradient.customExpression')).toBeInTheDocument();
  });

  it('polish-01: gradient preview swatch is NOT rendered in solid mode', () => {
    render(<LineGradientControls paint={{}} styleConfig={null} onPaintProp={vi.fn()} onBuilderChange={vi.fn()} t={t} />);
    expect(screen.queryByTestId('line-gradient-preview-swatch')).not.toBeInTheDocument();
  });

  it('polish-02: gradient stop rows do not render the per-row "Color" label key', () => {
    const stops = [
      { position: 0, color: '#000' },
      { position: 0.5, color: '#888' },
      { position: 1, color: '#fff' },
    ];
    render(
      <LineGradientControls
        paint={{ 'line-gradient': stopsToLineGradientExpression(stops) }}
        styleConfig={{ builder: { lineGradient: { stops } } } as unknown as StyleConfig}
        onPaintProp={vi.fn()}
        onBuilderChange={vi.fn()}
        t={t}
      />,
    );
    // In gradient mode the solid-mode StyleColorPicker is not rendered.
    // None of the gradient-row StyleColorPicker labels should be the i18n key.
    expect(screen.queryAllByText('style.lineGradient.color')).toHaveLength(0);
  });

  it('polish-03: Solid/Gradient toggle buttons carry focus-visible ring + cursor-pointer classes', () => {
    render(<LineGradientControls paint={{}} styleConfig={null} onPaintProp={vi.fn()} onBuilderChange={vi.fn()} t={t} />);
    const solid = screen.getByRole('button', { name: 'style.lineGradient.solid' });
    const gradient = screen.getByRole('button', { name: 'style.lineGradient.gradient' });
    for (const btn of [solid, gradient]) {
      expect(btn.className).toContain('focus-visible:ring-2');
      expect(btn.className).toContain('focus-visible:ring-ring');
      expect(btn.className).toContain('focus-visible:ring-offset-1');
      expect(btn.className).toContain('cursor-pointer');
    }
  });

  it('polish-04: advanced disclosure button spans full width with w-full + justify-start', () => {
    render(<LineGradientControls paint={{}} styleConfig={null} onPaintProp={vi.fn()} onBuilderChange={vi.fn()} t={t} />);
    const disclosure = screen.getByRole('button', { name: 'style.lineGradient.advanced' });
    expect(disclosure.className).toContain('w-full');
    expect(disclosure.className).toContain('justify-start');
  });

  it('polish-05: each gradient stop row renders a visible "pos" prefix span', () => {
    const stops = [
      { position: 0, color: '#000' },
      { position: 0.5, color: '#888' },
      { position: 1, color: '#fff' },
    ];
    render(
      <LineGradientControls
        paint={{ 'line-gradient': stopsToLineGradientExpression(stops) }}
        styleConfig={{ builder: { lineGradient: { stops } } } as unknown as StyleConfig}
        onPaintProp={vi.fn()}
        onBuilderChange={vi.fn()}
        t={t}
      />,
    );
    expect(screen.getAllByText('pos')).toHaveLength(stops.length);
  });

  it('polish-07: trash button is wrapped in a Tooltip with data-slot="tooltip-trigger"', () => {
    const stops = [
      { position: 0, color: '#000' },
      { position: 0.5, color: '#888' },
      { position: 1, color: '#fff' },
    ];
    render(
      <LineGradientControls
        paint={{ 'line-gradient': stopsToLineGradientExpression(stops) }}
        styleConfig={{ builder: { lineGradient: { stops } } } as unknown as StyleConfig}
        onPaintProp={vi.fn()}
        onBuilderChange={vi.fn()}
        t={t}
      />,
    );
    const trashButtons = screen.getAllByRole('button', { name: 'style.lineGradient.removeStop' });
    expect(trashButtons).toHaveLength(3);
    // Radix asChild merges data-slot onto the child; if not propagated in jsdom,
    // fall back to closest ancestor with the attribute.
    for (const btn of trashButtons) {
      const hasTriggerSlot =
        btn.getAttribute('data-slot') === 'tooltip-trigger' ||
        btn.closest('[data-slot="tooltip-trigger"]') !== null;
      expect(hasTriggerSlot).toBe(true);
    }
  });

  it('polish-07: trash button preserves aria-label through Tooltip wrap', () => {
    const stops = [
      { position: 0, color: '#000' },
      { position: 0.5, color: '#888' },
      { position: 1, color: '#fff' },
    ];
    render(
      <LineGradientControls
        paint={{ 'line-gradient': stopsToLineGradientExpression(stops) }}
        styleConfig={{ builder: { lineGradient: { stops } } } as unknown as StyleConfig}
        onPaintProp={vi.fn()}
        onBuilderChange={vi.fn()}
        t={t}
      />,
    );
    for (const btn of screen.getAllByRole('button', { name: 'style.lineGradient.removeStop' })) {
      expect(btn.getAttribute('aria-label')).toBe('style.lineGradient.removeStop');
    }
  });

  it('polish-07: trash button stays disabled at minimum 2 stops through Tooltip wrap', () => {
    const stops = [{ position: 0, color: '#000' }, { position: 1, color: '#fff' }];
    render(
      <LineGradientControls
        paint={{ 'line-gradient': stopsToLineGradientExpression(stops) }}
        styleConfig={{ builder: { lineGradient: { stops } } } as unknown as StyleConfig}
        onPaintProp={vi.fn()}
        onBuilderChange={vi.fn()}
        t={t}
      />,
    );
    for (const btn of screen.getAllByRole('button', { name: 'style.lineGradient.removeStop' })) {
      expect(btn).toBeDisabled();
    }
  });
});

describe('LineGradientControls — stable stop keys (Phase 258)', () => {
  it('polish-06: stopsToLineGradientExpression strips id from canonical paint output', () => {
    const stopsWithIds = [
      { position: 0, color: '#000', id: 'aaa' },
      { position: 1, color: '#fff', id: 'bbb' },
    ];
    const stopsWithoutIds = [
      { position: 0, color: '#000' },
      { position: 1, color: '#fff' },
    ];
    expect(stopsToLineGradientExpression(stopsWithIds)).toEqual(
      stopsToLineGradientExpression(stopsWithoutIds),
    );
    expect(stopsToLineGradientExpression(stopsWithIds)).toEqual([
      'interpolate',
      ['linear'],
      ['line-progress'],
      0, '#000',
      1, '#fff',
    ]);
  });

  it('polish-06: addStop assigns a fresh id to the new stop and preserves existing ids', async () => {
    const onPaintProp = vi.fn();
    const onBuilderChange = vi.fn();
    const user = userEvent.setup();
    // Pre-seed builder stops WITH stable ids so we can assert preservation.
    const initialStops = [
      { position: 0, color: '#000', id: 'stop-a' },
      { position: 1, color: '#fff', id: 'stop-b' },
    ];
    render(
      <LineGradientControls
        paint={{ 'line-gradient': stopsToLineGradientExpression(initialStops) }}
        styleConfig={{ builder: { lineGradient: { stops: initialStops } } } as unknown as StyleConfig}
        onPaintProp={onPaintProp}
        onBuilderChange={onBuilderChange}
        t={t}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.addStop' }));

    const lastBuilderCall = onBuilderChange.mock.calls[onBuilderChange.mock.calls.length - 1];
    const committedStops = lastBuilderCall[0].lineGradient.stops as Array<{ position: number; color: string; id?: string }>;
    expect(committedStops).toHaveLength(3);
    // All 3 stops must have an id.
    for (const s of committedStops) {
      expect(typeof s.id).toBe('string');
      expect(s.id!.length).toBeGreaterThan(0);
    }
    // Existing ids preserved.
    const ids = committedStops.map((s) => s.id);
    expect(ids).toContain('stop-a');
    expect(ids).toContain('stop-b');
    // The third id is fresh and unique.
    const freshId = ids.find((id) => id !== 'stop-a' && id !== 'stop-b');
    expect(freshId).toBeTruthy();
    expect(freshId).not.toBe('stop-a');
    expect(freshId).not.toBe('stop-b');
  });

  it('polish-06: legacy builder stops without ids get assigned ids at first hydration', async () => {
    const onBuilderChange = vi.fn();
    const user = userEvent.setup();
    // Mount with stops that lack `id` (legacy JSONB shape).
    const legacyStops = [
      { position: 0, color: '#000' },
      { position: 1, color: '#fff' },
    ];
    render(
      <LineGradientControls
        paint={{ 'line-gradient': stopsToLineGradientExpression(legacyStops) }}
        styleConfig={{ builder: { lineGradient: { stops: legacyStops } } } as unknown as StyleConfig}
        onPaintProp={vi.fn()}
        onBuilderChange={onBuilderChange}
        t={t}
      />,
    );
    // Trigger a commit (e.g., addStop) so we can inspect the next stops.
    await user.click(screen.getByRole('button', { name: 'style.lineGradient.addStop' }));
    const lastBuilderCall = onBuilderChange.mock.calls[onBuilderChange.mock.calls.length - 1];
    const committedStops = lastBuilderCall[0].lineGradient.stops as Array<{ position: number; color: string; id?: string }>;
    // Every stop in the committed builder JSONB now has an id (the legacy ones got
    // assigned at hydration; the freshly-added one got assigned at addStop).
    for (const s of committedStops) {
      expect(typeof s.id).toBe('string');
      expect(s.id!.length).toBeGreaterThan(0);
    }
  });

  it('polish-06: midpoint insertion preserves React identity of pre-existing stop rows (key=stop.id)', async () => {
    const onBuilderChange = vi.fn();
    const user = userEvent.setup();
    const initialStops = [
      { position: 0, color: '#000', id: 'first' },
      { position: 1, color: '#fff', id: 'last' },
    ];
    const { rerender, container } = render(
      <LineGradientControls
        paint={{ 'line-gradient': stopsToLineGradientExpression(initialStops) }}
        styleConfig={{ builder: { lineGradient: { stops: initialStops } } } as unknown as StyleConfig}
        onPaintProp={vi.fn()}
        onBuilderChange={onBuilderChange}
        t={t}
      />,
    );
    // Tag the first and last stop rows by recording their DOM nodes.
    const positionInputsBefore = screen.getAllByRole('spinbutton', { name: 'style.lineGradient.position' });
    expect(positionInputsBefore).toHaveLength(2);
    const firstNodeBefore = positionInputsBefore[0];
    const lastNodeBefore = positionInputsBefore[1];

    await user.click(screen.getByRole('button', { name: 'style.lineGradient.addStop' }));
    // Re-render with the committed 3-stop set (parent normally pushes this back via styleConfig).
    const committed = onBuilderChange.mock.calls[onBuilderChange.mock.calls.length - 1][0].lineGradient.stops;
    rerender(
      <LineGradientControls
        paint={{ 'line-gradient': stopsToLineGradientExpression(committed) }}
        styleConfig={{ builder: { lineGradient: { stops: committed } } } as unknown as StyleConfig}
        onPaintProp={vi.fn()}
        onBuilderChange={onBuilderChange}
        t={t}
      />,
    );
    const positionInputsAfter = screen.getAllByRole('spinbutton', { name: 'style.lineGradient.position' });
    expect(positionInputsAfter).toHaveLength(3);
    // The inputs at the FIRST and LAST positions must be the same DOM nodes as before
    // (React reused them because their parent rows were keyed by stable id).
    // After sorted insertion of the midpoint stop, the `first` stop (id='first', pos=0) is
    // still at index 0 and the `last` stop (id='last', pos=1) is now at index 2.
    expect(positionInputsAfter[0]).toBe(firstNodeBefore);
    expect(positionInputsAfter[2]).toBe(lastNodeBefore);
    // Sanity: container still mounted.
    expect(container.contains(positionInputsAfter[0])).toBe(true);
  });
});
