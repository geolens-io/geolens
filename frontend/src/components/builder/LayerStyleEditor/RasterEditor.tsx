import { useState } from 'react';
import { ChevronRight } from 'lucide-react';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import {
  RASTER_PAINT_DEFAULTS,
  RASTER_OWNED_PAINT_PROPERTIES,
} from '../layer-adapters/raster-adapter';
import { RasterAppearanceSliders } from '../RasterAppearanceSliders';
import { RasterStretchControls } from './RasterStretchControls';
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
 * builder-audit #338 DUP-04: the appearance sliders are now the shared
 * RasterAppearanceSliders component (also consumed by RasterLayerControls). The
 * RAF coalesce keys are still per-layer per-property (coalesceId={layer.id}).
 */
export function RasterEditor({ layer, paint, onPaintProp, t }: BaseStyleEditorProps) {
  const [resetOpen, setResetOpen] = useState(false);

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
            <RasterAppearanceSliders
              paint={paint}
              onPaintProp={onPaintProp}
              t={t}
              coalesceId={layer.id}
            />
          </div>
        </div>
      </section>

      {/* COLORMAP/STRETCH section — shared with RasterLayerControls via RasterStretchControls.
          Mounted here for the RenderModeSwitch raster path; band_count is null for the
          vector paths this editor also serves, so the section self-hides there. */}
      <RasterStretchControls
        bandCount={layer.band_count}
        paint={paint}
        onPaintProp={onPaintProp}
        t={t}
      />

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
