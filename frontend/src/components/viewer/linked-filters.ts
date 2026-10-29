import type { FilterSpecification } from 'maplibre-gl';
import { convertFilter } from '@maplibre/maplibre-gl-style-spec';
import type { WidgetSelection } from '@/components/widgets/contract';
import { isIntegerColumn } from '@/lib/column-utils';
import {
  buildNullSafeNumericComparison,
  layerFilterToServerCql2,
  type Cql2Expression,
} from '@/lib/maplibre-filter-utils';
import type { SharedLayerResponse } from '@/types/api';

/** A reader's pick on one dashboard widget. It filters the widget's layer for the session and is never saved. */
export interface LinkedPick {
  widgetId: string;
  layerId: string;
  selection: WidgetSelection;
  /** The pick as the other widgets on the layer send it. */
  cql2: Cql2Expression;
}

export const NO_PICKS: readonly never[] = [];

function columnType(layer: SharedLayerResponse, column: string): string | undefined {
  return layer.column_info?.find((candidate) => candidate.name === column)?.type ?? undefined;
}

/**
 * The MapLibre filter that keeps the rows `selection` picks, written in the
 * forms the layer filter editor writes so `layerFilterToServerCql2` reads it as
 * it reads a saved filter. Numbers compare null-safely, as the editor's numeric
 * conditions do. On an integer column a range's edges move inward to the whole
 * numbers it holds, because the server takes only whole-number literals there.
 */
export function selectionFilter(selection: WidgetSelection, type?: string): FilterSpecification {
  const { column } = selection;
  if ('range' in selection) {
    let { lower, upper } = selection.range;
    const { includeUpper } = selection.range;
    if (type && isIntegerColumn(type)) {
      lower = Math.ceil(lower);
      upper = includeUpper ? Math.floor(upper) : Math.ceil(upper);
    }
    return [
      'all',
      buildNullSafeNumericComparison(column, '>=', lower),
      buildNullSafeNumericComparison(column, includeUpper ? '<=' : '<', upper),
    ] as unknown as FilterSpecification;
  }
  const parts: unknown[] = [];
  const listed = selection.values.filter((value) => value !== null && typeof value !== 'number');
  if (listed.length > 0) parts.push(['in', ['get', column], ['literal', listed]]);
  for (const value of selection.values) {
    if (typeof value === 'number') parts.push(buildNullSafeNumericComparison(column, '==', value));
  }
  if (selection.values.includes(null)) {
    parts.push(['any', ['!', ['has', column]], ['==', ['get', column], null]]);
  }
  return (parts.length === 1 ? parts[0] : ['any', ...parts]) as FilterSpecification;
}

/**
 * `filter` in expression syntax. MapLibre reads a filter wholly as expressions
 * or wholly as the legacy syntax, so a legacy saved filter must be converted
 * before picks join it. One the converter refuses comes back unchanged.
 */
function expressionFilter(filter: FilterSpecification): FilterSpecification {
  try {
    return convertFilter(filter as Parameters<typeof convertFilter>[0]) as FilterSpecification;
  } catch {
    return filter;
  }
}

/**
 * The layers as the viewer's map draws them: each layer with picks on it
 * gets a copy whose filter is its saved filter and every pick. The saved
 * layers are left as they are.
 */
export function linkMapLayers(
  layers: readonly SharedLayerResponse[],
  picks: readonly LinkedPick[],
): SharedLayerResponse[] {
  if (picks.length === 0) return layers as SharedLayerResponse[];
  return layers.map((layer) => {
    const own = picks.filter((pick) => pick.layerId === layer.id);
    if (own.length === 0) return layer;
    const saved = Array.isArray(layer.filter) && layer.filter.length > 0 ? [expressionFilter(layer.filter)] : [];
    const picked = own.map(({ selection }) => selectionFilter(selection, columnType(layer, selection.column)));
    const parts = [...saved, ...picked];
    return { ...layer, filter: (parts.length === 1 ? parts[0] : ['all', ...parts]) as FilterSpecification };
  });
}

/** The pick as CQL2 for `layer`'s rows, or null when the server can't take it, such as an unusual timestamp. */
export function selectionCql2(layer: SharedLayerResponse, selection: WidgetSelection): Cql2Expression | null {
  const converted = layerFilterToServerCql2(
    selectionFilter(selection, columnType(layer, selection.column)),
    layer.column_info,
  );
  return converted === 'unsupported' ? null : converted;
}

/**
 * The CQL2 filter a widget on `layer` sends: the layer's saved filter, unless
 * the server can't take it (`savedIgnored`), and the picks on the other widgets
 * on the layer. A widget's own pick is left out, so it keeps showing every value.
 */
export function widgetFilter(
  layer: SharedLayerResponse,
  otherPicks: readonly Cql2Expression[],
): { filter: Cql2Expression | null; savedIgnored: boolean } {
  const saved = layerFilterToServerCql2(layer.filter, layer.column_info);
  const parts: Cql2Expression[] = [...(saved && saved !== 'unsupported' ? [saved] : []), ...otherPicks];
  return {
    filter: parts.length === 0 ? null : parts.length === 1 ? parts[0] : { op: 'and', args: parts },
    savedIgnored: saved === 'unsupported',
  };
}
