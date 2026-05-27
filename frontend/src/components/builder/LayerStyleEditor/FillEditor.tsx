import { AlertTriangle } from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { StyleColorPicker } from '../StyleColorPicker';
import { SliderRow } from '../HeatmapStyleControls';
import { StrokeControls } from './StrokeControls';
import { getPaintValue, FILL_DEFAULTS } from './utils';
import type { BaseStyleEditorProps } from './types';

function deriveExtrusionRange(samples: unknown[] | undefined): { min: string; max: string; count: number } | null {
  if (!samples || samples.length === 0) return null;
  const numeric = samples.filter((v): v is number => typeof v === 'number' && Number.isFinite(v));
  if (numeric.length === 0) return null;
  const min = Math.min(...numeric);
  const max = Math.max(...numeric);
  const fmt = (n: number) => (Number.isInteger(n) ? n.toLocaleString() : n.toFixed(1));
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
  onBuilderChange,
  isPolygon,
  numericColumns,
  currentHeightCol,
  t,
}: BaseStyleEditorProps) {
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
          ) : (
            <StyleColorPicker
              label={t('style.color')}
              color={getPaintValue(paint, 'fill-color', FILL_DEFAULTS['fill-color'])}
              onChange={(hex) => onPaintProp('fill-color', hex)}
            />
          )}
          <SliderRow
            label={t('style.opacity')}
            value={getPaintValue(paint, 'fill-opacity', FILL_DEFAULTS['fill-opacity'])}
            min={0} max={1} step={0.01} format="percent"
            onChange={(val) => onPaintProp('fill-opacity', val)}
          />
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
            <SelectTrigger className="h-8 text-xs w-36">
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
              count: range.count.toLocaleString(),
              defaultValue: 'Range: {{min}}–{{max}}, {{count}} features',
            })}
          </div>
        );
      })()}
      {isPolygon && currentHeightCol && !(layer.dataset_column_info ?? []).some((col) => col.name === currentHeightCol) && (
        <div className="flex items-start gap-2 rounded bg-warning/15 p-2">
          <AlertTriangle className="h-4 w-4 shrink-0 text-warning-foreground mt-0.5" />
          <span className="text-xs text-warning-foreground">
            Height column &ldquo;{currentHeightCol}&rdquo; was removed during re-upload. Select a new column or clear this setting.
          </span>
        </div>
      )}
    </>
  );
}

export default FillEditor;
