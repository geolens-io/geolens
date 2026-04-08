import { useCallback, useLayoutEffect, useRef } from 'react';
import type { Map as MaplibreMap, FilterSpecification } from 'maplibre-gl';
import { getLayerType, resolveAdapterType, getCompoundOpacity, CUSTOM_PAINT_PROPS } from '@/components/builder/map-sync';
import { buildLabelLayerSpec, syncLabelLayer } from '@/components/builder/label-layer-utils';
import type { MapLayerResponse, LabelConfig, StyleConfig } from '@/types/api';

type LayerUpdater = (layer: MapLayerResponse) => MapLayerResponse;
type LayerSideEffect = (map: MaplibreMap, updated: MapLayerResponse) => void;

export function useLayerMapSync(
  localLayers: MapLayerResponse[],
  setLocalLayers: React.Dispatch<React.SetStateAction<MapLayerResponse[]>>,
  setHasUnsavedChanges: React.Dispatch<React.SetStateAction<boolean>>,
  mapInstanceRef: React.RefObject<MaplibreMap | null>,
) {
  // Mirror current layers in a ref so the memoized callbacks can read fresh
  // state without having `localLayers` in their dependency list. Without this
  // ref, every layer mutation would invalidate all callbacks, tearing down
  // React.memo() on LayerItem and re-rendering every layer for every tweak
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
      let updated: MapLayerResponse | undefined;
      setLocalLayers((prev) =>
        prev.map((l) => {
          if (l.id !== layerId) return l;
          const next = updater(l);
          updated = next;
          return next;
        }),
      );
      setHasUnsavedChanges(true);

      if (!applyFn) return;
      const map = mapInstanceRef.current;
      if (!map || !map.isStyleLoaded()) return;
      if (!updated) return;
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
          if (map.getLayer(mapLayerId)) map.setLayoutProperty(mapLayerId, 'visibility', newVis);
          if (map.getLayer(outlineId)) map.setLayoutProperty(outlineId, 'visibility', newVis);
          if (map.getLayer(labelId)) map.setLayoutProperty(labelId, 'visibility', newVis);
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
          const outlineId = `layer-${layerId}-outline`;
          const adapterType = resolveAdapterType(layer.dataset_geometry_type, layer.style_config);

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
            if (adapterType === 'heatmap') {
              map.setPaintProperty(mapLayerId, 'heatmap-opacity', (layer.opacity ?? 1) * 0.8);
            } else {
              const geomType = adapterType as 'fill' | 'line' | 'circle';
              map.setPaintProperty(mapLayerId, `${geomType}-opacity`, getCompoundOpacity(newPaint, geomType, layer.opacity ?? 1));
            }
          }

          // Also compound circle-stroke-opacity with master opacity
          if (adapterType === 'circle' && newPaint['circle-stroke-opacity'] !== undefined && map.getLayer(mapLayerId)) {
            const strokeOpacity = (newPaint['circle-stroke-opacity'] as number) * (layer.opacity ?? 1);
            map.setPaintProperty(mapLayerId, 'circle-stroke-opacity', strokeOpacity);
          }

          // Custom outline props -> outline line layer (not applicable for heatmap)
          if (adapterType !== 'heatmap' && map.getLayer(outlineId)) {
            const oc = newPaint['_outline-color'] ?? newPaint['outline-color'];
            if (oc !== undefined) {
              map.setPaintProperty(outlineId, 'line-color', oc);
            }
            const ow = newPaint['_outline-width'] ?? newPaint['outline-width'];
            if (ow !== undefined) {
              map.setPaintProperty(outlineId, 'line-width', ow);
            }
          }
        },
      );
    },
    [applyLayerUpdate],
  );

  const handleStyleConfigChange = useCallback(
    (layerId: string, config: StyleConfig | null, paint: Record<string, unknown>) => {
      applyLayerUpdate(
        layerId,
        (l) => ({ ...l, style_config: config, paint }),
        (map) => {
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
          const adapterType = resolveAdapterType(layer.dataset_geometry_type, layer.style_config);

          if (layer.layer_type === 'raster_geolens') {
            if (map.getLayer(mapLayerId)) {
              map.setPaintProperty(mapLayerId, 'raster-opacity', newOpacity);
            }
          } else if (adapterType === 'heatmap') {
            if (map.getLayer(mapLayerId)) {
              const storedHeatmapOpacity = ((layer.paint as Record<string, unknown>)?.['heatmap-opacity'] as number) ?? 0.8;
              map.setPaintProperty(mapLayerId, 'heatmap-opacity', newOpacity * storedHeatmapOpacity);
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
      applyLayerUpdate(
        layerId,
        (l) => ({ ...l, filter: expression }),
        (map) => {
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
        },
      );
    },
    [applyLayerUpdate],
  );

  const handleLabelChange = useCallback(
    (layerId: string, config: LabelConfig | null) => {
      const layer = layersRef.current.find((l) => l.id === layerId);
      const geomType = layer ? getLayerType(layer.dataset_geometry_type) : 'fill';

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
            map.setFilter(labelLayerId, layer.filter);
          }
        },
      );
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
  };
}
