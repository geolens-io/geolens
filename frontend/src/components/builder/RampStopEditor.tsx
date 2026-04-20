import { useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, X } from 'lucide-react';
import { HexColorPicker } from 'react-colorful';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Button } from '@/components/ui/button';

interface ColorStop {
  value: number;
  color: string;
}

interface RampStopEditorProps {
  /** The data-driven paint expression (step or interpolate). */
  expression: unknown[];
  /** Column name driving the ramp. */
  column: string;
  /** Called with a rebuilt expression whenever stops change. */
  onChange: (expression: unknown[]) => void;
}

/**
 * Parse a `step` or `interpolate` expression into an array of {value, color} stops.
 *
 * step format:     ["step", ["get", col], defaultColor, break0, color1, break1, color2, ...]
 * interpolate fmt: ["interpolate", ["linear"], ["get", col], val0, color0, val1, color1, ...]
 *
 * For `step`, the defaultColor applies below the first break.
 * For `interpolate`, stops are value/color pairs starting at index 3.
 */
function parseStops(expr: unknown[]): { kind: 'step' | 'interpolate'; stops: ColorStop[]; defaultColor?: string } | null {
  if (!Array.isArray(expr)) return null;

  // Unwrap a `case` guard: ["case", null-check, "#ccc", stepExpr]
  let inner = expr;
  if (inner[0] === 'case' && Array.isArray(inner[3])) {
    inner = inner[3] as unknown[];
  }

  const op = inner[0];

  if (op === 'step') {
    // ["step", ["get", col], defaultColor, break0, color1, break1, color2, ...]
    const defaultColor = typeof inner[2] === 'string' ? inner[2] : '#cccccc';
    const stops: ColorStop[] = [{ value: -Infinity, color: defaultColor }];
    for (let i = 3; i < inner.length; i += 2) {
      const val = inner[i];
      const col = inner[i + 1];
      if (typeof val === 'number' && typeof col === 'string') {
        stops.push({ value: val, color: col });
      }
    }
    return { kind: 'step', stops, defaultColor };
  }

  if (op === 'interpolate') {
    // ["interpolate", ["linear"], ["get", col], val0, color0, val1, color1, ...]
    const stops: ColorStop[] = [];
    for (let i = 3; i < inner.length; i += 2) {
      const val = inner[i];
      const col = inner[i + 1];
      if (typeof val === 'number' && typeof col === 'string') {
        stops.push({ value: val, color: col });
      }
    }
    return { kind: 'interpolate', stops };
  }

  return null;
}

/** Rebuild the expression from edited stops. */
function buildExpression(
  kind: 'step' | 'interpolate',
  stops: ColorStop[],
  column: string,
): unknown[] {
  if (kind === 'step') {
    const defaultColor = stops[0]?.color ?? '#cccccc';
    const step: unknown[] = ['step', ['get', column], defaultColor];
    for (let i = 1; i < stops.length; i++) {
      step.push(stops[i].value, stops[i].color);
    }
    // Wrap in null guard
    return ['case', ['==', ['get', column], null], '#cccccc', step];
  }

  // interpolate
  const interp: unknown[] = ['interpolate', ['linear'], ['get', column]];
  for (const stop of stops) {
    interp.push(stop.value, stop.color);
  }
  return interp;
}

export function RampStopEditor({ expression, column, onChange }: RampStopEditorProps) {
  const { t } = useTranslation('builder');
  const parsed = useMemo(() => parseStops(expression), [expression]);

  const handleColorChange = useCallback((index: number, color: string) => {
    if (!parsed) return;
    const { kind, stops } = parsed;
    const next = [...stops];
    next[index] = { ...next[index], color };
    onChange(buildExpression(kind, next, column));
  }, [parsed, onChange, column]);

  const handleRemove = useCallback((index: number) => {
    if (!parsed || parsed.stops.length <= 2) return;
    const { kind, stops } = parsed;
    const next = stops.filter((_, i) => i !== index);
    onChange(buildExpression(kind, next, column));
  }, [parsed, onChange, column]);

  const handleAdd = useCallback(() => {
    if (!parsed) return;
    const { kind, stops } = parsed;
    const last = stops[stops.length - 1];
    const secondLast = stops.length >= 2 ? stops[stops.length - 2] : { value: 0 };
    // Guard against -Infinity sentinel in step expressions
    const lastVal = isFinite(last.value) ? last.value : 0;
    const prevVal = isFinite(secondLast.value) ? secondLast.value : lastVal - 10;
    const newValue = Math.round((lastVal + (lastVal - prevVal)) * 100) / 100;
    const next = [...stops, { value: newValue, color: last.color }];
    onChange(buildExpression(kind, next, column));
  }, [parsed, onChange, column]);

  if (!parsed || parsed.stops.length === 0) return null;

  const { stops } = parsed;

  return (
    <div className="mt-2 space-y-1">
      <div className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground mb-1.5">
        {t('inspector.colorStops', { defaultValue: 'Color Stops' })}
      </div>
      {stops.map((stop, i) => (
        <div key={i} className="flex items-center gap-2 group">
          <span className="font-mono text-[11px] text-muted-foreground w-10 text-end tabular-nums shrink-0">
            {stop.value === -Infinity ? '< ' : ''}
            {stop.value === -Infinity
              ? (stops[1]?.value ?? 0)
              : stop.value}
          </span>
          <Popover>
            <PopoverTrigger asChild>
              <button
                className="h-5 flex-1 rounded-sm border border-border/50 cursor-pointer hover:ring-1 hover:ring-primary transition-shadow"
                style={{ backgroundColor: stop.color }}
                aria-label={`${stop.color} at ${stop.value}`}
              />
            </PopoverTrigger>
            <PopoverContent className="w-auto p-3" side="left">
              <HexColorPicker
                color={stop.color}
                onChange={(color) => handleColorChange(i, color)}
              />
            </PopoverContent>
          </Popover>
          <button
            onClick={() => handleRemove(i)}
            disabled={stops.length <= 2}
            className="h-4 w-4 flex items-center justify-center rounded opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive hover:bg-destructive/10 disabled:opacity-0 transition-opacity"
            aria-label={t('common:actions.delete', { defaultValue: 'Remove' })}
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      ))}
      <Button
        variant="ghost"
        size="sm"
        className="w-full text-xs gap-1 h-6 mt-1"
        onClick={handleAdd}
      >
        <Plus className="h-3 w-3" />
        {t('inspector.addStop', { defaultValue: 'Add stop' })}
      </Button>
    </div>
  );
}
