import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { Map as MaplibreMap, FilterSpecification } from 'maplibre-gl';
import { getLayerType, resolveAdapterType, getCompoundOpacity, CUSTOM_PAINT_PROPS } from '@/components/builder/map-sync';
import { getAdapter } from '@/components/builder/layer-adapters/registry';
import type { AdapterLayerInput } from '@/components/builder/layer-adapters/types';
import { DEFAULT_HEATMAP_PAINT } from '@/components/builder/layer-adapters/heatmap-adapter';
import { buildSignedTileUrl } from '@/lib/tile-utils';
import { buildLabelLayerSpec, syncLabelLayer } from '@/components/builder/label-layer-utils';
import { resolveBasemapId } from '@/lib/basemap-utils';
import type { MapLayerResponse, MapResponse, LabelConfig, StyleConfig } from '@/types/api';
import type { useAddLayer, useRemoveLayer } from '@/hooks/use-maps';

const EPHEMERAL_LAYERS = [
  'ephemeral-result-fill',
  'ephemeral-result-outline',
  'ephemeral-result-line',
  'ephemeral-result-circle',
] as const;
const EPHEMERAL_SOURCE = 'ephemeral-result';

export function useBuilderLayers(
  mapData: MapResponse | undefined,
  mapInstanceRef: React.RefObject<MaplibreMap | null>,
  mapId: string | undefined,
  addLayerMutation: ReturnType<typeof useAddLayer>,
  removeLayerMutation: ReturnType<typeof useRemoveLayer>,
  searchParams: URLSearchParams,
  setSearchParams: ReturnType<typeof useSearchParams>[1],
) {
  const { t } = useTranslation('builder');

  const initializedRef = useRef(false);
  const addDatasetProcessedRef = useRef(false);

  const [localLayers, setLocalLayers] = useState<MapLayerResponse[]>([]);
  const [localBasemap, setLocalBasemap] = useState<string>('openfreemap-positron');
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [expandedLayerId, setExpandedLayerId] = useState<string | null>(null);
  const [activeEditorTab, setActiveEditorTab] = useState<'style' | 'filter' | 'labels' | null>(null);
  const [showBasemapLabels, setShowBasemapLabels] = useState(true);
  const [ephemeralResult, setEphemeralResult] = useState<{
    geojson: GeoJSON.FeatureCollection;
    bbox: [number, number, number, number];
  } | null>(null);

  // Initialize local state from API data (once)
  useEffect(() => {
    if (mapData && !initializedRef.current) {
      setLocalLayers(mapData.layers);
      setLocalBasemap(resolveBasemapId(mapData.basemap_style || 'positron'));
      setShowBasemapLabels(mapData.show_basemap_labels ?? true);
      initializedRef.current = true;
    }
  }, [mapData]);

  // Sync layers from API when they change (after add/remove mutations)
  const apiLayers = mapData?.layers;
  useEffect(() => {
    if (apiLayers && initializedRef.current) {
      setLocalLayers(apiLayers);
    }
  }, [apiLayers]);

  // Handle ?add_dataset URL param: auto-add a dataset as a layer on map load
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
  }, [initializedRef.current, searchParams]);

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

  // --- Ephemeral layer management ---

  const clearEphemeralLayer = useCallback(() => {
    const map = mapInstanceRef.current;
    if (map) {
      for (const layerId of EPHEMERAL_LAYERS) {
        if (map.getLayer(layerId)) map.removeLayer(layerId);
      }
      if (map.getSource(EPHEMERAL_SOURCE)) map.removeSource(EPHEMERAL_SOURCE);
    }
    setEphemeralResult(null);
  }, [mapInstanceRef]);

  // Add ephemeral GeoJSON layers to the map when result changes
  useEffect(() => {
    if (!ephemeralResult) return;
    const map = mapInstanceRef.current;
    if (!map) return;

    function addLayers() {
      if (!map || !ephemeralResult) return;
      // Remove any existing ephemeral layers/source first
      for (const layerId of EPHEMERAL_LAYERS) {
        if (map.getLayer(layerId)) map.removeLayer(layerId);
      }
      if (map.getSource(EPHEMERAL_SOURCE)) map.removeSource(EPHEMERAL_SOURCE);

      map.addSource(EPHEMERAL_SOURCE, {
        type: 'geojson',
        data: ephemeralResult.geojson,
      });

      // Polygon fill
      map.addLayer({
        id: 'ephemeral-result-fill',
        type: 'fill',
        source: EPHEMERAL_SOURCE,
        filter: ['==', '$type', 'Polygon'],
        paint: { 'fill-color': '#f97316', 'fill-opacity': 0.15 },
      });

      // Polygon outline
      map.addLayer({
        id: 'ephemeral-result-outline',
        type: 'line',
        source: EPHEMERAL_SOURCE,
        filter: ['==', '$type', 'Polygon'],
        paint: { 'line-color': '#f97316', 'line-width': 2, 'line-dasharray': [3, 2] },
      });

      // Line layer
      map.addLayer({
        id: 'ephemeral-result-line',
        type: 'line',
        source: EPHEMERAL_SOURCE,
        filter: ['==', '$type', 'LineString'],
        paint: { 'line-color': '#f97316', 'line-width': 2.5, 'line-dasharray': [3, 2] },
      });

      // Point layer
      map.addLayer({
        id: 'ephemeral-result-circle',
        type: 'circle',
        source: EPHEMERAL_SOURCE,
        filter: ['==', '$type', 'Point'],
        paint: {
          'circle-radius': 6,
          'circle-color': '#f97316',
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 2,
        },
      });

      // Auto-zoom to bounds
      const [west, south, east, north] = ephemeralResult.bbox;
      map.fitBounds([[west, south], [east, north]], { padding: 40, maxZoom: 18 });
    }

    if (map.isStyleLoaded()) {
      addLayers();
    } else {
      map.once('style.load', addLayers);
    }
  }, [ephemeralResult, mapInstanceRef]);

  const handleQueryResult = useCallback((geojson: GeoJSON.FeatureCollection, bbox: [number, number, number, number]) => {
    setEphemeralResult({ geojson, bbox });
  }, []);

  const handleDismissEphemeral = useCallback(() => {
    clearEphemeralLayer();
  }, [clearEphemeralLayer]);

  // --- Layer handlers ---

  function handleToggleVisibility(layerId: string, visible?: boolean) {
    setLocalLayers((prev) =>
      prev.map((l) =>
        l.id === layerId
          ? { ...l, visible: visible !== undefined ? visible : !l.visible }
          : l,
      ),
    );
    setHasUnsavedChanges(true);
  }

  function handleMoveUp(layerId: string) {
    setLocalLayers((prev) => {
      const idx = prev.findIndex((l) => l.id === layerId);
      if (idx <= 0) return prev;
      const next = [...prev];
      [next[idx - 1], next[idx]] = [next[idx], next[idx - 1]];
      return next.map((l, i) => ({ ...l, sort_order: i }));
    });
    setHasUnsavedChanges(true);
  }

  function handleMoveDown(layerId: string) {
    setLocalLayers((prev) => {
      const idx = prev.findIndex((l) => l.id === layerId);
      if (idx < 0 || idx >= prev.length - 1) return prev;
      const next = [...prev];
      [next[idx], next[idx + 1]] = [next[idx + 1], next[idx]];
      return next.map((l, i) => ({ ...l, sort_order: i }));
    });
    setHasUnsavedChanges(true);
  }

  function handleReorder(reorderedLayers: MapLayerResponse[]) {
    setLocalLayers(reorderedLayers.map((l, i) => ({ ...l, sort_order: i })));
    setHasUnsavedChanges(true);
  }

  function handleDisplayNameChange(layerId: string, newName: string | null) {
    setLocalLayers((prev) =>
      prev.map((l) => (l.id === layerId ? { ...l, display_name: newName } : l)),
    );
    setHasUnsavedChanges(true);
  }

  function handleToggleExpand(layerId: string) {
    setExpandedLayerId((prev) => (prev === layerId ? null : layerId));
    if (expandedLayerId !== layerId) setActiveEditorTab('style');
  }

  function handleTabChange(_layerId: string, tab: 'style' | 'filter' | 'labels') {
    setActiveEditorTab((prev) => (prev === tab ? null : tab));
  }

  function handleFilterChange(layerId: string, expression: FilterSpecification | null) {
    setLocalLayers((prev) =>
      prev.map((l) => (l.id === layerId ? { ...l, filter: expression } : l)),
    );
    setHasUnsavedChanges(true);

    // Live map update
    const map = mapInstanceRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const mapLayerId = `layer-${layerId}`;
    if (map.getLayer(mapLayerId)) {
      map.setFilter(mapLayerId, expression);
    }
    // Also filter outline layer for polygons
    const outlineId = `layer-${layerId}-outline`;
    if (map.getLayer(outlineId)) {
      map.setFilter(outlineId, expression);
    }
    // Also filter label layer
    const labelId = `layer-${layerId}-label`;
    if (map.getLayer(labelId)) {
      map.setFilter(labelId, expression);
    }
  }

  function handleLabelChange(layerId: string, config: LabelConfig | null) {
    setLocalLayers((prev) =>
      prev.map((l) => (l.id === layerId ? { ...l, label_config: config } : l)),
    );
    setHasUnsavedChanges(true);

    // Live map update
    const map = mapInstanceRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const labelLayerId = `layer-${layerId}-label`;
    const layer = localLayers.find((l) => l.id === layerId);
    const geomType = layer ? getLayerType(layer.dataset_geometry_type) : 'fill';

    // Remove label layer if config is null or column is empty
    if (!config || !config.column) {
      if (map.getLayer(labelLayerId)) {
        map.removeLayer(labelLayerId);
      }
      return;
    }

    // Update existing label layer
    if (map.getLayer(labelLayerId)) {
      syncLabelLayer(map, labelLayerId, config, geomType);
      return;
    }

    // Add new label layer
    if (!layer) return;

    const sourceId = `source-${layerId}`;
    if (!map.getSource(sourceId)) return;

    const sourceLayer = `data.${layer.dataset_table_name}`;
    map.addLayer(buildLabelLayerSpec({ labelId: labelLayerId, sourceId, sourceLayer, lc: config, geomType }));

    // Match parent visibility
    const parentLayerId = `layer-${layerId}`;
    if (map.getLayer(parentLayerId)) {
      const vis = map.getLayoutProperty(parentLayerId, 'visibility') ?? 'visible';
      map.setLayoutProperty(labelLayerId, 'visibility', vis);
    }

    // Apply parent filter if any
    if (layer.filter && Array.isArray(layer.filter) && layer.filter.length > 0) {
      map.setFilter(labelLayerId, layer.filter);
    }
  }

  function handleStyleConfigChange(
    layerId: string,
    config: StyleConfig | null,
    paint: Record<string, unknown>,
  ) {
    setLocalLayers((prev) =>
      prev.map((l) =>
        l.id === layerId ? { ...l, style_config: config, paint } : l,
      ),
    );
    setHasUnsavedChanges(true);

    // Live map update — apply paint properties (including expressions)
    const map = mapInstanceRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const mapLayerId = `layer-${layerId}`;
    if (!map.getLayer(mapLayerId)) return;

    for (const [prop, value] of Object.entries(paint)) {
      if (value !== undefined && !CUSTOM_PAINT_PROPS.has(prop)) {
        try {
          map.setPaintProperty(
            mapLayerId,
            prop,
            value as Parameters<MaplibreMap['setPaintProperty']>[2],
          );
        } catch (e) {
          if (import.meta.env.DEV) console.debug(`[builder] Failed to set ${prop}:`, e);
        }
      }
    }

    // Also sync custom props to the outline layer
    const outlineId = `layer-${layerId}-outline`;
    if (map.getLayer(outlineId)) {
      const oc = paint['_outline-color'] ?? paint['outline-color'];
      if (oc !== undefined) {
        try { map.setPaintProperty(outlineId, 'line-color', oc); } catch (e) { if (import.meta.env.DEV) console.debug('[builder] outline-color sync:', e); }
      }
      const ow = paint['_outline-width'] ?? paint['outline-width'];
      if (ow !== undefined) {
        try { map.setPaintProperty(outlineId, 'line-width', ow); } catch (e) { if (import.meta.env.DEV) console.debug('[builder] outline-width sync:', e); }
      }
    }
  }

  function handlePaintChange(layerId: string, newPaint: Record<string, unknown>) {
    let resolvedLayer: MapLayerResponse | undefined;
    setLocalLayers((prev) => {
      const updated = prev.map((l) => (l.id === layerId ? { ...l, paint: newPaint } : l));
      resolvedLayer = updated.find((l) => l.id === layerId);
      return updated;
    });
    setHasUnsavedChanges(true);

    const map = mapInstanceRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const layer = resolvedLayer;
    if (!layer) return;

    const mapLayerId = `layer-${layerId}`;
    const outlineId = `layer-${layerId}-outline`;
    const geomType = getLayerType(layer.dataset_geometry_type);

    // Generic paint property sync
    for (const [prop, value] of Object.entries(newPaint)) {
      if (CUSTOM_PAINT_PROPS.has(prop)) continue;
      if (value !== undefined && map.getLayer(mapLayerId)) {
        try {
          map.setPaintProperty(mapLayerId, prop, value);
        } catch (e) {
          if (import.meta.env.DEV) console.debug(`[builder] Failed to set ${prop}:`, e);
        }
      }
    }

    // Compound opacity override (product of per-type and master opacity)
    if (map.getLayer(mapLayerId)) {
      const opacityProp = `${geomType}-opacity`;
      map.setPaintProperty(mapLayerId, opacityProp, getCompoundOpacity(newPaint, geomType, layer.opacity ?? 1));
    }

    // Custom outline props -> outline line layer
    if (map.getLayer(outlineId)) {
      const oc = newPaint['_outline-color'] ?? newPaint['outline-color'];
      if (oc !== undefined) {
        map.setPaintProperty(outlineId, 'line-color', oc);
      }
      const ow = newPaint['_outline-width'] ?? newPaint['outline-width'];
      if (ow !== undefined) {
        map.setPaintProperty(outlineId, 'line-width', ow);
      }
    }
  }

  function handleOpacityChange(layerId: string, newOpacity: number) {
    let resolvedLayer: MapLayerResponse | undefined;
    setLocalLayers((prev) => {
      const updated = prev.map((l) => (l.id === layerId ? { ...l, opacity: newOpacity } : l));
      resolvedLayer = updated.find((l) => l.id === layerId);
      return updated;
    });
    setHasUnsavedChanges(true);

    const map = mapInstanceRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const layer = resolvedLayer;
    if (!layer) return;

    const mapLayerId = `layer-${layerId}`;
    const outlineId = `layer-${layerId}-outline`;
    const adapterType = resolveAdapterType(layer.dataset_geometry_type, layer.style_config);

    if (layer.layer_type === 'raster_geolens') {
      if (map.getLayer(mapLayerId)) {
        map.setPaintProperty(mapLayerId, 'raster-opacity', newOpacity);
      }
    } else if (adapterType === 'heatmap') {
      if (map.getLayer(mapLayerId)) {
        map.setPaintProperty(mapLayerId, 'heatmap-opacity', newOpacity * 0.8);
      }
    } else {
      const geomType = adapterType as 'fill' | 'line' | 'circle';
      if (map.getLayer(mapLayerId)) {
        map.setPaintProperty(
          mapLayerId,
          `${geomType}-opacity`,
          getCompoundOpacity(layer.paint ?? {}, geomType, newOpacity),
        );
      }
      if (geomType === 'fill' && map.getLayer(outlineId)) {
        map.setPaintProperty(outlineId, 'line-opacity', newOpacity);
      }
    }
  }

  function handleZoomToLayer(layerId: string) {
    const map = mapInstanceRef.current;
    if (!map) return;
    const layer = localLayers.find((l) => l.id === layerId);
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
  }

  function handleRemove(layerId: string) {
    if (!mapId) return;
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
  }

  function handleAddDataset(datasetId: string) {
    if (!mapId) return;
    // Prevent duplicate layer for the same dataset
    if (localLayers.some((l) => l.dataset_id === datasetId)) {
      toast.error(t('toasts.layerAlreadyAdded', { defaultValue: 'Dataset already added as a layer' }));
      return;
    }
    const nextSortOrder = localLayers.length;
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
  }

  // AI-specific remove: removes locally (persisted on Save)
  function handleAiRemoveLayer(layerId: string) {
    setLocalLayers((prev) => prev.filter((l) => l.id !== layerId));
    setHasUnsavedChanges(true);
  }

  function handleToggleLegend(layerId: string) {
    setLocalLayers((prev) =>
      prev.map((l) =>
        l.id === layerId ? { ...l, show_in_legend: !l.show_in_legend } : l,
      ),
    );
    setHasUnsavedChanges(true);
  }

  /** Swap the MapLibre layer for a given dataset between adapter types (e.g. circle ↔ heatmap). */
  function swapLayerOnMap(
    layer: MapLayerResponse,
    adapterType: string,
    updatedPaint: Record<string, unknown>,
  ) {
    const map = mapInstanceRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const mapLayerId = `layer-${layer.id}`;
    const sourceId = `source-${layer.id}`;
    const labelId = `layer-${layer.id}-label`;

    // Remove old layer
    if (map.getLayer(mapLayerId)) {
      map.removeLayer(mapLayerId);
    }

    // Get tile URL from existing source
    const source = map.getSource(sourceId) as { tiles?: string[] } | undefined;
    const tileUrl = source?.tiles?.[0] ?? buildSignedTileUrl(layer.dataset_table_name, null, undefined);
    const sourceLayer = `data.${layer.dataset_table_name}`;

    const adapterInput: AdapterLayerInput = {
      id: layer.id,
      dataset_table_name: layer.dataset_table_name,
      dataset_geometry_type: layer.dataset_geometry_type,
      opacity: layer.opacity ?? 1,
      visible: layer.visible,
      paint: updatedPaint,
      layout: (layer.layout as Record<string, unknown>) ?? {},
      filter: layer.filter,
      label_config: layer.label_config,
      sourceId,
      layerId: mapLayerId,
      sourceLayer,
      tileUrl,
    };

    getAdapter(adapterType).addLayers(map, adapterInput);

    // Manage label layer: hide for heatmap, restore for points
    if (adapterType === 'heatmap') {
      if (map.getLayer(labelId)) {
        map.setLayoutProperty(labelId, 'visibility', 'none');
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
  }

  function handleRenderModeChange(layerId: string, mode: 'points' | 'heatmap') {
    const layer = localLayers.find((l) => l.id === layerId);
    if (!layer) return;

    const currentStyleConfig = (layer.style_config ?? {}) as Record<string, unknown>;
    let updatedPaint = { ...(layer.paint as Record<string, unknown>) };

    if (mode === 'heatmap') {
      const savedCirclePaint = { ...updatedPaint };
      const savedHeatmapPaint = (currentStyleConfig['heatmapPaint'] as Record<string, unknown> | undefined) ?? {};

      updatedPaint = Object.keys(savedHeatmapPaint).length > 0
        ? { ...savedHeatmapPaint }
        : { ...DEFAULT_HEATMAP_PAINT };

      const updatedStyleConfig = {
        ...currentStyleConfig,
        render_mode: 'heatmap',
        savedCirclePaint: savedCirclePaint,
      };

      setLocalLayers((prev) =>
        prev.map((l) =>
          l.id === layerId
            ? { ...l, paint: updatedPaint, style_config: updatedStyleConfig as typeof l.style_config }
            : l,
        ),
      );

      swapLayerOnMap(layer, 'heatmap', updatedPaint);
    } else {
      const savedHeatmapPaint = { ...updatedPaint };
      const savedCirclePaint = (currentStyleConfig['savedCirclePaint'] as Record<string, unknown> | undefined) ?? {};

      updatedPaint = Object.keys(savedCirclePaint).length > 0 ? savedCirclePaint : {
        'circle-color': '#3b82f6',
        'circle-radius': 5,
        'circle-stroke-color': '#ffffff',
        'circle-stroke-width': 1,
      };

      const updatedStyleConfig = {
        ...currentStyleConfig,
        render_mode: 'points',
        heatmapPaint: savedHeatmapPaint,
      };
      delete updatedStyleConfig['savedCirclePaint'];

      setLocalLayers((prev) =>
        prev.map((l) =>
          l.id === layerId
            ? { ...l, paint: updatedPaint, style_config: updatedStyleConfig as typeof l.style_config }
            : l,
        ),
      );

      swapLayerOnMap(layer, 'circle', updatedPaint);
    }

    setHasUnsavedChanges(true);
  }

  function handleLayoutChange(layerId: string, newLayout: Record<string, unknown>) {
    const prevLayout = (localLayers.find((l) => l.id === layerId)?.layout ?? {}) as Record<string, unknown>;
    setLocalLayers((prev) =>
      prev.map((l) => (l.id === layerId ? { ...l, layout: newLayout } : l)),
    );
    setHasUnsavedChanges(true);

    // Live map update
    const map = mapInstanceRef.current;
    if (!map || !map.isStyleLoaded()) return;
    const mapLayerId = `layer-${layerId}`;
    if (!map.getLayer(mapLayerId)) return;

    // Apply layer zoom range from custom layout props (main + outline companion)
    const minzoom = (newLayout['_minzoom'] as number) ?? 0;
    const maxzoom = (newLayout['_maxzoom'] as number) ?? 22;
    map.setLayerZoomRange(mapLayerId, minzoom, maxzoom);
    const outlineLayerId = `${mapLayerId}-outline`;
    if (map.getLayer(outlineLayerId)) {
      map.setLayerZoomRange(outlineLayerId, minzoom, maxzoom);
    }

    for (const [prop, value] of Object.entries(newLayout)) {
      // Skip custom props — not real MapLibre layout properties
      if (prop.startsWith('_')) continue;
      try {
        // line-dasharray is stored in layout JSON but is a MapLibre paint property
        if (prop === 'line-dasharray') {
          map.setPaintProperty(mapLayerId, prop, value ?? undefined);
        } else {
          map.setLayoutProperty(mapLayerId, prop, value ?? undefined);
        }
      } catch (e) {
        if (import.meta.env.DEV) console.debug(`[builder] Failed to set layout ${prop}:`, e);
      }
    }
    // Clear removed props (e.g., removing line-dasharray sets solid)
    for (const prop of Object.keys(prevLayout)) {
      if (prop.startsWith('_')) continue;
      if (!(prop in newLayout)) {
        try {
          if (prop === 'line-dasharray') {
            map.setPaintProperty(mapLayerId, prop, undefined);
          } else {
            map.setLayoutProperty(mapLayerId, prop, undefined);
          }
        } catch (e) {
          if (import.meta.env.DEV) console.debug(`[builder] Failed to clear layout ${prop}:`, e);
        }
      }
    }
  }

  const markDirty = useCallback(() => setHasUnsavedChanges(true), []);

  return {
    localLayers,
    localBasemap, setLocalBasemap,
    hasUnsavedChanges, setHasUnsavedChanges,
    expandedLayerId,
    activeEditorTab,
    showBasemapLabels, setShowBasemapLabels,
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
    handleStyleConfigChange,
    handlePaintChange,
    handleOpacityChange,
    handleRenderModeChange,
    handleLayoutChange,
    handleZoomToLayer,
    handleRemove,
    handleAddDataset,
    handleAiRemoveLayer,
    handleQueryResult,
    handleToggleLegend,
    handleDismissEphemeral,
    markDirty,
  };
}
