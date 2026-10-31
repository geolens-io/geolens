import type { FilterSpecification } from 'maplibre-gl';
import { convertFilter } from '@maplibre/maplibre-gl-style-spec';
import { shouldFetchClusterGeoJson } from '@/components/builder/cluster-source';
import type { SelectionValue, WidgetSelection } from '@/components/widgets/contract';
import { isIntegerColumn } from '@/lib/column-utils';
import {
  buildNullSafeNumericComparison,
  layerFilterToServerCql2,
  legacyFilterToExpression,
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
 * With `geoJson`, each value or range edge also matches the spelling a
 * bounded cluster's GeoJSON gives it (`geoJsonSpellings`).
 */
export function selectionFilter(selection: WidgetSelection, type?: string, geoJson = false): FilterSpecification {
  const { column } = selection;
  if ('range' in selection) {
    let { lower, upper } = selection.range;
    const { includeUpper } = selection.range;
    if (type && isIntegerColumn(type)) {
      lower = Math.ceil(lower);
      upper = includeUpper ? Math.floor(upper) : Math.ceil(upper);
    } else if (type === 'real') {
      // The server rounds an edge to float4. Edges that are float4 already, the
      // lower one up and an exclusive upper one up, keep exactly the values the
      // bin's float8 range holds, as the map compares them.
      lower = float4Ceil(lower);
      upper = includeUpper ? float4Floor(upper) : float4Ceil(upper);
      if (geoJson) {
        // GeoJSON writes an edge's value as its shortest decimal, which can sit on
        // either side of the edge; each bound moves to whichever keeps the same points.
        lower = Math.min(lower, float4Text(lower));
        upper = includeUpper ? Math.max(upper, float4Text(upper)) : Math.min(upper, float4Text(upper));
      }
    }
    return [
      'all',
      buildNullSafeNumericComparison(column, '>=', lower),
      buildNullSafeNumericComparison(column, includeUpper ? '<=' : '<', upper),
    ] as unknown as FilterSpecification;
  }
  const parts: unknown[] = [];
  const values = geoJson ? selection.values.flatMap((value) => geoJsonSpellings(value, type)) : selection.values;
  const listed = values.filter((value) => value !== null && typeof value !== 'number');
  if (listed.length > 0) parts.push(['in', ['get', column], ['literal', listed]]);
  for (const value of values) {
    if (typeof value === 'number') parts.push(buildNullSafeNumericComparison(column, '==', value));
  }
  if (selection.values.includes(null)) {
    parts.push(['any', ['!', ['has', column]], ['==', ['get', column], null]]);
  }
  return (parts.length === 1 ? parts[0] : ['any', ...parts]) as FilterSpecification;
}

const FLOAT4_BITS = new DataView(new ArrayBuffer(4));

/** The smallest float4 that is at least `value`, as a double. */
function float4Ceil(value: number): number {
  const rounded = Math.fround(value);
  if (!Number.isFinite(rounded) || rounded >= value) return rounded;
  if (rounded === 0) return 2 ** -149;
  FLOAT4_BITS.setFloat32(0, rounded);
  FLOAT4_BITS.setInt32(0, FLOAT4_BITS.getInt32(0) + (rounded > 0 ? 1 : -1));
  return FLOAT4_BITS.getFloat32(0);
}

/** The largest float4 that is at most `value`, as a double. */
function float4Floor(value: number): number {
  return -float4Ceil(-value);
}

/** The shortest decimal that reads back as the float4 `value`, as PostgreSQL writes a `real` in JSON. */
function float4Text(value: number): number {
  if (Math.fround(value) !== value) return value;
  for (let digits = 1; digits <= 9; digits += 1) {
    const shortest = Number(value.toPrecision(digits));
    if (Math.fround(shortest) === value) return shortest;
  }
  return value;
}

/**
 * A picked value as each source of the map's features writes it. The value
 * comes from the aggregate endpoint, which writes a timestamp as PostgreSQL
 * text and a `real` at double precision, as vector tiles do. A bounded
 * cluster's GeoJSON is written by `to_jsonb`, which puts a `T` in a timestamp
 * and the shortest decimal in a `real`. A timestamptz is left alone: the
 * endpoint, the tiles and the GeoJSON all write it as the same UTC text.
 */
function geoJsonSpellings(value: SelectionValue, type: string | undefined): SelectionValue[] {
  if (typeof value === 'string' && type === 'timestamp without time zone' && value.includes(' ')) {
    return [value, value.replace(' ', 'T')];
  }
  if (typeof value === 'number' && type === 'real') {
    const json = float4Text(value);
    return json === value ? [value] : [value, json];
  }
  return [value];
}

/**
 * `filter` in expression syntax. MapLibre reads a filter wholly as expressions
 * or wholly as the legacy syntax, so a legacy saved filter must be converted
 * before picks join it. The editor's forms come first, so the cluster tiles
 * can still send it as CQL2; failing those, MapLibre's converter writes it,
 * and one that refuses too comes back unchanged.
 */
function expressionFilter(filter: FilterSpecification): FilterSpecification {
  const translated = legacyFilterToExpression(filter);
  if (translated && translated !== 'unsupported') return translated;
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
    // A bounded cluster draws its GeoJSON, or its tiles while that loads.
    const geoJson = shouldFetchClusterGeoJson(layer);
    const picked = own.map(({ selection }) => selectionFilter(selection, columnType(layer, selection.column), geoJson));
    const parts = [...saved, ...picked];
    return { ...layer, filter: (parts.length === 1 ? parts[0] : ['all', ...parts]) as FilterSpecification };
  });
}

/**
 * Whether the viewer's map holds `column` on the layer's features, so a pick
 * on it can filter them there. A bounded cluster loads its points as GeoJSON
 * with every property; tiles carry only the dataset's allowlist, when it has one.
 */
export function mapCarriesColumn(layer: SharedLayerResponse, column: string): boolean {
  if (shouldFetchClusterGeoJson(layer)) return true;
  const allowlist = layer.dataset_tile_columns;
  return allowlist == null || allowlist.includes(column);
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
