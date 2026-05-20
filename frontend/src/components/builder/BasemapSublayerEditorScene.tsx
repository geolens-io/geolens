import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronRight } from 'lucide-react';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { Slider } from '@/components/ui/slider';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { StyleColorPicker } from '@/components/builder/StyleColorPicker';

// Phase 1051 Plan 11 (INV-01): DETAIL LEVEL pill strip REMAINS REMOVED.
// Disposition unchanged per Phase 1059 CONTEXT.md D-18 — do not resurrect.
// The activeDetailLevel/isCustomized/onDetailLevelChange props were always
// passed hardcoded defaults from MapBuilderPage; no consumer ever implemented
// sublayer detail-level style mutation.
//
// Phase 1059 BSE-01 (Path B FIX): STROKE + CASING + ZOOM sections RESTORED with
// a working persistence path through MapBasemapConfig.sublayer_overrides jsonb
// (zero-migration backward compat). Replaces the v1011.1 EMRG-FN-01 REMOVE
// disposition (commits 3629ec04 + 3e48d331). Backend schema: SublayerOverride
// Pydantic model at backend/app/modules/catalog/maps/schemas.py (Plan 1059-01).
// MapLibre style mutation: frontend/src/lib/builder/basemap-style-mutation.ts
// applySublayerOverrides (Plan 1059-02). All 6 new callback props are optional
// for back-compat with callers that haven't wired through yet.

export interface BasemapSublayerEditorSceneProps {
  sublayerId: string;
  sublayerName: string;
  // Existing live props (KEEP unchanged):
  opacity: number;
  onOpacityChange: (opacity: number) => void;
  onResetSublayer: () => void;
  // Phase 1059 BSE-01 new live props — restore EMRG-FN-01-removed surface:
  strokeColor?: string;          // hex #RRGGBB or undefined (= use default)
  strokeWidth?: number;          // 0..20
  casingColor?: string;
  casingWidth?: number;          // 0..20
  minZoom?: number;              // 0..24
  maxZoom?: number;              // 0..24
  onStrokeColorChange?: (color: string) => void;
  onStrokeWidthChange?: (width: number) => void;
  onCasingColorChange?: (color: string) => void;
  onCasingWidthChange?: (width: number) => void;
  onMinZoomChange?: (zoom: number) => void;
  onMaxZoomChange?: (zoom: number) => void;
}

export interface BasemapSublayerEditorFooterProps {
  onBackToBasemap: () => void;
}

export function BasemapSublayerEditorScene({
  sublayerId,
  sublayerName,
  opacity,
  onOpacityChange,
  onResetSublayer,
  strokeColor,
  strokeWidth,
  casingColor,
  casingWidth,
  minZoom,
  maxZoom,
  onStrokeColorChange,
  onStrokeWidthChange,
  onCasingColorChange,
  onCasingWidthChange,
  onMinZoomChange,
  onMaxZoomChange,
}: BasemapSublayerEditorSceneProps) {
  const { t } = useTranslation('builder');
  const [resetOpen, setResetOpen] = useState(false);
  const [confirmingReset, setConfirmingReset] = useState(false);

  // Reset confirmingReset and resetOpen when sublayerId changes.
  // Without resetting resetOpen, navigating from sublayer A (with the RESET collapsible
  // open) to sublayer B would render sublayer B pre-expanded. The LayerEditorPanel uses
  // key={expandedLayerId} for top-level layers, but basemap sublayer navigation reuses
  // the same component instance — so the effect is the only reset mechanism.
  useEffect(() => {
    setConfirmingReset(false);
    setResetOpen(false);
  }, [sublayerId]);

  const safeOpacity = typeof opacity === 'number' && Number.isFinite(opacity) ? opacity : 1;

  return (
    <>
      {/* 1. STROKE section — Phase 1059 BSE-01 restored */}
      <section className="border-b">
        <div className="px-4 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2">
            {t('basemapSublayer.strokeLabel', { defaultValue: 'STROKE' })}
          </p>
          <div className="space-y-3">
            <StyleColorPicker
              label={t('basemapSublayer.strokeColor', { defaultValue: 'Color' })}
              color={strokeColor ?? '#888888'}
              onChange={(hex) => onStrokeColorChange?.(hex)}
            />
            <div className="grid grid-cols-[auto_1fr_auto] gap-2 items-center">
              <Label className="text-xs text-muted-foreground w-20 shrink-0">
                {t('basemapSublayer.strokeWidth', { defaultValue: 'Width' })}
              </Label>
              <Slider
                aria-label={t('basemapSublayer.strokeWidthLabel', { defaultValue: 'Stroke width' })}
                aria-valuetext={`${(strokeWidth ?? 0).toFixed(1)}px`}
                value={[strokeWidth ?? 0]}
                min={0}
                max={20}
                step={0.5}
                onValueChange={([v]) => onStrokeWidthChange?.(v ?? 0)}
              />
              <span className="text-xs tabular-nums text-muted-foreground w-12 shrink-0 text-end">
                {(strokeWidth ?? 0).toFixed(1)}px
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* 2. CASING section — Phase 1059 BSE-01 restored */}
      <section className="border-b">
        <div className="px-4 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2">
            {t('basemapSublayer.casingLabel', { defaultValue: 'CASING' })}
          </p>
          <div className="space-y-3">
            <StyleColorPicker
              label={t('basemapSublayer.casingColor', { defaultValue: 'Casing color' })}
              color={casingColor ?? '#cccccc'}
              onChange={(hex) => onCasingColorChange?.(hex)}
            />
            <div className="grid grid-cols-[auto_1fr_auto] gap-2 items-center">
              <Label className="text-xs text-muted-foreground w-20 shrink-0">
                {t('basemapSublayer.casingWidth', { defaultValue: 'Width' })}
              </Label>
              <Slider
                aria-label={t('basemapSublayer.casingWidthLabel', { defaultValue: 'Casing width' })}
                aria-valuetext={`${(casingWidth ?? 0).toFixed(1)}px`}
                value={[casingWidth ?? 0]}
                min={0}
                max={20}
                step={0.5}
                onValueChange={([v]) => onCasingWidthChange?.(v ?? 0)}
              />
              <span className="text-xs tabular-nums text-muted-foreground w-12 shrink-0 text-end">
                {(casingWidth ?? 0).toFixed(1)}px
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* 3. ZOOM RANGE section — Phase 1059 BSE-01 restored */}
      <section className="border-b">
        <div className="px-4 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2">
            {t('basemapSublayer.zoomLabel', { defaultValue: 'ZOOM RANGE' })}
          </p>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <Label htmlFor={`${sublayerId}-minzoom`} className="text-xs text-muted-foreground">
                {t('layerEditor.visibility.minZoom', { defaultValue: 'Minimum zoom' })}
              </Label>
              <Input
                id={`${sublayerId}-minzoom`}
                type="number"
                min={0}
                max={24}
                step={0.5}
                value={minZoom ?? 0}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  if (!Number.isFinite(v)) return;
                  onMinZoomChange?.(Math.min(24, Math.max(0, v)));
                }}
                className="h-8 text-xs"
                aria-label={t('layerEditor.visibility.minZoom', { defaultValue: 'Minimum zoom' })}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor={`${sublayerId}-maxzoom`} className="text-xs text-muted-foreground">
                {t('layerEditor.visibility.maxZoom', { defaultValue: 'Maximum zoom' })}
              </Label>
              <Input
                id={`${sublayerId}-maxzoom`}
                type="number"
                min={0}
                max={24}
                step={0.5}
                value={maxZoom ?? 22}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  if (!Number.isFinite(v)) return;
                  onMaxZoomChange?.(Math.min(24, Math.max(0, v)));
                }}
                className="h-8 text-xs"
                aria-label={t('layerEditor.visibility.maxZoom', { defaultValue: 'Maximum zoom' })}
              />
            </div>
          </div>
        </div>
      </section>

      {/* 4. Visibility section — opacity only (existing, untouched) */}
      <section className="border-b">
        <div className="px-4 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2">
            {t('layerEditor.section.visibility', { defaultValue: 'Visibility' })}
          </p>
          <div className="space-y-3">
            {/* Opacity slider */}
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">
                {t('layerEditor.visibility.opacity', { defaultValue: 'Opacity' })}
              </Label>
              <Slider
                aria-label={t('layerEditor.visibility.opacity', { defaultValue: 'Opacity' })}
                aria-valuetext={`${Math.round(safeOpacity * 100)}%`}
                value={[safeOpacity]}
                min={0}
                max={1}
                step={0.05}
                className="w-full"
                onValueChange={([value]) => {
                  onOpacityChange(Number((value ?? safeOpacity).toFixed(2)));
                }}
              />
            </div>
          </div>
        </div>
      </section>

      {/* 5. Reset section — collapsed by default (existing, untouched) */}
      <Collapsible
        open={resetOpen}
        onOpenChange={(open) => {
          setResetOpen(open);
          if (!open) setConfirmingReset(false); // restore initial state on close
        }}
      >
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full items-center gap-2 px-4 py-2 hover:bg-[var(--surface-2,theme(colors.muted.DEFAULT))] border-b"
          >
            <ChevronRight
              className={cn('h-4 w-4 shrink-0 transition-transform duration-[--motion-fast]', resetOpen && 'rotate-90')}
              aria-hidden="true"
            />
            <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              {t('basemapSublayer.resetLabel', { defaultValue: 'RESET' })}
            </span>
            {!resetOpen && (
              <span className="ml-auto text-xs text-muted-foreground">
                {t('basemapSublayer.resetHint', { defaultValue: 'Reset to preset default' })}
              </span>
            )}
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="px-4 py-2 border-b">
            {!confirmingReset ? (
              <Button
                type="button"
                variant="ghost"
                className="w-full"
                onClick={() => setConfirmingReset(true)}
              >
                {t('basemapSublayer.resetAction', { defaultValue: 'Reset to default' })}
              </Button>
            ) : (
              <div role="alertdialog" aria-labelledby="confirm-reset-title" className="space-y-2">
                <p id="confirm-reset-title" className="text-sm text-destructive text-center">
                  {t('basemapSublayer.resetConfirmMessage', {
                    sublayer: sublayerName,
                    defaultValue: 'This will remove all custom appearance for {{sublayer}}.',
                  })}
                </p>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant="destructive"
                    className="flex-1"
                    onClick={() => {
                      onResetSublayer();
                      setConfirmingReset(false);
                    }}
                  >
                    {t('basemapSublayer.resetConfirmAction', { defaultValue: 'Reset' })}
                  </Button>
                  {/* autoFocus on the safe choice — "Keep customization" */}
                  <Button
                    type="button"
                    variant="secondary"
                    className="flex-1"
                    // eslint-disable-next-line jsx-a11y/no-autofocus
                    autoFocus
                    onClick={() => setConfirmingReset(false)}
                  >
                    {t('basemapSublayer.resetConfirmCancel', { defaultValue: 'Keep customization' })}
                  </Button>
                </div>
              </div>
            )}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </>
  );
}

export function BasemapSublayerEditorFooter({ onBackToBasemap }: BasemapSublayerEditorFooterProps) {
  const { t } = useTranslation('builder');
  return (
    <div>
      <Button type="button" variant="ghost" className="w-full" onClick={onBackToBasemap}>
        {t('basemapSublayer.footerBack', { defaultValue: 'Back to basemap' })}
      </Button>
    </div>
  );
}
