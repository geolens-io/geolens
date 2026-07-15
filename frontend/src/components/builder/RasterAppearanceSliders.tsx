import { Slider } from '@/components/ui/slider';
import { coalesceFrame } from '@/lib/builder/raf-coalesce';
import { getNumberPaint } from './paint-accessors';
import { RASTER_PAINT_DEFAULTS } from './layer-adapters/raster-adapter';
import { formatNumber } from '@/lib/format';

/**
 * builder-audit #338 DUP-04: the single brightness/contrast/saturation/hue appearance
 * slider surface, previously implemented twice — once in RasterEditor (RenderModeSwitch
 * path) and once in RasterLayerControls (LayerEditorPanel path) with subtly different
 * step values and formatting. Both editors now consume this component so a fix lands once.
 *
 * Fallbacks are read from the adapter's RASTER_PAINT_DEFAULTS (single source of truth)
 * so the editor display and the rendered default cannot diverge.
 */

type TFn = (key: string, opts?: Record<string, unknown>) => string;

type RasterValueFormat = 'decimal2' | 'degrees' | 'ms' | 'percent';

function formatRasterValue(value: number, format: RasterValueFormat): string {
  switch (format) {
    case 'degrees':
      return `${Math.round(value)}°`;
    case 'ms':
      return `${Math.round(value)}ms`;
    case 'percent':
      return `${Math.round(value * 100)}%`;
    case 'decimal2':
    default:
      return formatNumber(value, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
}

export interface RasterSliderRowProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
  format?: RasterValueFormat;
}

/** A single labelled raster slider row, shared by the appearance sliders and the
 *  RasterLayerControls opacity control. */
export function RasterSliderRow({
  label,
  value,
  min,
  max,
  step,
  onChange,
  format = 'decimal2',
}: RasterSliderRowProps) {
  const display = formatRasterValue(value, format);
  return (
    <div className="grid grid-cols-[auto_1fr_auto] items-center gap-2">
      <span className="w-28 shrink-0 text-xs text-muted-foreground">{label}</span>
      <Slider
        min={min}
        max={max}
        step={step}
        value={[value]}
        onValueChange={([v]) => onChange(v ?? min)}
        className="flex-1"
        aria-label={label}
        aria-valuetext={display}
      />
      <span className="w-12 shrink-0 text-end text-xs tabular-nums text-muted-foreground">
        {display}
      </span>
    </div>
  );
}

export interface RasterAppearanceSlidersProps {
  paint: Record<string, unknown>;
  /** Patch a single raster paint key. */
  onPaintProp: (key: string, value: number | string) => void;
  t: TFn;
  /** When set, slider writes are RAF-coalesced per (id, property) — the RenderModeSwitch path. */
  coalesceId?: string;
  /** RasterLayerControls renders brightness-max + range error; RasterEditor does not. */
  showBrightnessMax?: boolean;
  /** RasterLayerControls renders the fade-duration slider; RasterEditor does not. */
  showFade?: boolean;
}

export function RasterAppearanceSliders({
  paint,
  onPaintProp,
  t,
  coalesceId,
  showBrightnessMax = false,
  showFade = false,
}: RasterAppearanceSlidersProps) {
  const brightnessMin = getNumberPaint(paint, 'raster-brightness-min', RASTER_PAINT_DEFAULTS['raster-brightness-min']);
  const brightnessMax = getNumberPaint(paint, 'raster-brightness-max', RASTER_PAINT_DEFAULTS['raster-brightness-max']);
  const hasBrightnessRangeError = showBrightnessMax && brightnessMin > brightnessMax;

  const write = (key: string, value: number) => {
    if (coalesceId) {
      coalesceFrame(`raster-paint:${coalesceId}:${key}`, () => onPaintProp(key, value));
    } else {
      onPaintProp(key, value);
    }
  };

  return (
    <>
      <RasterSliderRow
        label={t('style.raster.brightnessMin', { defaultValue: 'Brightness min' })}
        value={brightnessMin}
        min={0}
        max={1}
        step={0.01}
        onChange={(v) => write('raster-brightness-min', v)}
      />
      {showBrightnessMax && (
        <RasterSliderRow
          label={t('style.raster.brightnessMax', { defaultValue: 'Brightness max' })}
          value={brightnessMax}
          min={0}
          max={1}
          step={0.01}
          onChange={(v) => write('raster-brightness-max', v)}
        />
      )}
      {hasBrightnessRangeError && (
        <p className="rounded-md bg-warning/15 px-2 py-1.5 text-mini leading-snug text-warning">
          {t('style.raster.brightnessRangeError', { defaultValue: 'Brightness min must be less than or equal to brightness max.' })}
        </p>
      )}
      <RasterSliderRow
        label={t('style.raster.contrast', { defaultValue: 'Contrast' })}
        value={getNumberPaint(paint, 'raster-contrast', RASTER_PAINT_DEFAULTS['raster-contrast'])}
        min={-1}
        max={1}
        step={0.05}
        onChange={(v) => write('raster-contrast', v)}
      />
      <RasterSliderRow
        label={t('style.raster.saturation', { defaultValue: 'Saturation' })}
        value={getNumberPaint(paint, 'raster-saturation', RASTER_PAINT_DEFAULTS['raster-saturation'])}
        min={-1}
        max={1}
        step={0.05}
        onChange={(v) => write('raster-saturation', v)}
      />
      <RasterSliderRow
        label={t('style.raster.hueRotate', { defaultValue: 'Hue' })}
        value={getNumberPaint(paint, 'raster-hue-rotate', RASTER_PAINT_DEFAULTS['raster-hue-rotate'])}
        min={0}
        max={360}
        step={1}
        format="degrees"
        onChange={(v) => write('raster-hue-rotate', v)}
      />
      {showFade && (
        <RasterSliderRow
          label={t('style.raster.fadeDuration', { defaultValue: 'Fade' })}
          value={getNumberPaint(paint, 'raster-fade-duration', RASTER_PAINT_DEFAULTS['raster-fade-duration'])}
          min={0}
          max={1000}
          step={50}
          format="ms"
          onChange={(v) => write('raster-fade-duration', v)}
        />
      )}
    </>
  );
}
