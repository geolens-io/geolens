import { useEffect, useState, useRef } from 'react';
import { Trash2, Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { StyleColorPicker } from './StyleColorPicker';
import type { BuilderStyleConfig, StyleConfig } from '@/types/api';
import { cn } from '@/lib/utils';

export const DEFAULT_GRADIENT_STOPS: ReadonlyArray<{ position: number; color: string }> = [
  { position: 0, color: '#0066cc' },
  { position: 1, color: '#cc3300' },
];

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
  onBuilderChange: (patch: BuilderStyleConfig) => void;
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

  // Local state for in-progress position edits so we can show validation
  // for transient invalid values (e.g. > 1) without committing them upstream.
  const [pendingPositionEdits, setPendingPositionEdits] = useState<Record<number, number>>({});

  const liveStops: Array<{ position: number; color: string }> | null =
    builderStops && builderStops.length > 0 ? builderStops : parsedFromPaint;
  const isCustomExpression = paintExpr != null && parsedFromPaint == null;

  function commitStops(nextStops: Array<{ position: number; color: string }>) {
    onPaintProp('line-gradient', stopsToLineGradientExpression(nextStops));
    onBuilderChange({ lineGradient: { stops: nextStops } });
  }

  function activateGradient() {
    const stops = (liveStops && liveStops.length >= 2) ? liveStops : [...DEFAULT_GRADIENT_STOPS];
    setMode('gradient');
    commitStops(stops);
  }

  function activateSolid() {
    setMode('solid');
    onPaintProp('line-gradient', undefined);
    onBuilderChange({ lineGradient: undefined });
    if (savedSolidColorRef.current) {
      onPaintProp('line-color', savedSolidColorRef.current);
    }
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
    // Clear pending entry once we commit a valid value.
    setPendingPositionEdits((prev) => {
      const { [index]: _drop, ...rest } = prev;
      void _drop;
      return rest;
    });
    const next = liveStops.map((s, i) => (i === index ? { ...s, position: raw } : s));
    commitStops(next);
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
    </div>
  );
}
