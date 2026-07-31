import { AlertTriangle } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { StyleColorPicker } from '../StyleColorPicker';
import { SliderRow } from '../HeatmapStyleControls';
import { StrokeControls } from './StrokeControls';
import { FillPatternPicker, EXPRESSION_PATTERN } from '../FillPatternPicker';
import { getPaintValue, FILL_DEFAULTS } from './utils';
import type { BaseStyleEditorProps } from './types';
import { formatNumber } from '@/lib/format';

function deriveExtrusionRange(samples: unknown[] | undefined): { min: string; max: string; count: number } | null {
  if (!samples || samples.length === 0) return null;
  // Coerce strings to numbers: dataset_sample_values from the API returns string values
  // (e.g., "573" not 573). Parse both native numbers and numeric strings.
  const numeric = samples
    .map((v) => {
      if (typeof v === 'number') return v;
      if (typeof v === 'string') return parseFloat(v);
      return NaN;
    })
    .filter((v): v is number => Number.isFinite(v));
  if (numeric.length === 0) return null;
  const min = Math.min(...numeric);
  const max = Math.max(...numeric);
  const fmt = (n: number) => formatNumber(n, { maximumFractionDigits: 1 });
  return { min: fmt(min), max: fmt(max), count: numeric.length };
}

export function FillEditor({
  layer,
  paint,
  isDataDriven,
  fillEnabled,
  strokeEnabled,
  onToggleFill,
  onToggleStroke,
  onPaintProp,
  onFillPatternChange,
  onBuilderChange,
  isPolygon,
  numericColumns,
  currentHeightCol,
  t,
}: BaseStyleEditorProps) {
  // fix(#910): fill-color and fill-pattern are mutually exclusive (EDIT-05), so
  // exactly one of the two controls is reachable at a time. The pattern picker
  // is also out in 3D-extrusion mode, where the extrusion companion reads
  // fill-color and a pattern click would reset the whole layer to the default.
  // It stays visible while a pattern IS set, because it is the only way to clear
  // one — selecting a height column with a pattern already applied would
  // otherwise strand the layer with a pattern and no control to remove it.
  // Any present value counts, not just a string: fill-pattern accepts MapLibre
  // expressions, and AdvancedJsonEditor lets one through. A gate that only saw
  // strings would leave the colour picker live on an expression-patterned layer,
  // where editing it writes both keys back — the EDIT-05 breakage this closes.
  const hasFillPattern = paint['fill-pattern'] != null;
  // An ACTIVE pattern always keeps its clearing control, whatever else is true of
  // the layer. Advanced JSON and the AI set_style action write paint through
  // onPaintChange, which bypasses the exclusion in handleStyleConfigChange, so a
  // data-driven or extruded layer can arrive here already carrying a pattern — and
  // hiding the picker then strands it with the pattern winning on the map. Applying
  // a NEW pattern stays gated to plain solid polygons.
  const showPatternPicker = isPolygon && (hasFillPattern || (!isDataDriven && !currentHeightCol));
  // fix(#910, codex P2): an expression-valued pattern is active but unrepresentable
  // as a swatch. Coercing it to undefined made None report aria-pressed while
  // MapLibre drew the expression, so it gets a sentinel: no swatch matches it, and
  // None correctly reads unpressed. Display-only — onChange never emits it.
  const patternValue = !hasFillPattern
    ? undefined
    : typeof paint['fill-pattern'] === 'string'
      ? (paint['fill-pattern'] as string)
      : EXPRESSION_PATTERN;
  return (
    <>
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium">{t('style.fill')}</div>
        <Switch
          checked={fillEnabled}
          onCheckedChange={onToggleFill}
          aria-label={t('style.toggleFill')}
          className="scale-75"
        />
      </div>
      {fillEnabled && (
        <>
          {isDataDriven ? (
            <div className="text-xs text-muted-foreground italic">
              {t('style.styledBy', { column: layer.style_config?.column })}
            </div>
          ) : hasFillPattern ? (
            <div className="text-xs text-muted-foreground italic">
              {t('style.fillColorUnavailablePattern')}
            </div>
          ) : (
            <StyleColorPicker
              label={t('style.color')}
              color={getPaintValue(paint, 'fill-color', FILL_DEFAULTS['fill-color'])}
              onChange={(hex) => onPaintProp('fill-color', hex)}
            />
          )}
          <SliderRow
            label={t('style.fillOpacity')}
            value={getPaintValue(paint, 'fill-opacity', FILL_DEFAULTS['fill-opacity'])}
            min={0} max={1} step={0.01} format="percent"
            onChange={(val) => onPaintProp('fill-opacity', val)}
          />
          {showPatternPicker ? (
            <FillPatternPicker
              value={patternValue}
              onChange={onFillPatternChange}
              t={t}
              clearOnly={isDataDriven || !!currentHeightCol}
            />
          ) : isPolygon && isDataDriven ? (
            <div className="text-xs text-muted-foreground italic">
              {t('style.fillPatternUnavailableDataDriven')}
            </div>
          ) : null}
        </>
      )}
      <StrokeControls
        paint={paint} strokeEnabled={strokeEnabled} onToggleStroke={onToggleStroke}
        colorKey="_outline-color" colorDefault={FILL_DEFAULTS['_outline-color']}
        widthKey="_outline-width" widthDefault={FILL_DEFAULTS['_outline-width']}
        onPaintProp={onPaintProp} t={t}
      />
      {isPolygon && numericColumns.length > 0 && (
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-muted-foreground">{t('style.heightColumn', { defaultValue: 'Height column' })}</span>
          <Select
            value={currentHeightCol}
            onValueChange={(val) => {
              onBuilderChange({ heightColumn: val === '' || val === '__none__' ? undefined : val });
            }}
          >
            <SelectTrigger className="h-8 text-xs w-36" aria-label={t('style.heightColumn', { defaultValue: 'Height column' })}>
              <SelectValue placeholder={t('style.none', { defaultValue: 'None' })} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">{t('style.none', { defaultValue: 'None' })}</SelectItem>
              {numericColumns.map((col) => (
                <SelectItem key={col.name} value={col.name}>{col.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
      {(() => {
        const range = isPolygon && currentHeightCol
          ? deriveExtrusionRange(layer.dataset_sample_values?.[currentHeightCol])
          : null;
        if (!range) return null;
        return (
          <div className="text-xs text-muted-foreground">
            {t('style.extrusionRange', {
              min: range.min,
              max: range.max,
              count: formatNumber(range.count),
              defaultValue: 'Range: {{min}}–{{max}}, {{count}} features',
            })}
          </div>
        );
      })()}
      {isPolygon && currentHeightCol && !(layer.dataset_column_info ?? []).some((col) => col.name === currentHeightCol) && (
        <div className="flex items-start gap-2 rounded-sm bg-warning/15 p-2">
          <AlertTriangle className="h-4 w-4 shrink-0 text-warning mt-0.5" />
          <span className="text-xs text-warning">
            {t('style.heightColumnRemoved', {
              column: currentHeightCol,
              defaultValue: 'Height column “{{column}}” was removed during re-upload. Select a new column or clear this setting.',
            })}
          </span>
        </div>
      )}
    </>
  );
}

export default FillEditor;
