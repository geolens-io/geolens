import { useState, useEffect, useLayoutEffect, useRef, useMemo, useCallback } from 'react';
import { useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { getLayerType, reorderDataLayers } from '@/components/builder/map-sync';
import { getAdapter } from '@/components/builder/layer-adapters/registry';
import type { AdapterLayerInput } from '@/components/builder/layer-adapters/types';
import { DEFAULT_HEATMAP_PAINT } from '@/components/builder/layer-adapters/heatmap-adapter';
import type { LayerActions } from '@/components/builder/ChatPanel';
import { buildSignedTileUrl } from '@/lib/tile-utils';
import { buildLabelLayerSpec } from '@/components/builder/label-layer-utils';
import { resolveBasemapId } from '@/lib/basemap-utils';
import type { MapBasemapConfig, MapLayerInput, MapLayerResponse, MapResponse, MapTerrainConfig, StyleConfig } from '@/types/api';
import type { useAddLayer, useRemoveLayer } from '@/hooks/use-maps';
import { useEphemeralLayers } from '@/components/builder/hooks/use-ephemeral-layers';
import { useLayerMapSync } from '@/components/builder/hooks/use-layer-map-sync';
import { buildRenderAsPatch } from '@/components/builder/renderAs';
import type { RenderAsId, RenderAsAdapterType } from '@/components/builder/renderAs';

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

export function useBuilderLayers(
  mapData: MapResponse | undefined,
  mapInstanceRef: React.RefObject<MaplibreMap | null>,
  mapId: string | undefined,
  addLayerMutation: ReturnType<typeof useAddLayer>,
  removeLayerMutation: ReturnType<typeof useRemoveLayer>,
) {
  const [searchParams, setSearchParams] = useSearchParams();
  const { t } = useTranslation('builder');

  const initializedRef = useRef(false);
  const addDatasetProcessedRef = useRef(false);

  const [localLayers, setLocalLayers] = useState<MapLayerResponse[]>([]);
  const [localBasemap, setLocalBasemap] = useState<string>('openfreemap-positron');
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [expandedLayerId, setExpandedLayerId] = useState<string | null>(null);
  const [activeEditorTab, setActiveEditorTab] = useState<'style' | 'filter' | 'labels' | 'popup' | null>(null);
  const [showBasemapLabels, setShowBasemapLabels] = useState(true);
  const [basemapConfig, setBasemapConfig] = useState<MapBasemapConfig | null>(null);
  const [localTerrainConfig, setLocalTerrainConfig] = useState<MapTerrainConfig | null>(null);
  const [localName, setLocalName] = useState('');
  const [localDescription, setLocalDescription] = useState('');
  const savedLayerBaselineRef = useRef<MapLayerResponse[]>([]);

  // Mirror current layers in a ref so stable callbacks can read fresh state
  // without invalidating on every layer mutation. Without this, each layer
  // edit would tear down React.memo() on LayerItem (KISS-2 / PERF-N2).
  const layersRef = useRef(localLayers);
  useLayoutEffect(() => {
    layersRef.current = localLayers;
  }, [localLayers]);

  // Delegate ephemeral layer management
  const {
    ephemeralResult,
    handleQueryResult,
    handleDismissEphemeral,
  } = useEphemeralLayers(mapInstanceRef);

  // Delegate live map sync handlers
  const {
    handleToggleVisibility,
    handlePaintChange,
    handleStyleConfigChange,
    handleOpacityChange,
    handleLayoutChange,
    handleFilterChange,
    handleLabelChange,
    handlePopupChange,
  } = useLayerMapSync(localLayers, setLocalLayers, setHasUnsavedChanges, mapInstanceRef);

  // Initialize local state from API data (once)
  useEffect(() => {
    if (mapData && !initializedRef.current) {
      setLocalLayers(mapData.layers ?? []);
      savedLayerBaselineRef.current = mapData.layers ?? [];
      setLocalBasemap(resolveBasemapId(mapData.basemap_style || 'positron'));
      setShowBasemapLabels(mapData.show_basemap_labels ?? true);
      setBasemapConfig(mapData.basemap_config ?? null);
      setLocalTerrainConfig(mapData.terrain_config ?? null);
      setLocalName(mapData.name);
      setLocalDescription(mapData.description ?? '');
      initializedRef.current = true;
    }
  }, [mapData]);

  // Sync layers from API when they change (after add/remove mutations)
  const apiLayers = mapData?.layers;
  useEffect(() => {
    if (apiLayers && initializedRef.current && !hasUnsavedChanges) {
      setLocalLayers(apiLayers);
      savedLayerBaselineRef.current = apiLayers;
    }
  }, [apiLayers, hasUnsavedChanges]);

  // Handle ?add_dataset URL param: auto-add a dataset as a layer on map load.
  // Depends on mapData so the effect re-evaluates once initializedRef is set.
  useEffect(() => {
    if (!initializedRef.current || addDatasetProcessedRef.current) return;
    const datasetId = searchParams.get('add_dataset');
    if (!datasetId) return;
    addDatasetProcessedRef.current = true;
    handleAddDataset(datasetId);
    setSearchParams((prev) => {
      prev.delete('add_dataset');
      return prev;
    }, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, mapData]);

  // Compute initial view state only once
  const initialViewState = useMemo(() => {
    if (!mapData) return undefined;
    return {
      center_lng: mapData.center_lng,
      center_lat: mapData.center_lat,
      zoom: mapData.zoom,
      bearing: mapData.bearing,
      pitch: mapData.pitch,
    };
    // Only compute on first load
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapData?.id]);

  // --- Layer handlers ---
  //
  // All handlers are wrapped in useCallback with stable deps so that
  // React.memo() on LayerItem actually prevents re-renders on unrelated state
  // changes. Handlers that need to read the current layers list use
  // `layersRef.current` instead of `localLayers` to keep their dep lists
  // stable (KISS-2 / PERF-N2).

  const handleMove = useCallback((layerId: string, direction: 'up' | 'down') => {
    const currentLayers = layersRef.current;
    const idx = currentLayers.findIndex((l) => l.id === layerId);
    if (direction === 'up' && idx <= 0) return;
    if (direction === 'down' && (idx < 0 || idx >= currentLayers.length - 1)) return;

    const next = [...currentLayers];
    const swapIdx = direction === 'up' ? idx - 1 : idx + 1;
    [next[idx], next[swapIdx]] = [next[swapIdx], next[idx]];
    const reordered = next.map((l, i) => ({ ...l, sort_order: i }));

    setLocalLayers(reordered);

    const map = mapInstanceRef.current;
    if (map && map.isStyleLoaded()) {
      reorderDataLayers(map, reordered);
    }

    setHasUnsavedChanges(true);
  }, [mapInstanceRef]);

  const handleMoveUp = useCallback((layerId: string) => handleMove(layerId, 'up'), [handleMove]);
  const handleMoveDown = useCallback((layerId: string) => handleMove(layerId, 'down'), [handleMove]);

  const handleReorder = useCallback((reorderedLayers: MapLayerResponse[]) => {
    setLocalLayers(reorderedLayers.map((l, i) => ({ ...l, sort_order: i })));

    // Imperatively reorder MapLibre layers so the visual change is immediate
    const map = mapInstanceRef.current;
    if (map && map.isStyleLoaded()) {
      reorderDataLayers(map, reorderedLayers);
    }

    setHasUnsavedChanges(true);
  }, [mapInstanceRef]);

  const handleDisplayNameChange = useCallback((layerId: string, newName: string | null) => {
    const normalized = newName?.trim() || null;
    setLocalLayers((prev) =>
      prev.map((l) => (l.id === layerId ? { ...l, display_name: normalized } : l)),
    );
    setHasUnsavedChanges(true);
  }, []);

  const handleToggleExpand = useCallback((layerId: string) => {
    setExpandedLayerId((prev) => {
      if (!layerId) return null;
      const next = prev === layerId ? null : layerId;
      if (next !== null) setActiveEditorTab('style');
      return next;
    });
  }, []);

  const handleTabChange = useCallback((_layerId: string, tab: 'style' | 'filter' | 'labels' | 'popup') => {
    setActiveEditorTab((prev) => (prev === tab ? null : tab));
  }, []);

  const handleZoomToLayer = useCallback((layerId: string) => {
    const map = mapInstanceRef.current;
    if (!map) return;
    const layer = layersRef.current.find((l) => l.id === layerId);
    if (!layer?.dataset_extent_bbox) return;
    const bbox = layer.dataset_extent_bbox;
    // Validate bbox: must be 4 finite numbers with non-inverted ranges
    // Note: equal min/max (point geometries) is valid — fitBounds zooms to maxZoom at that point
    if (
      bbox.length !== 4 ||
      bbox.some((v) => !Number.isFinite(v)) ||
      bbox[0] > bbox[2] ||
      bbox[1] > bbox[3]
    ) return;
    try {
      map.fitBounds(
        [[bbox[0], bbox[1]], [bbox[2], bbox[3]]],
        { padding: 40, maxZoom: 18 },
      );
    } catch {
      // Silently ignore invalid bounds (e.g. out-of-range coordinates)
    }
  }, [mapInstanceRef]);

  const handleRemove = useCallback((layerId: string) => {
    if (!mapId) return;
    setExpandedLayerId((prev) => prev === layerId ? null : prev);
    removeLayerMutation.mutate(
      { mapId, layerId },
      {
        onSuccess: () => {
          toast.success(t('toasts.layerRemoved'));
        },
        onError: () => {
          toast.error(t('toasts.layerRemoveFailed'));
        },
      },
    );
  }, [mapId, removeLayerMutation, t]);

  const handleAddDataset = useCallback((datasetId: string) => {
    if (!mapId) return;
    const nextSortOrder = layersRef.current.length;
    addLayerMutation.mutate(
      { mapId, data: { dataset_id: datasetId, sort_order: nextSortOrder } },
      {
        onSuccess: () => {
          toast.success(t('toasts.layerAdded'));
        },
        onError: () => {
          toast.error(t('toasts.layerAddFailed'));
        },
      },
    );
  }, [mapId, addLayerMutation, t]);

  // AI-specific remove: removes locally (persisted on Save)
  const handleAiRemoveLayer = useCallback((layerId: string) => {
    setLocalLayers((prev) => prev.filter((l) => l.id !== layerId));
    // Clean up MapLibre layers imperatively
    const map = mapInstanceRef.current;
    if (map && map.isStyleLoaded()) {
      const ids = [
        `layer-${layerId}`, `layer-${layerId}-outline`,
        `layer-${layerId}-label`, `layer-${layerId}-extrusion`,
        `layer-${layerId}-arrow`,
      ];
      for (const id of ids) {
        if (map.getLayer(id)) map.removeLayer(id);
      }
      const sourceId = `source-${layerId}`;
      if (map.getSource(sourceId)) map.removeSource(sourceId);
    }
    setHasUnsavedChanges(true);
  }, [mapInstanceRef]);

  const handleToggleLegend = useCallback((layerId: string) => {
    setLocalLayers((prev) =>
      prev.map((l) =>
        l.id === layerId ? { ...l, show_in_legend: !l.show_in_legend } : l,
      ),
    );
    setHasUnsavedChanges(true);
  }, []);

  /** Swap the MapLibre layer for a given dataset between adapter types (e.g. circle <-> heatmap). */
  const swapLayerOnMap = useCallback((
    layer: MapLayerResponse,
    adapterType: RenderAsAdapterType,
    updatedPaint: Record<string, unknown>,
  ) => {
    const map = mapInstanceRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const mapLayerId = `layer-${layer.id}`;
    const sourceId = `source-${layer.id}`;
    const labelId = `layer-${layer.id}-label`;

    // Remove old layer
    if (map.getLayer(mapLayerId)) {
      map.removeLayer(mapLayerId);
    }
    const outlineId = `layer-${layer.id}-outline`;
    if (map.getLayer(outlineId)) {
      map.removeLayer(outlineId);
    }
    const extrusionId = `layer-${layer.id}-extrusion`;
    if (map.getLayer(extrusionId)) {
      map.removeLayer(extrusionId);
    }
    const arrowId = `layer-${layer.id}-arrow`;
    if (map.getLayer(arrowId)) {
      map.removeLayer(arrowId);
    }
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
      getAdapter(adapterType).addLayers(map, adapterInput);
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
        map.setLayoutProperty(labelId, 'visibility', vis);
      } else if (map.getLayer(labelId)) {
        map.setLayoutProperty(labelId, 'visibility', vis);
      }
    }
  }, [mapInstanceRef, t]);

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
      style_config: mutation.patch.style_config ?? layer.style_config,
      layer_type: mutation.patch.layer_type ?? layer.layer_type,
    };

    setLocalLayers((prev) =>
      prev.map((candidate) => (candidate.id === layerId ? updatedLayer : candidate)),
    );
    swapLayerOnMap(updatedLayer, mutation.adapterType, updatedLayer.paint ?? {});
    setHasUnsavedChanges(true);
  }, [swapLayerOnMap]);

  const handleRenderModeChange = useCallback((layerId: string, mode: 'points' | 'heatmap' | 'symbol') => {
    const layer = layersRef.current.find((l) => l.id === layerId);
    if (!layer) return;

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

      swapLayerOnMap(layer, 'heatmap', updatedPaint);
    } else if (mode === 'symbol') {
      const savedCirclePaint = currentStyleConfig.savedCirclePaint ?? { ...updatedPaint };
      const nextStyleConfig = {
        ...layer.style_config,
        ...currentStyleConfig,
        render_mode: 'symbol',
        savedCirclePaint,
        symbol: currentStyleConfig.symbol ?? { iconImage: 'marker', iconSize: 1, iconRotation: 0, iconAnchor: 'center', iconOffset: [0, 0] },
      } as StyleConfig;

      setLocalLayers((prev) =>
        prev.map((l) =>
          l.id === layerId
            ? { ...l, paint: updatedPaint, style_config: nextStyleConfig }
            : l,
        ),
      );

      swapLayerOnMap({ ...layer, style_config: nextStyleConfig }, 'symbol', updatedPaint);
    } else {
      const savedHeatmapPaint = { ...updatedPaint };
      const savedCirclePaint = currentStyleConfig.savedCirclePaint ?? {};

      updatedPaint = Object.keys(savedCirclePaint).length > 0 ? savedCirclePaint : {
        'circle-color': '#3b82f6',
        'circle-radius': 5,
        'circle-stroke-color': '#ffffff',
        'circle-stroke-width': 1,
      };

      const { savedCirclePaint: _dropped, symbol: _symbol, ...restConfig } = currentStyleConfig;

      setLocalLayers((prev) =>
        prev.map((l) =>
          l.id === layerId
            ? { ...l, paint: updatedPaint, style_config: { ...l.style_config, ...restConfig, render_mode: undefined, heatmapPaint: savedHeatmapPaint } as StyleConfig }
            : l,
        ),
      );

      swapLayerOnMap(layer, 'circle', updatedPaint);
    }

    setHasUnsavedChanges(true);
  }, [swapLayerOnMap]);

  const handleDuplicateRendering = useCallback((layerId: string) => {
    if (!mapId) return;
    const layer = layersRef.current.find((candidate) => candidate.id === layerId);
    if (!layer) return;

    const currentLayers = layersRef.current;
    const data = buildDuplicateRenderingInput(layer, currentLayers);
    const nextSortOrder = data.sort_order ?? currentLayers.length;

    addLayerMutation.mutate(
      { mapId, data },
      {
        onSuccess: (createdLayer) => {
          setLocalLayers((prev) => {
            if (prev.some((candidate) => candidate.id === createdLayer.id)) return prev;
            const next = [...prev, createdLayer].map((candidate, index) => ({
              ...candidate,
              sort_order: candidate.id === createdLayer.id ? nextSortOrder : candidate.sort_order ?? index,
            }));
            layersRef.current = next;
            return next;
          });
          savedLayerBaselineRef.current = [
            ...savedLayerBaselineRef.current.filter((candidate) => candidate.id !== createdLayer.id),
            createdLayer,
          ];
          toast.success(t('toasts.layerAdded'));
        },
        onError: () => {
          toast.error(t('toasts.layerAddFailed'));
        },
      },
    );
  }, [addLayerMutation, mapId, t]);

  const markDirty = useCallback(() => setHasUnsavedChanges(true), []);

  const chatLayerActions: LayerActions = useMemo(() => ({
    onFilterChange: handleFilterChange,
    onPaintChange: handlePaintChange,
    onStyleConfigChange: handleStyleConfigChange,
    onLabelChange: handleLabelChange,
    onToggleVisibility: handleToggleVisibility,
    onAddDataset: handleAddDataset,
    onRemove: handleAiRemoveLayer,
    onOpacityChange: handleOpacityChange,
  }), [
    handleFilterChange, handlePaintChange, handleStyleConfigChange,
    handleLabelChange, handleToggleVisibility, handleAddDataset,
    handleAiRemoveLayer, handleOpacityChange,
  ]);

  return {
    localName, setLocalName,
    localDescription, setLocalDescription,
    localLayers,
    savedLayerBaseline: savedLayerBaselineRef.current,
    localBasemap, setLocalBasemap,
    hasUnsavedChanges, setHasUnsavedChanges,
    expandedLayerId,
    activeEditorTab,
    showBasemapLabels, setShowBasemapLabels,
    basemapConfig, setBasemapConfig,
    localTerrainConfig, setLocalTerrainConfig,
    ephemeralResult,
    initialViewState,
    handleToggleVisibility,
    handleMoveUp,
    handleMoveDown,
    handleReorder,
    handleDisplayNameChange,
    handleToggleExpand,
    handleTabChange,
    handleFilterChange,
    handleLabelChange,
    handlePopupChange,
    handleStyleConfigChange,
    handlePaintChange,
    handleOpacityChange,
    handleRenderAsChange,
    handleRenderModeChange,
    handleLayoutChange,
    handleZoomToLayer,
    handleRemove,
    handleAddDataset,
    handleDuplicateRendering,
    handleAiRemoveLayer,
    handleQueryResult,
    handleToggleLegend,
    handleDismissEphemeral,
    markDirty,
    chatLayerActions,
  };
}
