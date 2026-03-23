import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { Map as MaplibreMap, FilterSpecification } from 'maplibre-gl';
import { getLayerType } from '@/components/builder/map-sync';
import { MAP_COLORS } from '@/lib/map-colors';
import { resolveBasemapId } from '@/lib/basemap-utils';
import type { MapLayerResponse, MapResponse, LabelConfig, StyleConfig } from '@/types/api';
import type { useAddLayer, useRemoveLayer } from '@/hooks/use-maps';

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
  const [localBasemap, setLocalBasemap] = useState<string>('carto-positron');
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
      initializedRef.current = true;
    }
  }, [mapData]);

  // Sync layers from API when they change (after add/remove mutations)
  useEffect(() => {
    if (mapData && initializedRef.current) {
      setLocalLayers(mapData.layers);
    }
  }, [mapData?.layers]);

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

  const handleMapRef = useCallback((map: MaplibreMap | null) => {
    (mapInstanceRef as React.MutableRefObject<MaplibreMap | null>).current = map;
  }, [mapInstanceRef]);

  // --- Ephemeral layer management ---

  const EPHEMERAL_LAYERS = [
    'ephemeral-result-fill',
    'ephemeral-result-outline',
    'ephemeral-result-line',
    'ephemeral-result-circle',
  ] as const;
  const EPHEMERAL_SOURCE = 'ephemeral-result';

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
  }, [ephemeralResult]);

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

    // Remove label layer if config is null or column is empty
    if (!config || !config.column) {
      if (map.getLayer(labelLayerId)) {
        map.removeLayer(labelLayerId);
      }
      return;
    }

    // Update existing label layer
    if (map.getLayer(labelLayerId)) {
      map.setLayoutProperty(labelLayerId, 'text-field', ['get', config.column]);
      map.setLayoutProperty(labelLayerId, 'text-size', config.fontSize ?? 12);
      map.setPaintProperty(labelLayerId, 'text-color', config.textColor ?? MAP_COLORS.label.color);
      map.setPaintProperty(labelLayerId, 'text-halo-color', config.haloColor ?? MAP_COLORS.label.halo);
      map.setPaintProperty(labelLayerId, 'text-halo-width', config.haloWidth ?? 1.5);
      return;
    }

    // Add new label layer
    const layer = localLayers.find((l) => l.id === layerId);
    if (!layer) return;

    const sourceId = `source-${layerId}`;
    if (!map.getSource(sourceId)) return;

    const sourceLayer = `data.${layer.dataset_table_name}`;
    const geomType = getLayerType(layer.dataset_geometry_type);

    map.addLayer({
      id: labelLayerId,
      type: 'symbol',
      source: sourceId,
      'source-layer': sourceLayer,
      layout: {
        'text-field': ['get', config.column],
        'text-size': config.fontSize ?? 12,
        'symbol-placement': geomType === 'line' ? 'line' : 'point',
        'text-allow-overlap': false,
        'text-font': ['Noto Sans Regular'],
        'text-max-width': 10,
        ...(geomType === 'circle' ? { 'text-offset': [0, -1.5] as [number, number] } : {}),
      },
      paint: {
        'text-color': config.textColor ?? MAP_COLORS.label.color,
        'text-halo-color': config.haloColor ?? MAP_COLORS.label.halo,
        'text-halo-width': config.haloWidth ?? 1.5,
      },
    });

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

  // Custom paint props stored in JSON but not valid MapLibre fill paint properties
  const CUSTOM_PROPS = new Set(['outline-width', 'fill-outline-color']);

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
      if (value !== undefined && !CUSTOM_PROPS.has(prop)) {
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
      if (paint['fill-outline-color'] !== undefined) {
        try { map.setPaintProperty(outlineId, 'line-color', paint['fill-outline-color']); } catch {}
      }
      if (paint['outline-width'] !== undefined) {
        try { map.setPaintProperty(outlineId, 'line-width', paint['outline-width']); } catch {}
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

    // Live map update
    const map = mapInstanceRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const layer = resolvedLayer ?? localLayers.find((l) => l.id === layerId);
    if (!layer) return;

    const mapLayerId = `layer-${layerId}`;
    const outlineId = `layer-${layerId}-outline`;
    const geomType = getLayerType(layer.dataset_geometry_type);

    if (geomType === 'fill') {
      if (newPaint['fill-color'] && map.getLayer(mapLayerId)) {
        map.setPaintProperty(mapLayerId, 'fill-color', newPaint['fill-color']);
      }
      if (newPaint['fill-opacity'] !== undefined && map.getLayer(mapLayerId)) {
        const masterOpacity = layer.opacity ?? 1;
        map.setPaintProperty(
          mapLayerId,
          'fill-opacity',
          (newPaint['fill-opacity'] as number) * masterOpacity,
        );
      }
      if (newPaint['fill-outline-color'] && map.getLayer(outlineId)) {
        map.setPaintProperty(outlineId, 'line-color', newPaint['fill-outline-color']);
      }
      if (newPaint['outline-width'] !== undefined && map.getLayer(outlineId)) {
        map.setPaintProperty(outlineId, 'line-width', newPaint['outline-width']);
      }
    } else if (geomType === 'line') {
      if (newPaint['line-color'] && map.getLayer(mapLayerId)) {
        map.setPaintProperty(mapLayerId, 'line-color', newPaint['line-color']);
      }
      if (newPaint['line-opacity'] !== undefined && map.getLayer(mapLayerId)) {
        const masterOpacity = layer.opacity ?? 1;
        map.setPaintProperty(
          mapLayerId,
          'line-opacity',
          (newPaint['line-opacity'] as number) * masterOpacity,
        );
      }
      if (newPaint['line-width'] !== undefined && map.getLayer(mapLayerId)) {
        map.setPaintProperty(mapLayerId, 'line-width', newPaint['line-width']);
      }
    } else if (geomType === 'circle') {
      if (newPaint['circle-color'] && map.getLayer(mapLayerId)) {
        map.setPaintProperty(mapLayerId, 'circle-color', newPaint['circle-color']);
      }
      if (newPaint['circle-opacity'] !== undefined && map.getLayer(mapLayerId)) {
        const masterOpacity = layer.opacity ?? 1;
        map.setPaintProperty(
          mapLayerId,
          'circle-opacity',
          (newPaint['circle-opacity'] as number) * masterOpacity,
        );
      }
      if (newPaint['circle-radius'] !== undefined && map.getLayer(mapLayerId)) {
        map.setPaintProperty(mapLayerId, 'circle-radius', newPaint['circle-radius']);
      }
      if (newPaint['circle-stroke-color'] && map.getLayer(mapLayerId)) {
        map.setPaintProperty(mapLayerId, 'circle-stroke-color', newPaint['circle-stroke-color']);
      }
      if (newPaint['circle-stroke-width'] !== undefined && map.getLayer(mapLayerId)) {
        map.setPaintProperty(mapLayerId, 'circle-stroke-width', newPaint['circle-stroke-width']);
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

    // Live map update
    const map = mapInstanceRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const layer = resolvedLayer ?? localLayers.find((l) => l.id === layerId);
    if (!layer) return;

    const mapLayerId = `layer-${layerId}`;
    const outlineId = `layer-${layerId}-outline`;
    const geomType = getLayerType(layer.dataset_geometry_type);

    if (layer.layer_type === 'raster_geolens') {
      if (map.getLayer(mapLayerId)) {
        map.setPaintProperty(mapLayerId, 'raster-opacity', newOpacity);
      }
    } else if (geomType === 'fill') {
      if (map.getLayer(mapLayerId)) {
        const fillOpacity = (layer.paint?.['fill-opacity'] as number) ?? 0.3;
        map.setPaintProperty(mapLayerId, 'fill-opacity', fillOpacity * newOpacity);
      }
      if (map.getLayer(outlineId)) {
        map.setPaintProperty(outlineId, 'line-opacity', newOpacity);
      }
    } else if (geomType === 'line') {
      if (map.getLayer(mapLayerId)) {
        const lineOpacity = (layer.paint?.['line-opacity'] as number) ?? 1;
        map.setPaintProperty(mapLayerId, 'line-opacity', lineOpacity * newOpacity);
      }
    } else if (geomType === 'circle') {
      if (map.getLayer(mapLayerId)) {
        const circleOpacity = (layer.paint?.['circle-opacity'] as number) ?? 1;
        map.setPaintProperty(mapLayerId, 'circle-opacity', circleOpacity * newOpacity);
      }
    }
  }

  function handleZoomToLayer(layerId: string) {
    const map = mapInstanceRef.current;
    if (!map) return;
    const layer = localLayers.find((l) => l.id === layerId);
    if (!layer?.dataset_extent_bbox) return;
    const bbox = layer.dataset_extent_bbox;
    map.fitBounds(
      [[bbox[0], bbox[1]], [bbox[2], bbox[3]]],
      { padding: 40, maxZoom: 18 },
    );
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

  // AI-specific add: adds a pending layer locally (persisted on Save)
  function handleAiAddDataset(datasetId: string) {
    if (!mapId) return;
    handleAddDataset(datasetId);
  }

  // AI-specific remove: removes locally (persisted on Save)
  function handleAiRemoveLayer(layerId: string) {
    setLocalLayers((prev) => prev.filter((l) => l.id !== layerId));
    setHasUnsavedChanges(true);
  }

  function markDirty() {
    setHasUnsavedChanges(true);
  }

  return {
    localLayers,
    localBasemap, setLocalBasemap,
    hasUnsavedChanges, setHasUnsavedChanges,
    expandedLayerId,
    activeEditorTab,
    showBasemapLabels, setShowBasemapLabels,
    ephemeralResult,
    initialViewState,
    handleMapRef,
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
    handleZoomToLayer,
    handleRemove,
    handleAddDataset,
    handleAiAddDataset,
    handleAiRemoveLayer,
    handleQueryResult,
    handleDismissEphemeral,
    clearEphemeralLayer,
    markDirty,
  };
}
