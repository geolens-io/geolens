/**
 * Single read-time boundary shared by `getMap()` and `getSharedMap()` in
 * `frontend/src/api/maps.ts`. Accepts a raw `MapResponse` or `SharedMapResponse`
 * and emits a `NormalizedSavedMap` compatible with `MapStackMapInput`.
 *
 * Pure (never mutates input), never throws (missing required fields warn in DEV
 * and fall back to defaults), and imports only from @/types/api.
 */
import type { MapBasemapConfig, MapLayerResponse, MapResponse, MapTerrainConfig, SharedLayerResponse, SharedMapResponse } from '@/types/api';

/**
 * The normalized shape produced by `normalizeSavedMap`. Structurally compatible
 * with `MapStackMapInput` from `frontend/src/components/builder/map-stack.ts`
 * but generic over the layer element type so `SharedLayerResponse[]` passes through
 * unchanged for shared/embed viewers.
 */
export type NormalizedSavedMap<TLayer = MapLayerResponse | SharedLayerResponse> = {
  /** Canonical non-null basemap style identifier; falls back to 'default'. */
  basemap_style: string;
  /**
   * Basemap label. MapResponse and SharedMapResponse do not carry this field, so
   * it is always null for real API inputs and exists for fixtures and callers
   * passing Partial<SavedMapInput>.
   */
  basemap_label: string | null;
  /** Whether basemap labels are shown; defaults to true when absent (older shared payloads). */
  show_basemap_labels: boolean;
  /** Basemap configuration object, preserved verbatim. */
  basemap_config: MapBasemapConfig | null;
  /** Terrain configuration object, preserved verbatim. */
  terrain_config: MapTerrainConfig | null;
  /** Layer array; defaults to [] when input has no layers field. */
  layers: TLayer[];
  /** Plugin list; defaults to null when input has undefined plugins. */
  plugins: string[] | null;
  /**
   * Per-group expansion state. Keys are group IDs; values carry { expanded: boolean }.
   * Defaults to {} when absent (all groups start collapsed).
   */
  group_meta: Record<string, { expanded: boolean }>;
};

/**
 * Union input shape accepted by `normalizeSavedMap`. Covers:
 * - `MapResponse` (builder + public viewer fetch)
 * - `SharedMapResponse` (shared-token + embed viewer fetch)
 * - Partial `MapStackMapInput`-like objects (for test fixtures and defensive callers)
 */
type SavedMapInput<TLayer = MapLayerResponse | SharedLayerResponse> =
  | MapResponse
  | SharedMapResponse
  | (Partial<{
      basemap_style: string | null;
      basemap_label: string | null;
      show_basemap_labels: boolean | null;
      basemap_config: MapBasemapConfig | null;
      terrain_config: MapTerrainConfig | null;
      layers: TLayer[];
      plugins: string[] | null;
      group_meta?: Record<string, { expanded: boolean }> | null;
    }>);

/**
 * Normalize a raw saved-map API response into a stable `NormalizedSavedMap`.
 * The single read-time boundary for all four viewer surfaces (builder, public,
 * shared, embed). Guarantees: `basemap_style` is a non-empty string (falls back
 * to 'default'), `show_basemap_labels` a boolean (true when absent), `layers`
 * an array, `plugins` string[] | null, and `basemap_config`/`terrain_config`
 * preserved verbatim. Returns a fresh object; input is never mutated.
 */
export function normalizeSavedMap<TLayer = MapLayerResponse | SharedLayerResponse>(
  input: SavedMapInput<TLayer>,
): NormalizedSavedMap<TLayer> {
  const rawStyle = (input as Record<string, unknown>).basemap_style;
  let basemap_style: string;
  if (rawStyle && typeof rawStyle === 'string') {
    basemap_style = rawStyle;
  } else {
    if (import.meta.env.DEV) {
      console.warn(
        '[normalize-saved-map] basemap_style is missing or invalid; falling back to "default".',
        { received: rawStyle },
      );
    }
    basemap_style = 'default';
  }

  const rawLabel = (input as Record<string, unknown>).basemap_label;
  const basemap_label: string | null =
    typeof rawLabel === 'string' ? rawLabel : null;

  // Older SharedMapResponse payloads omit show_basemap_labels.
  const rawShowLabels = (input as Record<string, unknown>).show_basemap_labels;
  const show_basemap_labels: boolean =
    typeof rawShowLabels === 'boolean' ? rawShowLabels : true;

  const rawBasemapConfig = (input as Record<string, unknown>).basemap_config;
  const basemap_config: MapBasemapConfig | null =
    rawBasemapConfig != null && typeof rawBasemapConfig === 'object'
      ? (rawBasemapConfig as MapBasemapConfig)
      : null;

  const rawTerrainConfig = (input as Record<string, unknown>).terrain_config;
  const terrain_config: MapTerrainConfig | null =
    rawTerrainConfig != null && typeof rawTerrainConfig === 'object'
      ? (rawTerrainConfig as MapTerrainConfig)
      : null;

  const rawLayers = (input as Record<string, unknown>).layers;
  const layers: TLayer[] = Array.isArray(rawLayers) ? (rawLayers as TLayer[]) : [];

  const rawPlugins = (input as Record<string, unknown>).plugins;
  const plugins: string[] | null =
    Array.isArray(rawPlugins) ? (rawPlugins as string[]) : null;

  // Entries are sanitized to objects with a boolean `expanded`: a malformed
  // { "g1": null } or { "g1": { "expanded": "yes" } } would otherwise flip the
  // toggle logic (!null === true).
  const rawGroupMeta = (input as Record<string, unknown>).group_meta;
  const group_meta: Record<string, { expanded: boolean }> = {};
  if (rawGroupMeta != null && typeof rawGroupMeta === 'object' && !Array.isArray(rawGroupMeta)) {
    for (const [key, val] of Object.entries(rawGroupMeta as Record<string, unknown>)) {
      if (val != null && typeof val === 'object' && !Array.isArray(val)) {
        const entry = val as Record<string, unknown>;
        group_meta[key] = { expanded: entry.expanded === true };
      }
    }
  }

  return {
    basemap_style,
    basemap_label,
    show_basemap_labels,
    basemap_config,
    terrain_config,
    layers,
    plugins,
    group_meta,
  };
}
