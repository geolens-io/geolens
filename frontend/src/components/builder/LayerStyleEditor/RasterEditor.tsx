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

      {/* COLORMAP/STRETCH section — gate-split:
          - STRETCH: visible for any numeric band_count >= 1 (single AND multi-band)
          - COLORMAP: single-band only (band_count === 1)
          _colormap and _stretch are builder-private paint keys that mutate the
          tile URL via buildColormapTileUrl; they never reach MapLibre setPaintProperty
          (Pitfall 6 — they are intentionally absent from RASTER_OWNED_PAINT_PROPERTIES).
          _pmin / _pmax / _sigma are also builder-private, written only via onPaintProp. */}
      {typeof layer.band_count === 'number' && layer.band_count >= 1 && (() => {
        const isSingleBand = layer.band_count === 1;
        const currentStretch = String(paint['_stretch'] ?? 'minmax');
        const currentColormap = String(paint['_colormap'] ?? 'gray');
        const pmin = typeof paint['_pmin'] === 'number' ? paint['_pmin'] : 2;
        const pmax = typeof paint['_pmax'] === 'number' ? paint['_pmax'] : 98;
        const sigma = typeof paint['_sigma'] === 'number' ? paint['_sigma'] : 2;

        const handlePminChange = (e: React.ChangeEvent<HTMLInputElement>) => {
          const candidate = Number(e.target.value);
          if (candidate >= 0 && candidate < pmax) {
            onPaintProp('_pmin', candidate);
          }
        };

        const handlePmaxChange = (e: React.ChangeEvent<HTMLInputElement>) => {
          const candidate = Number(e.target.value);
          if (candidate > pmin && candidate <= 100) {
            onPaintProp('_pmax', candidate);
          }
        };

        return (
          <section className="border-b">
            <div className="px-4 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2">
                {isSingleBand
                  ? t('style.raster.sectionColormap', { defaultValue: 'COLORMAP' })
                  : t('style.raster.stretchLabel', { defaultValue: 'STRETCH' })}
              </p>
              <div className="space-y-3">
                {/* Colormap select row — single-band only */}
                {isSingleBand && (
                  <div className="flex items-center gap-2">
                    <span className="w-28 shrink-0 text-xs text-muted-foreground">
                      {t('style.raster.colormapLabel')}
                    </span>
                    <Select
                      value={currentColormap}
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
                )}

                {/* Stretch select row — minmax (dtype rescale) / percentile (p2–p98) /
                    stddev (mean±2σ). percentile and stddev compute a stats-based rescale
                    via the raster-proxy → Titiler /cog/statistics (RASTER-STRETCH-01/02).
                    Visible for all band_count >= 1 (RASTER-STRETCH-03). */}
                <div className="flex items-center gap-2">
                  <span className="w-28 shrink-0 text-xs text-muted-foreground">
                    {t('style.raster.stretchLabel')}
                  </span>
                  <Select
                    value={currentStretch}
                    onValueChange={(v) => onPaintProp('_stretch', v)}
                  >
                    <SelectTrigger className="h-8 text-xs flex-1">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="minmax">{t('style.raster.stretchMinmax')}</SelectItem>
                      <SelectItem value="percentile">{t('style.raster.stretchPercentile')}</SelectItem>
                      <SelectItem value="stddev">{t('style.raster.stretchStddev')}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {/* Percentile bounds (RASTER-STRETCH-UI-01) — pmin/pmax inputs */}
                {currentStretch === 'percentile' && (
                  <div className="flex gap-2">
                    <div className="flex-1 flex flex-col gap-1">
                      <Label className="text-xs text-muted-foreground">
                        {t('style.raster.pminLabel')}
                      </Label>
                      <input
                        type="number"
                        className="h-8 text-xs w-full rounded-md border border-input bg-background px-2"
                        min={0}
                        max={100}
                        step={1}
                        value={pmin}
                        onChange={handlePminChange}
                      />
                    </div>
                    <div className="flex-1 flex flex-col gap-1">
                      <Label className="text-xs text-muted-foreground">
                        {t('style.raster.pmaxLabel')}
                      </Label>
                      <input
                        type="number"
                        className="h-8 text-xs w-full rounded-md border border-input bg-background px-2"
                        min={0}
                        max={100}
                        step={1}
                        value={pmax}
                        onChange={handlePmaxChange}
                      />
                    </div>
                  </div>
                )}

                {/* Sigma segmented control (RASTER-STRETCH-UI-01) — 1/2/3 */}
                {currentStretch === 'stddev' && (
                  <div className="flex items-center gap-2">
                    <Label className="w-28 shrink-0 text-xs text-muted-foreground">
                      {t('style.raster.sigmaLabel')}
                    </Label>
                    <div className="flex gap-1">
                      {([1, 2, 3] as const).map((v) => (
                        <button
                          key={v}
                          type="button"
                          aria-pressed={sigma === v}
                          className={cn(
                            'h-8 w-8 text-xs rounded-md border',
                            sigma === v
                              ? 'bg-primary text-primary-foreground border-primary'
                              : 'bg-background text-foreground border-input hover:bg-muted',
                          )}
                          onClick={() => onPaintProp('_sigma', v)}
                        >
                          {v}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* Stretch↔colormap hint (RASTER-STRETCH-UI-02) — single-band only,
                    shown when stretch is not minmax AND colormap is not gray */}
                {isSingleBand && currentStretch !== 'minmax' && currentColormap !== 'gray' && (
                  <p
                    role="note"
                    className="text-[11px] leading-snug text-muted-foreground"
                  >
                    {t('style.raster.stretchColormapHint')}
                  </p>
                )}
              </div>
            </div>
          </section>
        );
      })()}

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
