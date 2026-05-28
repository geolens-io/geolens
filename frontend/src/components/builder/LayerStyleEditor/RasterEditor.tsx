import { useState } from 'react';
import { ChevronRight } from 'lucide-react';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { Slider } from '@/components/ui/slider';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';
import { coalesceFrame } from '@/lib/builder/raf-coalesce';
import {
  RASTER_PAINT_DEFAULTS,
  RASTER_OWNED_PAINT_PROPERTIES,
} from '../layer-adapters/raster-adapter';
import type { BaseStyleEditorProps } from './types';

/**
 * RasterEditor — 4 functional sliders (brightness, contrast, saturation,
 * hue-rotate) + Reset collapsible, mirroring BasemapSublayerEditorScene anatomy.
 *
 * Pitfall #9 compliant: all writes route through onPaintProp → RasterAdapter
 * OWNED_PAINT_PROPERTIES. No direct map paint/layout calls in this file.
 * Pitfall #2: Reading values from props.paint with RASTER_PAINT_DEFAULTS fallback
 * guarantees save→reload symmetry (serialize → deserialize → renders identically).
 *
 * coalesceFrame keys are per-layer per-property so last-write-wins within a frame.
 */
export function RasterEditor({ layer, paint, onPaintProp, t }: BaseStyleEditorProps) {
  const [resetOpen, setResetOpen] = useState(false);

  // Read current values from paint props, fall back to MapLibre defaults.
  const brightnessValue =
    typeof paint['raster-brightness-min'] === 'number'
      ? (paint['raster-brightness-min'] as number)
      : RASTER_PAINT_DEFAULTS['raster-brightness-min'];

  const contrastValue =
    typeof paint['raster-contrast'] === 'number'
      ? (paint['raster-contrast'] as number)
      : RASTER_PAINT_DEFAULTS['raster-contrast'];

  const saturationValue =
    typeof paint['raster-saturation'] === 'number'
      ? (paint['raster-saturation'] as number)
      : RASTER_PAINT_DEFAULTS['raster-saturation'];

  const hueValue =
    typeof paint['raster-hue-rotate'] === 'number'
      ? (paint['raster-hue-rotate'] as number)
      : RASTER_PAINT_DEFAULTS['raster-hue-rotate'];

  // Slider write handlers — all route through coalesceFrame + onPaintProp (Pitfall #9).
  const handleBrightnessChange = (next: number) => {
    coalesceFrame(`raster-paint:${layer.id}:raster-brightness-min`, () => {
      onPaintProp('raster-brightness-min', next);
    });
  };

  const handleContrastChange = (next: number) => {
    coalesceFrame(`raster-paint:${layer.id}:raster-contrast`, () => {
      onPaintProp('raster-contrast', next);
    });
  };

  const handleSaturationChange = (next: number) => {
    coalesceFrame(`raster-paint:${layer.id}:raster-saturation`, () => {
      onPaintProp('raster-saturation', next);
    });
  };

  const handleHueChange = (next: number) => {
    coalesceFrame(`raster-paint:${layer.id}:raster-hue-rotate`, () => {
      onPaintProp('raster-hue-rotate', next);
    });
  };

  // Reset: restore all 4 owned properties to MapLibre defaults.
  // Non-destructive (restores to known defaults) — no confirm step needed.
  const handleReset = () => {
    for (const key of RASTER_OWNED_PAINT_PROPERTIES) {
      onPaintProp(key, RASTER_PAINT_DEFAULTS[key]);
    }
  };

  return (
    <>
      {/* APPEARANCE section — 4 slider rows */}
      <section className="border-b">
        <div className="px-4 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2">
            {t('style.raster.title')}
          </p>
          <div className="space-y-3">
            {/* Brightness row */}
            <div className="grid grid-cols-[auto_1fr_auto] gap-2 items-center">
              <Label className="text-xs text-muted-foreground w-28 shrink-0">
                {t('style.raster.brightnessMin')}
              </Label>
              <Slider
                aria-label={t('style.raster.brightnessMin')}
                aria-valuetext={brightnessValue.toFixed(2)}
                value={[brightnessValue]}
                min={0}
                max={1}
                step={0.05}
                onValueChange={([next]) => handleBrightnessChange(next ?? 0)}
              />
              <span className="text-xs tabular-nums text-muted-foreground w-12 shrink-0 text-end">
                {brightnessValue.toFixed(2)}
              </span>
            </div>

            {/* Contrast row */}
            <div className="grid grid-cols-[auto_1fr_auto] gap-2 items-center">
              <Label className="text-xs text-muted-foreground w-28 shrink-0">
                {t('style.raster.contrast')}
              </Label>
              <Slider
                aria-label={t('style.raster.contrast')}
                aria-valuetext={contrastValue.toFixed(2)}
                value={[contrastValue]}
                min={-1}
                max={1}
                step={0.05}
                onValueChange={([next]) => handleContrastChange(next ?? 0)}
              />
              <span className="text-xs tabular-nums text-muted-foreground w-12 shrink-0 text-end">
                {contrastValue.toFixed(2)}
              </span>
            </div>

            {/* Saturation row */}
            <div className="grid grid-cols-[auto_1fr_auto] gap-2 items-center">
              <Label className="text-xs text-muted-foreground w-28 shrink-0">
                {t('style.raster.saturation')}
              </Label>
              <Slider
                aria-label={t('style.raster.saturation')}
                aria-valuetext={saturationValue.toFixed(2)}
                value={[saturationValue]}
                min={-1}
                max={1}
                step={0.05}
                onValueChange={([next]) => handleSaturationChange(next ?? 0)}
              />
              <span className="text-xs tabular-nums text-muted-foreground w-12 shrink-0 text-end">
                {saturationValue.toFixed(2)}
              </span>
            </div>

            {/* Hue-rotate row */}
            <div className="grid grid-cols-[auto_1fr_auto] gap-2 items-center">
              <Label className="text-xs text-muted-foreground w-28 shrink-0">
                {t('style.raster.hueRotate')}
              </Label>
              <Slider
                aria-label={t('style.raster.hueRotate')}
                aria-valuetext={`${Math.round(hueValue)}°`}
                value={[hueValue]}
                min={0}
                max={360}
                step={1}
                onValueChange={([next]) => handleHueChange(next ?? 0)}
              />
              <span className="text-xs tabular-nums text-muted-foreground w-12 shrink-0 text-end">
                {Math.round(hueValue)}°
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* COLORMAP section — gated on band_count === 1 (single-band rasters only).
          _colormap and _stretch are builder-private paint keys that mutate the
          tile URL via buildColormapTileUrl; they never reach MapLibre setPaintProperty
          (Pitfall 6 — they are intentionally absent from RASTER_OWNED_PAINT_PROPERTIES). */}
      {layer.band_count === 1 && (
        <section className="border-b">
          <div className="px-4 py-2">
            <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2">
              {t('style.raster.sectionColormap', { defaultValue: 'COLORMAP' })}
            </p>
            <div className="space-y-3">
              {/* Colormap select row */}
              <div className="flex items-center gap-2">
                <span className="w-28 shrink-0 text-xs text-muted-foreground">
                  {t('style.raster.colormapLabel')}
                </span>
                <Select
                  value={String(paint['_colormap'] ?? 'gray')}
                  onValueChange={(v) => onPaintProp('_colormap', v)}
                >
                  <SelectTrigger className="h-8 text-xs flex-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="gray">{t('style.raster.colormapGray')}</SelectItem>
                    <SelectItem value="viridis">{t('style.raster.colormapViridis')}</SelectItem>
                    <SelectItem value="inferno">{t('style.raster.colormapInferno')}</SelectItem>
                    <SelectItem value="plasma">{t('style.raster.colormapPlasma')}</SelectItem>
                    <SelectItem value="magma">{t('style.raster.colormapMagma')}</SelectItem>
                    <SelectItem value="ylorrd">{t('style.raster.colormapYlorrd')}</SelectItem>
                    <SelectItem value="bugn">{t('style.raster.colormapBugn')}</SelectItem>
                    <SelectItem value="terrain">{t('style.raster.colormapTerrain')}</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Stretch select row — Option A: minmax is the only active option;
                  percentile and stddev render as disabled with a "coming soon" suffix
                  so the roadmap is signaled without ever silently no-op-ing.
                  Backend stats-based percentile/stddev computation is the v1032 follow-up. */}
              <div className="flex items-center gap-2">
                <span className="w-28 shrink-0 text-xs text-muted-foreground">
                  {t('style.raster.stretchLabel')}
                </span>
                <Select
                  value={String(paint['_stretch'] ?? 'minmax')}
                  onValueChange={(v) => onPaintProp('_stretch', v)}
                >
                  <SelectTrigger className="h-8 text-xs flex-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="minmax">{t('style.raster.stretchMinmax')}</SelectItem>
                    <SelectItem value="percentile" disabled>
                      {`${t('style.raster.stretchPercentile')} (${t('style.raster.stretchComingSoon')})`}
                    </SelectItem>
                    <SelectItem value="stddev" disabled>
                      {`${t('style.raster.stretchStddev')} (${t('style.raster.stretchComingSoon')})`}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Reset section — collapsible, closed by default (non-destructive) */}
      <Collapsible open={resetOpen} onOpenChange={setResetOpen}>
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full items-center gap-2 px-4 py-2 hover:bg-[var(--surface-2,theme(colors.muted.DEFAULT))] border-b"
          >
            <ChevronRight
              className={cn(
                'h-4 w-4 shrink-0 transition-transform duration-[--motion-fast]',
                resetOpen && 'rotate-90',
              )}
              aria-hidden="true"
            />
            <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              {t('style.raster.reset')}
            </span>
            {!resetOpen && (
              <span className="ml-auto text-xs text-muted-foreground">
                {t('style.raster.resetTitle')}
              </span>
            )}
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="px-4 py-2 border-b">
            <Button type="button" variant="ghost" className="w-full" onClick={handleReset}>
              {t('style.raster.reset')}
            </Button>
          </div>
        </CollapsibleContent>
      </Collapsible>
    </>
  );
}

export default RasterEditor;
