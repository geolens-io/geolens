import { memo, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { eyebrowClassName } from './EmptyStackState';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { ChevronRight, RotateCcw } from 'lucide-react';
import { cn } from '@/lib/utils';
import { getWidgets } from '@/components/map-widgets/registry';
import { StyleColorPicker } from './StyleColorPicker';
import type { MapTerrainConfig } from '@/types/api';

export interface SettingsEditorSceneProps {
  // Terrain
  terrainConfig: MapTerrainConfig | null;
  /** True when at least one DEM layer has render_mode === 'terrain' */
  isTerrainActive: boolean;
  /** Name of the bound DEM layer (for the "Bound to:" hint) */
  boundLayerName?: string;
  // Widgets
  activeWidgetIds: Set<string>;
  onToggleWidget: (widgetId: string) => void;
  // Appearance
  backgroundColor: string | null;
  onBackgroundColorChange: (color: string) => void;
  onBackgroundColorReset: () => void;
  // Projection (runtime-only, v1)
  projection: 'mercator' | 'globe';
  onSetProjection: (projection: 'mercator' | 'globe') => void;
}

export const SettingsEditorScene = memo(function SettingsEditorScene({
  terrainConfig: _terrainConfig,
  isTerrainActive,
  boundLayerName,
  activeWidgetIds,
  onToggleWidget,
  backgroundColor,
  onBackgroundColorChange,
  onBackgroundColorReset,
  projection,
  onSetProjection,
}: SettingsEditorSceneProps) {
  const { t } = useTranslation('builder');
  const [appearanceOpen, setAppearanceOpen] = useState(true);
  const [terrainOpen, setTerrainOpen] = useState(true);
  const [widgetsOpen, setWidgetsOpen] = useState(true);
  const [projectionOpen, setProjectionOpen] = useState(true);

  const widgets = useMemo(() => getWidgets(), []);

  const backgroundSwatch = backgroundColor ?? '#ffffff';

  const terrainCollapsedHint = isTerrainActive
    ? boundLayerName ?? t('settings.terrainActiveHint', { defaultValue: 'Terrain active' })
    : t('settings.terrainInactiveCollapsedHint', { defaultValue: 'No terrain active' });

  const projectionPills: { id: 'mercator' | 'globe'; label: string }[] = [
    { id: 'mercator', label: t('settings.projectionMercator', { defaultValue: 'Mercator' }) },
    { id: 'globe', label: t('settings.projectionGlobe', { defaultValue: 'Globe' }) },
  ];

  return (
    <div className="flex flex-col h-full overflow-y-auto">

      {/* Section 1: APPEARANCE */}
      <Collapsible open={appearanceOpen} onOpenChange={setAppearanceOpen}>
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full items-center gap-2 px-4 py-2 hover:bg-[var(--surface-2,theme(colors.muted.DEFAULT))] border-b"
          >
            <ChevronRight
              className={cn('h-4 w-4 shrink-0 transition-transform duration-[--motion-fast]', appearanceOpen && 'rotate-90')}
              aria-hidden="true"
            />
            <span className={eyebrowClassName}>
              {t('settings.appearanceLabel', { defaultValue: 'APPEARANCE' })}
            </span>
            {!appearanceOpen && (
              <span className="ml-auto text-xs text-muted-foreground">
                {backgroundColor ?? t('settings.defaultBackgroundColor', { defaultValue: 'Default' })}
              </span>
            )}
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <div className="px-4 py-2 border-b">
            <div className="flex h-9 items-center justify-between gap-2">
              <StyleColorPicker
                label={t('settings.backgroundColor', { defaultValue: 'Background' })}
                color={backgroundSwatch}
                onChange={onBackgroundColorChange}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8 shrink-0"
                disabled={!backgroundColor}
                onClick={onBackgroundColorReset}
                aria-label={t('settings.resetBackgroundColor', { defaultValue: 'Reset background color' })}
                title={t('settings.resetBackgroundColor', { defaultValue: 'Reset background color' })}
              >
                <RotateCcw className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
          </div>
        </CollapsibleContent>
      </Collapsible>

      {/* Section 2: TERRAIN */}
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
            <span className={eyebrowClassName}>
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
            {isTerrainActive && boundLayerName && (
              <p className="text-xs text-muted-foreground">
                {t('settings.boundTo', { defaultValue: 'Bound to: {{name}}', name: boundLayerName })}
              </p>
            )}
            {!isTerrainActive && (
              <p className="text-xs italic text-muted-foreground">
                {t('settings.terrainInactiveHint', {
                  defaultValue: 'No terrain layer is active.',
                })}
              </p>
            )}
          </div>
        </CollapsibleContent>
      </Collapsible>

      {/* Section 3: WIDGETS */}
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
            <span className={eyebrowClassName}>
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
            <>
              {/* UX-04: clarify that this section controls AVAILABILITY (vs live interaction on the map). */}
              <p className="px-4 pt-2 pb-1 text-[11px] text-muted-foreground">
                {t('settings.widgetsAvailabilityNote', {
                  defaultValue: 'Controls whether each widget appears on the map.',
                })}
              </p>
              <div role="group" aria-label={t('settings.widgetsGroupAria', { defaultValue: 'Widgets' })}>
                {widgets.map((widget) => {
                  const isEnabled = activeWidgetIds.has(widget.id);
                  const widgetLabel = t(widget.labelKey, { defaultValue: widget.id });
                  // UX-04: state-specific aria labels — "Enable {name}" / "Disable {name}" —
                  // replace the older "{action} {name} widget" composite key.
                  const switchAriaLabel = isEnabled
                    ? t('settings.disableWidget', { defaultValue: 'Disable {{name}}', name: widgetLabel })
                    : t('settings.enableWidget', { defaultValue: 'Enable {{name}}', name: widgetLabel });
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
                        aria-label={switchAriaLabel}
                      />
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </CollapsibleContent>
      </Collapsible>

      {/* Section 4: PROJECTION */}
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
            <span className={eyebrowClassName}>
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
