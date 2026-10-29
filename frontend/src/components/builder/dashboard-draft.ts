import { deepEqual } from '@/components/builder/LayerStyleEditor/utils';
import { dashboardPanelPosition, type PanelPosition } from '@/components/viewer/DashboardPanel';
import type { WidgetInstance } from '@/components/widgets/contract';
import { getWidgetDefinition, parseStoredWidget } from '@/components/widgets/registry';
import { isAggregateNumeric } from '@/lib/column-utils';
import { canOpenAttributeTable } from '@/lib/layer-capabilities';
import type { DashboardConfig, MapLayerResponse } from '@/types/api';
import type { components } from '@/types/api.generated';

/** The server's limit on widgets per dashboard (`MAX_DASHBOARD_WIDGETS` in maps/dashboard.py). */
export const MAX_DASHBOARD_WIDGETS = 50;

/** The Builder's working copy of a map's dashboard. */
export interface DashboardDraft {
  panel: PanelPosition;
  widgets: WidgetInstance[];
}

type DashboardConfigInput = components['schemas']['DashboardConfigInput'];

/** The dashboard as the map response shows it, ready to edit. */
export function toDashboardDraft(config: DashboardConfig | null | undefined): DashboardDraft {
  const widgets: WidgetInstance[] = [];
  for (const raw of config?.widgets ?? []) {
    const parsed = parseStoredWidget(raw, 'dashboard');
    if (parsed.ok) widgets.push(parsed.instance);
  }
  return { panel: dashboardPanelPosition(config), widgets };
}

/** A widget as a save stores it: its title trimmed, and left out when blank. */
function toSaved({ title, ...widget }: WidgetInstance): WidgetInstance {
  return title?.trim() ? { ...widget, title: title.trim() } : widget;
}

/**
 * The dashboard the server stores for a save of `draft`, in the form a map
 * response reads back: titles trimmed or left out, and no widgets meaning no
 * dashboard, which reads as a right panel. With `layers`, the widgets whose
 * layer is gone from them are dropped, as a save does.
 */
export function canonicalDashboard(
  draft: DashboardDraft,
  layers?: readonly MapLayerResponse[],
): DashboardDraft {
  const kept = layers ? draft.widgets.filter((widget) => !widgetLayerGone(widget, layers)) : draft.widgets;
  const widgets = kept.map(toSaved);
  return { panel: widgets.length > 0 ? draft.panel : 'right', widgets };
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
  return !layers.some((layer) => layer.id === widget.layer_id && canOpenAttributeTable(layer));
}

export type WidgetProblem =
  | { kind: 'missingColumn' | 'notNumeric'; column: string }
  /** The widget follows the map view on a layer with no geometry, which the endpoint refuses. */
  | { kind: 'viewWithoutGeometry' };

/** True when `layer` has geometry a map view can bound. */
export function layerFollowsView(layer: MapLayerResponse): boolean {
  return !!layer.dataset_geometry_type;
}

/**
 * What stops the widget from saving on `layer`: a view scope the layer can't
 * follow, or a column it lacks or holds as anything but a number where one is
 * needed. Without column metadata the server judges the columns.
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
  }
  return null;
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

/**
 * The `dashboard_config` a save sends: the draft without the widgets whose
 * layer is gone, or null when none are left. `panel` is sent only when the
 * panel is or was at the bottom: a 1.28.0 server refuses the key during a
 * rolling upgrade, and one that stored a bottom panel knows it.
 */
export function dashboardPayload(
  draft: DashboardDraft,
  layers: readonly MapLayerResponse[],
  savedPanel: PanelPosition,
): DashboardConfigInput | null {
  const { panel, widgets } = canonicalDashboard(draft, layers);
  if (widgets.length === 0) return null;
  return {
    version: 1,
    ...(panel === 'bottom' || savedPanel === 'bottom' ? { panel } : {}),
    widgets: widgets as DashboardConfigInput['widgets'],
  } as DashboardConfigInput;
}
