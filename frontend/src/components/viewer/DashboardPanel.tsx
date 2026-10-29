import { useCallback, useEffect, useId, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { LayoutDashboard, Loader2, PanelBottomClose, PanelRightClose } from 'lucide-react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { ApiError } from '@/api/client';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { WidgetView } from '@/components/widgets/WidgetView';
import { parseStoredWidget, type ParsedWidget } from '@/components/widgets/registry';
import type { Bbox } from '@/lib/bbox';
import { readStorage, removeStorage, storageKeys, writeStorage } from '@/lib/storage';
import { cn } from '@/lib/utils';
import type { DashboardConfig, SharedLayerResponse } from '@/types/api';
import { useMapViewBbox, useWidgetAggregate } from './hooks/use-dashboard-data';

type ReadyWidget = Extract<ParsedWidget, { ok: true }>;

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
}: {
  parsed: ReadyWidget;
  layer: SharedLayerResponse;
  viewBbox: Bbox | null;
  embedToken?: string;
  /** 4 where the widget sits under a heading of its own, as in the Builder's editor. */
  headingLevel?: 3 | 4;
  /** Told when the widget's data fails or recovers, so the panel can announce it once for all widgets. */
  onFailedChange?: (id: string, failed: boolean) => void;
}) {
  const { t } = useTranslation('widgets');
  const headingId = useId();
  const Heading = headingLevel === 4 ? 'h4' : 'h3';
  const { instance, definition } = parsed;
  const { query, filterIgnored, loading } = useWidgetAggregate({
    instance,
    definition,
    layer,
    viewBbox,
    embedToken,
  });
  const layerName = layer.display_name || layer.dataset_name;
  const heading = instance.title || layerName;
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
      aria-labelledby={headingId}
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
        {(instance.title || followsView) && (
          <p className="text-xs text-muted-foreground break-words">
            {instance.title && layerName}
            {instance.title && followsView && ' · '}
            {followsView && t('dashboard.followsView')}
          </p>
        )}
      </header>
      {filterIgnored && (
        <p className="text-xs text-muted-foreground">{t('dashboard.filterIgnored')}</p>
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
          <WidgetView parsed={parsed} data={query.data} />
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
}: {
  id: string;
  widgets: readonly PanelWidget[];
  layers: readonly SharedLayerResponse[];
  hiddenLayers?: ReadonlySet<string>;
  map: MaplibreMap | null;
  embedToken?: string;
  panel: PanelPosition;
}) {
  const { t } = useTranslation('widgets');
  const layersById = useMemo(() => new Map(layers.map((layer) => [layer.id, layer])), [layers]);
  // A widget leaves the panel only when the reader turns its layer off; a
  // layer saved hidden can still drive numbers, as a reference layer does.
  const shown = hiddenLayers?.size
    ? widgets.filter(({ parsed }) => !parsed.ok || !hiddenLayers.has(parsed.instance.layer_id ?? ''))
    : widgets;
  const followsView = shown.some(({ parsed }) => parsed.ok && parsed.instance.scope === 'view');
  const viewBbox = useMapViewBbox(map, followsView);
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

  if (shown.length === 0) {
    return (
      <p id={id} className="p-3 text-sm text-muted-foreground">
        {t('dashboard.allHidden')}
      </p>
    );
  }
  return (
    <>
    <p role="status" className="sr-only">
      {failedIds.size > 0 ? t('dashboard.someFailed') : ''}
    </p>
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
          return (
            <li key={key}>
              <DashboardWidget
                parsed={parsed}
                layer={layer}
                viewBbox={parsed.instance.scope === 'view' ? viewBbox : null}
                embedToken={embedToken}
                onFailedChange={onFailedChange}
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
    </>
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
}

/**
 * The map's dashboard to the right of the map or below it, as its author
 * chose; on narrow screens always below. Readers
 * can collapse and reopen it; the choice is remembered per map where storage
 * allows and a map id is given. Collapsed, its widgets unmount and stop fetching.
 */
export function DashboardPanel({
  config,
  layers,
  hiddenLayers,
  map,
  embedToken,
  mapId,
  startCollapsed = false,
}: DashboardPanelProps) {
  const { t } = useTranslation('widgets');
  const contentId = useId();
  const storageKey = mapId ? storageKeys.dashboardCollapsed(mapId) : null;
  const [collapsed, setCollapsed] = useState(
    () => startCollapsed || (storageKey !== null && readStorage(storageKey) === '1'),
  );

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
  const toggleLabel = collapsed ? t('dashboard.open') : t('dashboard.hide');

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
      <div className={cn('flex items-center gap-2 px-3 py-2', !collapsed && 'border-b')}>
        {!collapsed && <h2 className="flex-1 text-sm font-semibold">{t('dashboard.title')}</h2>}
        <Button
          type="button"
          variant="ghost"
          size={collapsed ? 'sm' : 'icon-sm'}
          aria-expanded={!collapsed}
          aria-controls={collapsed ? undefined : contentId}
          title={toggleLabel}
          onClick={toggle}
        >
          {collapsed ? (
            <LayoutDashboard aria-hidden="true" />
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
      </div>
      {!collapsed && (
        <DashboardWidgetList
          id={contentId}
          widgets={widgets}
          layers={layers}
          hiddenLayers={hiddenLayers}
          map={map}
          embedToken={embedToken}
          panel={panel}
        />
      )}
    </section>
  );
}
