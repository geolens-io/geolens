import type { LayerSpec } from './layer-adapters/types';

const LEGACY_FILTER_OPERATORS = new Set(['==', '!=', '<', '>', '<=', '>=', 'in', '!in', 'has', '!has']);
// MapLibre's legacy token syntax, which text-field and icon-image still accept.
const TOKEN = /\{([^{}]+)\}/g;
const TOKEN_KEYS = new Set(['text-field', 'icon-image']);

/** What the cluster tile query emits itself; these are not dataset columns. */
export const CLUSTER_OUTPUT_PROPERTIES: ReadonlySet<string> = new Set([
  'cluster', 'point_count', 'point_count_abbreviated', 'cluster_id', 'expansion_zoom', 'source_gid',
]);

/**
 * The feature columns a map layer reads, and whether it also reads columns it
 * does not name: a computed property name or `properties`. A source with such a
 * layer cannot be narrowed to a list of columns.
 *
 * Every `get` or `has` of an
 * expression, the `property` of a legacy function, the field of a legacy
 * filter and the `{field}` tokens of a text or icon layout value.
 */
export function columnsReadBy(layer: LayerSpec['layer']): { cols: string[]; dynamic: boolean } {
  const cols = new Set<string>();
  let dynamic = false;

  function walk(node: unknown): void {
    if (Array.isArray(node)) {
      if ((node[0] === 'get' || node[0] === 'has') && typeof node[1] === 'string') {
        cols.add(node[1]);
        return;
      }
      if (node[0] === 'properties' || ((node[0] === 'get' || node[0] === 'has') && node.length > 1 && typeof node[1] !== 'string')) {
        dynamic = true;
      }
      for (const child of node) walk(child);
      return;
    }
    if (node && typeof node === 'object') {
      const { property } = node as { property?: unknown };
      if (typeof property === 'string' && property) cols.add(property);
      for (const child of Object.values(node)) walk(child);
    }
  }

  function walkTokens(value: unknown): void {
    if (typeof value === 'string') {
      for (const match of value.matchAll(TOKEN)) cols.add(match[1]);
    } else if (Array.isArray(value)) {
      value.forEach(walkTokens);
    }
  }

  function walkLegacyFilter(node: unknown): void {
    if (!Array.isArray(node)) return;
    const [op, field] = node;
    if (op === 'all' || op === 'any' || op === 'none') {
      for (const child of node.slice(1)) walkLegacyFilter(child);
    } else if (typeof field === 'string' && field !== '$type' && field !== '$id'
      && LEGACY_FILTER_OPERATORS.has(op as string)) {
      cols.add(field);
    }
  }

  walk(layer.paint);
  walk(layer.layout);
  walk(layer.filter);
  walkLegacyFilter(layer.filter);
  for (const key of TOKEN_KEYS) walkTokens(layer.layout?.[key]);
  return { cols: [...cols], dynamic };
}
