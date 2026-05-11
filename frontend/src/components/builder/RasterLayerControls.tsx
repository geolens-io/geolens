import { RotateCcw } from 'lucide-react';
import { Slider } from '@/components/ui/slider';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { formatNumber } from '@/lib/format';
import { useTranslation } from 'react-i18next';
import { StyleColorPicker } from './StyleColorPicker';
import type { StyleConfig } from '@/types/api';

const RASTER_PAINT_KEYS = [
  'raster-brightness-min',
  'raster-brightness-max',
  'raster-contrast',
  'raster-saturation',
  'raster-hue-rotate',
  'raster-resampling',
  'raster-fade-duration',
] as const;

type RasterPaintKey = typeof RASTER_PAINT_KEYS[number];

const HILLSHADE_PAINT_KEYS = [
  'hillshade-illumination-direction',
  'hillshade-illumination-anchor',
  'hillshade-exaggeration',
  'hillshade-shadow-color',
  'hillshade-highlight-color',
  'hillshade-accent-color',
] as const;

type HillshadePaintKey = typeof HILLSHADE_PAINT_KEYS[number];

interface RasterLayerControlsProps {
  paint: Record<string, unknown>;
  onPaintChange: (paint: Record<string, unknown>) => void;
  opacity: number;
  onOpacityChange: (value: number) => void;
  isDem?: boolean | null;
  styleConfig?: Partial<StyleConfig> | null;
  onStyleConfigChange?: (config: StyleConfig | null, paint: Record<string, unknown>) => void;
}

export function RasterLayerControls({
  paint,
  onPaintChange,
  opacity,
  onOpacityChange,
  isDem = false,
  styleConfig = null,
  onStyleConfigChange,
}: RasterLayerControlsProps) {
  const { t } = useTranslation('builder');
  const renderMode = isDem && styleConfig?.render_mode === 'hillshade' ? 'hillshade' : 'raster';
  const brightnessMin = getNumber('raster-brightness-min', 0);
  const brightnessMax = getNumber('raster-brightness-max', 1);
  const hasBrightnessRangeError = renderMode === 'raster' && brightnessMin > brightnessMax;

  function getNumber(key: RasterPaintKey | HillshadePaintKey, fallback: number): number {
    return typeof paint[key] === 'number' ? paint[key] : fallback;
  }

  function getString(key: HillshadePaintKey, fallback: string): string {
    return typeof paint[key] === 'string' ? paint[key] : fallback;
  }

  function setPaintValue(key: RasterPaintKey | HillshadePaintKey, value: number | string) {
    onPaintChange({ ...paint, [key]: value });
  }

  function setRenderMode(mode: 'raster' | 'hillshade') {
    const nextConfig = { ...(styleConfig ?? {}) } as Record<string, unknown>;
    if (mode === 'hillshade') {
      nextConfig.render_mode = 'hillshade';
    } else {
      delete nextConfig.render_mode;
    }
    onStyleConfigChange?.(Object.keys(nextConfig).length > 0 ? nextConfig as StyleConfig : null, paint);
  }

  function handleReset() {
    const nextPaint = { ...paint };
    for (const key of RASTER_PAINT_KEYS) {
      delete nextPaint[key];
    }
    for (const key of HILLSHADE_PAINT_KEYS) {
      delete nextPaint[key];
    }
    onPaintChange(nextPaint);
    onOpacityChange(1);
  }

  return (
    <div className="space-y-3 px-2 pb-2 pt-1">
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-medium">
          {t('style.raster.title', { defaultValue: 'Raster' })}
        </div>
        <Button
          type="button"
          variant="ghost"
          size="xs"
          onClick={handleReset}
          title={t('style.raster.resetTitle', { defaultValue: 'Reset raster style' })}
        >
          <RotateCcw className="h-3 w-3" />
          {t('style.raster.reset', { defaultValue: 'Reset' })}
        </Button>
      </div>
      <p className="text-[11px] leading-snug text-muted-foreground">
        {renderMode === 'hillshade'
          ? t('style.hillshade.help', { defaultValue: 'Tune the relief overlay generated from this DEM layer.' })
          : t('style.raster.help', { defaultValue: 'Adjust imagery appearance for this layer only.' })}
      </p>

      {isDem && (
        <div className="flex items-center gap-2">
          <span className="w-28 shrink-0 text-xs text-muted-foreground">
            {t('style.raster.renderMode', { defaultValue: 'Render' })}
          </span>
          <Select
            value={renderMode}
            onValueChange={(v) => setRenderMode(v as 'raster' | 'hillshade')}
          >
            <SelectTrigger
              aria-label={t('style.raster.renderMode', { defaultValue: 'Render' })}
              className="h-8 flex-1 text-xs"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="raster" className="text-xs">
                {t('style.raster.renderRaster', { defaultValue: 'Raster' })}
              </SelectItem>
              <SelectItem value="hillshade" className="text-xs">
                {t('style.raster.renderHillshade', { defaultValue: 'Hillshade' })}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
      )}

      {renderMode === 'hillshade' ? (
        <>
          <RasterSliderRow
            label={t('style.hillshade.direction', { defaultValue: 'Direction' })}
            value={getNumber('hillshade-illumination-direction', 335)}
            min={0}
            max={359}
            step={1}
            suffix="deg"
            onChange={(v) => setPaintValue('hillshade-illumination-direction', v)}
          />
          <div className="flex items-center gap-2">
            <span className="w-28 shrink-0 text-xs text-muted-foreground">
              {t('style.hillshade.anchor', { defaultValue: 'Anchor' })}
            </span>
            <Select
              value={getString('hillshade-illumination-anchor', 'viewport')}
              onValueChange={(v) => setPaintValue('hillshade-illumination-anchor', v)}
            >
              <SelectTrigger
                aria-label={t('style.hillshade.anchor', { defaultValue: 'Anchor' })}
                className="h-8 flex-1 text-xs"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="viewport" className="text-xs">
                  {t('style.hillshade.anchorViewport', { defaultValue: 'Viewport' })}
                </SelectItem>
                <SelectItem value="map" className="text-xs">
                  {t('style.hillshade.anchorMap', { defaultValue: 'Map' })}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <RasterSliderRow
            label={t('style.hillshade.exaggeration', { defaultValue: 'Relief' })}
            value={getNumber('hillshade-exaggeration', 0.5)}
            min={0}
            max={1}
            step={0.05}
            onChange={(v) => setPaintValue('hillshade-exaggeration', v)}
          />
          <StyleColorPicker
            label={t('style.hillshade.shadow', { defaultValue: 'Shadow' })}
            color={getString('hillshade-shadow-color', '#000000')}
            onChange={(v) => setPaintValue('hillshade-shadow-color', v)}
          />
          <StyleColorPicker
            label={t('style.hillshade.highlight', { defaultValue: 'Highlight' })}
            color={getString('hillshade-highlight-color', '#ffffff')}
            onChange={(v) => setPaintValue('hillshade-highlight-color', v)}
          />
          <StyleColorPicker
            label={t('style.hillshade.accent', { defaultValue: 'Accent' })}
            color={getString('hillshade-accent-color', '#000000')}
            onChange={(v) => setPaintValue('hillshade-accent-color', v)}
          />
        </>
      ) : (
        <>
      <RasterSliderRow
        label={t('style.raster.brightnessMin', { defaultValue: 'Brightness min' })}
        value={brightnessMin}
        min={0}
        max={1}
        step={0.01}
        format="percent"
        onChange={(v) => setPaintValue('raster-brightness-min', v)}
      />
      <RasterSliderRow
        label={t('style.raster.brightnessMax', { defaultValue: 'Brightness max' })}
        value={brightnessMax}
        min={0}
        max={1}
        step={0.01}
        format="percent"
        onChange={(v) => setPaintValue('raster-brightness-max', v)}
      />
      {hasBrightnessRangeError && (
        <p className="rounded-md bg-warning/15 px-2 py-1.5 text-[11px] leading-snug text-warning-foreground">
          {t('style.raster.brightnessRangeError', { defaultValue: 'Brightness min must be less than or equal to brightness max.' })}
        </p>
      )}
      <RasterSliderRow
        label={t('style.raster.contrast', { defaultValue: 'Contrast' })}
        value={getNumber('raster-contrast', 0)}
        min={-1}
        max={1}
        step={0.05}
        signed
        onChange={(v) => setPaintValue('raster-contrast', v)}
      />
      <RasterSliderRow
        label={t('style.raster.saturation', { defaultValue: 'Saturation' })}
        value={getNumber('raster-saturation', 0)}
        min={-1}
        max={1}
        step={0.05}
        signed
        onChange={(v) => setPaintValue('raster-saturation', v)}
      />
      <RasterSliderRow
        label={t('style.raster.hueRotate', { defaultValue: 'Hue' })}
        value={getNumber('raster-hue-rotate', 0)}
        min={0}
        max={360}
        step={1}
        suffix="deg"
        onChange={(v) => setPaintValue('raster-hue-rotate', v)}
      />
      <RasterSliderRow
        label={t('style.raster.fadeDuration', { defaultValue: 'Fade' })}
        value={getNumber('raster-fade-duration', 300)}
        min={0}
        max={1000}
        step={50}
        suffix="ms"
        onChange={(v) => setPaintValue('raster-fade-duration', v)}
      />
      <RasterSliderRow
        label={t('style.raster.opacity', { defaultValue: 'Opacity' })}
        value={opacity}
        min={0}
        max={1}
        step={0.01}
        format="percent"
        onChange={onOpacityChange}
      />

      <div className="flex items-center gap-2">
        <span className="w-28 shrink-0 text-xs text-muted-foreground">
          {t('style.raster.resampling', { defaultValue: 'Resampling' })}
        </span>
        <Select
          value={paint['raster-resampling'] === 'nearest' ? 'nearest' : 'linear'}
          onValueChange={(v) => setPaintValue('raster-resampling', v as 'linear' | 'nearest')}
        >
          <SelectTrigger className="h-8 flex-1 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="linear" className="text-xs">
              {t('style.raster.resamplingLinear', { defaultValue: 'Linear' })}
            </SelectItem>
            <SelectItem value="nearest" className="text-xs">
              {t('style.raster.resamplingNearest', { defaultValue: 'Nearest' })}
            </SelectItem>
          </SelectContent>
        </Select>
      </div>
        </>
      )}
    </div>
  );
}

interface RasterSliderRowProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
  format?: 'percent';
  signed?: boolean;
  suffix?: string;
}

function RasterSliderRow({
  label,
  value,
  min,
  max,
  step,
  onChange,
  format,
  signed,
  suffix,
}: RasterSliderRowProps) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-28 shrink-0 text-xs text-muted-foreground">{label}</span>
      <Slider
        min={min}
        max={max}
        step={step}
        value={[value]}
        onValueChange={([v]) => onChange(v)}
        className="flex-1"
        aria-label={label}
      />
      <span className="w-12 shrink-0 text-end text-xs tabular-nums text-muted-foreground">
        {formatRasterValue(value, { format, signed, suffix })}
      </span>
    </div>
  );
}

function formatRasterValue(
  value: number,
  options: Pick<RasterSliderRowProps, 'format' | 'signed' | 'suffix'>,
) {
  if (options.format === 'percent') {
    return formatNumber(value, { style: 'percent', maximumFractionDigits: 0 });
  }

  const formatted = formatNumber(value, { maximumFractionDigits: 2 });
  const prefix = options.signed && value > 0 ? '+' : '';
  return `${prefix}${formatted}${options.suffix ?? ''}`;
}
