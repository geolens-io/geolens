import { useEffect, useState, useRef } from 'react';
import { Trash2, Plus, ChevronDown, ChevronRight, Code } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { StyleColorPicker } from './StyleColorPicker';
import type { BuilderStyleConfig, StyleConfig } from '@/types/api';
import { cn } from '@/lib/utils';

export const DEFAULT_GRADIENT_STOPS: ReadonlyArray<{ position: number; color: string }> = [
  { position: 0, color: '#0066cc' },
  { position: 1, color: '#cc3300' },
];

// Permissive allowlist for the raw-expression structural validator. The goal
// is to reject obvious garbage (random strings, plain objects, unknown ops)
// before commit; full MapLibre semantic validation happens at runtime.
const KNOWN_MAPLIBRE_OPERATORS = new Set<string>([
  'interpolate', 'interpolate-hcl', 'interpolate-lab', 'step', 'match', 'case', 'let', 'var',
  'coalesce', 'concat', 'literal', 'at', 'length', 'get', 'has', 'in', 'feature-state',
  'geometry-type', 'id', 'properties', 'to-string', 'to-number', 'to-boolean', 'typeof',
  'rgb', 'rgba', 'to-color', 'to-rgba',
  // arithmetic
  '+', '-', '*', '/', '%', '^', 'abs', 'min', 'max', 'round', 'floor', 'ceil', 'sqrt', 'log10', 'log2', 'ln', 'exp', 'pi', 'e',
  // comparison
  '==', '!=', '<', '<=', '>', '>=', '!', 'all', 'any',
  // string
  'upcase', 'downcase', 'resolved-locale',
  // collator
  'collator',
  // formatted
  'format',
  // input
  'zoom', 'heatmap-density', 'line-progress', 'accumulated', 'distance-from-center', 'pitch',
]);

type ExpressionValidationResult =
  | { ok: true; value: unknown[] }
  | { ok: false; error: 'parseError' | 'structureError' };

export function validateLineGradientExpressionInput(text: string): ExpressionValidationResult {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { ok: false, error: 'parseError' };
  }
  if (!Array.isArray(parsed) || parsed.length === 0) {
    return { ok: false, error: 'structureError' };
  }
  const op = parsed[0];
  if (typeof op !== 'string' || !KNOWN_MAPLIBRE_OPERATORS.has(op)) {
    return { ok: false, error: 'structureError' };
  }
  return { ok: true, value: parsed };
}

export function stopsToLineGradientExpression(
  stops: ReadonlyArray<{ position: number; color: string }>,
): unknown[] {
  const tail: unknown[] = [];
  for (const s of stops) tail.push(s.position, s.color);
  return ['interpolate', ['linear'], ['line-progress'], ...tail];
}

export function lineGradientExpressionToStops(
  expr: unknown,
): Array<{ position: number; color: string }> | null {
  if (!Array.isArray(expr)) return null;
  if (expr[0] !== 'interpolate') return null;
  const interp = expr[1];
  if (!Array.isArray(interp) || interp[0] !== 'linear' || interp.length !== 1) return null;
  const input = expr[2];
  if (!Array.isArray(input) || input[0] !== 'line-progress' || input.length !== 1) return null;
  const tail = expr.slice(3);
  if (tail.length === 0 || tail.length % 2 !== 0) return null;
  const stops: Array<{ position: number; color: string }> = [];
  for (let i = 0; i < tail.length; i += 2) {
    const position = tail[i];
    const color = tail[i + 1];
    if (typeof position !== 'number' || !Number.isFinite(position)) return null;
    if (typeof color !== 'string') return null;
    stops.push({ position, color });
  }
  return stops;
}

interface LineGradientControlsProps {
  paint: Record<string, unknown>;
  styleConfig: StyleConfig | null;
  onPaintProp: (key: string, value: unknown) => void;
  onBuilderChange: (patch: BuilderStyleConfig, nextPaint?: Record<string, unknown>) => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

export function LineGradientControls({ paint, styleConfig, onPaintProp, onBuilderChange, t }: LineGradientControlsProps) {
  const builderStops = (styleConfig?.builder?.lineGradient?.stops ?? null) as Array<{ position: number; color: string }> | null;
  const paintExpr = paint['line-gradient'];
  const parsedFromPaint = paintExpr != null ? lineGradientExpressionToStops(paintExpr) : null;

  const initialMode: 'solid' | 'gradient' =
    (paintExpr != null || (builderStops?.length ?? 0) > 0) ? 'gradient' : 'solid';
  const [mode, setMode] = useState<'solid' | 'gradient'>(initialMode);

  const savedSolidColorRef = useRef<string>(
    typeof paint['line-color'] === 'string' ? (paint['line-color'] as string) : '#0066cc',
  );
  useEffect(() => {
    if (mode === 'solid' && typeof paint['line-color'] === 'string') {
      savedSolidColorRef.current = paint['line-color'] as string;
    }
  }, [mode, paint]);

  // Preserve any non-canonical (custom) line-gradient expression so that a
  // Solid -> Gradient round-trip restores it instead of silently overwriting
  // with the canonical 2-stop default. Phase 256 review — WR-03.
  const savedGradientExprRef = useRef<unknown>(null);

  // Local state for in-progress position edits so we can show validation
  // for transient invalid values (e.g. > 1) without committing them upstream.
  const [pendingPositionEdits, setPendingPositionEdits] = useState<Record<number, number>>({});

  // Raw expression editor (advanced disclosure) — collapsed by default.
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [advancedText, setAdvancedText] = useState<string>('');
  const [advancedError, setAdvancedError] = useState<'parseError' | 'structureError' | null>(null);

  const liveStops: Array<{ position: number; color: string }> | null =
    builderStops && builderStops.length > 0 ? builderStops : parsedFromPaint;
  const isCustomExpression = paintExpr != null && parsedFromPaint == null;

  function commitStops(nextStops: Array<{ position: number; color: string }>) {
    // Compose the next paint snapshot once and pass it to both callbacks so the
    // upstream save sees a single consistent state. Without `nextPaint`,
    // `onBuilderChange` would resolve `paint` from a stale closure and shadow
    // the gradient committed by `onPaintProp`. (UAT regression — Phase 256.)
    //
    // Clear pendingPositionEdits because the entry indices are about to be
    // invalidated by the structural change (add/remove/sort/etc). Pending
    // edits are keyed by array index and would otherwise leak across
    // index shifts (Phase 256 review — WR-02).
    setPendingPositionEdits({});
    const expr = stopsToLineGradientExpression(nextStops);
    const nextPaint = { ...paint, 'line-gradient': expr };
    onPaintProp('line-gradient', expr);
    onBuilderChange({ lineGradient: { stops: nextStops } }, nextPaint);
  }

  function activateGradient() {
    setMode('gradient');
    // Restore a previously-preserved non-canonical (custom) expression if the
    // user toggled away from it via Solid. Phase 256 review — WR-03.
    const savedExpr = savedGradientExprRef.current;
    if (savedExpr != null && lineGradientExpressionToStops(savedExpr) == null) {
      savedGradientExprRef.current = null;
      const nextPaint = { ...paint, 'line-gradient': savedExpr };
      onPaintProp('line-gradient', savedExpr);
      // Custom expression cannot be represented as builder stops, so clear
      // builder.lineGradient — the customExpression hint will surface again.
      onBuilderChange({ lineGradient: undefined }, nextPaint);
      return;
    }
    const stops = (liveStops && liveStops.length >= 2) ? liveStops : [...DEFAULT_GRADIENT_STOPS];
    commitStops(stops);
  }

  function activateSolid() {
    setMode('solid');
    // Preserve any non-canonical expression so a re-toggle to Gradient can
    // restore it. Phase 256 review — WR-03.
    if (paintExpr != null && parsedFromPaint == null) {
      savedGradientExprRef.current = paintExpr;
    }
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { 'line-gradient': _drop, ...paintWithoutGradient } = paint;
    const nextPaint =
      savedSolidColorRef.current
        ? { ...paintWithoutGradient, 'line-color': savedSolidColorRef.current }
        : paintWithoutGradient;
    // Atomicity: route the entire transition through one onBuilderChange call
    // with the fully-composed nextPaint. Drop the redundant onPaintProp('line-color', ...)
    // so we don't fire a separate intermediate state update — same pattern as
    // commitStops (Phase 256 review — WR-04, mirrors the UAT regression fix).
    // The first onPaintProp('line-gradient', undefined) is kept so the MapLibre
    // adapter sees the explicit removal signal.
    onPaintProp('line-gradient', undefined);
    onBuilderChange({ lineGradient: undefined }, nextPaint);
  }

  function addStop() {
    if (!liveStops || liveStops.length < 2) return;
    const last = liveStops[liveStops.length - 1];
    const prev = liveStops[liveStops.length - 2];
    const newPosition = Math.round(((prev.position + last.position) / 2) * 100) / 100;
    // Keep stops in sorted (monotonically increasing position) order so the
    // canonical interpolate-linear-line-progress expression renders correctly.
    const next = [...liveStops, { position: newPosition, color: last.color }]
      .slice()
      .sort((a, b) => a.position - b.position);
    commitStops(next);
  }

  function removeStop(index: number) {
    if (!liveStops || liveStops.length <= 2) return;
    const next = liveStops.filter((_, i) => i !== index);
    commitStops(next);
  }

  function updateStopColor(index: number, color: string) {
    if (!liveStops) return;
    const next = liveStops.map((s, i) => (i === index ? { ...s, color } : s));
    commitStops(next);
  }

  function updateStopPosition(index: number, raw: number) {
    if (!liveStops) return;
    // Always reflect the typed value in local pending state so the validation
    // message renders even when the value is out of range.
    setPendingPositionEdits((prev) => ({ ...prev, [index]: raw }));
    if (raw < 0 || raw > 1 || !Number.isFinite(raw)) {
      // Don't commit invalid values upstream.
      return;
    }
    // commitStops() resets pendingPositionEdits to {} so this index's
    // entry is dropped along with any other stale entries (WR-02).
    const next = liveStops.map((s, i) => (i === index ? { ...s, position: raw } : s));
    commitStops(next);
  }

  function openAdvanced() {
    const expr = paint['line-gradient'] ?? null;
    setAdvancedText(JSON.stringify(expr, null, 2));
    setAdvancedError(null);
    setAdvancedOpen(true);
  }

  function cancelAdvanced() {
    setAdvancedOpen(false);
    setAdvancedError(null);
    setAdvancedText('');
  }

  function applyAdvanced() {
    const result = validateLineGradientExpressionInput(advancedText);
    if (!result.ok) {
      setAdvancedError(result.error);
      return;
    }
    onPaintProp('line-gradient', result.value);
    // If canonical, hydrate builder.lineGradient.stops; else clear builder.lineGradient
    // so the customExpression hint surfaces (no silent flatten).
    const parsedStops = lineGradientExpressionToStops(result.value);
    if (parsedStops != null) {
      onBuilderChange({ lineGradient: { stops: parsedStops } });
    } else {
      onBuilderChange({ lineGradient: undefined });
    }
    setAdvancedOpen(false);
    setAdvancedError(null);
  }

  return (
    <div className="space-y-2">
      <div className="text-xs font-medium">{t('style.lineGradient.label')}</div>

      <div className="inline-flex rounded border border-border overflow-hidden text-xs">
        <button
          type="button"
          aria-label={t('style.lineGradient.solid')}
          aria-pressed={mode === 'solid'}
          className={cn(
            'px-2 py-1',
            mode === 'solid' ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground',
          )}
          onClick={() => mode === 'gradient' && activateSolid()}
        >
          {t('style.lineGradient.solid')}
        </button>
        <button
          type="button"
          aria-label={t('style.lineGradient.gradient')}
          aria-pressed={mode === 'gradient'}
          className={cn(
            'px-2 py-1',
            mode === 'gradient' ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground',
          )}
          onClick={() => mode === 'solid' && activateGradient()}
        >
          {t('style.lineGradient.gradient')}
        </button>
      </div>

      {mode === 'solid' && (
        <StyleColorPicker
          label={t('style.lineGradient.color')}
          color={typeof paint['line-color'] === 'string' ? (paint['line-color'] as string) : '#0066cc'}
          onChange={(hex) => onPaintProp('line-color', hex)}
        />
      )}

      {mode === 'gradient' && isCustomExpression && (
        <div className="text-xs italic text-muted-foreground">
          {t('style.lineGradient.customExpression')}
        </div>
      )}

      {mode === 'gradient' && !isCustomExpression && liveStops && (
        <div className="space-y-1.5">
          {liveStops.map((stop, idx) => {
            const pendingPos = pendingPositionEdits[idx];
            const displayedPos = pendingPos !== undefined ? pendingPos : stop.position;
            const positionValid =
              displayedPos >= 0 && displayedPos <= 1 && Number.isFinite(displayedPos);
            const monotonic = idx === 0 || stop.position > liveStops[idx - 1].position;
            return (
              <div key={idx} className="space-y-1">
                <div className="flex items-center gap-2">
                  <StyleColorPicker
                    label={t('style.lineGradient.color')}
                    color={stop.color}
                    onChange={(hex) => updateStopColor(idx, hex)}
                  />
                  <Input
                    type="number"
                    aria-label={t('style.lineGradient.position')}
                    min={0}
                    max={1}
                    step={0.01}
                    value={String(displayedPos)}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      updateStopPosition(idx, v);
                    }}
                    className="h-7 w-20 text-xs"
                  />
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={t('style.lineGradient.removeStop')}
                    disabled={liveStops.length <= 2}
                    onClick={() => removeStop(idx)}
                    className="h-7 w-7 p-0"
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
                {!positionValid && (
                  <div className="text-xs text-destructive">{t('style.lineGradient.invalidPosition')}</div>
                )}
                {positionValid && !monotonic && (
                  <div className="text-xs text-warning-foreground">{t('style.lineGradient.duplicatePosition')}</div>
                )}
              </div>
            );
          })}
          <Button
            size="sm"
            variant="ghost"
            aria-label={t('style.lineGradient.addStop')}
            onClick={addStop}
            className="h-7 text-xs gap-1"
          >
            <Plus className="h-3 w-3" /> {t('style.lineGradient.addStop')}
          </Button>
        </div>
      )}

      <div className="border-t pt-2">
        <button
          type="button"
          aria-label={t('style.lineGradient.advanced')}
          aria-expanded={advancedOpen}
          className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
          onClick={() => (advancedOpen ? cancelAdvanced() : openAdvanced())}
        >
          {advancedOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3 rtl-mirror" />}
          <Code className="h-3 w-3" />
          {t('style.lineGradient.advanced')}
        </button>
        {advancedOpen && (
          <div className="mt-2 space-y-1.5">
            <div className="text-xs italic text-muted-foreground">{t('style.lineGradient.advancedHint')}</div>
            <textarea
              aria-label={t('style.lineGradient.advanced')}
              className="w-full rounded border border-input bg-background p-2 text-xs font-mono resize-y min-h-[80px] outline-none focus:ring-1 focus:ring-ring"
              value={advancedText}
              onChange={(e) => { setAdvancedText(e.target.value); setAdvancedError(null); }}
              spellCheck={false}
            />
            {advancedError && (
              <div className="text-xs text-destructive">
                {advancedError === 'parseError' ? t('style.lineGradient.parseError') : t('style.lineGradient.structureError')}
              </div>
            )}
            <div className="flex gap-1.5">
              <Button size="sm" className="h-6 text-xs px-2" aria-label={t('style.lineGradient.applyExpression')} onClick={applyAdvanced}>
                {t('style.lineGradient.applyExpression')}
              </Button>
              <Button size="sm" variant="ghost" className="h-6 text-xs px-2" aria-label={t('style.lineGradient.cancelExpression')} onClick={cancelAdvanced}>
                {t('style.lineGradient.cancelExpression')}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
