/**
 * normalize-saved-map.ts
 *
 * BSR-21: Single read-time boundary shared by `getMap()` and `getSharedMap()` in
 * `frontend/src/api/maps.ts`. Accepts raw `MapResponse` (builder/public viewer) or
 * `SharedMapResponse` (shared-token/embed viewer) and emits a `NormalizedSavedMap`
 * that is structurally compatible with `MapStackMapInput` consumed by `buildMapStack`.
 *
 * Rules:
 * - Pure function: never mutates input, returns a new object literal.
 * - No thrown exceptions: unrecognized/missing required fields produce console.warn
 *   (DEV only) and fall back to best-effort defaults.
 * - Imports only from @/types/api — no UI, hook, or builder dependencies.
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
   * Basemap label; pulled from input when present, else null.
   * NOTE: MapResponse and SharedMapResponse do not carry this field — it is
   * derived from basemap settings in the UI layer (currentBasemapEntry() in
   * MapStackPanel.tsx). This field is always null for real API inputs and
   * exists only to satisfy the MapStackMapInput-compatible output shape used
   * by test fixtures and direct callers that pass Partial<MapStackMapInput>.
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
  /** Widget list; defaults to null when input has undefined widgets. */
  widgets: string[] | null;
};

/**
 * Union input shape accepted by `normalizeSavedMap`. Covers:
 * - `MapResponse` (builder + public viewer fetch)
 * - `SharedMapResponse` (shared-token + embed viewer fetch)
 * - Partial `MapStackMapInput`-like objects (for test fixtures and defensive callers)
 */
export type SavedMapInput<TLayer = MapLayerResponse | SharedLayerResponse> =
  | MapResponse
  | SharedMapResponse
  | (Partial<{
      basemap_style: string | null;
      basemap_label: string | null;
      show_basemap_labels: boolean | null;
      basemap_config: MapBasemapConfig | null;
      terrain_config: MapTerrainConfig | null;
      layers: TLayer[];
      widgets: string[] | null;
    }>);

/**
 * Normalize a raw saved-map API response into a stable `NormalizedSavedMap` shape.
 *
 * This is the single read-time boundary all four viewer surfaces (builder, public,
 * shared, embed) route through. It guarantees:
 * - `basemap_style` is always a non-empty string (falls back to 'default').
 * - `show_basemap_labels` is always a boolean (defaults to true when absent).
 * - `layers` is always an array (defaults to []).
 * - `widgets` is always string[] | null (never undefined).
 * - `basemap_config` and `terrain_config` are preserved verbatim.
 *
 * @param input Raw MapResponse or SharedMapResponse from the API.
 * @returns NormalizedSavedMap — a fresh object; input is never mutated.
 */
export function normalizeSavedMap<TLayer = MapLayerResponse | SharedLayerResponse>(
  input: SavedMapInput<TLayer>,
): NormalizedSavedMap<TLayer> {
  // basemap_style: must be a non-empty string; warn and fall back to 'default' if missing.
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

  // basemap_label: optional on all input shapes; null when absent.
  const rawLabel = (input as Record<string, unknown>).basemap_label;
  const basemap_label: string | null =
    typeof rawLabel === 'string' ? rawLabel : null;

  // show_basemap_labels: optional on SharedMapResponse (older payloads omit it).
  // Mirrors map-stack.ts:495 `show_basemap_labels ?? true` default.
  const rawShowLabels = (input as Record<string, unknown>).show_basemap_labels;
  const show_basemap_labels: boolean =
    typeof rawShowLabels === 'boolean' ? rawShowLabels : true;

  // basemap_config: preserved verbatim; null when absent.
  const rawBasemapConfig = (input as Record<string, unknown>).basemap_config;
  const basemap_config: MapBasemapConfig | null =
    rawBasemapConfig != null && typeof rawBasemapConfig === 'object'
      ? (rawBasemapConfig as MapBasemapConfig)
      : null;

  // terrain_config: preserved verbatim; null when absent.
  const rawTerrainConfig = (input as Record<string, unknown>).terrain_config;
  const terrain_config: MapTerrainConfig | null =
    rawTerrainConfig != null && typeof rawTerrainConfig === 'object'
      ? (rawTerrainConfig as MapTerrainConfig)
      : null;

  // layers: defaults to [] when absent; never undefined.
  const rawLayers = (input as Record<string, unknown>).layers;
  const layers: TLayer[] = Array.isArray(rawLayers) ? (rawLayers as TLayer[]) : [];

  // widgets: defaults to null when undefined; canonical null over undefined.
  const rawWidgets = (input as Record<string, unknown>).widgets;
  const widgets: string[] | null =
    Array.isArray(rawWidgets) ? (rawWidgets as string[]) : null;

  return {
    basemap_style,
    basemap_label,
    show_basemap_labels,
    basemap_config,
    terrain_config,
    layers,
    widgets,
  };
}
