import { deepEqual } from '@/lib/deep-equal';
import { dashboardPanelPosition, type PanelPosition } from '@/components/viewer/DashboardPanel';
import type { WidgetInstance } from '@/components/widgets/contract';
import {
  dashboardReadableTypes,
  getWidgetDefinition,
  isLayerBound,
  parseStoredWidget,
} from '@/components/widgets/registry';
import { isAggregateNumeric, isDateColumn, isListableColumn, isSortableColumn } from '@/lib/column-utils';
import { canOpenAttributeTable } from '@/lib/layer-capabilities';
import { filterFields, layerFilterToServerCql2 } from '@/lib/maplibre-filter-utils';
import type { DashboardConfig, MapLayerResponse } from '@/types/api';
import type { components } from '@/types/api.generated';

/** The server's limit on widgets per dashboard (`MAX_DASHBOARD_WIDGETS` in maps/dashboard.py). */
export const MAX_DASHBOARD_WIDGETS = 50;

/** The Builder's working copy of a map's dashboard. */
export interface DashboardDraft {
  panel: PanelPosition;
  theme?: DashboardTheme;
  widgets: WidgetInstance[];
  /** Set only when the author hides the map; an absent value is a visible map. */
  mapHidden?: boolean;
}

export type DashboardTheme = DashboardConfig['theme'];

type DashboardConfigInput = components['schemas']['DashboardConfigInput'];

/** The dashboard as the map response shows it, ready to edit. */
export function toDashboardDraft(config: DashboardConfig | null | undefined): DashboardDraft {
  const widgets: WidgetInstance[] = [];
  for (const raw of config?.widgets ?? []) {
    const parsed = parseStoredWidget(raw, 'dashboard');
    if (parsed.ok) widgets.push(parsed.instance);
  }
  return {
    panel: dashboardPanelPosition(config),
    theme: config?.theme,
    widgets,
    ...(config?.map_hidden ? { mapHidden: true } : {}),
  };
}

/**
 * A widget as a save stores it: its title trimmed and left out when blank, its
 * filter left out when it has none, and its version the oldest one that can
 * hold its config and filter.
 */
function toSaved({ title, filter, ...widget }: WidgetInstance): WidgetInstance {
  const definition = getWidgetDefinition(widget.type, 'dashboard');
  const base = definition?.storedVersion?.(widget.config) ?? widget.v;
  const filterVersion = filter ? definition?.filterVersion : undefined;
  const v = filterVersion ? Math.max(base, filterVersion) : base;
  const saved: WidgetInstance = { ...widget, v, ...(filterVersion ? { filter } : {}) };
  return title?.trim() ? { ...saved, title: title.trim() } : saved;
}

/**
 * The dashboard the server stores for a save of `draft`, in the form a map
 * response reads back: titles trimmed or left out, and no widgets meaning no
 * dashboard, which reads as a right panel with the map shown. With `layers`, the widgets whose
 * layer is gone from them are dropped, as a save does.
 */
export function canonicalDashboard(
  draft: DashboardDraft,
  layers?: readonly MapLayerResponse[],
): DashboardDraft {
  const kept = layers ? draft.widgets.filter((widget) => !widgetLayerGone(widget, layers)) : draft.widgets;
  const widgets = kept.map(toSaved);
  if (widgets.length === 0) return { panel: 'right', widgets };
  return {
    panel: draft.panel,
    widgets,
    ...(draft.mapHidden ? { mapHidden: true } : {}),
    // An absent theme reads as `follow`, which a dashboard stores as nothing.
    ...(draft.theme && draft.theme !== 'follow' ? { theme: draft.theme } : {}),
  };
}

/**
 * Whether `a` and `b` store different dashboards: compared in their canonical
 * forms, and with `layers` as a save to those layers would store them.
 */
export function dashboardChanged(
  a: DashboardDraft,
  b: DashboardDraft,
  layers?: readonly MapLayerResponse[],
): boolean {
  return !deepEqual(canonicalDashboard(a, layers), canonicalDashboard(b, layers));
}

/** The layers a dashboard widget can summarize: those with rows to aggregate. */
export function dashboardLayers(layers: readonly MapLayerResponse[]): MapLayerResponse[] {
  return layers.filter(canOpenAttributeTable);
}

/** True when the widget's layer is no longer one it can summarize; the save drops the widget. */
export function widgetLayerGone(widget: WidgetInstance, layers: readonly MapLayerResponse[]): boolean {
  if (!isLayerBound(widget.type)) return false;
  return !layers.some((layer) => layer.id === widget.layer_id && canOpenAttributeTable(layer));
}

export type WidgetProblem =
  | { kind: 'missingColumn' | 'notNumeric' | 'notSortable' | 'notListable' | 'notDate'; column: string }
  /** The widget follows the map view on a layer with no geometry, which the endpoint refuses. */
  | { kind: 'viewWithoutGeometry' }
  /** The widget's own filter is one the aggregate endpoint can't take. */
  | { kind: 'filterUnsupported' };

/** True when `layer` has geometry a map view can bound. */
export function layerFollowsView(layer: MapLayerResponse): boolean {
  return !!layer.dataset_geometry_type;
}

/**
 * What stops the widget from saving on `layer`: a view scope the layer can't
 * follow, a column it lacks or holds as anything but a number where one is
 * needed, or a filter the aggregate endpoint can't take. Without column
 * metadata the server judges the columns.
 */
export function widgetProblem(widget: WidgetInstance, layer: MapLayerResponse): WidgetProblem | null {
  if (widget.scope === 'view' && !layerFollowsView(layer)) return { kind: 'viewWithoutGeometry' };
  const columns = layer.dataset_column_info;
  if (!columns) return null;
  const uses = getWidgetDefinition(widget.type, 'dashboard')?.readsColumns?.(widget.config) ?? [];
  for (const use of uses) {
    const column = columns.find((candidate) => candidate.name === use.name);
    if (!column) return { kind: 'missingColumn', column: use.name };
    if (use.numeric && !isAggregateNumeric(column.type)) return { kind: 'notNumeric', column: use.name };
    if (use.date && !isDateColumn(column.type)) return { kind: 'notDate', column: use.name };
    if (use.listable && !isListableColumn(use.name, column.type)) return { kind: 'notListable', column: use.name };
    if (use.sortable && !isSortableColumn(use.name, column.type)) return { kind: 'notSortable', column: use.name };
  }
  if (!widget.filter) return null;
  const missing = filterFields(widget.filter).find((name) => !columns.some((column) => column.name === name));
  if (missing !== undefined) return { kind: 'missingColumn', column: missing };
  return layerFilterToServerCql2(widget.filter, columns) === 'unsupported' ? { kind: 'filterUnsupported' } : null;
}

/** The first problem that holds the save; a widget whose layer is gone isn't sent, so it holds nothing. */
export function firstWidgetProblem(
  draft: DashboardDraft,
  layers: readonly MapLayerResponse[],
): WidgetProblem | null {
  for (const widget of draft.widgets) {
    const layer = layers.find((candidate) => candidate.id === widget.layer_id);
    if (!layer || !canOpenAttributeTable(layer)) continue;
    const problem = widgetProblem(widget, layer);
    if (problem) return problem;
  }
  return null;
}

/** What a server takes a save to read when it names nothing: the dashboard widgets of earlier releases. */
const LEGACY_READABLE = ['markdown:1', 'indicator:1', 'bar_chart:1', 'histogram:1', 'category_selector:1'];

/**
 * The `type:v` pairs this build parses, or undefined when they are the ones a
 * server assumes. An earlier server refuses the key, so it goes only when it
 * says something. A stored widget outside the list is kept in place by the server.
 */
function readableToSend(): string[] | undefined {
  const reads = dashboardReadableTypes();
  const same = reads.length === LEGACY_READABLE.length && LEGACY_READABLE.every((pair) => reads.includes(pair));
  return same ? undefined : reads;
}

/** A key an older server refuses: present only when it carries a value now or did when last stored. */
function sentIfSetNowOrBefore<K extends string, V>(key: K, value: V, send: boolean): { [P in K]?: V } {
  return send ? ({ [key]: value } as { [P in K]: V }) : {};
}

/**
 * The save payload, which for a dashboard emptied of widgets still lists what
 * this build reads, so the server clears those stored widgets rather than keeping them.
 */
export function dashboardSavePayload(
  draft: DashboardDraft,
  layers: readonly MapLayerResponse[],
  saved: DashboardDraft,
): DashboardConfigInput | null {
  const payload = dashboardPayload(draft, layers, saved);
  const readable = readableToSend();
  if (payload || saved.widgets.length === 0 || !readable) return payload;
  return {
    version: 1,
    panel: 'right',
    map_hidden: false,
    theme: 'follow',
    readable,
    widgets: [],
  };
}

/**
 * The `dashboard_config` a save sends: the draft without the widgets whose
 * layer is gone, or null when none are left. `panel` is sent only when the
 * panel is or was at the bottom: a 1.28.0 server refuses the key during a
 * rolling upgrade, and one that stored a bottom panel knows it. `map_hidden`
 * follows the same rule: sent when the map is hidden, or was and is shown again.
 * `theme` follows the same rule, and goes out as `follow` to reset a stored
 * light or dark. `saved` is the dashboard as last stored.
 */
export function dashboardPayload(
  draft: DashboardDraft,
  layers: readonly MapLayerResponse[],
  saved: Pick<DashboardDraft, 'panel' | 'mapHidden' | 'theme'>,
): DashboardConfigInput | null {
  const { panel, widgets, mapHidden, theme = 'follow' } = canonicalDashboard(draft, layers);
  if (widgets.length === 0) return null;
  const readable = readableToSend();
  return {
    version: 1,
    ...sentIfSetNowOrBefore('panel', panel, panel === 'bottom' || saved.panel === 'bottom'),
    ...sentIfSetNowOrBefore('map_hidden', !!mapHidden, !!mapHidden || !!saved.mapHidden),
    ...sentIfSetNowOrBefore('theme', theme, theme !== 'follow' || (saved.theme ?? 'follow') !== 'follow'),
    ...(readable ? { readable } : {}),
    widgets: widgets as DashboardConfigInput['widgets'],
  } as DashboardConfigInput;
}
