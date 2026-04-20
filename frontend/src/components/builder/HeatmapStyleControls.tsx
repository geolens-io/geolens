import { memo, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { Slider } from '@/components/ui/slider';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { ColorRampPicker } from './ColorRampPicker';
import { buildHeatmapColorExpression } from './layer-adapters/heatmap-adapter';
import { isNumericColumn } from '@/lib/column-utils';
import type { MapLayerResponse } from '@/types/api';

/** Radix Select disallows empty string values; use sentinel for "no weight". */
const NONE_VALUE = '__none__';

interface HeatmapStyleControlsProps {
  layer: MapLayerResponse;
  onPaintChange: (layerId: string, paint: Record<string, unknown>) => void;
}

export const HeatmapStyleControls = memo(function HeatmapStyleControls({
  layer,
  onPaintChange,
}: HeatmapStyleControlsProps) {
  const { t } = useTranslation('builder');
  const paint = layer.paint as Record<string, unknown>;

  const numericColumns = useMemo(
    () => (layer.dataset_column_info ?? []).filter((col) => isNumericColumn(col.type)),
    [layer.dataset_column_info],
  );

  const weightColumn = (paint['_heatmap-weight-column'] as string) ?? NONE_VALUE;
  const rampName = (paint['_heatmap-ramp'] as string) ?? 'YlOrRd';
  const radius = typeof paint['heatmap-radius'] === 'number' ? (paint['heatmap-radius'] as number) : 30;
  const intensity = typeof paint['heatmap-intensity'] === 'number' ? (paint['heatmap-intensity'] as number) : 1;

  const handleWeightColumnChange = useCallback((col: string) => {
    const newPaint = { ...paint };
    if (col === NONE_VALUE || col === '') {
      newPaint['heatmap-weight'] = 1;
      delete newPaint['_heatmap-weight-column'];
    } else {
      newPaint['heatmap-weight'] = ['get', col];
      newPaint['_heatmap-weight-column'] = col;
    }
    onPaintChange(layer.id, newPaint);
  }, [paint, layer.id, onPaintChange]);

  const handleRampChange = useCallback((name: string) => {
    onPaintChange(layer.id, {
      ...paint,
      '_heatmap-ramp': name,
      'heatmap-color': buildHeatmapColorExpression(name),
    });
  }, [paint, layer.id, onPaintChange]);

  const handleRadiusChange = useCallback((val: number) => {
    onPaintChange(layer.id, { ...paint, 'heatmap-radius': val });
  }, [paint, layer.id, onPaintChange]);

  const handleIntensityChange = useCallback((val: number) => {
    onPaintChange(layer.id, { ...paint, 'heatmap-intensity': val });
  }, [paint, layer.id, onPaintChange]);

  return (
    <div className="space-y-3">
      {/* Weight column */}
      <div className="space-y-1">
        <div className="text-xs font-medium">{t('style.heatmap.weight')}</div>
        <Select value={weightColumn} onValueChange={handleWeightColumnChange}>
          <SelectTrigger className="h-8 text-xs">
            <SelectValue placeholder={t('style.heatmap.weightNone')} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE_VALUE}>{t('style.heatmap.weightNone')}</SelectItem>
            {numericColumns.map((col) => (
              <SelectItem key={col.name} value={col.name}>
                {col.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Color ramp */}
      <div className="space-y-1">
        <div className="text-xs font-medium">{t('style.heatmap.colorRamp')}</div>
        <ColorRampPicker rampName={rampName} onChange={handleRampChange} mode="graduated" />
      </div>

      {/* Radius */}
      <div className="space-y-1">
        <SliderRow
          label={t('style.heatmap.radius')}
          value={radius}
          min={1}
          max={100}
          step={1}
          display={`${radius}px`}
          onChange={handleRadiusChange}
        />
      </div>

      {/* Intensity */}
      <div className="space-y-1">
        <SliderRow
          label={t('style.heatmap.intensity')}
          value={intensity}
          min={0.1}
          max={5.0}
          step={0.1}
          display={intensity.toFixed(1)}
          onChange={handleIntensityChange}
        />
      </div>

      {/* Opacity */}
      <div className="space-y-1">
        <SliderRow
          label={t('style.heatmap.opacity', { defaultValue: 'Opacity' })}
          value={typeof paint['heatmap-opacity'] === 'number' ? (paint['heatmap-opacity'] as number) : 0.8}
          min={0}
          max={1}
          step={0.05}
          format="percent"
          onChange={(val) => onPaintChange(layer.id, { ...paint, 'heatmap-opacity': val })}
        />
      </div>
    </div>
  );
});

interface SliderRowProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (val: number) => void;
  /** Pre-computed display string. Takes precedence over `format`. */
  display?: string;
  /** Format shorthand: percent (0-1 → "50%"), px ("5px"), zoom ("3"). */
  format?: 'percent' | 'px' | 'zoom';
}

function formatValue(value: number, format?: 'percent' | 'px' | 'zoom'): string {
  if (format === 'percent') return `${Math.round(value * 100)}%`;
  if (format === 'px') return `${value}px`;
  return `${value}`;
}

/** Shared slider row component used by heatmap controls and style editor. */
export function SliderRow({ label, value, min, max, step, display, format, onChange }: SliderRowProps) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground w-20">{label}</span>
      <Slider
        value={[value]}
        min={min}
        max={max}
        step={step}
        onValueChange={([v]) => onChange(v)}
        className="flex-1"
      />
      <span className="text-xs text-muted-foreground w-10 text-end">
        {display ?? formatValue(value, format)}
      </span>
    </div>
  );
}
