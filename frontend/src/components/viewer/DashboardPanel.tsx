import { useCallback, useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { LayoutDashboard, Loader2, PanelBottomClose, PanelRightClose } from 'lucide-react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { ApiError } from '@/api/client';
import { Button } from '@/components/ui/button';
import { LiveAnnouncement } from '@/components/ui/live-announcement';
import { Skeleton } from '@/components/ui/skeleton';
import type { AnyWidgetDefinition, WidgetInstance, WidgetRenderProps, WidgetSelection } from '@/components/widgets/contract';
import { categoryColors } from '@/components/map/legend-facts';
import { LayerColorsProvider } from '@/components/widgets/layer-colors';
import { WidgetView } from '@/components/widgets/WidgetView';
import { isLayerBound, parseStoredWidget, type ParsedWidget } from '@/components/widgets/registry';
import type { Bbox } from '@/lib/bbox';
import { getClusterSourceStrategy } from '@/components/builder/cluster-source';
import { useTileConfig } from '@/hooks/use-settings';
import { isCql2QueryableColumn, type Cql2Expression } from '@/lib/maplibre-filter-utils';
import { isMvtSourceLayerConfigReady } from '@/lib/tile-utils';
import { readStorage, removeStorage, storageKeys, writeStorage } from '@/lib/storage';
import { cn } from '@/lib/utils';
import type { SharedLayerResponse } from '@/types/api';
import { FilterChips } from './FilterChips';
import { useMapViewBbox, useWidgetAggregate } from './hooks/use-dashboard-data';
import { useFeatureZoom } from './hooks/use-feature-zoom';
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

/**
 * Refusals a retry repeats: a column the reader can't see is refused like a
 * missing one, and a view too wide stays so until the map moves.
 */
const REFUSED_CODES: ReadonlySet<unknown> = new Set(['invalid_column', 'invalid_filter', 'too_wide']);

function errorCode(error: unknown): unknown {
  return error instanceof ApiError && typeof error.body === 'object' && error.body !== null
    ? (error.body as { code?: unknown }).code
    : undefined;
}

function errorKey(
  code: unknown,
): 'dashboard.tooWide' | 'dashboard.columnUnavailable' | 'dashboard.filterRefused' | 'dashboard.loadFailed' {
  if (code === 'too_wide') return 'dashboard.tooWide';
  if (code === 'invalid_filter') return 'dashboard.filterRefused';
  return code === 'invalid_column' ? 'dashboard.columnUnavailable' : 'dashboard.loadFailed';
}

/** The card around a dashboard widget. */
function WidgetShell({
  labelledBy,
  busy,
  children,
}: {
  labelledBy?: string;
  busy?: boolean;
  children: ReactNode;
}) {
  return (
    <article
      aria-labelledby={labelledBy}
      aria-busy={busy}
      className="space-y-2 rounded-md border bg-card p-3 text-card-foreground"
    >
      {children}
    </article>
  );
}

/** Why a widget has no numbers to show: its request failed, or its view holds too many rows. */
type WidgetProblem = 'failed' | 'tooWide';

/** One widget with its heading, notices and data; the Builder's editor previews widgets with it. */
export function DashboardWidget({
  parsed,
  layer,
  viewBbox,
  embedToken,
  headingLevel = 3,
  onProblemChange,
  linked,
  selection,
  onSelect,
  mapHidden = false,
  onZoomTo,
}: {
  parsed: ReadyWidget;
  layer: SharedLayerResponse;
  viewBbox: Bbox | null;
  embedToken?: string;
  /** 4 where the widget sits under a heading of its own, as in the Builder's editor. */
  headingLevel?: 3 | 4;
  /** Told when the widget's data fails, is refused as too wide, or recovers, so the panel can announce it once for all widgets. */
  onProblemChange?: (id: string, problem: WidgetProblem | null) => void;
  /** The reader's picks on the layer's other widgets, which filter this widget's numbers. */
  linked?: readonly Cql2Expression[];
  /** This widget's own pick, which it shows without filtering its own numbers by it. */
  selection?: WidgetSelection | null;
  /** Set where picks link widgets, as in the viewer; see `WidgetRenderProps`. */
  onSelect?: (selection: WidgetSelection | null) => void;
  /** Set where the dashboard hides its map: a view-scoped widget then reads its whole layer and says so. */
  mapHidden?: boolean;
  /** Set where the dashboard has a map the widget can zoom; see `WidgetRenderProps`. */
  onZoomTo?: WidgetRenderProps<unknown>['onZoomTo'];
}) {
  const { t } = useTranslation('widgets');
  const headingId = useId();
  const layerLineId = useId();
  const Heading = headingLevel === 4 ? 'h4' : 'h3';
  const { instance, definition } = parsed;
  const { query, filterIgnored, loading, followsView, loadMore, loadingMore, loadMoreFailed } = useWidgetAggregate({
    instance,
    definition,
    layer,
    viewBbox,
    embedToken,
    linked,
    mapHidden,
  });
  const layerColors = useMemo(() => categoryColors(layer), [layer]);
  const loadingSkeleton = (
    <Skeleton className="h-12 w-full">
      <span className="sr-only">{t('common:loading')}</span>
    </Skeleton>
  );
  const layerName = layerDisplayName(layer);
  const named = widgetName(definition, instance, layer.column_info, t);
  const heading = named || layerName;
  const layerBelow = !!named;
  // Numbers kept on screen while a pan's new ones load.
  const stale = query.isPlaceholderData;
  const failed = query.isError;
  const code = failed ? errorCode(query.error) : undefined;
  const problem: WidgetProblem | null = !failed ? null : code === 'too_wide' ? 'tooWide' : 'failed';
  useEffect(() => {
    onProblemChange?.(instance.id, problem);
  }, [onProblemChange, instance.id, problem]);
  useEffect(() => () => onProblemChange?.(instance.id, null), [onProblemChange, instance.id]);

  return (
    <WidgetShell
      // A derived name like "Count" repeats across layers, so the layer joins it.
      labelledBy={layerBelow && !instance.title?.trim() ? `${headingId} ${layerLineId}` : headingId}
      busy={query.isFetching}
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
          <p className="text-xs text-destructive">{t(errorKey(code))}</p>
          {!REFUSED_CODES.has(code) && (
            <Button type="button" variant="outline" size="xs" onClick={() => void query.refetch()}>
              {t('dashboard.retry')}
            </Button>
          )}
        </div>
      )}
      {loading ? (
        loadingSkeleton
      ) : failed && query.data === undefined ? null : (
        <div className={cn('transition-opacity', stale && 'opacity-50')}>
          <LayerColorsProvider value={layerColors}>
            <WidgetView
              parsed={parsed}
              data={query.data}
              selection={selection}
              onSelect={onSelect}
              mapHidden={mapHidden}
              onLoadMore={loadMore}
              loadingMore={loadingMore}
              loadMoreFailed={loadMoreFailed}
              onZoomTo={onZoomTo}
              columnLabel={(column) => columnDisplayName(layer.column_info, column)}
              loadingFallback={loadingSkeleton}
            />
          </LayerColorsProvider>
        </div>
      )}
    </WidgetShell>
  );
}

/**
 * A widget with no layer, such as text. It is titled only when its author
 * gave it a title, and its own headings go one level below that title.
 */
export function DashboardTextWidget({
  parsed,
  headingLevel = 3,
}: {
  parsed: ReadyWidget;
  /** 4 where the widget sits under a heading of its own, as in the Builder's editor. */
  headingLevel?: 3 | 4;
}) {
  const headingId = useId();
  const Heading = headingLevel === 4 ? 'h4' : 'h3';
  const title = parsed.instance.title?.trim();
  const contentLevel = title ? (headingLevel === 4 ? 5 : 4) : headingLevel;
  return (
    <WidgetShell labelledBy={title ? headingId : undefined}>
      {title && (
        <Heading id={headingId} className="text-sm font-medium break-words">
          {title}
        </Heading>
      )}
      <WidgetView parsed={parsed} headingLevel={contentLevel} />
    </WidgetShell>
  );
}

/** The part of a dashboard config the panel reads: a stored one, or a draft's as a save would send it. */
type PanelConfig = { panel?: string | null; map_hidden?: boolean | null; widgets?: readonly { id: string }[] };

type PanelWidget = { key: string; parsed: ParsedWidget };
export type PanelPosition = 'right' | 'bottom';

/** Where the author put the panel; a dashboard from before the choice existed sits on the right. */
export function dashboardPanelPosition(config: PanelConfig | null | undefined): PanelPosition {
  return config?.panel === 'bottom' ? 'bottom' : 'right';
}

/** How the dashboard sits: beside the map, below it, or as the whole page when its author hides the map. */
export type DashboardLayout = PanelPosition | 'page';

export function dashboardLayout(config: PanelConfig | null | undefined): DashboardLayout {
  return config?.map_hidden ? 'page' : dashboardPanelPosition(config);
}

// Two 16rem columns and the gap between them: below this width the grid has one column.
const WIDE_SPAN = '@[32.75rem]:col-span-2';
const WIDE_TYPES: ReadonlySet<string> = new Set(['bar_chart', 'pie_chart', 'histogram', 'table', 'feature_list']);

/** The expanded panel's widgets; unmounted on collapse, so the view bbox starts over on reopen. */
function DashboardWidgetList({
  id,
  widgets,
  layers,
  hiddenLayers,
  map,
  embedToken,
  layout,
  picks,
  onChoose,
  onZoom,
  onProblemChange,
}: {
  id: string;
  widgets: readonly PanelWidget[];
  layers: readonly SharedLayerResponse[];
  hiddenLayers?: ReadonlySet<string>;
  map: MaplibreMap | null;
  embedToken?: string;
  layout: DashboardLayout;
  picks: readonly LinkedPick[];
  onChoose?: (widgetId: string, layer: SharedLayerResponse, selection: WidgetSelection | null) => void;
  /** Set where a map can show a feature a widget names. */
  onZoom?: (layer: SharedLayerResponse, feature: { id: number | string; bbox: Bbox }) => void;
  onProblemChange: (id: string, problem: WidgetProblem | null) => void;
}) {
  const { t } = useTranslation('widgets');
  const { data: tileConfig } = useTileConfig();
  const layersById = useMemo(() => new Map(layers.map((layer) => [layer.id, layer])), [layers]);
  // A widget leaves the panel only when the reader turns its layer off; a
  // layer saved hidden can still drive numbers, as a reference layer does.
  const shown = hiddenLayers?.size
    ? widgets.filter(({ parsed }) => !parsed.ok || !hiddenLayers.has(parsed.instance.layer_id ?? ''))
    : widgets;
  const followsView = layout !== 'page' && shown.some(({ parsed }) => parsed.ok && parsed.instance.scope === 'view');
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
        layout !== 'right'
          ? '@container grid grid-cols-[repeat(auto-fill,minmax(min(100%,16rem),1fr))] content-start gap-3'
          : 'space-y-3',
      )}
    >
      {shown.map(({ key, parsed }) => {
        if (parsed.ok && !isLayerBound(parsed.instance.type)) {
          return (
            <li key={key}>
              <DashboardTextWidget parsed={parsed} />
            </li>
          );
        }
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
            // With no map to filter, only the server's own filtering matters.
            (layout === 'page' ||
              (mapCarriesColumn(layer, column) &&
                (getClusterSourceStrategy(layer).kind !== 'server-tile' || isMvtSourceLayerConfigReady(tileConfig))));
          return (
            <li key={key} className={layout !== 'right' && WIDE_TYPES.has(parsed.instance.type) ? WIDE_SPAN : undefined}>
              <DashboardWidget
                parsed={parsed}
                layer={layer}
                viewBbox={parsed.instance.scope === 'view' ? viewBbox : null}
                embedToken={embedToken}
                mapHidden={layout === 'page'}
                onZoomTo={onZoom ? (feature) => onZoom(layer, feature) : undefined}
                onProblemChange={onProblemChange}
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
  config: PanelConfig | null | undefined;
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
  /** A branding extension's logo, shown in the open panel's header. */
  logoUrl?: string;
  /** False where the map isn't the viewer's, as in the Builder's preview, so features aren't offered a zoom. */
  canZoom?: boolean;
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
  logoUrl,
  canZoom = true,
}: DashboardPanelProps) {
  const { t } = useTranslation('widgets');
  const contentId = useId();
  const storageKey = mapId ? storageKeys.dashboardCollapsed(mapId) : null;
  const [collapsedChoice, setCollapsed] = useState(
    () => startCollapsed || (storageKey !== null && readStorage(storageKey) === '1'),
  );
  const layout = dashboardLayout(config);
  const mapHidden = layout === 'page';
  // Without a map the dashboard is the page, so there is nothing to collapse it for.
  const collapsed = !mapHidden && collapsedChoice;
  const toggleRef = useRef<HTMLButtonElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const { choose, remove, announcement, layerName, pickLabel } = usePicks(picks, onPicksChange, layers);
  const zoomTo = useFeatureZoom(mapHidden ? null : map);
  // One announcement for the panel, so a pan that fails every widget doesn't speak once per widget.
  const [problems, setProblems] = useState<ReadonlyMap<string, WidgetProblem>>(() => new Map());
  const onProblemChange = useCallback((widgetId: string, problem: WidgetProblem | null) => {
    setProblems((current) => {
      if ((current.get(widgetId) ?? null) === problem) return current;
      const next = new Map(current);
      if (problem) next.set(widgetId, problem);
      else next.delete(widgetId);
      return next;
    });
  }, []);
  const problemKinds = new Set(problems.values());

  const widgets: PanelWidget[] = useMemo(
    () =>
      (config?.widgets ?? []).map((raw) => ({
        key: raw.id,
        parsed: parseStoredWidget(raw, 'dashboard'),
      })),
    [config],
  );
  // Renderer chunks download alongside the aggregate requests.
  useEffect(() => {
    for (const { parsed } of widgets) {
      if (parsed.ok) void parsed.definition.loadRenderer().catch(() => {});
    }
  }, [widgets]);
  if (widgets.length === 0) return null;
  const right = layout === 'right';

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
      fallbackFocus={mapHidden ? headingRef : toggleRef}
      className={className}
    />
  );

  return (
    <section
      aria-label={t('dashboard.title')}
      className={cn(
        'flex flex-col bg-background',
        mapHidden ? 'min-h-0 w-full flex-1' : 'shrink-0 border-t',
        right && 'md:border-s md:border-t-0',
        !mapHidden &&
          !collapsed && [
            'max-h-[45dvh]',
            // Stacked below the map in a short window or iframe, the map keeps most of the height.
            right ? 'max-md:[@media(max-height:480px)]:max-h-[35dvh]' : '[@media(max-height:480px)]:max-h-[35dvh]',
            right && 'md:max-h-none md:w-80 lg:w-96',
          ],
      )}
    >
      <LiveAnnouncement
        text={[
          problemKinds.has('failed') ? t('dashboard.someFailed') : '',
          problemKinds.has('tooWide') ? t('dashboard.someTooWide') : '',
          announcement.text,
        ]
          .filter(Boolean)
          .join(' ')}
        trigger={String(announcement.count)}
      />
      <div className={cn('flex items-center gap-2 px-3 py-2', !collapsed && 'border-b')}>
        {!collapsed && logoUrl && (
          // Decorative: a brand mark beside the heading, not content.
          <img src={logoUrl} alt="" referrerPolicy="no-referrer" className="h-6 w-auto max-w-32 object-contain" />
        )}
        {!collapsed && (
          // Focusable by script so focus has a place to land when the last chip leaves with no toggle.
          <h2 ref={headingRef} tabIndex={-1} className="flex-1 text-sm font-semibold outline-none">
            {t('dashboard.title')}
          </h2>
        )}
        {!mapHidden && (
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
        )}
        {collapsed && !right && chips('min-w-0 flex-1')}
      </div>
      {!collapsed && chips('border-b px-3 py-2')}
      {!collapsed && mapHidden && widgets.some(({ parsed }) => parsed.ok && parsed.instance.scope === 'view') && (
        <p className="px-3 pt-2 text-xs text-muted-foreground">{t('dashboard.viewScopeUnavailable')}</p>
      )}
      {!collapsed && (
        <DashboardWidgetList
          id={contentId}
          widgets={widgets}
          layers={layers}
          hiddenLayers={hiddenLayers}
          map={map}
          embedToken={embedToken}
          layout={layout}
          picks={picks}
          onChoose={onPicksChange ? choose : undefined}
          onZoom={map && !mapHidden && canZoom ? zoomTo : undefined}
          onProblemChange={onProblemChange}
        />
      )}
    </section>
  );
}
