import { useTranslation } from 'react-i18next';
import { Eye, EyeOff } from 'lucide-react';
import { Slider } from '@/components/ui/slider';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { basemapThumbnail } from '@/lib/basemap-utils';
import { cn } from '@/lib/utils';

interface BasemapPreset {
  id: string;
  name: string;
  provider?: string;
}

interface BasemapSublayer {
  id: string;
  name: string;
  visible: boolean;
  opacity: number;
  kind: 'vector' | 'raster';
}

export interface BasemapGroupEditorSceneProps {
  activePresetId: string;
  presets: BasemapPreset[];
  sublayers: BasemapSublayer[];
  masterOpacity: number;
  onSwapBasemap: (presetId: string) => void;
  onAddCustomBasemap: () => void;
  onSublayerVisibilityChange: (sublayerId: string) => void;
  onSublayerOpacityChange: (sublayerId: string, opacity: number) => void;
  onMasterOpacityChange: (opacity: number) => void;
}

export interface BasemapGroupEditorFooterProps {
  onResetAppearance: () => void;
  onRemoveBasemap: () => void;
}

function SublayerTypeIcon({ kind }: { kind: 'vector' | 'raster' }) {
  if (kind === 'raster') {
    return (
      <span
        className="flex items-center justify-center h-[22px] w-[22px] rounded-sm bg-[--type-raster-bg] text-[--type-raster] text-xs font-medium shrink-0"
        aria-hidden="true"
      >
        ▦
      </span>
    );
  }
  return (
    <span
      className="flex items-center justify-center h-[22px] w-[22px] rounded-sm bg-[var(--surface-3,theme(colors.muted.DEFAULT))] text-muted-foreground text-xs font-medium shrink-0"
      aria-hidden="true"
    >
      ≡
    </span>
  );
}

export function BasemapGroupEditorScene({
  activePresetId,
  presets,
  sublayers,
  masterOpacity,
  onSwapBasemap,
  onAddCustomBasemap,
  onSublayerVisibilityChange,
  onSublayerOpacityChange,
  onMasterOpacityChange,
}: BasemapGroupEditorSceneProps) {
  const { t } = useTranslation('builder');

  return (
    <>
      {/* 1. Preset section */}
      <section className="border-b">
        <div className="px-4 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2">
            {t('basemapGroup.presetSectionLabel', { defaultValue: 'PRESET' })}
          </p>
          <div className="grid grid-cols-2 gap-2">
            {presets.map((preset) => {
              const isActive = preset.id === activePresetId;
              return (
                <button
                  key={preset.id}
                  type="button"
                  onClick={() => onSwapBasemap(preset.id)}
                  className={cn(
                    'flex flex-col rounded-[var(--radius-md)] border p-2 text-left transition-colors',
                    isActive
                      ? 'border-primary shadow-[0_0_0_1px_var(--primary)]'
                      : 'border-[var(--border)] hover:bg-[var(--surface-2)]',
                  )}
                >
                  <img
                    src={basemapThumbnail(preset.id)}
                    alt=""
                    aria-hidden="true"
                    className="w-full rounded-[var(--radius-sm)] object-cover"
                    style={{ height: '56px' }}
                  />
                  <span className="mt-1 block truncate text-[11px] text-foreground">
                    {preset.name}
                  </span>
                  {preset.provider && (
                    <span className="block truncate text-[10px] text-muted-foreground">
                      {preset.provider}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
          <button
            type="button"
            onClick={onAddCustomBasemap}
            className="text-[12px] text-primary text-left mt-2 hover:underline"
          >
            {t('basemapGroup.addCustomBasemap', { defaultValue: '＋ Add custom basemap…' })}
          </button>
        </div>
      </section>

      {/* 2. Sublayers section */}
      <section className="border-b">
        <div className="px-4 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground mb-2">
            {t('basemapGroup.sublayersSectionLabel', { defaultValue: 'SUBLAYERS' })}
          </p>
          <p className="text-xs text-muted-foreground mb-2">
            {t('basemapGroup.sublayersSectionHint', {
              defaultValue: 'Click any sublayer in the sidebar to style it individually.',
            })}
          </p>
          <ul className="space-y-0">
            {sublayers.map((sublayer) => {
              const safeOpacity = typeof sublayer.opacity === 'number' && Number.isFinite(sublayer.opacity)
                ? sublayer.opacity
                : 1;
              return (
                <li
                  key={sublayer.id}
                  className="group/row grid grid-cols-[16px_14px_22px_22px_1fr_60px_22px] gap-2 items-center py-2 px-2"
                >
                  {/* Col 1 (16px): caret — hidden; sublayers are not collapsible from scene B */}
                  <span
                    style={{ visibility: 'hidden' }}
                    className="h-[14px] w-[14px]"
                    aria-hidden="true"
                  />

                  {/* Col 2 (14px): grip — hidden; sublayers are not draggable from scene B */}
                  <span
                    className="opacity-0 pointer-events-none h-[14px] w-[14px]"
                    aria-hidden="true"
                  />

                  {/* Col 3 (22px): Eye visibility toggle */}
                  <button
                    type="button"
                    aria-label={t('stackRow.toggleVisibility', {
                      defaultValue: 'Toggle visibility for {{name}}',
                      name: sublayer.name,
                    })}
                    className="flex items-center justify-center h-[22px] w-[22px] shrink-0 rounded text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    onClick={(e) => {
                      e.stopPropagation();
                      onSublayerVisibilityChange(sublayer.id);
                    }}
                  >
                    {sublayer.visible ? (
                      <Eye className="h-3.5 w-3.5" aria-hidden="true" />
                    ) : (
                      <EyeOff className="h-3.5 w-3.5" aria-hidden="true" />
                    )}
                  </button>

                  {/* Col 4 (22px): Type icon */}
                  <SublayerTypeIcon kind={sublayer.kind} />

                  {/* Col 5 (1fr): Name */}
                  <span className="text-xs text-foreground truncate min-w-0">
                    {sublayer.name}
                  </span>

                  {/* Col 6 (60px): Opacity slider */}
                  {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions, jsx-a11y/click-events-have-key-events */}
                  <div
                    className="flex items-center"
                    onPointerDown={(e) => e.stopPropagation()}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Slider
                      aria-label={t('stackRow.opacitySlider', {
                        defaultValue: 'Opacity for {{name}}',
                        name: sublayer.name,
                      })}
                      aria-valuetext={`${Math.round(safeOpacity * 100)}%`}
                      value={[safeOpacity]}
                      min={0}
                      max={1}
                      step={0.05}
                      className="w-[60px]"
                      onValueChange={([value]) => {
                        onSublayerOpacityChange(sublayer.id, Number((value ?? safeOpacity).toFixed(2)));
                      }}
                    />
                  </div>

                  {/* Col 7 (22px): spacer for kebab column alignment */}
                  <span aria-hidden="true" />
                </li>
              );
            })}
          </ul>
        </div>
      </section>

      {/* 3. Visibility section — master opacity */}
      <section className="border-b">
        <div className="px-4 py-2">
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">
              {t('basemapGroup.masterOpacity', { defaultValue: 'Master opacity' })}
            </Label>
            <Slider
              aria-label={t('basemapGroup.masterOpacity', { defaultValue: 'Master opacity' })}
              aria-valuetext={`${Math.round(masterOpacity * 100)}%`}
              value={[masterOpacity]}
              min={0}
              max={1}
              step={0.05}
              className="w-full"
              onValueChange={([value]) => {
                onMasterOpacityChange(Number((value ?? masterOpacity).toFixed(2)));
              }}
            />
          </div>
        </div>
      </section>
    </>
  );
}

export function BasemapGroupEditorFooter({
  onResetAppearance,
  onRemoveBasemap,
}: BasemapGroupEditorFooterProps) {
  const { t } = useTranslation('builder');
  return (
    <footer data-testid="layer-editor-footer" className="shrink-0 border-t p-3">
      <div className="flex gap-2">
        <Button type="button" variant="ghost" className="flex-1" onClick={onResetAppearance}>
          {t('basemapGroup.resetAppearance', { defaultValue: 'Reset appearance' })}
        </Button>
        <Button
          type="button"
          variant="ghost"
          className="flex-1 text-destructive hover:bg-[oklch(0.97_0.02_27)] hover:text-destructive"
          onClick={onRemoveBasemap}
        >
          {t('basemapGroup.removeBasemap', { defaultValue: 'Remove basemap' })}
        </Button>
      </div>
    </footer>
  );
}
