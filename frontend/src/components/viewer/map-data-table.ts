import type { Map as MaplibreMap } from 'maplibre-gl';
import type { AttributeTableProps } from '@/components/dataset/AttributeTable';
import type { HighlightTarget } from '@/components/dataset/hooks/use-map-feature-highlight';
import { canOpenAttributeTable } from '@/lib/layer-capabilities';
import type { Bbox } from '@/lib/bbox';
import type { Cql2Expression } from '@/lib/maplibre-filter-utils';
import type { SharedLayerResponse } from '@/types/api';
import { viewerManagedLayerIds } from './viewer-query-layer-ids';

type TableColumns = NonNullable<AttributeTableProps['columns']>;

/**
 * Whether a layer offers a reader table: it has a feature table, and its popup
 * is enabled and lists at least one field.
 */
export function offersTable(layer: SharedLayerResponse): boolean {
  const popup = layer.popup_config;
  return canOpenAttributeTable(layer) && popup?.enabled !== false && popup?.visible_fields?.length !== 0;
}

/**
 * The columns a reader's table offers: the popup fields first, in popup
 * order, then the layer's other columns and the row id waiting in the Columns
 * menu; all with attribute titles and value labels. An embed reader of a
 * non-public dataset gets only its tile column allowlist (plus the row id),
 * as the rows route does. Undefined (every returned column) when the layer
 * names no columns at all.
 */
export function tableColumns(
  layer: SharedLayerResponse,
  { embedded, allDatasetsPublic }: { embedded: boolean; allDatasetsPublic: boolean },
): TableColumns | undefined {
  const info = layer.column_info ?? [];
  const byName = new Map(info.map((col) => [col.name, col]));
  const shown = layer.popup_config?.visible_fields ?? info.map((col) => col.name);
  const shownSet = new Set(shown);
  const rest = [...info.map((col) => col.name).filter((name) => !shownSet.has(name)), 'gid']
    .filter((name) => !shownSet.has(name));
  const allowlist = embedded && !allDatasetsPublic && layer.dataset_tile_columns
    ? new Set(['gid', ...layer.dataset_tile_columns])
    : null;
  const entry = (name: string, hidden: boolean) => {
    const col = byName.get(name);
    return { name, title: col?.title || undefined, valueLabels: col?.value_labels, hidden };
  };
  if (info.length === 0 && !layer.popup_config?.visible_fields) {
    return allowlist ? [...allowlist].map((name) => entry(name, name === 'gid')) : undefined;
  }
  return [...shown.map((name) => entry(name, false)), ...rest.map((name) => entry(name, true))]
    .filter(({ name }) => !allowlist || allowlist.has(name));
}

function ring(west: number, south: number, east: number, north: number): number[][] {
  return [[west, south], [east, south], [east, north], [west, north], [west, south]];
}

/**
 * CQL2 for "intersects the map view". A view across the antimeridian (west >
 * east) splits at it, as the server's bbox literal does.
 */
export function inViewFilter([west, rawSouth, east, rawNorth]: Bbox): Cql2Expression {
  const south = Math.max(-90, rawSouth);
  const north = Math.min(90, rawNorth);
  const geometry = west > east
    ? { type: 'MultiPolygon', coordinates: [[ring(west, south, 180, north)], [ring(-180, south, east, north)]] }
    : { type: 'Polygon', coordinates: [ring(west, south, east, north)] };
  return { op: 's_intersects', args: [{ property: 'geometry' }, geometry] };
}

/** AND of the given expressions, serialized for the rows route; undefined when there are none. */
export function combineCql2(...parts: (Cql2Expression | null)[]): string | undefined {
  const present = parts.filter((part): part is Cql2Expression => part !== null);
  if (present.length === 0) return undefined;
  return JSON.stringify(present.length === 1 ? present[0] : { op: 'and', args: present });
}

/**
 * The map source a layer draws from, for a highlight by feature id. Read from
 * the layer's own style layers, so cluster and vector-tile sources both resolve.
 */
export function layerHighlightSource(
  map: MaplibreMap,
  layer: SharedLayerResponse,
  key: string,
): Omit<Extract<HighlightTarget, { source: string }>, 'bbox'> | null {
  for (const id of viewerManagedLayerIds(layer, key)) {
    const styleLayer = map.getLayer(id);
    if (styleLayer?.source) {
      return styleLayer.sourceLayer
        ? { source: styleLayer.source, sourceLayer: styleLayer.sourceLayer }
        : { source: styleLayer.source };
    }
  }
  return null;
}
