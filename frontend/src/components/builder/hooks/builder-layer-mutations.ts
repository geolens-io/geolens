import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerInput, MapLayerResponse, MapTerrainConfig, StyleConfig } from '@/types/api';
import { getAdapter } from '@/components/builder/layer-adapters/registry';
import { isTerrainCapableDemLayer } from '@/components/builder/map-stack';
import { getCompanionLayerIds, COLOR_RELIEF_SUFFIX } from '@/components/builder/companion-ids';

/**
 * Phase 999.17 Fix 2 (D-05 / Advisory A2): decide whether deleting a layer must
 * tear down active 3D terrain.
 *
 * Terrain is backed by a DEM dataset (terrain_config.source_dataset_id), not by
 * a single layer id. The teardown keys on DATASET IDENTITY: terrain is cleared
 * ONLY when, after the delete, NO remaining layer is a DEM layer for the terrain
 * source dataset. This correctly:
 *   - clears when the (last) DEM backing the terrain dataset is removed,
 *   - PRESERVES terrain when an unrelated DEM/vector layer is deleted (A2),
 *   - PRESERVES terrain when another DEM layer on the same dataset still exists.
 *
 * @param remainingLayers - layers that survive the delete (already filtered)
 * @param terrainConfig - the current (local) terrain_config
 */
export function shouldClearTerrainOnDelete(
  remainingLayers: MapLayerResponse[],
  terrainConfig: MapTerrainConfig | null | undefined,
): boolean {
  if (!terrainConfig?.enabled || !terrainConfig.source_dataset_id) return false;
  const sourceDatasetId = terrainConfig.source_dataset_id;
  // 999.17 MD-02: "still backed" must mean "still RESOLVABLE as a terrain source"
  // — use the canonical isTerrainCapableDemLayer predicate (is_dem AND a DEM
  // record type) exactly as the mesh resolver (BuilderMap/use-viewer-terrain) and
  // the stack compute it. A bare is_dem check could keep terrain_config alive for
  // a layer the mesh resolver can no longer attach, leaving a dangling config.
  const datasetStillBacked = remainingLayers.some(
    (layer) => layer.dataset_id === sourceDatasetId && isTerrainCapableDemLayer(layer),
  );
  return !datasetStillBacked;
}

/**
 * Derive the full set of MapLibre layer ids that the adapter owns for a given
 * raw layer id. Falls back to the canonical companion-id set
 * (`getCompanionLayerIds`, SYNC-04) when the render mode is unknown so that
 * legacy call sites and future unregistered render modes continue to work.
 *
 * Known render_mode values NOT in the adapter registry:
 *   - 'arrow': not registered as a first-class adapter; getAdapter('arrow') returns the
 *     circleAdapter fallback whose type === 'circle'. The `adapter.type === renderMode`
 *     guard fails, causing the code to fall through to the companion-id fallback — which
 *     does include the '-arrow' companion. This is the correct behavior. If 'arrow' is
 *     ever added to the registry, ensure getLayerIds returns both the base id and the
 *     '-arrow' companion. See MAP-17 Test 3c for the regression pin.
 *
 * @param rawLayerId - the logical layer id (NOT prefixed with `layer-`)
 * @param renderMode - value from style_config.render_mode (or inferred adapter type)
 */
function deriveCompanionIds(rawLayerId: string, renderMode: string | null | undefined): string[] {
  const prefixedLayerId = `layer-${rawLayerId}`;
  if (renderMode) {
    try {
      // getAdapter returns circleAdapter as a fallback for unknown types; use
      // the adapter only when its registered type matches exactly.
      const adapter = getAdapter(renderMode);
      if (adapter.type === renderMode) {
        const ids = adapter.getLayerIds(prefixedLayerId);
        return renderMode === 'hillshade'
          ? [...ids, `${prefixedLayerId}${COLOR_RELIEF_SUFFIX}`]
          : ids;
      }
    } catch {
      // Defensive — getAdapter should never throw, but fall through to the
      // canonical companion-id set.
    }
  }
  // SYNC-04: the full companion set (base + outline + label + extrusion + arrow
  // + colorrelief + cluster + cluster-count) from the single source of truth.
  // The label companion is included because no current adapter declares it in
  // getLayerIds — labels are managed by map-sync.ts syncLayersToMap, not by
  // adapters. Color-relief is included because DEM hillshade layers can create
  // it as a conditional companion on the same raster-dem source.
  const c = getCompanionLayerIds(rawLayerId);
  return [c.layer, c.outline, c.label, c.extrusion, c.arrow, c.colorRelief, c.cluster, c.clusterCount, c.mixedLines, c.mixedPoints];
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
    const renderMode = renderModeByLayerId?.get(id) ?? null;
    const companionIds = deriveCompanionIds(id, renderMode);
    for (const lid of companionIds) {
      if (map.getLayer(lid)) map.removeLayer(lid);
    }
  }
}

export function buildDuplicateRenderingInput(
  layer: MapLayerResponse,
  // fix(#392): no longer used for the sort_order hint (kept
  // for call-site/type stability); the duplicate now anchors on the source
  // layer's own sort_order instead of scanning the full stack for its max. (audit B-004b/LM-02)
  _currentLayers: MapLayerResponse[],
): MapLayerInput {
  // Place the duplicate adjacent to its source (source.sort_order + 1) instead
  // of at the stack bottom (max(sort_order)+1) — a grouped source's copy must
  // land next to it, not escape past every other group/layer. This is a
  // backend hint only — handleDuplicateRendering's caller renumbers sort_order
  // by final local array index at splice time, and prepareLayersForPersistence
  // renumbers again by array index at save time.
  const nextSortOrder = layer.sort_order + 1;
  const baseName = layer.display_name || layer.dataset_name || layer.dataset_table_name || 'Layer';
  return {
    dataset_id: layer.dataset_id,
    sort_order: nextSortOrder,
    // B-031: inherit the source layer's visibility so duplicating a hidden
    // layer yields a hidden copy rather than forcing it visible.
    visible: layer.visible ?? true,
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
