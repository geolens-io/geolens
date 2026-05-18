import { useState, useEffect, useLayoutEffect, useRef, useMemo, useCallback } from 'react';
import { useSearchParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { useQueryClient } from '@tanstack/react-query';
import { getLayerType, getSourceIdForLayer, reorderDataLayers } from '@/components/builder/map-sync';
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
import { bulkDeleteLayersApi } from '@/api/maps';

/**
 * Frontend-only extension of MapLayerResponse with group-related fields.
 * parent_group_id is an in-memory-only field used to track group membership
 * during the builder session. It is not persisted to the API.
 * layer_type is widened to string to support 'group:folder' and 'group:basemap' variants.
 */
type GroupedLayer = Omit<MapLayerResponse, 'layer_type'> & {
  layer_type?: string | null;
  parent_group_id?: string | null;
};

/**
 * WR-01 (Phase 1050-rev): imperatively remove per-layer companion MapLibre
 * layers (label / outline / extrusion / arrow / cluster-circle / cluster-count
 * + main `layer-${id}`) when a layer is removed. Required because
 * `removeStaleSourcesAndLayers` in map-sync.ts derives companion ids by
 * stripping the source prefix — that path no longer produces correct layer
 * ids under the SF-04 dedupe contract (the stripped value is
 * `data-${dataset_table_name}`, not the real layer id). Without this
 * imperative cleanup, every non-AI removal path (handleRemove,
 * handleBulkDelete) leaks the companion layers until basemap-switch or
 * page reload.
 *
 * Sources are intentionally NOT removed here — the next syncFromState
 * invocation's reference-count-aware `removeStaleSourcesAndLayers`
 * desired-set prune handles source teardown correctly (deduped sources
 * stay if siblings still reference them).
 */
function removePerLayerCompanions(
  map: MaplibreMap | null,
  layerIds: Iterable<string>,
): void {
  if (!map || !map.isStyleLoaded()) return;
  const suffixes = ['', '-outline', '-label', '-extrusion', '-arrow', '-cluster', '-cluster-count'];
  for (const id of layerIds) {
    for (const suffix of suffixes) {
      const lid = `layer-${id}${suffix}`;
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

export function useBuilderLayers(
  mapData: MapResponse | undefined,
  mapInstanceRef: React.RefObject<MaplibreMap | null>,
  mapId: string | undefined,
  addLayerMutation: ReturnType<typeof useAddLayer>,
  removeLayerMutation: ReturnType<typeof useRemoveLayer>,
) {
  const [searchParams, setSearchParams] = useSearchParams();
  const { t } = useTranslation('builder');
  const queryClient = useQueryClient();

  const initializedRef = useRef(false);
  const addDatasetProcessedRef = useRef(false);

  const [localLayers, setLocalLayers] = useState<MapLayerResponse[]>([]);
  const [localBasemap, setLocalBasemap] = useState<string>('openfreemap-positron');
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [expandedLayerId, setExpandedLayerId] = useState<string | null>(null);
  const [activeEditorTab, setActiveEditorTab] = useState<'style' | 'filter' | 'labels' | 'popup' | null>(null);
  const [showBasemapLabels, setShowBasemapLabels] = useState(true);
  const [basemapConfig, _setBasemapConfigRaw] = useState<MapBasemapConfig | null>(null);
  // WR-02 (quick-260516-9g9 followup): wrap setBasemapConfig so external callers
  // get dirty-tracking for free — Option B's single-source-of-truth principle
  // means basemapConfig writes always imply user intent to persist. The raw
  // setter is reserved for the load path (line ~120) where the initial
  // hydration must NOT mark dirty.
  const setBasemapConfig = useCallback(
    (next: MapBasemapConfig | null | ((prev: MapBasemapConfig | null) => MapBasemapConfig | null)) => {
      _setBasemapConfigRaw(next);
      setHasUnsavedChanges(true);
    },
    [],
  );
  const [localTerrainConfig, setLocalTerrainConfig] = useState<MapTerrainConfig | null>(null);
  const [groupMeta, setGroupMeta] = useState<Record<string, { expanded: boolean }>>({});
  const [localName, setLocalName] = useState('');
  const [localDescription, setLocalDescription] = useState('');
  const [freshLayerId, setFreshLayerId] = useState<string | null>(null);
  // Phase 1047-04 (PERF-03): tracks in-flight bulk-delete to gate BulkActionBar spinner
  const [isDeleting, setIsDeleting] = useState(false);
  const freshLayerTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const savedLayerBaselineRef = useRef<MapLayerResponse[]>([]);

  // Mirror current layers in a ref so stable callbacks can read fresh state
  // without invalidating on every layer mutation. Without this, each layer
  // edit would tear down React.memo() on StackRow (KISS-2 / PERF-N2).
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
      _setBasemapConfigRaw(mapData.basemap_config ?? null);
      setLocalTerrainConfig(mapData.terrain_config ?? null);
      setGroupMeta((mapData as { group_meta?: Record<string, { expanded: boolean }> }).group_meta ?? {});
      setLocalName(mapData.name);
      setLocalDescription(mapData.description ?? '');
      initializedRef.current = true;
    }
  }, [mapData]);

  // Cleanup freshLayerId timeout on unmount (T-1042-04-03 mitigation)
  useEffect(() => () => {
    if (freshLayerTimeoutRef.current) clearTimeout(freshLayerTimeoutRef.current);
  }, []);

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
  // React.memo() on StackRow actually prevents re-renders on unrelated state
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

  const handleToggleGroupExpand = useCallback((groupId: string) => {
    if (!groupId) return;
    setGroupMeta((prev) => ({
      ...prev,
      [groupId]: { expanded: !(prev[groupId]?.expanded ?? false) },
    }));
    // Not marking dirty — group_meta is not in MapUpdateRequest and is never persisted.
    // Add setHasUnsavedChanges(true) here once group_meta is added to the backend schema.
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

    // BUG-02 (Phase 1051-02): optimistic state update + rollback on error,
    // mirroring handleBulkDelete (lines 580-661). Without this, the user
    // clicks delete and nothing visibly happens — the API mutation fires
    // and onSuccess invalidates the map query, but the resync useEffect at
    // line 181-186 is gated by `!hasUnsavedChanges`, which is usually false
    // during the builder editing flow. The sidebar row then stays visible
    // until a full page reload.
    const previousLayers = layersRef.current;
    setLocalLayers((prev) =>
      prev
        .filter((l) => l.id !== layerId)
        .map((l, i) => ({ ...l, sort_order: i })),
    );

    // WR-01 (Phase 1050-rev): imperatively clean per-layer companions
    // BEFORE the mutation so the visual artifacts (outline/label/extrusion/
    // arrow/cluster glyphs) disappear in lockstep with the user action.
    // Deduped sources are left in place for the next syncFromState to prune
    // via the reference-count-aware desired-set logic.
    removePerLayerCompanions(mapInstanceRef.current, [layerId]);
    removeLayerMutation.mutate(
      { mapId, layerId },
      {
        onSuccess: () => {
          // Sync baseline so a subsequent React-Query refetch is not blocked
          // by a stale savedLayerBaselineRef (CR-01 from handleBulkDelete).
          savedLayerBaselineRef.current = savedLayerBaselineRef.current.filter(
            (l) => l.id !== layerId,
          );
          toast.success(t('toasts.layerRemoved'));
        },
        onError: () => {
          // Rollback: restore the prior localLayers snapshot so the user
          // sees the layer reappear in the sidebar.
          setLocalLayers(previousLayers);
          toast.error(t('toasts.layerRemoveFailed'));
        },
      },
    );
  }, [mapId, mapInstanceRef, removeLayerMutation, t]);

  // --- Folder-group handlers ---
  // These operate on the in-memory localLayers array. Group layers are encoded
  // as layers with layer_type: 'group:folder' or 'group:basemap'. Child layers
  // reference their parent via parent_group_id (frontend-only field, not persisted to API).

  const handleCreateGroupWithLayer = useCallback((layerId: string) => {
    // Generate id OUTSIDE the updater so both setters share the same value.
    const groupId = `group-${Date.now()}`;

    setLocalLayers((prev) => {
      const idx = prev.findIndex((l) => l.id === layerId);
      if (idx < 0) return prev;

      // Generate a unique group name
      const existingGroupCount = prev.filter((l) =>
        (l as GroupedLayer).layer_type === 'group:folder',
      ).length;
      const groupName = `Group ${existingGroupCount + 1}`;

      const groupRow: GroupedLayer = {
        ...(prev[idx] as GroupedLayer),
        id: groupId,
        display_name: groupName,
        layer_type: 'group:folder',
        sort_order: prev[idx].sort_order,
        parent_group_id: null,
      };

      const childLayer: GroupedLayer = {
        ...(prev[idx] as GroupedLayer),
        parent_group_id: groupId,
      };

      const next = [...prev];
      next.splice(idx, 1, groupRow as unknown as MapLayerResponse, childLayer as unknown as MapLayerResponse);
      return next.map((l, i) => ({ ...l, sort_order: i }));
    });
    // groupId is now in scope — auto-expand so the child layer is visible immediately.
    setGroupMeta((prev) => ({ ...prev, [groupId]: { expanded: true } }));
    setHasUnsavedChanges(true);
  }, []);

  const handleRenameGroup = useCallback((groupId: string, name: string) => {
    const trimmed = name.trim();
    if (!trimmed) return; // silent revert per UI-SPEC
    setLocalLayers((prev) =>
      prev.map((l) =>
        l.id === groupId ? { ...l, display_name: trimmed } : l,
      ),
    );
    setHasUnsavedChanges(true);
  }, []);

  const handleUngroup = useCallback((groupId: string) => {
    setLocalLayers((prev) => {
      // Remove the group container, keep children (clear their parent_group_id)
      const next = prev
        .filter((l) => l.id !== groupId)
        .map((l) => {
          const gl = l as GroupedLayer;
          if (gl.parent_group_id === groupId) {
            return { ...gl, parent_group_id: null } as MapLayerResponse;
          }
          return l;
        });
      return next.map((l, i) => ({ ...l, sort_order: i }));
    });
    setHasUnsavedChanges(true);
  }, []);

  const handleDeleteGroup = useCallback((groupId: string) => {
    setLocalLayers((prev) => {
      const next = prev.filter((l) => {
        if (l.id === groupId) return false;
        const gl = l as GroupedLayer;
        if (gl.parent_group_id === groupId) return false;
        return true;
      });
      return next.map((l, i) => ({ ...l, sort_order: i }));
    });
    setHasUnsavedChanges(true);
  }, []);

  // --- Bulk operation handlers ---
  // Visibility, opacity, group, and ungroup are PURE LOCAL STATE MUTATIONS
  // (single setLocalLayers call each, persisted via the existing Save gate).
  // Only handleBulkDelete calls the per-layer DELETE endpoint.

  const handleBulkVisibility = useCallback((selectedIds: Set<string>) => {
    const current = layersRef.current;
    const selectedLayers = current.filter((l) => selectedIds.has(l.id));
    if (selectedLayers.length === 0) return;

    const visibleCount = selectedLayers.filter((l) => l.visible !== false).length;
    const majorityVisible = visibleCount > selectedLayers.length / 2;
    const nextVisible = !majorityVisible;

    // Single setState call for the entire batch
    setLocalLayers((prev) =>
      prev.map((l) => (selectedIds.has(l.id) ? { ...l, visible: nextVisible } : l)),
    );
    setHasUnsavedChanges(true);

    // Live-map sync: mirror the setLayoutProperty calls from handleToggleVisibility
    // for each selected layer without firing N separate React re-renders.
    const map = mapInstanceRef.current;
    if (map && map.isStyleLoaded()) {
      const newVis = nextVisible ? 'visible' : 'none';
      for (const l of selectedLayers) {
        const id = l.id;
        const ids = [
          `layer-${id}`,
          `layer-${id}-outline`,
          `layer-${id}-label`,
          `layer-${id}-extrusion`,
          `layer-${id}-cluster`,
          `layer-${id}-cluster-count`,
        ];
        for (const subId of ids) {
          if (map.getLayer(subId)) map.setLayoutProperty(subId, 'visibility', newVis);
        }
      }
    }
  }, [mapInstanceRef]);

  const handleBulkOpacity = useCallback((selectedIds: Set<string>, opacity: number) => {
    const current = layersRef.current;
    const selectedLayers = current.filter((l) => selectedIds.has(l.id));
    if (selectedLayers.length === 0) return;

    // Single setState call for the entire batch
    setLocalLayers((prev) =>
      prev.map((l) => (selectedIds.has(l.id) ? { ...l, opacity } : l)),
    );
    setHasUnsavedChanges(true);

    // Live-map sync: set opacity paint properties on each selected layer
    const map = mapInstanceRef.current;
    if (map && map.isStyleLoaded()) {
      for (const l of selectedLayers) {
        const id = l.id;
        const mapLayerId = `layer-${id}`;
        const outlineId = `layer-${id}-outline`;
        if (l.layer_type === 'raster_geolens') {
          if (map.getLayer(mapLayerId)) {
            map.setPaintProperty(mapLayerId, 'raster-opacity', opacity);
          }
        } else if (l.style_config?.render_mode === 'heatmap') {
          if (map.getLayer(mapLayerId)) {
            const storedHeatmapOpacity = (l.paint?.['heatmap-opacity'] as number) ?? 0.8;
            map.setPaintProperty(mapLayerId, 'heatmap-opacity', opacity * storedHeatmapOpacity);
          }
        } else {
          // fill, line, circle — use adapter type derived from geometry type
          const geomType = l.dataset_geometry_type;
          const adapterType =
            geomType === 'Polygon' || geomType === 'MultiPolygon' ? 'fill'
            : geomType === 'LineString' || geomType === 'MultiLineString' ? 'line'
            : 'circle';
          if (map.getLayer(mapLayerId)) {
            map.setPaintProperty(mapLayerId, `${adapterType}-opacity`, opacity);
          }
          if (adapterType === 'fill' && map.getLayer(outlineId)) {
            map.setPaintProperty(outlineId, 'line-opacity', opacity);
          }
        }
      }
    }
  }, [mapInstanceRef]);

  const handleBulkGroup = useCallback((selectedIds: Set<string>) => {
    const current = layersRef.current;
    // Defense-in-depth: all selected must be loose vector layers
    const selectedLayers = current.filter((l) =>
      selectedIds.has(l.id) &&
      l.dataset_record_type === 'vector_dataset' &&
      !(l as GroupedLayer).parent_group_id &&
      (l as GroupedLayer).layer_type !== 'group:folder',
    );
    if (selectedLayers.length !== selectedIds.size || selectedLayers.length < 2) return;

    const groupId = `group-${Date.now()}`;
    const existingGroupCount = current.filter(
      (l) => (l as GroupedLayer).layer_type === 'group:folder',
    ).length;
    const groupName = `Group ${existingGroupCount + 1}`;
    const minSortOrder = Math.min(...selectedLayers.map((l) => l.sort_order));

    const groupRow: GroupedLayer = {
      ...(selectedLayers[0] as GroupedLayer),
      id: groupId,
      display_name: groupName,
      layer_type: 'group:folder',
      sort_order: minSortOrder,
      parent_group_id: null,
    };

    setLocalLayers((prev) => {
      const next = prev.map((l) =>
        selectedIds.has(l.id)
          ? ({ ...l, parent_group_id: groupId } as unknown as MapLayerResponse)
          : l,
      );
      // Insert group row at position of first selected layer (smallest sort_order)
      const insertIdx = next.findIndex((l) => selectedIds.has(l.id));
      if (insertIdx >= 0) {
        next.splice(insertIdx, 0, groupRow as unknown as MapLayerResponse);
      } else {
        next.push(groupRow as unknown as MapLayerResponse);
      }
      return next.map((l, i) => ({ ...l, sort_order: i }));
    });
    setGroupMeta((prev) => ({ ...prev, [groupId]: { expanded: true } }));
    setHasUnsavedChanges(true);
  }, []);

  const handleBulkUngroup = useCallback((selectedIds: Set<string>) => {
    const current = layersRef.current;
    // Defense-in-depth: all selected must be folder-group rows
    const selectedGroups = current.filter(
      (l) => selectedIds.has(l.id) && (l as GroupedLayer).layer_type === 'group:folder',
    );
    if (selectedGroups.length !== selectedIds.size || selectedGroups.length === 0) return;

    setLocalLayers((prev) => {
      const next = prev
        .filter((l) => !selectedIds.has(l.id)) // remove group container rows
        .map((l) => {
          const gl = l as GroupedLayer;
          if (gl.parent_group_id && selectedIds.has(gl.parent_group_id)) {
            return { ...gl, parent_group_id: null } as MapLayerResponse;
          }
          return l;
        });
      return next.map((l, i) => ({ ...l, sort_order: i }));
    });
    setHasUnsavedChanges(true);
  }, []);

  const handleBulkDelete = useCallback(async (selectedIds: Set<string>): Promise<boolean> => {
    if (!mapId || selectedIds.size === 0) return false;

    const previousLayers = layersRef.current;
    // Filter out frontend-only group container rows — they have no backend record
    // and would produce a not_found error in the bulk-delete endpoint.
    const idsToDelete = Array.from(selectedIds).filter((id) => {
      const layer = previousLayers.find((l) => l.id === id);
      if (!layer) return false;
      if ((layer as GroupedLayer).layer_type === 'group:folder') return false;
      return true;
    });
    if (idsToDelete.length === 0) return false;

    // Clear expanded layer if it's being deleted
    setExpandedLayerId((prev) => (prev && selectedIds.has(prev) ? null : prev));

    // Optimistic update — remove only layers actually sent to the backend (idsToDelete),
    // not the full selectedIds which may include frontend-only group folder rows (WR-04).
    const idsToDeleteSet = new Set(idsToDelete);
    setLocalLayers((prev) =>
      prev
        .filter((l) => !idsToDeleteSet.has(l.id))
        .map((l, i) => ({ ...l, sort_order: i })),
    );

    // WR-01 (Phase 1050-rev): imperatively clean per-layer companions for
    // every id in the batch so visual artifacts vanish in lockstep with the
    // optimistic state update. removeStaleSourcesAndLayers cannot derive
    // these ids under the SF-04 dedupe contract — the stripped source id
    // produces `data-${dataset_table_name}`, not the real per-layer id.
    removePerLayerCompanions(mapInstanceRef.current, idsToDelete);

    // Phase 1047-04 (PERF-03): one batched call replaces N sequential DELETEs
    setIsDeleting(true);
    try {
      const result = await bulkDeleteLayersApi(mapId, idsToDelete);

      if (result.failed.length === 0) {
        // Full success — sync baseline immediately so the subsequent invalidateQueries
        // refetch is not blocked by a stale savedLayerBaselineRef (CR-01).
        savedLayerBaselineRef.current = savedLayerBaselineRef.current.filter(
          (l) => !idsToDeleteSet.has(l.id),
        );
        await queryClient.invalidateQueries({ queryKey: ['map', mapId] });
        toast.success(t('bulkActions.deleteSuccess', { count: idsToDelete.length }));
        return true;
      }

      if (result.deleted.length === 0) {
        // Full failure — rollback all layers
        setLocalLayers(previousLayers);
        toast.error(t('bulkActions.deleteRollback'));
        return false;
      }

      // Partial failure: keep deleted layers removed, restore failed layers
      const failedIds = new Set(result.failed.map((f) => f.id));
      setLocalLayers((current) => {
        // Re-insert failed layers from previousLayers at their original sort_order positions
        const failedLayers = previousLayers.filter((l) => failedIds.has(l.id));
        const merged = [...current, ...failedLayers];
        // Re-sort by original sort_order so failed layers slot back in naturally
        merged.sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
        return merged.map((l, i) => ({ ...l, sort_order: i }));
      });
      // Partial state differs from server — prevent silent refetch wipe (CR-01)
      setHasUnsavedChanges(true);
      toast.error(
        t('bulkActions.deletePartialFailure', {
          deleted: result.deleted.length,
          count: idsToDelete.length,
          failed: result.failed.length,
        }),
        {
          action: {
            label: t('bulkActions.retryAction'),
            onClick: () => handleBulkDelete(new Set(result.failed.map((f) => f.id))),
          },
        },
      );
      return false;
    } finally {
      setIsDeleting(false);
    }
  }, [mapId, mapInstanceRef, t, queryClient]);

  const handleAddLayerToExistingGroup = useCallback((layerId: string, groupId: string) => {
    setLocalLayers((prev) => {
      const targetIdx = prev.findIndex((l) => l.id === layerId);
      if (targetIdx < 0) return prev;
      const updatedLayer: GroupedLayer = { ...(prev[targetIdx] as GroupedLayer), parent_group_id: groupId };
      const next = [...prev];
      next[targetIdx] = updatedLayer as MapLayerResponse;
      return next;
    });
    setGroupMeta((prev) => {
      if (prev[groupId]?.expanded) return prev;
      return { ...prev, [groupId]: { expanded: true } };
    });
    setHasUnsavedChanges(true);
  }, []);

  const handleMoveLayerOutOfGroup = useCallback((layerId: string) => {
    setLocalLayers((prev) => {
      const idx = prev.findIndex((l) => l.id === layerId);
      if (idx < 0) return prev;
      const gl = prev[idx] as GroupedLayer;
      const parentGroupId = gl.parent_group_id;
      if (!parentGroupId) return prev; // already not in a group

      // Find the position of the group container to place the layer just after it
      const groupIdx = prev.findIndex((l) => l.id === parentGroupId);
      const updatedLayer: GroupedLayer = { ...gl, parent_group_id: null };

      const next = prev.filter((l) => l.id !== layerId) as MapLayerResponse[];
      const insertAt = groupIdx >= 0 ? groupIdx + 1 : next.length;
      next.splice(insertAt, 0, updatedLayer as MapLayerResponse);
      return next.map((l, i) => ({ ...l, sort_order: i }));
    });
    setHasUnsavedChanges(true);
  }, []);

  const handleAddDataset = useCallback(
    (
      datasetId: string,
      onSuccessCb?: (newLayerId: string) => void,
      parentGroupId?: string | null,
      datasetName?: string,
    ) => {
      if (!mapId) return;
      // Per BSR-18 UI-SPEC §4b: new layers PREPEND at top of user stack (sort_order: 0).
      // The mutation onSuccess refresh (via React Query invalidation elsewhere) will
      // renumber existing layers as needed. Do NOT use layersRef.current.length here
      // (append) — that buries the new layer under existing ones and conflicts with
      // the auto-open flyout UX.
      addLayerMutation.mutate(
        { mapId, data: { dataset_id: datasetId, sort_order: 0 } },
        {
          onSuccess: (createdLayer) => {
            // CR-02: when dropping onto a folder group, the new layer is not yet in
            // localLayers at this point — the invalidation refetch is async and the
            // useEffect sync only runs when !hasUnsavedChanges. Optimistically prepend
            // the layer with parent_group_id already set so handleAddLayerToExistingGroup
            // finds it immediately instead of getting targetIdx === -1 and silently no-oping.
            if (parentGroupId && createdLayer?.id) {
              setLocalLayers((prev) => {
                if (prev.some((l) => l.id === createdLayer.id)) return prev;
                const newLayer: GroupedLayer = {
                  ...createdLayer,
                  parent_group_id: parentGroupId,
                };
                return [newLayer as MapLayerResponse, ...prev];
              });
              handleAddLayerToExistingGroup(createdLayer.id, parentGroupId);
            }
            // Phase 1040 POL-05: named toast when datasetName is provided; generic
            // fallback preserves backward-compat for callers that omit the name.
            if (datasetName) {
              toast.success(t('toasts.datasetAdded', { name: datasetName }), {
                id: `add-layer-${datasetId}`,
              });
            } else {
              toast.success(t('toasts.layerAdded'));
            }
            if (onSuccessCb && createdLayer?.id) {
              onSuccessCb(createdLayer.id);
            }
            // Phase 1042 POL-15: entry animation — set freshLayerId for 200ms so
            // StackRow can apply animate-in fade-in. Single-flight: clear any prior
            // timer before scheduling a new one (T-1042-04-03 mitigation).
            if (createdLayer?.id) {
              if (freshLayerTimeoutRef.current) clearTimeout(freshLayerTimeoutRef.current);
              setFreshLayerId(createdLayer.id);
              freshLayerTimeoutRef.current = setTimeout(() => {
                setFreshLayerId(null);
                freshLayerTimeoutRef.current = null;
              }, 200);
            }
          },
          onError: () => {
            toast.error(t('toasts.layerAddFailed'));
          },
        },
      );
    },
    [mapId, addLayerMutation, t, handleAddLayerToExistingGroup],
  );

  // AI-specific remove: removes locally (persisted on Save).
  //
  // Phase 1050 SF-04: per-layer companion layers (label/outline/extrusion/
  // arrow + main layer-{id}) are still cleaned up imperatively because they
  // remain per-layer in the new keying scheme. Source teardown, however, is
  // delegated to the next `syncFromState` invocation's
  // `removeStaleSourcesAndLayers` desired-set prune — which is reference-
  // count-aware via `desiredSources.add(sourceId)` and will correctly leave
  // a deduped `source-data-${dataset_table_name}` in place while sibling
  // layers still reference it.
  const handleAiRemoveLayer = useCallback((layerId: string) => {
    setLocalLayers((prev) => prev.filter((l) => l.id !== layerId));
    // Clean up MapLibre per-layer companions imperatively. WR-01 (Phase
    // 1050-rev) factored this into removePerLayerCompanions so handleRemove
    // and handleBulkDelete now use the same helper. Sources are NOT
    // removed here — the deduped source may still be shared by sibling
    // layers, and the next syncFromState invocation's desired-set prune
    // correctly removes only truly-orphaned sources.
    removePerLayerCompanions(mapInstanceRef.current, [layerId]);
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

  /** Swap the MapLibre layer for a given dataset between adapter types (e.g. circle <-> heatmap).
   *
   *  Phase 1050 SF-04: sourceId now routes through `getSourceIdForLayer` so
   *  non-cluster vector layers correctly inherit the deduped
   *  `source-data-${dataset_table_name}` source's tile URL. Cluster and
   *  raster/hillshade layers keep their per-layer source id via the helper's
   *  branching contract.
   */
  const swapLayerOnMap = useCallback((
    layer: MapLayerResponse,
    adapterType: RenderAsAdapterType,
    updatedPaint: Record<string, unknown>,
  ) => {
    const map = mapInstanceRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const mapLayerId = `layer-${layer.id}`;
    const sourceId = getSourceIdForLayer(layer);
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
  }, [handleRenderAsChange, swapLayerOnMap]);

  const handleDEMTerrainBind = useCallback((layerId: string) => {
    const layer = layersRef.current.find((l) => l.id === layerId);
    if (!layer) return;
    setLocalTerrainConfig((prev) => ({
      enabled: true,
      source_dataset_id: layer.dataset_id,
      exaggeration: prev?.exaggeration ?? 1,
    }));
    setHasUnsavedChanges(true);
  }, []);

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
    freshLayerId,
    savedLayerBaseline: savedLayerBaselineRef.current,
    localBasemap, setLocalBasemap,
    hasUnsavedChanges, setHasUnsavedChanges,
    expandedLayerId,
    activeEditorTab,
    showBasemapLabels, setShowBasemapLabels,
    basemapConfig, setBasemapConfig,
    localTerrainConfig, setLocalTerrainConfig,
    groupMeta,
    ephemeralResult,
    initialViewState,
    handleToggleVisibility,
    handleMoveUp,
    handleMoveDown,
    handleReorder,
    handleDisplayNameChange,
    handleToggleExpand,
    handleToggleGroupExpand,
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
    handleDEMTerrainBind,
    handleCreateGroupWithLayer,
    handleRenameGroup,
    handleUngroup,
    handleDeleteGroup,
    handleAddLayerToExistingGroup,
    handleMoveLayerOutOfGroup,
    handleAddDataset,
    handleDuplicateRendering,
    handleAiRemoveLayer,
    handleQueryResult,
    handleToggleLegend,
    handleDismissEphemeral,
    markDirty,
    chatLayerActions,
    // Bulk operation handlers (Phase 1041 Plan 03)
    handleBulkVisibility,
    handleBulkOpacity,
    handleBulkGroup,
    handleBulkUngroup,
    handleBulkDelete,
    // Phase 1047-04 (PERF-03): in-flight state for BulkActionBar spinner
    isDeleting,
  };
}
