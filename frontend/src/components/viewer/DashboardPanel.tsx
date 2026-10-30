import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { LayoutDashboard, Loader2, PanelBottomClose, PanelRightClose } from 'lucide-react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { ApiError } from '@/api/client';
import { Button } from '@/components/ui/button';
import { LiveAnnouncement } from '@/components/ui/live-announcement';
import { Skeleton } from '@/components/ui/skeleton';
import type { AnyWidgetDefinition, WidgetInstance, WidgetSelection } from '@/components/widgets/contract';
import { WidgetView } from '@/components/widgets/WidgetView';
import { parseStoredWidget, type ParsedWidget } from '@/components/widgets/registry';
import type { Bbox } from '@/lib/bbox';
import { getClusterSourceStrategy } from '@/components/builder/cluster-source';
import { useTileConfig } from '@/hooks/use-settings';
import { isCql2QueryableColumn, type Cql2Expression } from '@/lib/maplibre-filter-utils';
import { isMvtSourceLayerConfigReady } from '@/lib/tile-utils';
import { readStorage, removeStorage, storageKeys, writeStorage } from '@/lib/storage';
import { cn } from '@/lib/utils';
import type { DashboardConfig, SharedLayerResponse } from '@/types/api';
import { FilterChips } from './FilterChips';
import { useMapViewBbox, useWidgetAggregate } from './hooks/use-dashboard-data';
import { usePicks } from './hooks/use-picks';
import { mapCarriesColumn, NO_PICKS, type LinkedPick } from './linked-filters';
import { columnDisplayName, layerDisplayName } from './shared-layer';

type ReadyWidget = Extract<ParsedWidget, { ok: true }>;

/** A widget's title, else the heading its type derives from its config. */
export function widgetName(
  definition: AnyWidgetDefinition,
  instance: WidgetInstance,
  columns: SharedLayerResponse['column_info'],
  t: TFunction<'widgets'>,
): string | undefined {
  return (
    instance.title?.trim() ||
    definition.heading?.(instance.config, t, (column) => columnDisplayName(columns, column))
  );
}

function errorKey(error: unknown): 'dashboard.tooWide' | 'dashboard.loadFailed' {
  const code =
    error instanceof ApiError && typeof error.body === 'object' && error.body !== null
      ? (error.body as { code?: unknown }).code
      : undefined;
  return code === 'too_wide' ? 'dashboard.tooWide' : 'dashboard.loadFailed';
}

/** One widget with its heading, notices and data; the Builder's editor previews widgets with it. */
export function DashboardWidget({
  parsed,
  layer,
  viewBbox,
  embedToken,
  headingLevel = 3,
  onFailedChange,
  linked,
  selection,
  onSelect,
}: {
  parsed: ReadyWidget;
  layer: SharedLayerResponse;
  viewBbox: Bbox | null;
  embedToken?: string;
  /** 4 where the widget sits under a heading of its own, as in the Builder's editor. */
  headingLevel?: 3 | 4;
  /** Told when the widget's data fails or recovers, so the panel can announce it once for all widgets. */
  onFailedChange?: (id: string, failed: boolean) => void;
  /** The reader's picks on the layer's other widgets, which filter this widget's numbers. */
  linked?: readonly Cql2Expression[];
  /** This widget's own pick, which it shows without filtering its own numbers by it. */
  selection?: WidgetSelection | null;
  /** Set where picks link widgets, as in the viewer; see `WidgetRenderProps`. */
  onSelect?: (selection: WidgetSelection | null) => void;
}) {
  const { t } = useTranslation('widgets');
  const headingId = useId();
  const layerLineId = useId();
  const Heading = headingLevel === 4 ? 'h4' : 'h3';
  const { instance, definition } = parsed;
  const { query, filterIgnored, loading } = useWidgetAggregate({
    instance,
    definition,
    layer,
    viewBbox,
    embedToken,
    linked,
  });
  const layerName = layerDisplayName(layer);
  const named = widgetName(definition, instance, layer.column_info, t);
  const heading = named || layerName;
  const layerBelow = !!named;
  const followsView = instance.scope === 'view' && !!layer.geometry_type;
  // Numbers kept on screen while a pan's new ones load.
  const stale = query.isPlaceholderData;
  const failed = query.isError;
  useEffect(() => {
    onFailedChange?.(instance.id, failed);
  }, [onFailedChange, instance.id, failed]);
  useEffect(() => () => onFailedChange?.(instance.id, false), [onFailedChange, instance.id]);

  return (
    <article
      // A derived name like "Count" repeats across layers, so the layer joins it.
      aria-labelledby={layerBelow && !instance.title?.trim() ? `${headingId} ${layerLineId}` : headingId}
      aria-busy={query.isFetching}
      className="space-y-2 rounded-md border bg-card p-3 text-card-foreground"
    >
      <header>
        <div className="flex items-start gap-2">
          <Heading id={headingId} className="flex-1 text-sm font-medium break-words">
            {heading}
          </Heading>
          {query.isFetching && !loading && (
            <Loader2 aria-hidden="true" className="mt-0.5 size-3.5 shrink-0 animate-spin text-muted-foreground" />
          )}
        </div>
        {(layerBelow || followsView) && (
          <p className="text-xs text-muted-foreground break-words">
            {layerBelow && <span id={layerLineId}>{layerName}</span>}
            {layerBelow && followsView && ' · '}
            {followsView && t('dashboard.followsView')}
          </p>
        )}
      </header>
      {filterIgnored && (
        <p className="text-xs text-muted-foreground">
          {t(linked?.length ? 'dashboard.filterIgnoredWithPicks' : 'dashboard.filterIgnored')}
        </p>
      )}
      {failed && (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-xs text-destructive">{t(errorKey(query.error))}</p>
          <Button type="button" variant="outline" size="xs" onClick={() => void query.refetch()}>
            {t('dashboard.retry')}
          </Button>
        </div>
      )}
      {loading ? (
        <Skeleton className="h-12 w-full">
          <span className="sr-only">{t('common:loading')}</span>
        </Skeleton>
      ) : (
        <div className={cn('transition-opacity', stale && 'opacity-50')}>
          <WidgetView parsed={parsed} data={query.data} selection={selection} onSelect={onSelect} />
        </div>
      )}
    </article>
  );
}

type PanelWidget = { key: string; parsed: ParsedWidget };
export type PanelPosition = 'right' | 'bottom';

/** Where the author put the panel; a dashboard from before the choice existed sits on the right. */
export function dashboardPanelPosition(config: DashboardConfig | null | undefined): PanelPosition {
  return config?.panel === 'bottom' ? 'bottom' : 'right';
}

/** The expanded panel's widgets; unmounted on collapse, so the view bbox starts over on reopen. */
function DashboardWidgetList({
  id,
  widgets,
  layers,
  hiddenLayers,
  map,
  embedToken,
  panel,
  picks,
  onChoose,
  onFailedChange,
}: {
  id: string;
  widgets: readonly PanelWidget[];
  layers: readonly SharedLayerResponse[];
  hiddenLayers?: ReadonlySet<string>;
  map: MaplibreMap | null;
  embedToken?: string;
  panel: PanelPosition;
  picks: readonly LinkedPick[];
  onChoose?: (widgetId: string, layer: SharedLayerResponse, selection: WidgetSelection | null) => void;
  onFailedChange: (id: string, failed: boolean) => void;
}) {
  const { t } = useTranslation('widgets');
  const { data: tileConfig } = useTileConfig();
  const layersById = useMemo(() => new Map(layers.map((layer) => [layer.id, layer])), [layers]);
  // A widget leaves the panel only when the reader turns its layer off; a
  // layer saved hidden can still drive numbers, as a reference layer does.
  const shown = hiddenLayers?.size
    ? widgets.filter(({ parsed }) => !parsed.ok || !hiddenLayers.has(parsed.instance.layer_id ?? ''))
    : widgets;
  const followsView = shown.some(({ parsed }) => parsed.ok && parsed.instance.scope === 'view');
  const viewBbox = useMapViewBbox(map, followsView);
  // Built once per change of picks, so each widget's request memo holds between them.
  const linkedByWidget = useMemo(() => {
    const linked = new Map<string, readonly Cql2Expression[]>();
    for (const { parsed } of widgets) {
      if (!parsed.ok) continue;
      const { id: widgetId, layer_id: layerId } = parsed.instance;
      const others = picks.filter((pick) => pick.layerId === layerId && pick.widgetId !== widgetId);
      linked.set(widgetId, others.length > 0 ? others.map((pick) => pick.cql2) : NO_PICKS);
    }
    return linked;
  }, [widgets, picks]);

  if (shown.length === 0) {
    return (
      <p id={id} className="p-3 text-sm text-muted-foreground">
        {t('dashboard.allHidden')}
      </p>
    );
  }
  return (
    <ul
      id={id}
      className={cn(
        'min-h-0 flex-1 overflow-y-auto p-3',
        panel === 'bottom'
          ? 'grid grid-cols-[repeat(auto-fill,minmax(min(100%,16rem),1fr))] content-start gap-3'
          : 'space-y-3',
      )}
    >
      {shown.map(({ key, parsed }) => {
        const layer = parsed.ok ? layersById.get(parsed.instance.layer_id ?? '') : undefined;
        if (parsed.ok && layer) {
          const { id: widgetId, config } = parsed.instance;
          // A pick must filter both the numbers and the map, so the server has to
          // filter on its column and the map's features have to carry it.
          const column = parsed.definition.picksColumn?.(config);
          // A server-clustered pick is measured against the map's tile URL, which needs the tile config.
          const pickable =
            !!onChoose &&
            column !== undefined &&
            isCql2QueryableColumn(column, layer.column_info) &&
            mapCarriesColumn(layer, column) &&
            (getClusterSourceStrategy(layer).kind !== 'server-tile' || isMvtSourceLayerConfigReady(tileConfig));
          return (
            <li key={key}>
              <DashboardWidget
                parsed={parsed}
                layer={layer}
                viewBbox={parsed.instance.scope === 'view' ? viewBbox : null}
                embedToken={embedToken}
                onFailedChange={onFailedChange}
                linked={linkedByWidget.get(widgetId)}
                selection={picks.find((pick) => pick.widgetId === widgetId)?.selection ?? null}
                onSelect={pickable ? (selection) => onChoose(widgetId, layer, selection) : undefined}
              />
            </li>
          );
        }
        // The response leaves out widgets on layers it hides, so a missing
        // layer means a malformed stored widget.
        const unavailable: ParsedWidget = parsed.ok ? { ok: false, reason: 'malformed' } : parsed;
        return (
          <li key={key}>
            <WidgetView parsed={unavailable} />
          </li>
        );
      })}
    </ul>
  );
}

interface DashboardPanelProps {
  config: DashboardConfig | null | undefined;
  layers: readonly SharedLayerResponse[];
  /** Ids of the layers the reader turned off in the legend; their widgets are left out. */
  hiddenLayers?: ReadonlySet<string>;
  /** The viewer's map, once loaded; view-scoped widgets read its bounds. */
  map: MaplibreMap | null;
  embedToken?: string;
  /**
   * The map id the reader's collapsed choice is remembered under. Share links
   * leave it out: their response has no map id, and the share token is a
   * credential that stays out of storage.
   */
  mapId?: string;
  /** Start collapsed whatever the remembered choice, as an embed's `dashboard=collapsed` asks. */
  startCollapsed?: boolean;
  /** The reader's picks, which filter their layers. They stay while the panel is collapsed. */
  picks?: readonly LinkedPick[];
  /** Given, a pick on a bar, bin or value filters its layer and the layer's other widgets. */
  onPicksChange?: (picks: readonly LinkedPick[]) => void;
}

/**
 * The map's dashboard to the right of the map or below it, as its author
 * chose; on narrow screens always below. Readers
 * can collapse and reopen it; the choice is remembered per map where storage
 * allows and a map id is given. Collapsed, its widgets unmount and stop fetching,
 * and the chips of the reader's picks stay in its header.
 */
export function DashboardPanel({
  config,
  layers,
  hiddenLayers,
  map,
  embedToken,
  mapId,
  startCollapsed = false,
  picks = NO_PICKS,
  onPicksChange,
}: DashboardPanelProps) {
  const { t } = useTranslation('widgets');
  const contentId = useId();
  const storageKey = mapId ? storageKeys.dashboardCollapsed(mapId) : null;
  const [collapsed, setCollapsed] = useState(
    () => startCollapsed || (storageKey !== null && readStorage(storageKey) === '1'),
  );
  const toggleRef = useRef<HTMLButtonElement>(null);
  const { choose, remove, announcement, layerName, pickLabel } = usePicks(picks, onPicksChange, layers);
  // One announcement for the panel, so a pan that fails every widget doesn't speak once per widget.
  const [failedIds, setFailedIds] = useState<ReadonlySet<string>>(() => new Set());
  const onFailedChange = useCallback((widgetId: string, failed: boolean) => {
    setFailedIds((current) => {
      if (current.has(widgetId) === failed) return current;
      const next = new Set(current);
      if (failed) next.add(widgetId);
      else next.delete(widgetId);
      return next;
    });
  }, []);

  const widgets: PanelWidget[] = useMemo(
    () =>
      (config?.widgets ?? []).map((raw) => ({
        key: raw.id,
        parsed: parseStoredWidget(raw, 'dashboard'),
      })),
    [config],
  );
  if (widgets.length === 0) return null;
  const panel = dashboardPanelPosition(config);
  const right = panel === 'right';

  const toggle = () => {
    const next = !collapsed;
    setCollapsed(next);
    if (!storageKey) return;
    if (next) writeStorage(storageKey, '1');
    else removeStorage(storageKey);
  };
  // The collapsed right rail stays narrow, so its toggle counts the filters instead of showing their chips.
  const countOnToggle = collapsed && right && picks.length > 0;
  const toggleLabel = countOnToggle
    ? t('dashboard.openWithFilters', { count: picks.length })
    : collapsed
      ? t('dashboard.open')
      : t('dashboard.hide');
  const chips = (className?: string) => (
    <FilterChips
      picks={picks}
      layerName={layerName}
      pickLabel={pickLabel}
      onRemove={remove}
      fallbackFocus={toggleRef}
      className={className}
    />
  );

  return (
    <section
      aria-label={t('dashboard.title')}
      className={cn(
        'flex shrink-0 flex-col border-t bg-background',
        right && 'md:border-s md:border-t-0',
        !collapsed && 'max-h-[45dvh]',
        // Stacked below the map in a short window or iframe, the map keeps most of the height.
        !collapsed && (right ? 'max-md:[@media(max-height:480px)]:max-h-[35dvh]' : '[@media(max-height:480px)]:max-h-[35dvh]'),
        !collapsed && right && 'md:max-h-none md:w-80 lg:w-96',
      )}
    >
      <LiveAnnouncement
        text={[failedIds.size > 0 ? t('dashboard.someFailed') : '', announcement.text].filter(Boolean).join(' ')}
        trigger={String(announcement.count)}
      />
      <div className={cn('flex items-center gap-2 px-3 py-2', !collapsed && 'border-b')}>
        {!collapsed && <h2 className="flex-1 text-sm font-semibold">{t('dashboard.title')}</h2>}
        <Button
          ref={toggleRef}
          type="button"
          variant="ghost"
          size={collapsed ? 'sm' : 'icon-sm'}
          aria-expanded={!collapsed}
          aria-controls={collapsed ? undefined : contentId}
          title={toggleLabel}
          onClick={toggle}
        >
          {collapsed ? (
            <>
              <LayoutDashboard aria-hidden="true" />
              {countOnToggle && (
                <span
                  aria-hidden="true"
                  className="min-w-4 rounded-full bg-primary px-1 text-center text-[10px] leading-4 font-semibold text-primary-foreground tabular-nums"
                >
                  {picks.length}
                </span>
              )}
            </>
          ) : (
            <>
              <PanelBottomClose aria-hidden="true" className={cn(right && 'md:hidden')} />
              {right && <PanelRightClose aria-hidden="true" className="hidden md:block" />}
            </>
          )}
          {/* The right panel collapses to a narrow rail on wide screens. */}
          <span className={collapsed ? (right ? 'md:sr-only' : undefined) : 'sr-only'}>
            {toggleLabel}
          </span>
        </Button>
        {collapsed && !right && chips('min-w-0 flex-1')}
      </div>
      {!collapsed && chips('border-b px-3 py-2')}
      {!collapsed && (
        <DashboardWidgetList
          id={contentId}
          widgets={widgets}
          layers={layers}
          hiddenLayers={hiddenLayers}
          map={map}
          embedToken={embedToken}
          panel={panel}
          picks={picks}
          onChoose={onPicksChange ? choose : undefined}
          onFailedChange={onFailedChange}
        />
      )}
    </section>
  );
}
