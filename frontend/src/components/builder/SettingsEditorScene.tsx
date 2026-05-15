import { memo, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { getWidgets } from '@/components/map-widgets/registry';
import type { MapTerrainConfig } from '@/types/api';

export interface SettingsEditorSceneProps {
  // Terrain
  terrainConfig: MapTerrainConfig | null;
  /** True when at least one DEM layer has render_mode === 'terrain' */
  isTerrainActive: boolean;
  /** Name of the bound DEM layer (for the "Bound to:" hint) */
  boundLayerName?: string;
  onExaggerationChange: (value: number) => void;
  // Widgets
  activeWidgetIds: Set<string>;
  onToggleWidget: (widgetId: string) => void;
  // Projection (runtime-only, v1)
  projection: 'mercator' | 'globe';
  onSetProjection: (projection: 'mercator' | 'globe') => void;
}

interface SliderRowProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  suffix: string;
  onChange: (v: number) => void;
  ariaLabel: string;
  disabled?: boolean;
}

function SliderRow({ label, value, min, max, step, suffix, onChange, ariaLabel, disabled }: SliderRowProps) {
  return (
    <div className={cn('grid grid-cols-[110px_1fr_auto] gap-2 items-center', disabled && 'cursor-not-allowed')}>
      <Label className="text-xs text-muted-foreground">{label}</Label>
      <Slider
        aria-label={ariaLabel}
        aria-valuetext={`${value}${suffix}`}
        aria-disabled={disabled}
        disabled={disabled}
        value={[value]}
        min={min}
        max={max}
        step={step}
        onValueChange={([v]) => onChange(v)}
      />
      <span className="text-xs tabular-nums text-muted-foreground w-12 shrink-0 text-end">
        {value}{suffix}
      </span>
    </div>
  );
}

export const SettingsEditorScene = memo(function SettingsEditorScene({
  terrainConfig,
  isTerrainActive,
  boundLayerName,
  onExaggerationChange,
  activeWidgetIds,
  onToggleWidget,
  projection,
  onSetProjection,
}: SettingsEditorSceneProps) {
  const { t } = useTranslation('builder');
  const [terrainOpen, setTerrainOpen] = useState(true);
  const [widgetsOpen, setWidgetsOpen] = useState(true);
  const [projectionOpen, setProjectionOpen] = useState(true);

  const widgets = useMemo(() => getWidgets(), []);

  const exaggerationValue = terrainConfig?.exaggeration ?? 1.0;

  const terrainCollapsedHint = isTerrainActive
    ? t('settings.terrainActiveHint', { defaultValue: '{{value}}× exaggeration', value: exaggerationValue })
    : t('settings.terrainInactiveCollapsedHint', { defaultValue: 'No terrain active' });

  const projectionPills: { id: 'mercator' | 'globe'; label: string }[] = [
    { id: 'mercator', label: t('settings.projectionMercator', { defaultValue: 'Mercator' }) },
    { id: 'globe', label: t('settings.projectionGlobe', { defaultValue: 'Globe' }) },
  ];

  return (
    <div className="flex flex-col h-full overflow-y-auto">

      {/* Section 1: TERRAIN */}
      <Collapsible open={terrainOpen} onOpenChange={setTerrainOpen}>
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full items-center gap-2 px-4 py-2 hover:bg-[var(--surface-2,theme(colors.muted.DEFAULT))] border-b"
          >
            <ChevronRight
              className={cn('h-4 w-4 shrink-0 transition-transform duration-[--motion-fast]', terrainOpen && 'rotate-90')}
              aria-hidden="true"
            />
            <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              {t('settings.terrainLabel', { defaultValue: 'TERRAIN' })}
            </span>
            {!terrainOpen && (
              <span className="ml-auto text-xs text-muted-foreground">
                {terrainCollapsedHint}
              </span>
            )}
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="px-4 py-2 border-b">
            <SliderRow
              label={t('settings.exaggeration', { defaultValue: 'Exaggeration' })}
              value={exaggerationValue}
              min={0.1}
              max={3.0}
              step={0.1}
              suffix="×"
              onChange={onExaggerationChange}
              ariaLabel={t('settings.terrainExaggerationAria', { defaultValue: 'Terrain exaggeration' })}
              disabled={!isTerrainActive}
            />
            {isTerrainActive && boundLayerName && (
              <p className="mt-2 text-xs text-muted-foreground">
                {t('settings.boundTo', { defaultValue: 'Bound to: {{name}}', name: boundLayerName })}
              </p>
            )}
            {!isTerrainActive && (
              <p className="mt-2 text-xs italic text-muted-foreground">
                {t('settings.terrainInactiveHint', {
                  defaultValue:
                    'No terrain layer is active. Switch a DEM layer to Terrain mode to enable global terrain exaggeration.',
                })}
              </p>
            )}
          </div>
        </CollapsibleContent>
      </Collapsible>

      {/* Section 2: WIDGETS */}
      <Collapsible open={widgetsOpen} onOpenChange={setWidgetsOpen}>
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full items-center gap-2 px-4 py-2 hover:bg-[var(--surface-2,theme(colors.muted.DEFAULT))] border-b"
          >
            <ChevronRight
              className={cn('h-4 w-4 shrink-0 transition-transform duration-[--motion-fast]', widgetsOpen && 'rotate-90')}
              aria-hidden="true"
            />
            <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              {t('settings.widgetsLabel', { defaultValue: 'WIDGETS' })}
            </span>
            {!widgetsOpen && (
              <span className="ml-auto text-xs text-muted-foreground">
                {t('settings.widgetsEnabledCount', { count: activeWidgetIds.size, defaultValue: '{{count}} enabled' })}
              </span>
            )}
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          {widgets.length === 0 ? (
            <p className="px-4 py-2 text-xs text-muted-foreground">
              {t('settings.noWidgets', { defaultValue: 'No widgets available.' })}
            </p>
          ) : (
            <div role="group" aria-label={t('settings.widgetsGroupAria', { defaultValue: 'Widgets' })}>
              {widgets.map((widget) => {
                const isEnabled = activeWidgetIds.has(widget.id);
                const widgetLabel = t(widget.labelKey, { defaultValue: widget.id });
                const action = isEnabled
                  ? t('settings.disableAction', { defaultValue: 'Disable' })
                  : t('settings.enableAction', { defaultValue: 'Enable' });
                return (
                  <div
                    key={widget.id}
                    className="flex h-9 items-center gap-2 px-4 hover:bg-[var(--surface-2,theme(colors.muted.DEFAULT))]"
                  >
                    <widget.icon className="h-4 w-4 text-muted-foreground shrink-0" aria-hidden="true" />
                    <span className="flex-1 text-xs text-foreground">{widgetLabel}</span>
                    <Switch
                      checked={isEnabled}
                      onCheckedChange={() => onToggleWidget(widget.id)}
                      aria-label={t('settings.toggleWidget', {
                        defaultValue: '{{action}} {{name}} widget',
                        action,
                        name: widgetLabel,
                      })}
                    />
                  </div>
                );
              })}
            </div>
          )}
        </CollapsibleContent>
      </Collapsible>

      {/* Section 3: PROJECTION */}
      <Collapsible open={projectionOpen} onOpenChange={setProjectionOpen}>
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full items-center gap-2 px-4 py-2 hover:bg-[var(--surface-2,theme(colors.muted.DEFAULT))] border-b"
          >
            <ChevronRight
              className={cn('h-4 w-4 shrink-0 transition-transform duration-[--motion-fast]', projectionOpen && 'rotate-90')}
              aria-hidden="true"
            />
            <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              {t('settings.projectionLabel', { defaultValue: 'PROJECTION' })}
            </span>
            {!projectionOpen && (
              <span className="ml-auto text-xs text-muted-foreground">
                {projection === 'globe'
                  ? t('settings.projectionGlobe', { defaultValue: 'Globe' })
                  : t('settings.projectionMercator', { defaultValue: 'Mercator' })}
              </span>
            )}
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="px-4 py-2 border-b">
            <div
              role="radiogroup"
              aria-label={t('settings.projectionAria', { defaultValue: 'Map projection' })}
              className="grid grid-cols-2 gap-2"
            >
              {projectionPills.map((pill) => {
                const isActive = projection === pill.id;
                return (
                  <button
                    key={pill.id}
                    type="button"
                    role="radio"
                    aria-checked={isActive}
                    className={[
                      'rounded-full border border-transparent px-[10px] py-[5px] text-[12px] transition-colors',
                      isActive
                        ? 'bg-primary text-primary-foreground border-transparent'
                        : 'bg-[var(--surface-2,theme(colors.muted.DEFAULT))] text-foreground hover:bg-[var(--surface-3,theme(colors.muted.DEFAULT))]',
                    ].join(' ')}
                    onClick={() => {
                      if (!isActive) onSetProjection(pill.id);
                    }}
                  >
                    {pill.label}
                  </button>
                );
              })}
            </div>
            {projection === 'globe' && (
              <p role="alert" className="mt-2 text-xs italic text-muted-foreground">
                {t('settings.globeDisclaimer', {
                  defaultValue: 'Globe projection is experimental. Some layers may not render correctly.',
                })}
              </p>
            )}
          </div>
        </CollapsibleContent>
      </Collapsible>

    </div>
  );
});
