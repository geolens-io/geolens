import { useCallback, useLayoutEffect, useRef } from 'react';
import type { Map as MaplibreMap, FilterSpecification } from 'maplibre-gl';
import { getLayerType, getSourceIdForLayer, resolveAdapterType, getCompoundOpacity, isDemTerrainVisualSuppressed } from '@/components/builder/map-sync';
import { getAdapter } from '@/components/builder/layer-adapters/registry';
import { getBuilderStyleConfig } from '@/components/builder/layer-adapters/shared';
import { mixedFamilyFilter } from '@/components/builder/layer-adapters/mixed-adapter';
import { coalesceFrame } from '@/lib/builder/raf-coalesce';
// fix(#394) VT-03/VT-04: single source of truth for the MVT source-layer name.
import { getMvtSourceLayerName } from '@/lib/tile-utils';
import { effectiveDemRenderMode, normalizeDemStyleConfig } from '@/lib/dem-render-mode';
import type { AdapterLayerInput } from '@/components/builder/layer-adapters/types';
import { buildLabelLayerSpec, syncLabelLayer } from '@/components/builder/label-layer-utils';
import type { MapLayerResponse, LabelConfig, PopupConfig, StyleConfig } from '@/types/api';
import { sanitizeNullableNumericFilter } from '@/lib/maplibre-filter-utils';
import { getCompanionLayerIds, COLOR_RELIEF_SUFFIX } from '@/components/builder/companion-ids';

type LayerUpdater = (layer: MapLayerResponse) => MapLayerResponse;
type LayerSideEffect = (map: MaplibreMap, updated: MapLayerResponse) => void;

function removeColorReliefLayer(map: MaplibreMap, layerId: string) {
  const colorReliefId = `${layerId}${COLOR_RELIEF_SUFFIX}`;
  if (map.getLayer(colorReliefId)) map.removeLayer(colorReliefId);
}

function resolveLayerAdapterType(layer: MapLayerResponse, paint: Record<string, unknown>, styleConfig?: StyleConfig | null): string {
  if (layer.layer_type === 'raster_geolens') {
    return layer.is_dem === true && effectiveDemRenderMode(styleConfig, layer.is_dem) === 'hillshade'
      ? 'hillshade'
      : 'raster';
  }
  return resolveAdapterType(layer.dataset_geometry_type, styleConfig ?? layer.style_config, paint);
}

// STATE-01 / SYNC-04: the canonical per-layer visibility map side-effect. The
// single-layer (`handleToggleVisibility`) AND the bulk
// (`handleBulkVisibility`) paths both call this so the strokeDisabled gate and
// the full companion set (including colorrelief + cluster) can never diverge.
// Companion ids are derived through `getCompanionLayerIds` — the one place the
// suffix convention lives.
export function applyLayerVisibilityToMap(
  map: MaplibreMap,
  layer: MapLayerResponse,
  nextVisible: boolean,
): void {
  const ids = getCompanionLayerIds(layer.id);
  const newVis = nextVisible ? 'visible' : 'none';
  if (map.getLayer(ids.layer)) map.setLayoutProperty(ids.layer, 'visibility', newVis);
  // BUG-036: a disabled fill outline carries its state as the outline layer's
  // layout visibility. Restoring it on the raw newVis resurrects a 1px outline
  // the user turned off (render-as 'Fill only'). Gate the outline on
  // strokeDisabled — mirror of fillAdapter.syncVisibility.
  if (map.getLayer(ids.outline)) {
    const builder = getBuilderStyleConfig(layer);
    const rawPaint = (layer.paint ?? {}) as Record<string, unknown>;
    const strokeDisabled = builder.strokeDisabled ?? !!rawPaint['_stroke-disabled'];
    map.setLayoutProperty(ids.outline, 'visibility', nextVisible && !strokeDisabled ? 'visible' : 'none');
  }
  if (map.getLayer(ids.label)) map.setLayoutProperty(ids.label, 'visibility', newVis);
  if (map.getLayer(ids.extrusion)) map.setLayoutProperty(ids.extrusion, 'visibility', newVis);
  if (map.getLayer(ids.arrow)) map.setLayoutProperty(ids.arrow, 'visibility', newVis);
  if (map.getLayer(ids.colorRelief)) map.setLayoutProperty(ids.colorRelief, 'visibility', newVis);
  if (map.getLayer(ids.cluster)) map.setLayoutProperty(ids.cluster, 'visibility', newVis);
  if (map.getLayer(ids.clusterCount)) map.setLayoutProperty(ids.clusterCount, 'visibility', newVis);
  if (map.getLayer(ids.mixedLines)) map.setLayoutProperty(ids.mixedLines, 'visibility', newVis);
  if (map.getLayer(ids.mixedPoints)) map.setLayoutProperty(ids.mixedPoints, 'visibility', newVis);
}

// STATE-03 / SYNC-04: the canonical per-layer opacity map side-effect. The
// single-layer (`handleOpacityChange`) AND the bulk (`handleBulkOpacity`)
// paths both call this so the getCompoundOpacity wrapping and the dedicated
// cluster branch can never diverge.
export function applyLayerOpacityToMap(
  map: MaplibreMap,
  layer: MapLayerResponse,
  opacity: number,
  mvtSourceLayerPrefix?: string | null,
): void {
  if (isDemTerrainVisualSuppressed(layer)) return;

  const ids = getCompanionLayerIds(layer.id);
  const mapLayerId = ids.layer;
  const paint = layer.paint ?? {};
  const adapterType = resolveLayerAdapterType(layer, paint, layer.style_config);

  if (adapterType === 'hillshade') {
    const input: AdapterLayerInput & { style_config?: StyleConfig | null } = {
      id: layer.id,
      dataset_table_name: layer.dataset_table_name,
      dataset_geometry_type: layer.dataset_geometry_type,
      opacity,
      visible: layer.visible,
      paint,
      layout: layer.layout ?? {},
      filter: layer.filter ?? null,
      sourceId: getSourceIdForLayer(layer),
      layerId: mapLayerId,
      sourceLayer: getMvtSourceLayerName(layer.dataset_table_name, mvtSourceLayerPrefix),
      tileUrl: '',
      style_config: layer.style_config ?? null,
      is_dem: layer.is_dem,
    };
    getAdapter('hillshade').syncPaint(map, input);
  } else if (layer.layer_type === 'raster_geolens') {
    if (map.getLayer(mapLayerId)) {
      map.setPaintProperty(mapLayerId, 'raster-opacity', opacity);
    }
  } else if (adapterType === 'heatmap') {
    if (map.getLayer(mapLayerId)) {
      const storedHeatmapOpacity = (paint['heatmap-opacity'] as number) ?? 0.8;
      map.setPaintProperty(mapLayerId, 'heatmap-opacity', opacity * storedHeatmapOpacity);
    }
  } else if (adapterType === 'cluster') {
    const input: AdapterLayerInput & { style_config?: StyleConfig | null } = {
      id: layer.id,
      dataset_table_name: layer.dataset_table_name,
      dataset_geometry_type: layer.dataset_geometry_type,
      opacity,
      visible: layer.visible,
      paint,
      layout: layer.layout ?? {},
      filter: layer.filter ?? null,
      // SF-04: cluster layers keep their per-layer source id; the helper routes
      // them through the cluster branch.
      sourceId: getSourceIdForLayer(layer),
      layerId: mapLayerId,
      sourceLayer: getMvtSourceLayerName(layer.dataset_table_name, mvtSourceLayerPrefix),
      tileUrl: '',
      style_config: layer.style_config ?? null,
      is_dem: layer.is_dem,
    };
    getAdapter('cluster').syncPaint(map, input);
  } else if (adapterType === 'mixed') {
    // fix(#430 codex r23): mixed-geometry layers spread opacity across four
    // family sublayers — route through the adapter like the cluster branch so
    // the slider affects points/lines too, not just the fill primary.
    const input: AdapterLayerInput & { style_config?: StyleConfig | null } = {
      id: layer.id,
      dataset_table_name: layer.dataset_table_name,
      dataset_geometry_type: layer.dataset_geometry_type,
      opacity,
      visible: layer.visible,
      paint,
      layout: layer.layout ?? {},
      filter: layer.filter ?? null,
      sourceId: getSourceIdForLayer(layer),
      layerId: mapLayerId,
      sourceLayer: getMvtSourceLayerName(layer.dataset_table_name, mvtSourceLayerPrefix),
      tileUrl: '',
      style_config: layer.style_config ?? null,
      is_dem: layer.is_dem,
    };
    getAdapter('mixed').syncPaint(map, input);
  } else if (adapterType === 'fill' || adapterType === 'line' || adapterType === 'circle') {
    if (map.getLayer(mapLayerId)) {
      map.setPaintProperty(
        mapLayerId,
        `${adapterType}-opacity`,
        getCompoundOpacity(paint, adapterType, opacity),
      );
    }
    if (adapterType === 'fill' && map.getLayer(ids.outline)) {
      map.setPaintProperty(ids.outline, 'line-opacity', opacity);
    }
  }
}

export function useLayerMapSync(
  localLayers: MapLayerResponse[],
  setLocalLayers: React.Dispatch<React.SetStateAction<MapLayerResponse[]>>,
  setHasUnsavedChanges: React.Dispatch<React.SetStateAction<boolean>>,
  mapInstanceRef: React.RefObject<MaplibreMap | null>,
  mvtSourceLayerPrefix?: string | null,
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

      // BUG-019: apply the updater INSIDE the functional setState so that
      // multiple synchronous applyLayerUpdate calls compose against the latest
      // `prev` rather than clobbering each other off the stale `layersRef`
      // snapshot. The existence gate above (ref-based) still guards the
      // dirty-flag; the actual mutation moves inside prev.map() so React's
      // functional update queue accumulates correctly.
      setLocalLayers((prev) =>
        prev.map((l) => (l.id === layerId ? updater(l) : l)),
      );
      setHasUnsavedChanges(true);

      if (!applyFn) return;
      const map = mapInstanceRef.current;
      if (!map || !map.isStyleLoaded()) return;
      // For the map side-effect we re-apply updater to the ref snapshot: the
      // map call is idempotent and the stale-ref issue only affects React state
      // composition, not the live-map sync. This keeps the applyFn signature
      // stable (it receives the just-computed updated layer, not a stale one).
      applyFn(map, updater(existing));
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
        (map, updated) => applyLayerVisibilityToMap(map, updated, nextVisible),
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
            // SF-04 dedupe: source id is per-dataset for non-cluster vector
            // layers, per-layer for cluster/raster/hillshade.
            sourceId: getSourceIdForLayer(layer),
            layerId: mapLayerId,
            sourceLayer: getMvtSourceLayerName(
              layer.dataset_table_name,
              mvtSourceLayerPrefix,
            ),
            tileUrl: '',
            is_dem: layer.is_dem,
          };
          input.style_config = layer.style_config ?? null;

          // Paint writes coalesce via rAF (PERF-04); visibility/filter/order remain
          // synchronous because they're idempotent and cheap, and synchronous
          // semantics let UI toggles feel instant.
          coalesceFrame(`paint:${layerId}`, () => adapter.syncPaint(map, input));
        },
      );
    },
    [applyLayerUpdate, mvtSourceLayerPrefix],
  );

  // Map-only side-effect for a style_config change — extracted so the bulk
  // "Apply style to selection" handler (ENH-03, Phase 1201-01) can drive the
  // live-map repaint per target WITHOUT triggering a second setLocalLayers
  // (its state write is a single atomic pass). `layer` must already carry the
  // post-merge paint + style_config.
  const syncStyleConfigToMap = useCallback(
    (map: MaplibreMap, layer: MapLayerResponse, paint: Record<string, unknown>) => {
      const mapLayerId = `layer-${layer.id}`;
      const nextConfig = layer.style_config;
      const sourceId = getSourceIdForLayer(layer);

      if (isDemTerrainVisualSuppressed({ is_dem: layer.is_dem, style_config: nextConfig })) {
        removeColorReliefLayer(map, mapLayerId);
        if (map.getLayer(mapLayerId)) map.removeLayer(mapLayerId);
        if (map.getSource(sourceId)) map.removeSource(sourceId);
        return;
      }

      if (!map.getLayer(mapLayerId)) return;

      const adapterType = resolveLayerAdapterType(layer, paint, nextConfig);
      const adapter = getAdapter(adapterType);
      // SF-04 dedupe: read from the shared per-dataset source for
      // non-cluster vector layers so tile URL inheritance still works.
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
        sourceLayer: getMvtSourceLayerName(
          layer.dataset_table_name,
          mvtSourceLayerPrefix,
        ),
        tileUrl,
        is_dem: layer.is_dem,
      };
      input.style_config = nextConfig;

      if (layer.layer_type === 'raster_geolens' && tileUrl) {
        removeColorReliefLayer(map, mapLayerId);
        if (map.getLayer(mapLayerId)) map.removeLayer(mapLayerId);
        if (map.getSource(sourceId)) map.removeSource(sourceId);
        adapter.addLayers(map, input);
        // BUG-01: re-assert visibility after the raster re-add. The
        // adapter's addLayers honors input.visible (raster-adapter:76-78),
        // but this defense-in-depth call mirrors the swapLayerOnMap fix
        // and guarantees the swap path never produces a layer in the
        // wrong visibility state — even if a future adapter forgets the
        // contract.
        adapter.syncVisibility(map, input);
      } else {
        adapter.syncPaint(map, input);
      }
    },
    [mvtSourceLayerPrefix],
  );

  const handleStyleConfigChange = useCallback(
    (layerId: string, config: StyleConfig | null, paint: Record<string, unknown>, opts?: { replace?: boolean }) => {
      // P1-07: a data-driven SOLID color (categorical, or graduated with the
      // color target) is incompatible with a line-gradient. Switching a line's
      // color to data-driven must drop the stale `line-gradient` paint AND the
      // `builder.lineGradient` intent stub — otherwise map-sync's
      // lineGradientNeededFor() re-adds the gradient and the saved JSON keeps
      // incompatible styling. This runs for BOTH the manual DataDrivenStyleEditor
      // path and the AI `set_style_config` action, which both land here.
      const isDataDrivenColor =
        !!config &&
        (config.mode === 'categorical' || config.mode === 'graduated') &&
        (config.target === undefined || config.target === 'color');
      let effectivePaint = paint;
      if (isDataDrivenColor && 'line-gradient' in paint) {
        const { 'line-gradient': _droppedGradient, ...rest } = paint;
        effectivePaint = rest;
      }
      applyLayerUpdate(
        layerId,
        (l) => {
          // fix(#461, codex P2): `replace` restores the config verbatim — used by
          // Revert-to-saved, which must NOT keep the draft's style_config.builder.
          // The default branch below deliberately preserves that builder when the
          // incoming config omits one (so setting a data-driven color doesn't wipe
          // your outline width), but on revert that preservation would strand a
          // discarded builder-only edit and keep the layer dirty.
          let mergedConfig: StyleConfig | null = opts?.replace
            ? config
            : config
              ? {
                  ...config,
                  ...(config.builder === undefined && l.style_config?.builder
                    ? { builder: l.style_config.builder }
                    : {}),
                }
              : l.style_config?.builder
                ? ({ builder: l.style_config.builder } as StyleConfig)
                : null;
          if (isDataDrivenColor && mergedConfig?.builder?.lineGradient) {
            const { lineGradient: _droppedLineGradient, ...restBuilder } = mergedConfig.builder;
            mergedConfig = {
              ...mergedConfig,
              builder: Object.keys(restBuilder).length > 0 ? restBuilder : undefined,
            };
          }
          return {
            ...l,
            style_config: normalizeDemStyleConfig(mergedConfig, l.is_dem),
            paint: effectivePaint,
          };
        },
        (map, layer) => {
          // Imperatively clear any stale line-gradient on the live map before the
          // adapter repaint; no-op for non-line layers (setPaintProperty throws).
          if (isDataDrivenColor) {
            const mapLayerId = `layer-${layer.id}`;
            if (map.getLayer(mapLayerId)) {
              try {
                map.setPaintProperty(mapLayerId, 'line-gradient', undefined);
              } catch {
                /* not a line layer — line-gradient is not a valid property */
              }
            }
          }
          syncStyleConfigToMap(map, layer, effectivePaint);
        },
      );
    },
    [applyLayerUpdate, syncStyleConfigToMap],
  );

  const handleOpacityChange = useCallback(
    (layerId: string, newOpacity: number) => {
      applyLayerUpdate(
        layerId,
        (l) => ({ ...l, opacity: newOpacity }),
        (map, layer) =>
          applyLayerOpacityToMap(map, layer, newOpacity, mvtSourceLayerPrefix),
      );
    },
    [applyLayerUpdate, mvtSourceLayerPrefix],
  );

  const handleLayoutChange = useCallback(
    (layerId: string, newLayout: Record<string, unknown>) => {
      const prevLayout = (layersRef.current.find((l) => l.id === layerId)?.layout ?? {}) as Record<string, unknown>;
      applyLayerUpdate(
        layerId,
        (l) => ({ ...l, layout: newLayout }),
        (map) => {
          const ids = getCompanionLayerIds(layerId);
          const mapLayerId = ids.layer;
          if (!map.getLayer(mapLayerId)) return;

          // Apply layer zoom range from custom layout props (main + outline companion)
          const minzoom = (newLayout['_minzoom'] as number) ?? 0;
          const maxzoom = (newLayout['_maxzoom'] as number) ?? 22;
          map.setLayerZoomRange(mapLayerId, minzoom, maxzoom);
          if (map.getLayer(ids.outline)) {
            map.setLayerZoomRange(ids.outline, minzoom, maxzoom);
          }
          // fix(HT-07): the DEM color-relief companion rides the same source
          // and must honor the layer's custom zoom range too.
          if (map.getLayer(ids.colorRelief)) {
            map.setLayerZoomRange(ids.colorRelief, minzoom, maxzoom);
          }
          if (map.getLayer(ids.cluster)) {
            map.setLayerZoomRange(ids.cluster, minzoom, maxzoom);
          }
          if (map.getLayer(ids.clusterCount)) {
            map.setLayerZoomRange(ids.clusterCount, minzoom, maxzoom);
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
          const ids = getCompanionLayerIds(layerId);
          // fix(#430 codex r23): mixed-geometry sublayers carry per-family
          // geometry-type filters as part of their identity — COMPOSE the data
          // filter with them (never replace), mirroring the dataset-page fix
          // for the same clobber class (codex r22).
          if (map.getLayer(ids.mixedPoints)) {
            map.setFilter(ids.layer, mixedFamilyFilter('polygon', filter));
            map.setFilter(ids.outline, mixedFamilyFilter('polygon', filter));
            map.setFilter(ids.mixedLines, mixedFamilyFilter('line', filter));
            map.setFilter(ids.mixedPoints, mixedFamilyFilter('point', filter));
            if (map.getLayer(ids.label)) {
              map.setFilter(ids.label, filter);
            }
            return;
          }
          // fix(#394) FL-01/B-020: cluster layers keep the bare point_count
          // predicate — cluster features carry no data properties, so ANDing
          // the data filter in hid every cluster bubble (mirrors the same fix
          // in cluster-adapter's clusterFilter).
          const clusterFilter = ['has', 'point_count'] as FilterSpecification;
          const unclusteredFilter = filter ? ['all', ['!', ['has', 'point_count']], filter] as FilterSpecification : ['!', ['has', 'point_count']] as FilterSpecification;
          if (map.getLayer(ids.layer)) {
            map.setFilter(ids.layer, map.getLayer(ids.cluster) ? unclusteredFilter : filter);
          }
          if (map.getLayer(ids.cluster)) {
            map.setFilter(ids.cluster, clusterFilter);
          }
          if (map.getLayer(ids.clusterCount)) {
            map.setFilter(ids.clusterCount, clusterFilter);
          }
          // Also filter outline layer for polygons
          if (map.getLayer(ids.outline)) {
            map.setFilter(ids.outline, filter);
          }
          // Also filter label layer
          if (map.getLayer(ids.label)) {
            map.setFilter(ids.label, filter);
          }
          // Also filter fill-extrusion companion layer
          if (map.getLayer(ids.extrusion)) {
            map.setFilter(ids.extrusion, filter);
          }
          // Also filter the line-arrow companion (B-004) so arrow symbols hide
          // for features removed by the filter.
          if (map.getLayer(ids.arrow)) {
            map.setFilter(ids.arrow, filter);
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
          const ids = getCompanionLayerIds(layerId);
          const labelLayerId = ids.label;

          // B-008/B-009: symbol-mode point layers carry their text in the
          // PRIMARY symbol layer (synced by syncLayersToMap on the state change
          // above); a companion *-label layer would duplicate it for one sync
          // cycle (flicker). Heatmaps carry no feature labels at all — the UI
          // gates the Labels tab, but the AI `set_label` action can bypass that
          // gate. In both modes tear down any stale companion and let
          // syncLayersToMap own the primary-layer text.
          const renderMode = (layer.style_config as { render_mode?: string } | null)
            ?.render_mode;
          if (renderMode === 'symbol' || renderMode === 'heatmap') {
            if (map.getLayer(labelLayerId)) {
              map.removeLayer(labelLayerId);
            }
            return;
          }

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

          // SF-04 dedupe: read from the shared per-dataset source.
          const sourceId = getSourceIdForLayer(layer);
          if (!map.getSource(sourceId)) return;

          const sourceLayer = getMvtSourceLayerName(
            layer.dataset_table_name,
            mvtSourceLayerPrefix,
          );
          const parentVis = (map.getLayer(ids.layer)
            ? (map.getLayoutProperty(ids.layer, 'visibility') ?? 'visible')
            : 'visible') as 'visible' | 'none';
          map.addLayer(buildLabelLayerSpec({ labelId: labelLayerId, sourceId, sourceLayer, lc: config, geomType, visibility: parentVis }));

          // Apply parent filter if any
          if (layer.filter) {
            map.setFilter(labelLayerId, sanitizeNullableNumericFilter(layer.filter));
          }
        },
      );
    },
    [applyLayerUpdate, mvtSourceLayerPrefix],
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
    // ENH-03 (Phase 1201-01): map-only style sync for bulk apply (single-setState
    // state write is owned by the bulk handler; this only repaints the map).
    syncStyleConfigToMap,
  };
}
