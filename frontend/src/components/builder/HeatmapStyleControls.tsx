import { useTranslation } from 'react-i18next';
import { Slider } from '@/components/ui/slider';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { ColorRampPicker } from './ColorRampPicker';
import { buildHeatmapColorExpression } from './layer-adapters/heatmap-adapter';
import type { MapLayerResponse } from '@/types/api';

const NUMERIC_TYPES = new Set([
  'integer', 'numeric', 'real', 'double', 'float',
  'bigint', 'smallint', 'int4', 'int8', 'int2', 'float4', 'float8',
  'double precision', 'int', 'serial', 'bigserial',
]);

function isNumericType(type: string): boolean {
  return NUMERIC_TYPES.has(type.toLowerCase());
}

interface HeatmapStyleControlsProps {
  layer: MapLayerResponse;
  onPaintChange: (layerId: string, paint: Record<string, unknown>) => void;
}

export function HeatmapStyleControls({ layer, onPaintChange }: HeatmapStyleControlsProps) {
  const { t } = useTranslation('builder');
  const paint = layer.paint as Record<string, unknown>;

  // Numeric columns for weight picker
  const numericColumns = (layer.dataset_column_info ?? []).filter((col) =>
    isNumericType(col.type),
  );

  // Current weight column (stored in _heatmap-weight-column custom prop)
  // Use '__none__' sentinel instead of empty string (Radix Select disallows empty string values)
  const NONE_VALUE = '__none__';
  const weightColumn = (paint['_heatmap-weight-column'] as string) ?? NONE_VALUE;

  // Current ramp (stored in _heatmap-ramp custom prop)
  const rampName = (paint['_heatmap-ramp'] as string) ?? 'YlOrRd';

  // Current radius and intensity
  const radius = typeof paint['heatmap-radius'] === 'number' ? (paint['heatmap-radius'] as number) : 30;
  const intensity = typeof paint['heatmap-intensity'] === 'number' ? (paint['heatmap-intensity'] as number) : 1;

  function handleWeightColumnChange(col: string) {
    const newPaint = { ...paint };
    if (col === NONE_VALUE || col === '') {
      // No weight column — constant weight 1
      newPaint['heatmap-weight'] = 1;
      delete newPaint['_heatmap-weight-column'];
    } else {
      newPaint['heatmap-weight'] = ['get', col];
      newPaint['_heatmap-weight-column'] = col;
    }
    onPaintChange(layer.id, newPaint);
  }

  function handleRampChange(name: string) {
    const newPaint = {
      ...paint,
      '_heatmap-ramp': name,
      'heatmap-color': buildHeatmapColorExpression(name),
    };
    onPaintChange(layer.id, newPaint);
  }

  function handleRadiusChange(val: number) {
    onPaintChange(layer.id, { ...paint, 'heatmap-radius': val });
  }

  function handleIntensityChange(val: number) {
    onPaintChange(layer.id, { ...paint, 'heatmap-intensity': val });
  }

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
        <HeatmapSliderRow
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
        <HeatmapSliderRow
          label={t('style.heatmap.intensity')}
          value={intensity}
          min={0.1}
          max={5.0}
          step={0.1}
          display={intensity.toFixed(1)}
          onChange={handleIntensityChange}
        />
      </div>
    </div>
  );
}

interface HeatmapSliderRowProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  display: string;
  onChange: (val: number) => void;
}

function HeatmapSliderRow({ label, value, min, max, step, display, onChange }: HeatmapSliderRowProps) {
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
      <span className="text-xs text-muted-foreground w-10 text-right">{display}</span>
    </div>
  );
}
