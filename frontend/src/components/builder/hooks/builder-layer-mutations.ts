import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerInput, MapLayerResponse, StyleConfig } from '@/types/api';
import { getAdapter } from '@/components/builder/layer-adapters/registry';

/**
 * Fallback suffix list used when no render mode is known (preserves back-compat
 * for the 3 existing call sites in use-builder-layers.ts that do not yet pass
 * renderModeByLayerId). The label companion is intentionally kept here because
 * no current adapter declares it in getLayerIds — labels are managed by
 * map-sync.ts syncLayersToMap, not by adapters.
 */
const FALLBACK_SUFFIXES = ['', '-outline', '-label', '-extrusion', '-arrow', '-cluster', '-cluster-count'];

/**
 * Derive the full set of MapLibre layer ids that the adapter owns for a given
 * prefixed layer id. Falls back to the static suffix list when the render mode
 * is unknown so that legacy call sites and future unregistered render modes
 * continue to work correctly.
 *
 * Known render_mode values NOT in the adapter registry:
 *   - 'arrow': not registered as a first-class adapter; getAdapter('arrow') returns the
 *     circleAdapter fallback whose type === 'circle'. The `adapter.type === renderMode`
 *     guard fails, causing the code to fall through to FALLBACK_SUFFIXES — which does
 *     include '-arrow'. This is the correct behavior. If 'arrow' is ever added to the
 *     registry, ensure getLayerIds returns both the base id and the '-arrow' companion.
 *     See MAP-17 Test 3c for the regression pin.
 *
 * @param prefixedLayerId - the `layer-<rawId>` form already including the prefix
 * @param renderMode - value from style_config.render_mode (or inferred adapter type)
 */
function deriveCompanionIds(prefixedLayerId: string, renderMode: string | null | undefined): string[] {
  if (renderMode) {
    try {
      // getAdapter returns circleAdapter as a fallback for unknown types; use
      // the adapter only when its registered type matches exactly.
      const adapter = getAdapter(renderMode);
      if (adapter.type === renderMode) {
        return adapter.getLayerIds(prefixedLayerId);
      }
    } catch {
      // Defensive — getAdapter should never throw, but fall through to suffix list
    }
  }
  return FALLBACK_SUFFIXES.map((suffix) => `${prefixedLayerId}${suffix}`);
}

/**
 * Imperatively remove per-layer companion MapLibre layers when a layer leaves
 * the builder draft. Sources are left for the normal sync prune because vector
 * sources may be shared by sibling layers.
 *
 * When `renderModeByLayerId` is provided, the function derives companion ids via
 * the LayerAdapter.getLayerIds() contract instead of the static suffix list.
 * Existing callers that omit `renderModeByLayerId` continue to use the suffix-
 * list fallback path — no call-site changes required.
 */
export function removePerLayerCompanions(
  map: MaplibreMap | null,
  layerIds: Iterable<string>,
  renderModeByLayerId?: Map<string, string>,
): void {
  if (!map || !map.isStyleLoaded()) return;
  for (const id of layerIds) {
    const prefixedId = `layer-${id}`;
    const renderMode = renderModeByLayerId?.get(id) ?? null;
    const companionIds = deriveCompanionIds(prefixedId, renderMode);
    for (const lid of companionIds) {
      if (map.getLayer(lid)) map.removeLayer(lid);
    }
  }
}

export function buildDuplicateRenderingInput(
  layer: MapLayerResponse,
  currentLayers: MapLayerResponse[],
): MapLayerInput {
  const nextSortOrder = currentLayers.reduce((max, candidate) => Math.max(max, candidate.sort_order), -1) + 1;
  const baseName = layer.display_name || layer.dataset_name || layer.dataset_table_name || 'Layer';
  return {
    dataset_id: layer.dataset_id,
    sort_order: nextSortOrder,
    visible: true,
    opacity: layer.opacity,
    paint: { ...(layer.paint ?? {}) },
    layout: { ...(layer.layout ?? {}) },
    display_name: `${baseName} rendering`,
    filter: layer.filter ?? null,
    label_config: layer.label_config ?? null,
    popup_config: layer.popup_config ?? null,
    style_config: layer.style_config ? ({ ...layer.style_config } as StyleConfig) : null,
    layer_type: layer.layer_type ?? null,
    show_in_legend: layer.show_in_legend ?? true,
  };
}
