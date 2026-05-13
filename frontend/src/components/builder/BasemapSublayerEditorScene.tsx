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
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { StyleColorPicker } from '@/components/builder/StyleColorPicker';
import { cn } from '@/lib/utils';

type DetailLevel = 'off' | 'minimal' | 'default' | 'full';

export interface BasemapSublayerEditorSceneProps {
  sublayerId: string;
  sublayerName: string;
  activeDetailLevel: DetailLevel;
  isCustomized: boolean;
  strokeColor: string;
  strokeWidth: number;
  casingColor: string;
  casingWidth: number;
  opacity: number;
  minZoom: number;
  maxZoom: number;
  onDetailLevelChange: (level: DetailLevel) => void;
  onStrokeColorChange: (color: string) => void;
  onStrokeWidthChange: (width: number) => void;
  onCasingColorChange: (color: string) => void;
  onCasingWidthChange: (width: number) => void;
  onOpacityChange: (opacity: number) => void;
  onZoomChange: (min: number, max: number) => void;
  onResetSublayer: () => void;
}

export interface BasemapSublayerEditorFooterProps {
  onBackToBasemap: () => void;
}

const DETAIL_LEVELS: { id: DetailLevel; labelKey: string; defaultLabel: string }[] = [
  { id: 'off', labelKey: 'basemapSublayer.detailLevelOff', defaultLabel: 'Off' },
  { id: 'minimal', labelKey: 'basemapSublayer.detailLevelMinimal', defaultLabel: 'Minimal' },
  { id: 'default', labelKey: 'basemapSublayer.detailLevelDefault', defaultLabel: 'Default' },
  { id: 'full', labelKey: 'basemapSublayer.detailLevelFull', defaultLabel: 'Full' },
];

export function BasemapSublayerEditorScene({
  sublayerId,
  sublayerName,
  activeDetailLevel,
  isCustomized,
  strokeColor,
  strokeWidth,
  casingColor,
  casingWidth,
  opacity,
  minZoom,
  maxZoom,
  onDetailLevelChange,
  onStrokeColorChange,
  onStrokeWidthChange,
  onCasingColorChange,
  onCasingWidthChange,
  onOpacityChange,
  onZoomChange,
  onResetSublayer,
}: BasemapSublayerEditorSceneProps) {
  const { t } = useTranslation('builder');
  const [resetOpen, setResetOpen] = useState(false);
  const [confirmingReset, setConfirmingReset] = useState(false);

  // Reset confirmingReset when sublayerId changes
  useEffect(() => {
    setConfirmingReset(false);
  }, [sublayerId]);

  const safeOpacity = typeof opacity === 'number' && Number.isFinite(opacity) ? opacity : 1;

  return (
    <>
      {/* 1. Detail Level section — always expanded */}
      <section className="border-b">
        <div className="px-4 py-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2">
            {t('basemapSublayer.detailLevelLabel', { defaultValue: 'DETAIL LEVEL' })}
          </p>
          <div role="radiogroup" className="flex flex-wrap gap-1.5">
            {DETAIL_LEVELS.map((pill) => {
              const isActive = pill.id === activeDetailLevel;
              return (
                <button
                  key={pill.id}
                  type="button"
                  role="radio"
                  aria-checked={isActive}
                  data-active={isActive ? 'true' : 'false'}
                  className={cn(
                    'rounded-full border border-transparent px-[10px] py-[5px] text-[12px] transition-colors',
                    isActive
                      ? 'bg-primary text-primary-foreground border-transparent'
                      : 'bg-[var(--surface-2,theme(colors.muted.DEFAULT))] text-foreground hover:bg-[var(--surface-3,theme(colors.muted.DEFAULT))]',
                  )}
                  onClick={() => {
                    if (!isActive) {
                      onDetailLevelChange(pill.id);
                    }
                  }}
                >
                  {t(pill.labelKey, { defaultValue: pill.defaultLabel })}
                </button>
              );
            })}
          </div>
          {activeDetailLevel !== 'default' && isCustomized && (
            <p className="text-[12px] text-muted-foreground italic mt-2">
              {t('basemapSublayer.customizedHint', {
                sublayer: sublayerName,
                defaultValue: '{{sublayer}} is currently customized',
              })}
            </p>
          )}
        </div>
      </section>

      {/* 2. Stroke section — always expanded */}
      <section className="border-b">
        <div className="px-4 py-3">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2">
            {t('basemapSublayer.strokeLabel', { defaultValue: 'STROKE' })}
          </p>
          <div className="space-y-3">
            {/* Color field */}
            <div className="grid grid-cols-[110px_1fr_auto] gap-2 items-center">
              <Label className="text-xs text-muted-foreground">
                {t('basemapSublayer.strokeColor', { defaultValue: 'Color' })}
              </Label>
              <StyleColorPicker
                label={t('basemapSublayer.strokeColor', { defaultValue: 'Color' })}
                color={strokeColor}
                onChange={onStrokeColorChange}
              />
            </div>

            {/* Width field */}
            <div className="grid grid-cols-[110px_1fr_auto] gap-2 items-center">
              <Label className="text-xs text-muted-foreground">
                {t('basemapSublayer.strokeWidth', { defaultValue: 'Width' })}
              </Label>
              <Slider
                aria-label={t('basemapSublayer.strokeWidthLabel', { defaultValue: 'Stroke width' })}
                aria-valuetext={`${strokeWidth}px`}
                value={[strokeWidth]}
                min={0}
                max={8}
                step={0.5}
                onValueChange={([v]) => onStrokeWidthChange(v)}
              />
              <span className="text-xs tabular-nums text-muted-foreground w-12 shrink-0 text-end">
                {strokeWidth}px
              </span>
            </div>

            {/* Casing color field */}
            <div className="grid grid-cols-[110px_1fr_auto] gap-2 items-center">
              <Label className="text-xs text-muted-foreground">
                {t('basemapSublayer.casingColor', { defaultValue: 'Casing color' })}
              </Label>
              <StyleColorPicker
                label={t('basemapSublayer.casingColor', { defaultValue: 'Casing color' })}
                color={casingColor}
                onChange={onCasingColorChange}
              />
            </div>

            {/* Casing width field */}
            <div className="grid grid-cols-[110px_1fr_auto] gap-2 items-center">
              <Label className="text-xs text-muted-foreground">
                {t('basemapSublayer.casingWidth', { defaultValue: 'Casing width' })}
              </Label>
              <Slider
                aria-label={t('basemapSublayer.casingWidthLabel', { defaultValue: 'Casing width' })}
                aria-valuetext={`${casingWidth}px`}
                value={[casingWidth]}
                min={0}
                max={4}
                step={0.5}
                onValueChange={([v]) => onCasingWidthChange(v)}
              />
              <span className="text-xs tabular-nums text-muted-foreground w-12 shrink-0 text-end">
                {casingWidth}px
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* 3. Visibility section — opacity + zoom range */}
      <section className="border-b">
        <div className="px-4 py-3">
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
            {/* Zoom range */}
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label
                  htmlFor={`${sublayerId}-minzoom`}
                  className="text-xs text-muted-foreground"
                >
                  {t('layerEditor.visibility.minZoom', { defaultValue: 'Minimum zoom' })}
                </Label>
                <Input
                  id={`${sublayerId}-minzoom`}
                  type="number"
                  min={0}
                  max={Math.max(0, maxZoom - 1)}
                  value={minZoom}
                  onChange={(e) => onZoomChange(Number(e.target.value), maxZoom)}
                  className="h-8 text-xs"
                  aria-label={t('layerEditor.visibility.minZoom', { defaultValue: 'Minimum zoom' })}
                />
              </div>
              <div className="space-y-1">
                <Label
                  htmlFor={`${sublayerId}-maxzoom`}
                  className="text-xs text-muted-foreground"
                >
                  {t('layerEditor.visibility.maxZoom', { defaultValue: 'Maximum zoom' })}
                </Label>
                <Input
                  id={`${sublayerId}-maxzoom`}
                  type="number"
                  min={Math.min(22, minZoom + 1)}
                  max={22}
                  value={maxZoom}
                  onChange={(e) => onZoomChange(minZoom, Number(e.target.value))}
                  className="h-8 text-xs"
                  aria-label={t('layerEditor.visibility.maxZoom', { defaultValue: 'Maximum zoom' })}
                />
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 4. Reset section — collapsed by default */}
      <Collapsible open={resetOpen} onOpenChange={setResetOpen}>
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full items-center gap-2 px-4 py-3 hover:bg-[var(--surface-2,theme(colors.muted.DEFAULT))] border-b"
          >
            <ChevronRight
              className={cn('h-4 w-4 shrink-0 transition-transform duration-150', resetOpen && 'rotate-90')}
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
          <div className="px-4 py-3 border-b">
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
    <footer data-testid="layer-editor-footer" className="shrink-0 border-t p-3">
      <Button type="button" variant="ghost" className="w-full" onClick={onBackToBasemap}>
        {t('basemapSublayer.footerBack', { defaultValue: 'Back to basemap' })}
      </Button>
    </footer>
  );
}
