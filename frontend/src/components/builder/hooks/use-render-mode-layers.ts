import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { getLayerType, getSourceIdForLayer } from '@/components/builder/map-sync';
import { getAdapter } from '@/components/builder/layer-adapters/registry';
import type { AdapterLayerInput } from '@/components/builder/layer-adapters/types';
import { DEFAULT_HEATMAP_PAINT } from '@/components/builder/layer-adapters/heatmap-adapter';
import { buildSignedTileUrl } from '@/lib/tile-utils';
import { buildLabelLayerSpec } from '@/components/builder/label-layer-utils';
import { sanitizeNullableNumericFilter } from '@/lib/maplibre-filter-utils';
import { normalizeDemStyleConfig } from '@/lib/dem-render-mode';
import type { MapLayerResponse, StyleConfig, SymbolStyleConfig } from '@/types/api';
import { getCompanionLayerIds } from '@/components/builder/companion-ids';
import { DEFAULT_CIRCLE_PAINT } from '@/components/builder/layer-adapters/builder-defaults';
import { buildRenderAsPatch } from '@/components/builder/renderAs';
import type { RenderAsId, RenderAsAdapterType } from '@/components/builder/renderAs';

// STATE-06: centralized default symbol style_config used when converting a
// layer to symbol render mode without a previously-saved symbol config. Lifted
// out of the inline literal in handleRenderModeChange so the swap defaults live
// in one place (alongside DEFAULT_CIRCLE_PAINT / DEFAULT_HEATMAP_PAINT).
const DEFAULT_SYMBOL_CONFIG: SymbolStyleConfig = {
  iconImage: 'marker',
  iconSize: 1,
  iconRotation: 0,
  iconAnchor: 'center',
  iconOffset: [0, 0],
};

/** A render-mode change that enters OR leaves cluster mode crosses a source
 *  boundary — cluster layers get a per-layer GeoJSON/server-tile source while
 *  every other render mode shares the deduped vector source. The imperative
 *  swapLayerOnMap assumes a stable source id, so these transitions must be
 *  handed to the reactive syncMapComposition (BuilderMap) which rebuilds the
 *  source + layers atomically instead. */
function isClusterTransition(
  prev: { style_config?: StyleConfig | null },
  next: { style_config?: StyleConfig | null },
): boolean {
  return prev.style_config?.render_mode === 'cluster'
    || next.style_config?.render_mode === 'cluster';
}

// STATE-02: render-mode / layer-swap cluster, relocated verbatim out of the
// useBuilderLayers god-hook. PURE RELOCATION — handler bodies are unchanged; the
// shared layers state (layersRef + setters) is threaded in as params.
interface UseRenderModeLayersParams {
  layersRef: React.RefObject<MapLayerResponse[]>;
  setLocalLayers: React.Dispatch<React.SetStateAction<MapLayerResponse[]>>;
  setHasUnsavedChanges: React.Dispatch<React.SetStateAction<boolean>>;
  mapInstanceRef: React.RefObject<MaplibreMap | null>;
}

export function useRenderModeLayers({
  layersRef,
  setLocalLayers,
  setHasUnsavedChanges,
  mapInstanceRef,
}: UseRenderModeLayersParams) {
  const { t } = useTranslation('builder');

  /** Swap the MapLibre layer for a given dataset between adapter types (e.g. circle <-> heatmap).
   *
   *  Phase 1050 SF-04: sourceId now routes through `getSourceIdForLayer` so
   *  non-cluster vector layers correctly inherit the deduped
   *  `source-data-${dataset_table_name}` source's tile URL. Cluster and
   *  raster/hillshade layers keep their per-layer source id via the helper's
   *  branching contract.
   */
  // STATE-02: named function expression so the BUG-018 idle-retry recursion
  // targets the function's own (immutable) name binding `runSwapLayerOnMap`
  // instead of the reactive useCallback identity — the React Compiler rejects
  // self-referencing a useCallback const. Behavior is identical to the prior
  // `swapLayerOnMap(...)` self-call.
  const swapLayerOnMap = useCallback(function runSwapLayerOnMap(
    layer: MapLayerResponse,
    adapterType: RenderAsAdapterType,
    updatedPaint: Record<string, unknown>,
  ): void {
    const map = mapInstanceRef.current;
    if (!map) return;
    // BUG-018: mirror the idle-retry pattern from BuilderMap.tsx (~:923).
    // A render-mode switch during a basemap style transition must not be silently
    // dropped. Register a one-shot `idle` listener so the swap is retried as soon
    // as the map settles (idle fires after style.load + tiles + transitions).
    if (!map.isStyleLoaded()) {
      map.once('idle', () => runSwapLayerOnMap(layer, adapterType, updatedPaint));
      return;
    }

    // SYNC-04: companion ids from the single source of truth.
    const ids = getCompanionLayerIds(layer.id);
    const mapLayerId = ids.layer;
    const sourceId = getSourceIdForLayer(layer);
    const labelId = ids.label;
    const colorReliefId = ids.colorRelief;

    // Remove old layer
    if (map.getLayer(colorReliefId)) {
      map.removeLayer(colorReliefId);
    }
    if (map.getLayer(mapLayerId)) {
      map.removeLayer(mapLayerId);
    }
    if (map.getLayer(ids.outline)) {
      map.removeLayer(ids.outline);
    }
    if (map.getLayer(ids.extrusion)) {
      map.removeLayer(ids.extrusion);
    }
    if (map.getLayer(ids.arrow)) {
      map.removeLayer(ids.arrow);
    }
    // Per-layer raster/hillshade source removal — these layer types keep
    // their per-layer source id via `getSourceIdForLayer`'s raster branch,
    // so this is still safe (no sibling layer shares it).
    if ((adapterType === 'raster' || adapterType === 'hillshade') && map.getSource(sourceId)) {
      map.removeSource(sourceId);
    }

    // Get tile URL from existing source
    const source = map.getSource(sourceId) as { tiles?: string[] } | undefined;
    const tileUrl = source?.tiles?.[0] ?? buildSignedTileUrl(layer.dataset_table_name, null, undefined);
    const sourceLayer = `data.${layer.dataset_table_name}`;

    const adapterInput: AdapterLayerInput & { style_config?: StyleConfig | null } = {
      id: layer.id,
      dataset_table_name: layer.dataset_table_name,
      dataset_geometry_type: layer.dataset_geometry_type,
      opacity: layer.opacity ?? 1,
      visible: layer.visible,
      paint: updatedPaint,
      layout: layer.layout ?? {},
      filter: layer.filter,
      label_config: layer.label_config ?? null,
      sourceId,
      layerId: mapLayerId,
      sourceLayer,
      tileUrl,
      style_config: layer.style_config ?? null,
      is_dem: layer.is_dem ?? null,
    };

    try {
      const adapter = getAdapter(adapterType);
      adapter.addLayers(map, adapterInput);
      // BUG-01: explicitly re-assert visibility after addLayers. The adapter
      // contract honors `input.visible` at initial add (defense-in-depth in
      // each adapter), and calling syncVisibility here also covers companion
      // layers (e.g. fill outline / cluster count) so the freshly-swapped
      // layer cannot become a "ghost visible" layer when the user is on a
      // hidden render-mode source.
      adapter.syncVisibility(map, adapterInput);
    } catch (e) {
      toast.error(t('toasts.renderModeSwitchFailed'));
      if (import.meta.env.DEV) console.error('[builder] swapLayerOnMap failed:', e);
      return;
    }

    // Manage companion label layer: heatmap hides labels, symbol consolidates
    // icon/text in the primary symbol layer, points restore companion labels.
    if (adapterType === 'heatmap') {
      if (map.getLayer(labelId)) {
        map.setLayoutProperty(labelId, 'visibility', 'none');
      }
    } else if (adapterType === 'symbol') {
      if (map.getLayer(labelId)) {
        map.removeLayer(labelId);
      }
    } else if (layer.label_config?.column) {
      const vis = layer.visible ? 'visible' : 'none';
      if (!map.getLayer(labelId) && map.getSource(sourceId)) {
        const geomType = getLayerType(layer.dataset_geometry_type);
        map.addLayer(buildLabelLayerSpec({ labelId, sourceId, sourceLayer, lc: layer.label_config, geomType }));
        // fix(LB-02): carry the parent layer's filter onto the re-added label so filtered-out features stay excluded
        map.setFilter(labelId, sanitizeNullableNumericFilter(layer.filter));
        map.setLayoutProperty(labelId, 'visibility', vis);
      } else if (map.getLayer(labelId)) {
        map.setLayoutProperty(labelId, 'visibility', vis);
      }
    }
  }, [mapInstanceRef, t]);

  /** Cluster transitions are handed to the reactive syncMapComposition, but that
   *  reconciler adds before it removes stale layers and SKIPS adding a layer id
   *  that already exists (map-sync `if (!map.getLayer(id)) adapter.addLayers`).
   *  The cluster⇄points transition reuses the layer's MapLibre ids on a DIFFERENT
   *  source, so the old layer graph must be torn down first or the reconciler
   *  skips the replacement and then deletes the stale layer → blank until the next
   *  sync (Codex #351). Remove the layer + every companion id here; source
   *  create/teardown stays with syncMapComposition's removeStaleSourcesAndLayers. */
  const removeLayerGraphForReactiveSync = useCallback(function runRemove(layerId: string): void {
    const map = mapInstanceRef.current;
    if (!map) return;
    if (!map.isStyleLoaded()) {
      map.once('idle', () => runRemove(layerId));
      return;
    }
    const ids = getCompanionLayerIds(layerId);
    for (const id of [ids.colorRelief, ids.label, ids.arrow, ids.extrusion, ids.outline, ids.clusterCount, ids.cluster, ids.layer]) {
      if (map.getLayer(id)) map.removeLayer(id);
    }
  }, [mapInstanceRef]);

  const handleRenderAsChange = useCallback((layerId: string, renderAs: RenderAsId) => {
    const layer = layersRef.current.find((l) => l.id === layerId);
    if (!layer) return;

    const mutation = buildRenderAsPatch(layer, renderAs);
    if (!mutation) return;

    const updatedLayer: MapLayerResponse = {
      ...layer,
      ...mutation.patch,
      paint: mutation.patch.paint ?? layer.paint,
      layout: mutation.patch.layout ?? layer.layout,
      style_config: normalizeDemStyleConfig(
        'style_config' in mutation.patch ? mutation.patch.style_config : layer.style_config,
        layer.is_dem,
      ),
      layer_type: mutation.patch.layer_type ?? layer.layer_type,
    };

    setLocalLayers((prev) =>
      prev.map((candidate) => (candidate.id === layerId ? updatedLayer : candidate)),
    );
    // Cluster uses a per-layer GeoJSON/server-tile source whose id differs from
    // the shared vector source and may not exist yet when switching in. The
    // imperative same-source swapLayerOnMap cannot bridge that source change — it
    // would add the cluster layer to a not-yet-created source and then collide
    // with the reactive reconcile ("source ... not found" / "layer ... already
    // exists"). Defer cluster transitions (entering OR leaving) to
    // syncMapComposition in BuilderMap, which rebuilds source + layers atomically.
    if (isClusterTransition(layer, updatedLayer)) {
      removeLayerGraphForReactiveSync(layerId);
    } else {
      swapLayerOnMap(updatedLayer, mutation.adapterType, updatedLayer.paint ?? {});
    }
    setHasUnsavedChanges(true);
  }, [layersRef, setLocalLayers, setHasUnsavedChanges, swapLayerOnMap, removeLayerGraphForReactiveSync]);

  const handleRenderModeChange = useCallback((layerId: string, mode: RenderAsId | 'points') => {
    const layer = layersRef.current.find((l) => l.id === layerId);
    if (!layer) return;

    // SF-02 (Phase 1049): renderAsOptions in LayerEditorPanel surfaces ALL RenderAsId
    // values (arrow / fill / stroke / fill-stroke / extrusion-3d / line plus the
    // legacy circle quartet handled below). Route everything that isn't a
    // circle-family transition through handleRenderAsChange + buildRenderAsPatch
    // so the layout/paint replacement is computed correctly. Without this gate,
    // line→arrow on a MultiLineString layer was falling through to the `circle`
    // branch and dispatching addLayer with stale line-cap / line-join layout
    // keys, which MapLibre rejects with `unknown property` validation errors.
    if (
      mode === 'cluster' ||
      mode === 'arrow' ||
      mode === 'line' ||
      mode === 'fill' ||
      mode === 'stroke' ||
      mode === 'fill-stroke' ||
      mode === 'extrusion-3d' ||
      mode === 'image' ||
      mode === 'hillshade'
    ) {
      handleRenderAsChange(layerId, mode);
      return;
    }

    // Leaving cluster crosses the per-layer→shared source boundary; defer the
    // map mutation to the reactive syncMapComposition (see isClusterTransition).
    const leavingCluster = layer.style_config?.render_mode === 'cluster';

    const currentStyleConfig: Partial<StyleConfig> = layer.style_config ?? {};
    let updatedPaint = { ...layer.paint };

    if (mode === 'heatmap') {
      const savedCirclePaint = { ...updatedPaint };
      const savedHeatmapPaint = currentStyleConfig.heatmapPaint ?? {};

      updatedPaint = Object.keys(savedHeatmapPaint).length > 0
        ? { ...savedHeatmapPaint }
        : { ...DEFAULT_HEATMAP_PAINT };

      const builder = {
        ...currentStyleConfig.builder,
        heatmapRamp: currentStyleConfig.builder?.heatmapRamp ?? 'YlOrRd',
      };

      setLocalLayers((prev) =>
        prev.map((l) =>
          l.id === layerId
            ? { ...l, paint: updatedPaint, style_config: { ...l.style_config, ...currentStyleConfig, render_mode: 'heatmap', savedCirclePaint, builder } as StyleConfig }
            : l,
        ),
      );

      if (leavingCluster) removeLayerGraphForReactiveSync(layerId);
      else swapLayerOnMap(layer, 'heatmap', updatedPaint);
    } else if (mode === 'symbol') {
      const savedCirclePaint = currentStyleConfig.savedCirclePaint ?? { ...updatedPaint };
      const nextStyleConfig = {
        ...layer.style_config,
        ...currentStyleConfig,
        render_mode: 'symbol',
        savedCirclePaint,
        symbol: currentStyleConfig.symbol ?? { ...DEFAULT_SYMBOL_CONFIG },
      } as StyleConfig;

      setLocalLayers((prev) =>
        prev.map((l) =>
          l.id === layerId
            ? { ...l, paint: updatedPaint, style_config: nextStyleConfig }
            : l,
        ),
      );

      if (leavingCluster) removeLayerGraphForReactiveSync(layerId);
      else swapLayerOnMap({ ...layer, style_config: nextStyleConfig }, 'symbol', updatedPaint);
    } else {
      const savedHeatmapPaint = { ...updatedPaint };
      const savedCirclePaint = currentStyleConfig.savedCirclePaint ?? {};

      updatedPaint = Object.keys(savedCirclePaint).length > 0
        ? savedCirclePaint
        : { ...DEFAULT_CIRCLE_PAINT };

      const { savedCirclePaint: _dropped, symbol: _symbol, ...restConfig } = currentStyleConfig;

      setLocalLayers((prev) =>
        prev.map((l) =>
          l.id === layerId
            ? { ...l, paint: updatedPaint, style_config: { ...l.style_config, ...restConfig, render_mode: undefined, heatmapPaint: savedHeatmapPaint } as StyleConfig }
            : l,
        ),
      );

      if (leavingCluster) removeLayerGraphForReactiveSync(layerId);
      else swapLayerOnMap(layer, 'circle', updatedPaint);
    }

    setHasUnsavedChanges(true);
  }, [layersRef, setLocalLayers, setHasUnsavedChanges, handleRenderAsChange, swapLayerOnMap, removeLayerGraphForReactiveSync]);

  return {
    swapLayerOnMap,
    handleRenderAsChange,
    handleRenderModeChange,
  };
}
