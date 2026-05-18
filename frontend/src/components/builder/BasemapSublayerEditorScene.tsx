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
import { cn } from '@/lib/utils';

// Phase 1051 Plan 11 (INV-01): DETAIL LEVEL pill strip removed — dead wiring.
// The activeDetailLevel/isCustomized/onDetailLevelChange props were always passed
// hardcoded defaults from MapBuilderPage; no consumer ever implemented sublayer
// detail-level style mutation. Removed rather than fix because a real consumer
// requires a multi-day MapLibre style-mutation implementation (out of v1011 scope
// per REQUIREMENTS.md Out-of-Scope row 1).
//
// Phase 1052 Plan 01 (EMRG-FN-01): STROKE section + zoom range inputs + 5
// stub callbacks removed. Same Phase 1038 root cause — onStrokeColorChange,
// onStrokeWidthChange, onCasingColorChange, onCasingWidthChange, and
// onZoomChange were all `TODO(BUILDER-SUBLAYER-PERSIST)` no-ops. Path A
// REMOVE chosen for v1011.1 hygiene close (Path B FIX is a 3-5 day feature
// phase per REQUIREMENTS.md Out of Scope). Live consumers preserved:
// opacity slider (onOpacityChange → handleSublayerOpacityChange) and Reset
// section (onResetSublayer → setSublayerState mutation).

export interface BasemapSublayerEditorSceneProps {
  sublayerId: string;
  sublayerName: string;
  opacity: number;
  onOpacityChange: (opacity: number) => void;
  onResetSublayer: () => void;
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
      {/* 1. Visibility section — opacity only */}
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

      {/* 2. Reset section — collapsed by default */}
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
