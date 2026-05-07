import { useEffect, useMemo, useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { SliderRow } from './HeatmapStyleControls';
import {
  buildZoomExpression,
  parseZoomExpression,
  validateZoomExpressionDraft,
  type ZoomExpression,
  type ZoomExpressionDraft,
  type ZoomExpressionKind,
} from '@/lib/zoom-expressions';
import { formatNumber } from '@/lib/format';
import { cn } from '@/lib/utils';

type NumericFormat = 'percent' | 'px' | 'zoom';

interface ZoomExpressionEditorProps {
  label: string;
  value: number | ZoomExpression | unknown;
  defaultValue: number;
  min: number;
  max: number;
  step: number;
  format?: NumericFormat;
  onChange: (value: number | ZoomExpression) => void;
}

const MAX_STOPS = 6;
const DEFAULT_ZOOM_GAP = 4;

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function formatDisplayValue(value: number, format?: NumericFormat): string {
  if (format === 'percent') {
    return formatNumber(value, { style: 'percent', maximumFractionDigits: 0 });
  }
  if (format === 'px') return `${formatNumber(value, { maximumFractionDigits: 2 })}px`;
  if (format === 'zoom') return formatNumber(value, { maximumFractionDigits: 0 });
  return formatNumber(value);
}

function clampValue(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function createDraft(kind: ZoomExpressionKind, fixedValue: number): ZoomExpressionDraft {
  if (kind === 'step') {
    return {
      kind,
      baseValue: fixedValue,
      stops: [{ zoom: 10, value: fixedValue }],
    };
  }
  return {
    kind,
    stops: [
      { zoom: 4, value: fixedValue },
      { zoom: 12, value: fixedValue },
    ],
  };
}

function minStops(kind: ZoomExpressionKind): number {
  return kind === 'step' ? 1 : 2;
}

function numericInputValue(value: number | undefined): string {
  return isFiniteNumber(value) ? String(value) : '';
}

export function ZoomExpressionEditor({
  label,
  value,
  defaultValue,
  min,
  max,
  step,
  format,
  onChange,
}: ZoomExpressionEditorProps) {
  const { t } = useTranslation('builder');
  const parsed = useMemo(() => parseZoomExpression(value), [value]);
  const isUnsupportedExpression = Array.isArray(value) && !parsed;
  const scalarValue = isFiniteNumber(value) ? value : defaultValue;
  const fixedValue = parsed
    ? (parsed.kind === 'step' ? parsed.baseValue : parsed.stops[0]?.value) ?? scalarValue
    : scalarValue;
  const [mode, setMode] = useState<'fixed' | 'zoom'>(parsed ? 'zoom' : 'fixed');
  const [draft, setDraft] = useState<ZoomExpressionDraft>(() => parsed ?? createDraft('interpolate', fixedValue));

  useEffect(() => {
    setMode(parsed ? 'zoom' : 'fixed');
    setDraft(parsed ?? createDraft('interpolate', fixedValue));
  }, [parsed, fixedValue]);

  const validation = validateZoomExpressionDraft(draft);
  const canRemoveStop = draft.stops.length > minStops(draft.kind);
  const canAddStop = draft.stops.length < MAX_STOPS;

  function emitDraft(nextDraft: ZoomExpressionDraft) {
    const nextValidation = validateZoomExpressionDraft(nextDraft);
    setDraft(nextDraft);
    if (nextValidation.ok) {
      onChange(buildZoomExpression(nextDraft));
    }
  }

  function switchToFixed() {
    setMode('fixed');
    onChange(fixedValue);
  }

  function switchToZoom() {
    const nextDraft = parsed ?? createDraft(draft.kind, fixedValue);
    setMode('zoom');
    emitDraft(nextDraft);
  }

  function setKind(kind: ZoomExpressionKind) {
    const firstValue = draft.kind === 'step' ? draft.baseValue : draft.stops[0]?.value;
    const nextDraft = createDraft(kind, isFiniteNumber(firstValue) ? firstValue : fixedValue);
    emitDraft(nextDraft);
  }

  function updateStop(index: number, patch: Partial<{ zoom: number; value: number }>) {
    emitDraft({
      ...draft,
      stops: draft.stops.map((stop, stopIndex) => (stopIndex === index ? { ...stop, ...patch } : stop)),
    });
  }

  function addStop() {
    if (!canAddStop) return;
    const previous = draft.stops[draft.stops.length - 1] ?? { zoom: 4, value: fixedValue };
    emitDraft({
      ...draft,
      stops: [
        ...draft.stops,
        {
          zoom: previous.zoom + DEFAULT_ZOOM_GAP,
          value: clampValue(previous.value, min, max),
        },
      ],
    });
  }

  function removeStop(index: number) {
    if (!canRemoveStop) return;
    emitDraft({
      ...draft,
      stops: draft.stops.filter((_, stopIndex) => stopIndex !== index),
    });
  }

  if (isUnsupportedExpression) {
    return (
      <div className="space-y-1.5">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-muted-foreground w-20">{label}</span>
          <p className="flex-1 text-xs text-warning-foreground bg-warning/15 rounded px-2 py-1">
            {t('style.zoomExpression.unsupported')}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-xs text-muted-foreground w-20">{label}</span>
        <div className="flex flex-1 rounded-md border bg-muted/30 p-0.5" role="group" aria-label={`${label} mode`}>
          <button
            type="button"
            aria-pressed={mode === 'fixed'}
            className={cn(
              'flex-1 cursor-pointer rounded px-2 py-1 text-xs transition-colors',
              mode === 'fixed' ? 'bg-background text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground',
            )}
            onClick={switchToFixed}
          >
            {t('style.zoomExpression.fixed')}
          </button>
          <button
            type="button"
            aria-pressed={mode === 'zoom'}
            className={cn(
              'flex-1 cursor-pointer rounded px-2 py-1 text-xs transition-colors',
              mode === 'zoom' ? 'bg-background text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground',
            )}
            onClick={switchToZoom}
          >
            {t('style.zoomExpression.variesByZoom')}
          </button>
        </div>
      </div>

      {mode === 'fixed' ? (
        <SliderRow
          label={label}
          value={fixedValue}
          min={min}
          max={max}
          step={step}
          display={formatDisplayValue(scalarValue, format)}
          onChange={onChange}
        />
      ) : (
        <div className="ms-20 space-y-2">
          <div className="flex gap-1" role="group" aria-label={t('style.zoomExpression.kindLabel')}>
            {(['interpolate', 'step'] as const).map((kind) => (
              <button
                key={kind}
                type="button"
                aria-pressed={draft.kind === kind}
                className={cn(
                  'flex-1 cursor-pointer rounded border px-2 py-1 text-xs transition-colors',
                  draft.kind === kind
                    ? 'bg-primary text-primary-foreground border-primary'
                    : 'bg-muted/50 text-muted-foreground border-border hover:bg-muted',
                )}
                onClick={() => setKind(kind)}
              >
                {t(`style.zoomExpression.${kind}`)}
              </button>
            ))}
          </div>

          {draft.kind === 'step' && (
            <div className="grid grid-cols-[1fr_5rem] items-center gap-2">
              <span className="text-xs text-muted-foreground">{t('style.zoomExpression.baseValue')}</span>
              <Input
                aria-label={`${label} ${t('style.zoomExpression.baseValue')}`}
                className="h-7 px-2 text-xs"
                type="number"
                min={min}
                max={max}
                step={step}
                value={numericInputValue(draft.baseValue)}
                onChange={(event) => emitDraft({ ...draft, baseValue: event.currentTarget.valueAsNumber })}
              />
            </div>
          )}

          <div className="space-y-1.5">
            {draft.stops.map((stop, index) => (
              <div key={index} className="grid grid-cols-[1fr_1fr_1.5rem] items-center gap-1.5">
                <Input
                  aria-label={`${label} ${t('style.zoomExpression.stopZoom', { index: index + 1 })}`}
                  className="h-7 px-2 text-xs"
                  type="number"
                  min={0}
                  max={22}
                  step={0.5}
                  value={numericInputValue(stop.zoom)}
                  onChange={(event) => updateStop(index, { zoom: event.currentTarget.valueAsNumber })}
                />
                <Input
                  aria-label={`${label} ${t('style.zoomExpression.stopValue', { index: index + 1 })}`}
                  className="h-7 px-2 text-xs"
                  type="number"
                  min={min}
                  max={max}
                  step={step}
                  value={numericInputValue(stop.value)}
                  onChange={(event) => updateStop(index, { value: event.currentTarget.valueAsNumber })}
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  aria-label={`${t('style.zoomExpression.removeStop')} ${index + 1}`}
                  disabled={!canRemoveStop}
                  onClick={() => removeStop(index)}
                >
                  <Trash2 className="h-3 w-3" />
                </Button>
              </div>
            ))}
          </div>

          {validation.errors.length > 0 && (
            <div className="text-xs text-destructive" role="alert">
              {validation.errors[0]}
            </div>
          )}

          <Button
            type="button"
            variant="outline"
            size="xs"
            disabled={!canAddStop}
            onClick={addStop}
          >
            <Plus className="h-3 w-3" />
            {t('style.zoomExpression.addStop')}
          </Button>
        </div>
      )}
    </div>
  );
}
