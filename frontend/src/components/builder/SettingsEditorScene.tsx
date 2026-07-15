import { memo, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { eyebrowClassName } from './EmptyStackState';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { ChevronRight, RotateCcw } from 'lucide-react';
import { cn } from '@/lib/utils';
import { getEnabledPluginDefinitions } from '@/components/map-plugins';
import { StyleColorPicker } from './StyleColorPicker';
import type { MapTerrainConfig } from '@/types/api';
import { MAP_COLORS } from '@/lib/map-colors';

export interface SettingsEditorSceneProps {
  // Terrain
  terrainConfig: MapTerrainConfig | null;
  /** True when terrain_config is enabled and bound to a visible terrain-capable
   *  DEM (any render_mode — hillshade DEMs drive the mesh too), matching what the
   *  map actually renders. */
  isTerrainActive: boolean;
  /** Name of the bound DEM layer (for the "Bound to:" hint) */
  boundLayerName?: string;
  /** fix(HT-04): open the bound DEM layer's editor from Settings so the
   *  terrain source is always reachable (its controls live in the DEM editor).
   *  Undefined when no bound layer resolves. */
  onOpenBoundLayer?: () => void;
  // Plugins
  /** Admin allowlist of plugin IDs (null/undefined = no restriction). The
   *  per-map toggle list is filtered to these so admin-disabled plugins do not
   *  appear as dead toggles (they would be stripped on render + save anyway). */
  enabledPluginIds: string[] | null | undefined;
  activePluginIds: Set<string>;
  onTogglePlugin: (pluginId: string) => void;
  // Appearance
  backgroundColor: string | null;
  onBackgroundColorChange: (color: string) => void;
  onBackgroundColorReset: () => void;
  // Projection (persisted on basemap_config.projection)
  projection: 'mercator' | 'globe';
  onSetProjection: (projection: 'mercator' | 'globe') => void;
}

export const SettingsEditorScene = memo(function SettingsEditorScene({
  terrainConfig: _terrainConfig,
  isTerrainActive,
  boundLayerName,
  onOpenBoundLayer,
  enabledPluginIds,
  activePluginIds,
  onTogglePlugin,
  backgroundColor,
  onBackgroundColorChange,
  onBackgroundColorReset,
  projection,
  onSetProjection,
}: SettingsEditorSceneProps) {
  const { t } = useTranslation('builder');
  const [appearanceOpen, setAppearanceOpen] = useState(true);
  const [terrainOpen, setTerrainOpen] = useState(true);
  const [pluginsOpen, setPluginsOpen] = useState(true);
  const [projectionOpen, setProjectionOpen] = useState(true);

  // Only surface plugins the admin allows. getEnabledPluginDefinitions(null)
  // returns all registered plugins (no restriction), so default deployments are
  // unaffected; a restricted allowlist hides toggles that would be no-ops.
  const plugins = useMemo(
    () => getEnabledPluginDefinitions(enabledPluginIds),
    [enabledPluginIds],
  );

  const backgroundSwatch = backgroundColor ?? MAP_COLORS.canvas.settingsBackground;

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
              className={cn('h-4 w-4 shrink-0 transition-transform duration-[--motion-fast]', appearanceOpen ? 'rotate-90' : 'rtl-mirror')}
              aria-hidden="true"
            />
            <span className={eyebrowClassName}>
              {t('settings.appearanceLabel', { defaultValue: 'APPEARANCE' })}
            </span>
            {!appearanceOpen && (
              <span className="ms-auto text-xs text-muted-foreground">
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
              className={cn('h-4 w-4 shrink-0 transition-transform duration-[--motion-fast]', terrainOpen ? 'rotate-90' : 'rtl-mirror')}
              aria-hidden="true"
            />
            <span className={eyebrowClassName}>
              {t('settings.terrainLabel', { defaultValue: 'TERRAIN' })}
            </span>
            {!terrainOpen && (
              <span className="ms-auto text-xs text-muted-foreground">
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
            {/* fix(HT-04): the terrain controls live in the bound DEM's editor;
                link there so the source stays reachable from Settings. */}
            {onOpenBoundLayer && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="mt-2 h-7 text-xs"
                onClick={onOpenBoundLayer}
              >
                {t('settings.openTerrainLayer', { defaultValue: 'Open terrain layer' })}
              </Button>
            )}
            {isTerrainActive && (
              // #186 (c): guide users with a small high-res DEM toward draping it
              // over a coarse global DEM so terrain stays smooth across the map.
              <p className="mt-1 text-mini italic text-muted-foreground">
                {t('settings.terrainSmallDemTip', {
                  defaultValue:
                    'Tip: for a small high-resolution DEM, drape it over a coarse global DEM (e.g. Copernicus GLO-30) so terrain stays smooth beyond its extent.',
                })}
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

      {/* Section 3: PLUGINS */}
      <Collapsible open={pluginsOpen} onOpenChange={setPluginsOpen}>
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full items-center gap-2 px-4 py-2 hover:bg-[var(--surface-2,theme(colors.muted.DEFAULT))] border-b"
          >
            <ChevronRight
              className={cn('h-4 w-4 shrink-0 transition-transform duration-[--motion-fast]', pluginsOpen ? 'rotate-90' : 'rtl-mirror')}
              aria-hidden="true"
            />
            <span className={eyebrowClassName}>
              {t('settings.pluginsLabel', { defaultValue: 'PLUGINS' })}
            </span>
            {!pluginsOpen && (
              <span className="ms-auto text-xs text-muted-foreground">
                {t('settings.pluginsEnabledCount', { count: activePluginIds.size, defaultValue: '{{count}} enabled' })}
              </span>
            )}
          </button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          {plugins.length === 0 ? (
            <p className="px-4 py-2 text-xs text-muted-foreground">
              {t('settings.noPlugins', { defaultValue: 'No plugins available.' })}
            </p>
          ) : (
            <>
              {/* UX-04: clarify that this section controls AVAILABILITY (vs live interaction on the map). */}
              <p className="px-4 pt-2 pb-1 text-mini text-muted-foreground">
                {t('settings.pluginsAvailabilityNote', {
                  defaultValue: 'Controls whether each plugin appears on the map.',
                })}
              </p>
              <div role="group" aria-label={t('settings.pluginsGroupAria', { defaultValue: 'Plugins' })}>
                {plugins.map((plugin) => {
                  const isEnabled = activePluginIds.has(plugin.id);
                  const pluginLabel = t(plugin.labelKey, { defaultValue: plugin.id });
                  // UX-04: state-specific aria labels — "Enable {name}" / "Disable {name}" —
                  // replace the older "{action} {name} plugin" composite key.
                  const switchAriaLabel = isEnabled
                    ? t('settings.disablePlugin', { defaultValue: 'Disable {{name}}', name: pluginLabel })
                    : t('settings.enablePlugin', { defaultValue: 'Enable {{name}}', name: pluginLabel });
                  return (
                    <div
                      key={plugin.id}
                      className="flex h-9 items-center gap-2 px-4 hover:bg-[var(--surface-2,theme(colors.muted.DEFAULT))]"
                    >
                      <plugin.icon className="h-4 w-4 text-muted-foreground shrink-0" aria-hidden="true" />
                      <span className="flex-1 text-xs text-foreground">{pluginLabel}</span>
                      <Switch
                        checked={isEnabled}
                        onCheckedChange={() => onTogglePlugin(plugin.id)}
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
              className={cn('h-4 w-4 shrink-0 transition-transform duration-[--motion-fast]', projectionOpen ? 'rotate-90' : 'rtl-mirror')}
              aria-hidden="true"
            />
            <span className={eyebrowClassName}>
              {t('settings.projectionLabel', { defaultValue: 'PROJECTION' })}
            </span>
            {!projectionOpen && (
              <span className="ms-auto text-xs text-muted-foreground">
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
                      'rounded-md border border-transparent px-2.5 py-1 text-xs transition-colors',
                      isActive
                        ? 'bg-primary text-primary-foreground border-transparent'
                        : 'bg-surface-2 text-foreground hover:bg-surface-3',
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
