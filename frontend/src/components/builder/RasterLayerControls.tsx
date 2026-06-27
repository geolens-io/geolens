import { RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useTranslation } from 'react-i18next';
import { RasterStretchControls } from './LayerStyleEditor/RasterStretchControls';
import { RasterAppearanceSliders, RasterSliderRow } from './RasterAppearanceSliders';
import { RASTER_PAINT_DEFAULTS } from './layer-adapters/raster-adapter';

// builder-audit DUP-02: derive the reset allowlist from the adapter's
// RASTER_PAINT_DEFAULTS (the documented single source of truth / paint-key
// allowlist) instead of re-hardcoding the 7 keys here.
const RASTER_PAINT_KEYS = Object.keys(RASTER_PAINT_DEFAULTS) as (keyof typeof RASTER_PAINT_DEFAULTS)[];

interface RasterLayerControlsProps {
  paint: Record<string, unknown>;
  onPaintChange: (paint: Record<string, unknown>) => void;
  opacity: number;
  /** Omit to hide the opacity slider (e.g. when the parent owns opacity via a separate control). */
  onOpacityChange?: (value: number) => void;
  isDem?: boolean | null;
  /** Resolved band count — gates the colormap/stretch section (single vs multi-band). */
  bandCount?: number | null;
}

// builder-audit DEAD-01 / DUP-01: this control is raster-only. The former
// renderMode==='hillshade' branch was unreachable dead code — DEM layers route to
// DEMEditorScene (the single hillshade editor) via deriveBuilderEditorScene, never to
// LayerEditorPanel/RasterLayerControls. The hillshade UI + HILLSHADE_PAINT_KEYS + getString
// were deleted. isDem is retained only to suppress the stretch/colormap section for DEMs.
export function RasterLayerControls({
  paint,
  onPaintChange,
  opacity,
  onOpacityChange,
  isDem = false,
  bandCount = null,
}: RasterLayerControlsProps) {
  const { t } = useTranslation('builder');

  const setPaintProp = (key: string, value: unknown) => {
    onPaintChange({ ...paint, [key]: value });
  };

  function handleReset() {
    const nextPaint = { ...paint };
    for (const key of RASTER_PAINT_KEYS) {
      delete nextPaint[key];
    }
    onPaintChange(nextPaint);
    onOpacityChange?.(1);
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
        {t('style.raster.help', { defaultValue: 'Adjust imagery appearance for this layer only.' })}
      </p>

      <RasterAppearanceSliders
        paint={paint}
        onPaintProp={setPaintProp}
        t={t}
        showBrightnessMax
        showFade
      />

      {onOpacityChange && (
        <RasterSliderRow
          label={t('style.raster.opacity', { defaultValue: 'Opacity' })}
          value={opacity}
          min={0}
          max={1}
          step={0.01}
          format="percent"
          onChange={onOpacityChange}
        />
      )}

      <div className="flex items-center gap-2">
        <span className="w-28 shrink-0 text-xs text-muted-foreground">
          {t('style.raster.resampling', { defaultValue: 'Resampling' })}
        </span>
        <Select
          value={paint['raster-resampling'] === 'nearest' ? 'nearest' : 'linear'}
          onValueChange={(v) => setPaintProp('raster-resampling', v as 'linear' | 'nearest')}
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

      {/* Colormap / Stretch (RASTER-STRETCH-03 / UI-01 / UI-02). Shared with
          RasterEditor via RasterStretchControls. onPaintProp merges into the
          full paint dict to match this component's onPaintChange contract.
          Not shown for DEM (terrainrgb) or when band_count is unknown. */}
      <RasterStretchControls
        bandCount={bandCount}
        paint={paint}
        onPaintProp={setPaintProp}
        isDem={isDem}
        t={t}
      />
    </div>
  );
}
