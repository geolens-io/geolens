import { useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { getAdapter } from '@/components/builder/layer-adapters/registry';
import { normalizeDemStyleConfig } from '@/lib/dem-render-mode';
import type { MapLayerResponse, StyleConfig } from '@/types/api';
import { builderAdapterInput } from '@/components/builder/hooks/use-layer-map-sync';
import { getDrawingLayerIds } from '@/components/builder/companion-ids';
import { removeDescribedLayers } from '@/components/builder/layer-writer';
import { buildRenderAsPatch, getCurrentRenderAs } from '@/components/builder/renderAs';
import type { RenderAsId, RenderAsAdapterType } from '@/components/builder/renderAs';

/** A render-mode change that enters or leaves cluster mode crosses a source
 *  boundary: cluster layers get a per-layer GeoJSON/server-tile source while
 *  every other mode shares the deduped vector source. The imperative
 *  swapLayerOnMap assumes a stable source id, so these transitions are handed
 *  to the reactive syncMapComposition (BuilderMap), which rebuilds source and
 *  layers atomically. */
function isClusterTransition(
  prev: { style_config?: StyleConfig | null },
  next: { style_config?: StyleConfig | null },
): boolean {
  return prev.style_config?.render_mode === 'cluster'
    || next.style_config?.render_mode === 'cluster';
}

// Render-mode / layer-swap handlers. The shared layers state (layersRef +
// setters) is threaded in as params.
interface UseRenderModeLayersParams {
  layersRef: React.RefObject<MapLayerResponse[]>;
  setLocalLayers: React.Dispatch<React.SetStateAction<MapLayerResponse[]>>;
  setHasUnsavedChanges: React.Dispatch<React.SetStateAction<boolean>>;
  mapInstanceRef: React.RefObject<MaplibreMap | null>;
  mvtSourceLayerPrefix?: string | null;
}

export function useRenderModeLayers({
  layersRef,
  setLocalLayers,
  setHasUnsavedChanges,
  mapInstanceRef,
  mvtSourceLayerPrefix,
}: UseRenderModeLayersParams) {
  const { t } = useTranslation('builder');

  /** Swap the MapLibre layer for a given dataset between vector adapter types (e.g. circle <-> heatmap).
   *  An image or hillshade switch is left to the sync pass. */
  // Named function expression so the idle-retry recursion targets the
  // function's own immutable name binding `runSwapLayerOnMap`, not the reactive
  // useCallback identity (the React Compiler rejects a useCallback const
  // referencing itself).
  const swapLayerOnMap = useCallback(function runSwapLayerOnMap(
    layer: MapLayerResponse,
    adapterType: RenderAsAdapterType,
    updatedPaint: Record<string, unknown>,
  ): void {
    // A raster source's URL comes from the dataset's tile token, which only the
    // sync pass holds, so that pass replaces the layer and its source.
    if (adapterType === 'raster' || adapterType === 'hillshade') return;
    const map = mapInstanceRef.current;
    if (!map) return;
    // Idle-retry, as in BuilderMap.tsx: a render-mode switch during a basemap
    // style transition must not be dropped. A one-shot `idle` listener retries
    // the swap once the map settles (after style.load + tiles + transitions).
    if (!map.isStyleLoaded()) {
      map.once('idle', () => runSwapLayerOnMap(layer, adapterType, updatedPaint));
      return;
    }

    removeDescribedLayers(map, getDrawingLayerIds(layer.id));

    const adapterInput = builderAdapterInput(layer, mvtSourceLayerPrefix, { paint: updatedPaint });
    if (!adapterInput) return;

    try {
      const adapter = getAdapter(adapterType);
      adapter.addLayers(map, adapterInput);
      // Re-assert visibility after addLayers. Adapters honor `input.visible` at
      // initial add, and syncVisibility also covers companion layers (fill
      // outline / cluster count / label), so the swapped layer can't become a
      // "ghost visible" layer on a hidden render-mode source.
      adapter.syncVisibility(map, adapterInput);
    } catch (e) {
      toast.error(t('toasts.renderModeSwitchFailed'));
      if (import.meta.env.DEV) console.error('[builder] swapLayerOnMap failed:', e);
      return;
    }
  }, [mapInstanceRef, mvtSourceLayerPrefix, t]);

  /** Cluster transitions are handed to the reactive syncMapComposition, but it
   *  adds before it removes stale layers and skips adding a layer id that
   *  already exists (map-sync `if (!map.getLayer(id)) adapter.addLayers`). The
   *  cluster⇄points transition reuses the layer's MapLibre ids on a different
   *  source, so the old layer graph must be torn down first or the reconciler
   *  skips the replacement and then deletes the stale layer, leaving the layer
   *  blank until the next sync. Removes the layer and every companion id; source
   *  create/teardown stays with syncMapComposition's removeStaleSourcesAndLayers.
   *  Runs at once, since a teardown deferred to `idle` can land after the
   *  reactive sync has redrawn the layer. */
  const removeLayerGraphForReactiveSync = useCallback((layerId: string): void => {
    const map = mapInstanceRef.current;
    if (!map) return;
    removeDescribedLayers(map, getDrawingLayerIds(layerId));
  }, [mapInstanceRef]);

  /** Returns whether the layer switched; false when the mode isn't available or is already current. */
  const handleRenderAsChange = useCallback((
    layerId: string,
    renderAs: RenderAsId,
    options?: { heightColumn?: string },
  ): boolean => {
    const layer = layersRef.current.find((l) => l.id === layerId);
    // Re-entering the current mode would reset its paint to the mode's defaults.
    if (!layer || (renderAs === getCurrentRenderAs(layer) && !options?.heightColumn)) return false;

    const mutation = buildRenderAsPatch(layer, renderAs, options);
    if (!mutation) return false;

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

    // Same-tick edits (a chat turn's next action) build on the switched layer.
    layersRef.current = layersRef.current.map((candidate) => (candidate.id === layerId ? updatedLayer : candidate));
    setLocalLayers((prev) =>
      prev.map((candidate) => (candidate.id === layerId ? updatedLayer : candidate)),
    );
    // Cluster uses a per-layer GeoJSON/server-tile source whose id differs from
    // the shared vector source and may not exist yet when switching in. The
    // imperative same-source swapLayerOnMap can't bridge that: it would add the
    // cluster layer to a not-yet-created source and collide with the reactive
    // reconcile ("source ... not found" / "layer ... already exists"). Entering
    // or leaving cluster is deferred to syncMapComposition in BuilderMap.
    if (isClusterTransition(layer, updatedLayer)) {
      removeLayerGraphForReactiveSync(layerId);
    } else {
      swapLayerOnMap(updatedLayer, mutation.adapterType, updatedLayer.paint ?? {});
    }
    setHasUnsavedChanges(true);
    return true;
  }, [layersRef, setLocalLayers, setHasUnsavedChanges, swapLayerOnMap, removeLayerGraphForReactiveSync]);

  return {
    swapLayerOnMap,
    handleRenderAsChange,
  };
}
