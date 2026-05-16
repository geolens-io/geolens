import { useCallback, useLayoutEffect, useRef } from 'react';
import type { Map as MaplibreMap, FilterSpecification } from 'maplibre-gl';
import { getLayerType, resolveAdapterType, getCompoundOpacity } from '@/components/builder/map-sync';
import { getAdapter } from '@/components/builder/layer-adapters/registry';
import type { AdapterLayerInput } from '@/components/builder/layer-adapters/types';
import { buildLabelLayerSpec, syncLabelLayer } from '@/components/builder/label-layer-utils';
import type { MapLayerResponse, LabelConfig, PopupConfig, StyleConfig } from '@/types/api';
import { sanitizeNullableNumericFilter } from '@/lib/maplibre-filter-utils';

type LayerUpdater = (layer: MapLayerResponse) => MapLayerResponse;
type LayerSideEffect = (map: MaplibreMap, updated: MapLayerResponse) => void;

function resolveLayerAdapterType(layer: MapLayerResponse, paint: Record<string, unknown>, styleConfig?: StyleConfig | null): string {
  if (layer.layer_type === 'raster_geolens') {
    return layer.is_dem === true && styleConfig?.render_mode === 'hillshade' ? 'hillshade' : 'raster';
  }
  return resolveAdapterType(layer.dataset_geometry_type, styleConfig ?? layer.style_config, paint);
}

export function useLayerMapSync(
  localLayers: MapLayerResponse[],
  setLocalLayers: React.Dispatch<React.SetStateAction<MapLayerResponse[]>>,
  setHasUnsavedChanges: React.Dispatch<React.SetStateAction<boolean>>,
  mapInstanceRef: React.RefObject<MaplibreMap | null>,
) {
  // Mirror current layers in a ref so the memoized callbacks can read fresh
  // state without having `localLayers` in their dependency list. Without this
  // ref, every layer mutation would invalidate all callbacks, tearing down
  // React.memo() on StackRow and re-rendering every layer for every tweak
  // (KISS-2 / PERF-N2).
  const layersRef = useRef(localLayers);
  useLayoutEffect(() => {
    layersRef.current = localLayers;
  }, [localLayers]);

  // Shared state-mutation + live-map-update pipeline for layer edits.
  // Collapses the dup 30-line boilerplate from paint/opacity/layout/style
  // handlers into one place (KISS-2). `updater` produces the new layer spec
  // inside the functional setState; `applyFn` runs the imperative MapLibre
  // sync using the freshly-computed layer.
  const applyLayerUpdate = useCallback(
    (layerId: string, updater: LayerUpdater, applyFn?: LayerSideEffect) => {
      // Pre-check existence against the synchronous ref so we can gate the
      // dirty-flag BEFORE React schedules the functional setState (whose
      // callback may not run until the next render). Closes the side-finding
      // from quick-260516-9g9: previously `setHasUnsavedChanges(true)` fired
      // unconditionally, which falsely marked dirty when a caller (e.g. the
      // dead BasemapGroupRow row slider via id="basemap-group") passed an id
      // that matched no layer.
      const existing = layersRef.current.find((l) => l.id === layerId);
      if (!existing) return;

      const updated = updater(existing);
      setLocalLayers((prev) =>
        prev.map((l) => (l.id === layerId ? updated : l)),
      );
      setHasUnsavedChanges(true);

      if (!applyFn) return;
      const map = mapInstanceRef.current;
      if (!map || !map.isStyleLoaded()) return;
      applyFn(map, updated);
    },
    [setLocalLayers, setHasUnsavedChanges, mapInstanceRef],
  );

  const handleToggleVisibility = useCallback(
    (layerId: string, visible?: boolean) => {
      const current = layersRef.current.find((l) => l.id === layerId);
      const nextVisible = visible !== undefined ? visible : !current?.visible;
      applyLayerUpdate(
        layerId,
        (l) => ({ ...l, visible: nextVisible }),
        (map) => {
          const newVis = nextVisible ? 'visible' : 'none';
          const mapLayerId = `layer-${layerId}`;
          const outlineId = `layer-${layerId}-outline`;
          const labelId = `layer-${layerId}-label`;
          const extrusionId = `layer-${layerId}-extrusion`;
          const clusterId = `layer-${layerId}-cluster`;
          const clusterCountId = `layer-${layerId}-cluster-count`;
          if (map.getLayer(mapLayerId)) map.setLayoutProperty(mapLayerId, 'visibility', newVis);
          if (map.getLayer(outlineId)) map.setLayoutProperty(outlineId, 'visibility', newVis);
          if (map.getLayer(labelId)) map.setLayoutProperty(labelId, 'visibility', newVis);
          if (map.getLayer(extrusionId)) map.setLayoutProperty(extrusionId, 'visibility', newVis);
          if (map.getLayer(clusterId)) map.setLayoutProperty(clusterId, 'visibility', newVis);
          if (map.getLayer(clusterCountId)) map.setLayoutProperty(clusterCountId, 'visibility', newVis);
        },
      );
    },
    [applyLayerUpdate],
  );

  const handlePaintChange = useCallback(
    (layerId: string, newPaint: Record<string, unknown>) => {
      applyLayerUpdate(
        layerId,
        (l) => ({ ...l, paint: newPaint }),
        (map, layer) => {
          const mapLayerId = `layer-${layerId}`;
          const adapterType = resolveLayerAdapterType(layer, newPaint);
          const adapter = getAdapter(adapterType);

          const input: AdapterLayerInput & { style_config?: StyleConfig | null } = {
            id: layer.id,
            dataset_table_name: layer.dataset_table_name,
            dataset_geometry_type: layer.dataset_geometry_type,
            opacity: layer.opacity ?? 1,
            visible: layer.visible,
            paint: newPaint,
            layout: layer.layout ?? {},
            filter: layer.filter ?? null,
            sourceId: `source-${layerId}`,
            layerId: mapLayerId,
            sourceLayer: `data.${layer.dataset_table_name}`,
            tileUrl: '',
            is_dem: layer.is_dem,
          };
          input.style_config = layer.style_config ?? null;

          adapter.syncPaint(map, input);
        },
      );
    },
    [applyLayerUpdate],
  );

  const handleStyleConfigChange = useCallback(
    (layerId: string, config: StyleConfig | null, paint: Record<string, unknown>) => {
      applyLayerUpdate(
        layerId,
        (l) => ({
          ...l,
          style_config: config
            ? {
                ...config,
                ...(config.builder === undefined && l.style_config?.builder
                  ? { builder: l.style_config.builder }
                  : {}),
              }
            : l.style_config?.builder
              ? ({ builder: l.style_config.builder } as StyleConfig)
              : null,
          paint,
        }),
        (map, layer) => {
          const mapLayerId = `layer-${layerId}`;
          if (!map.getLayer(mapLayerId)) return;

          const nextConfig = layer.style_config;
          const adapterType = resolveLayerAdapterType(layer, paint, nextConfig);
          const adapter = getAdapter(adapterType);
          const sourceId = `source-${layerId}`;
          const existingSource = map.getSource(sourceId) as { tiles?: string[] } | undefined;
          const rawTileUrl = existingSource?.tiles?.[0] ?? '';
          const tileUrl = rawTileUrl.startsWith(window.location.origin)
            ? rawTileUrl.slice(window.location.origin.length)
            : rawTileUrl;
          const input: AdapterLayerInput & { style_config?: StyleConfig | null } = {
            id: layer.id,
            dataset_table_name: layer.dataset_table_name,
            dataset_geometry_type: layer.dataset_geometry_type,
            opacity: layer.opacity ?? 1,
            visible: layer.visible,
            paint,
            layout: layer.layout ?? {},
            filter: layer.filter ?? null,
            sourceId,
            layerId: mapLayerId,
            sourceLayer: `data.${layer.dataset_table_name}`,
            tileUrl,
            is_dem: layer.is_dem,
          };
          input.style_config = nextConfig;

          if (layer.layer_type === 'raster_geolens' && tileUrl) {
            if (map.getLayer(mapLayerId)) map.removeLayer(mapLayerId);
            if (map.getSource(sourceId)) map.removeSource(sourceId);
            adapter.addLayers(map, input);
          } else {
            adapter.syncPaint(map, input);
          }
        },
      );
    },
    [applyLayerUpdate],
  );

  const handleOpacityChange = useCallback(
    (layerId: string, newOpacity: number) => {
      applyLayerUpdate(
        layerId,
        (l) => ({ ...l, opacity: newOpacity }),
        (map, layer) => {
          const mapLayerId = `layer-${layerId}`;
          const outlineId = `layer-${layerId}-outline`;
          const adapterType = resolveAdapterType(layer.dataset_geometry_type, layer.style_config, layer.paint);

          if (layer.layer_type === 'raster_geolens') {
            if (map.getLayer(mapLayerId)) {
              map.setPaintProperty(mapLayerId, 'raster-opacity', newOpacity);
            }
          } else if (adapterType === 'heatmap') {
            if (map.getLayer(mapLayerId)) {
              const storedHeatmapOpacity = (layer.paint?.['heatmap-opacity'] as number) ?? 0.8;
              map.setPaintProperty(mapLayerId, 'heatmap-opacity', newOpacity * storedHeatmapOpacity);
            }
          } else if (adapterType === 'cluster') {
            const input: AdapterLayerInput & { style_config?: StyleConfig | null } = {
              id: layer.id,
              dataset_table_name: layer.dataset_table_name,
              dataset_geometry_type: layer.dataset_geometry_type,
              opacity: newOpacity,
              visible: layer.visible,
              paint: layer.paint ?? {},
              layout: layer.layout ?? {},
              filter: layer.filter ?? null,
              sourceId: `source-${layerId}`,
              layerId: mapLayerId,
              sourceLayer: `data.${layer.dataset_table_name}`,
              tileUrl: '',
              style_config: layer.style_config ?? null,
              is_dem: layer.is_dem,
            };
            getAdapter('cluster').syncPaint(map, input);
          } else if (adapterType === 'fill' || adapterType === 'line' || adapterType === 'circle') {
            if (map.getLayer(mapLayerId)) {
              map.setPaintProperty(
                mapLayerId,
                `${adapterType}-opacity`,
                getCompoundOpacity(layer.paint ?? {}, adapterType, newOpacity),
              );
            }
            if (adapterType === 'fill' && map.getLayer(outlineId)) {
              map.setPaintProperty(outlineId, 'line-opacity', newOpacity);
            }
          }
        },
      );
    },
    [applyLayerUpdate],
  );

  const handleLayoutChange = useCallback(
    (layerId: string, newLayout: Record<string, unknown>) => {
      const prevLayout = (layersRef.current.find((l) => l.id === layerId)?.layout ?? {}) as Record<string, unknown>;
      applyLayerUpdate(
        layerId,
        (l) => ({ ...l, layout: newLayout }),
        (map) => {
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
          const clusterLayerId = `${mapLayerId}-cluster`;
          const clusterCountLayerId = `${mapLayerId}-cluster-count`;
          if (map.getLayer(clusterLayerId)) {
            map.setLayerZoomRange(clusterLayerId, minzoom, maxzoom);
          }
          if (map.getLayer(clusterCountLayerId)) {
            map.setLayerZoomRange(clusterCountLayerId, minzoom, maxzoom);
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
        },
      );
    },
    [applyLayerUpdate],
  );

  const handleFilterChange = useCallback(
    (layerId: string, expression: FilterSpecification | null) => {
      const filter = sanitizeNullableNumericFilter(expression);
      applyLayerUpdate(
        layerId,
        (l) => ({ ...l, filter }),
        (map) => {
          const mapLayerId = `layer-${layerId}`;
          const clusterId = `${mapLayerId}-cluster`;
          const clusterCountId = `${mapLayerId}-cluster-count`;
          const clusterFilter = filter ? ['all', ['has', 'point_count'], filter] as FilterSpecification : ['has', 'point_count'] as FilterSpecification;
          const unclusteredFilter = filter ? ['all', ['!', ['has', 'point_count']], filter] as FilterSpecification : ['!', ['has', 'point_count']] as FilterSpecification;
          if (map.getLayer(mapLayerId)) {
            map.setFilter(mapLayerId, map.getLayer(clusterId) ? unclusteredFilter : filter);
          }
          if (map.getLayer(clusterId)) {
            map.setFilter(clusterId, clusterFilter);
          }
          if (map.getLayer(clusterCountId)) {
            map.setFilter(clusterCountId, clusterFilter);
          }
          // Also filter outline layer for polygons
          const outlineId = `layer-${layerId}-outline`;
          if (map.getLayer(outlineId)) {
            map.setFilter(outlineId, filter);
          }
          // Also filter label layer
          const labelId = `layer-${layerId}-label`;
          if (map.getLayer(labelId)) {
            map.setFilter(labelId, filter);
          }
          // Also filter fill-extrusion companion layer
          const extrusionId = `layer-${layerId}-extrusion`;
          if (map.getLayer(extrusionId)) {
            map.setFilter(extrusionId, filter);
          }
        },
      );
    },
    [applyLayerUpdate],
  );

  const handleLabelChange = useCallback(
    (layerId: string, config: LabelConfig | null) => {
      // Normalize empty column to null to prevent persisting non-functional config
      if (config && !config.column) {
        config = null;
      }
      const layer = layersRef.current.find((l) => l.id === layerId);
      if (!layer) return;
      const geomType = getLayerType(layer.dataset_geometry_type);

      applyLayerUpdate(
        layerId,
        (l) => ({ ...l, label_config: config }),
        (map) => {
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
            syncLabelLayer(map, labelLayerId, config, geomType);
            return;
          }

          // Add new label layer
          if (!layer) return;

          const sourceId = `source-${layerId}`;
          if (!map.getSource(sourceId)) return;

          const sourceLayer = `data.${layer.dataset_table_name}`;
          const parentVis = (map.getLayer(`layer-${layerId}`)
            ? (map.getLayoutProperty(`layer-${layerId}`, 'visibility') ?? 'visible')
            : 'visible') as 'visible' | 'none';
          map.addLayer(buildLabelLayerSpec({ labelId: labelLayerId, sourceId, sourceLayer, lc: config, geomType, visibility: parentVis }));

          // Apply parent filter if any
          if (layer.filter) {
            map.setFilter(labelLayerId, sanitizeNullableNumericFilter(layer.filter));
          }
        },
      );
    },
    [applyLayerUpdate],
  );

  const handlePopupChange = useCallback(
    (layerId: string, config: PopupConfig | null) => {
      // No map side-effect: popup is a React component, not a MapLibre layer.
      applyLayerUpdate(layerId, (l) => ({ ...l, popup_config: config }));
    },
    [applyLayerUpdate],
  );

  return {
    handleToggleVisibility,
    handlePaintChange,
    handleStyleConfigChange,
    handleOpacityChange,
    handleLayoutChange,
    handleFilterChange,
    handleLabelChange,
    handlePopupChange,
  };
}
