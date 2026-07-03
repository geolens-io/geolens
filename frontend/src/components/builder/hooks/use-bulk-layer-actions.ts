import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerResponse, MapTerrainConfig } from '@/types/api';
import { normalizeTerrainExaggeration } from '@/components/builder/map-sync';
import {
  applyLayerVisibilityToMap,
  applyLayerOpacityToMap,
} from '@/components/builder/hooks/use-layer-map-sync';
import {
  removePerLayerCompanions,
  shouldClearTerrainOnDelete,
} from '@/components/builder/hooks/builder-layer-mutations';
import { type GroupedLayer } from '@/components/builder/folder-groups';
import { bulkDeleteLayersApi } from '@/api/maps';
import {
  extractCopyableStyle,
  isStyleCompatible,
  applyCopiedStyleToLayer,
  type CopiedStyle,
} from '@/lib/builder/layer-style-clipboard';

type SyncStyleConfigToMap = (
  map: MaplibreMap,
  layer: MapLayerResponse,
  paint: Record<string, unknown>,
) => void;

// STATE-02: bulk-operation handlers (apply-style / visibility / opacity / group /
// ungroup / delete), relocated verbatim out of the useBuilderLayers god-hook.
// PURE RELOCATION — handler bodies are unchanged; shared state (layersRef +
// setters + clipboard ref) is threaded in as params. Visibility, opacity, group,
// and ungroup are PURE LOCAL STATE MUTATIONS (single setLocalLayers call each,
// persisted via the existing Save gate). Only handleBulkDelete calls the
// per-layer DELETE endpoint. The hook OWNS the in-flight isDeleting state.
interface UseBulkLayerActionsParams {
  layersRef: React.RefObject<MapLayerResponse[]>;
  setLocalLayers: React.Dispatch<React.SetStateAction<MapLayerResponse[]>>;
  setHasUnsavedChanges: React.Dispatch<React.SetStateAction<boolean>>;
  setExpandedLayerId: React.Dispatch<React.SetStateAction<string | null>>;
  setGroupMeta: React.Dispatch<React.SetStateAction<Record<string, { expanded: boolean }>>>;
  mapInstanceRef: React.RefObject<MaplibreMap | null>;
  mapId: string | undefined;
  localTerrainConfig: MapTerrainConfig | null;
  setLocalTerrainConfig: React.Dispatch<React.SetStateAction<MapTerrainConfig | null>>;
  savedLayerBaselineRef: React.MutableRefObject<MapLayerResponse[]>;
  copiedStyleRef: React.RefObject<CopiedStyle | null>;
  syncStyleConfigToMap: SyncStyleConfigToMap;
}

export function useBulkLayerActions({
  layersRef,
  setLocalLayers,
  setHasUnsavedChanges,
  setExpandedLayerId,
  setGroupMeta,
  mapInstanceRef,
  mapId,
  localTerrainConfig,
  setLocalTerrainConfig,
  savedLayerBaselineRef,
  copiedStyleRef,
  syncStyleConfigToMap,
}: UseBulkLayerActionsParams) {
  const { t } = useTranslation('builder');
  const queryClient = useQueryClient();

  // Phase 1047-04 (PERF-03): tracks in-flight bulk-delete to gate BulkActionBar spinner
  const [isDeleting, setIsDeleting] = useState(false);

  // ENH-03 (Phase 1201-01): apply one source style to every OTHER compatible
  // selected layer in a SINGLE setLocalLayers pass (no per-field clobber).
  // Source = the copied style if present, else the lowest-sort_order selected
  // layer. Incompatible-geometry targets are skipped and surfaced via a count
  // toast. No-ops when fewer than 2 compatible targets would be written.
  const handleBulkApplyStyle = useCallback((selectedIds: Set<string>) => {
    const current = layersRef.current;
    const selected = current
      .filter((l) => selectedIds.has(l.id))
      .sort((a, b) => a.sort_order - b.sort_order);
    if (selected.length === 0) return;

    const copied = copiedStyleRef.current;
    // Determine the source style + which selected layer (if any) authored it so
    // we never re-apply a layer's own style onto itself.
    let source: CopiedStyle;
    let sourceLayerId: string | null;
    if (copied) {
      source = copied;
      sourceLayerId = null; // copied style may originate from a non-selected layer
    } else {
      const first = selected[0];
      source = extractCopyableStyle(first);
      sourceLayerId = first.id;
    }

    const targets = selected.filter(
      (l) => l.id !== sourceLayerId && isStyleCompatible(source, l),
    );
    if (targets.length === 0) return;

    const targetIds = new Set(targets.map((l) => l.id));
    // Count selected layers that were skipped for geometry incompatibility
    // (exclude the source layer itself from the skip count).
    const skipped = selected.filter(
      (l) => l.id !== sourceLayerId && !targetIds.has(l.id),
    ).length;

    // Single atomic write — replace every compatible target in one pass
    // (the multi-field clobber rule: never field-by-field per layer).
    setLocalLayers((prev) =>
      prev.map((l) => (targetIds.has(l.id) ? applyCopiedStyleToLayer(l, source) : l)),
    );
    setHasUnsavedChanges(true);

    // Live-map sync: repaint each target via the map-ONLY adapter sync (it does
    // NOT re-write React state — the single setLocalLayers above owns state).
    // Gated internally on map.isStyleLoaded().
    const map = mapInstanceRef.current;
    if (map && map.isStyleLoaded()) {
      for (const target of targets) {
        const merged = applyCopiedStyleToLayer(target, source);
        syncStyleConfigToMap(map, merged, merged.paint);
      }
    }

    toast.success(t('toasts.bulkStyleApplied', { count: targets.length }));
    if (skipped > 0) {
      toast.info(t('toasts.bulkStyleSkipped', { count: skipped }));
    }
  }, [layersRef, copiedStyleRef, setLocalLayers, setHasUnsavedChanges, mapInstanceRef, syncStyleConfigToMap, t]);

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

    // STATE-01: delegate the per-layer live-map sync to the SAME shared
    // side-effect handleToggleVisibility uses, so the strokeDisabled gate and
    // the full companion set (colorrelief + cluster) cannot diverge between the
    // single and bulk paths. Still a single setLocalLayers write above — only
    // the N map repaints are delegated.
    const map = mapInstanceRef.current;
    if (map && map.isStyleLoaded()) {
      for (const l of selectedLayers) {
        applyLayerVisibilityToMap(map, l, nextVisible);
      }
    }
  }, [layersRef, setLocalLayers, setHasUnsavedChanges, mapInstanceRef]);

  const handleBulkOpacity = useCallback((selectedIds: Set<string>, opacity: number) => {
    const current = layersRef.current;
    const selectedLayers = current.filter((l) => selectedIds.has(l.id));
    if (selectedLayers.length === 0) return;

    // Single setState call for the entire batch
    setLocalLayers((prev) =>
      prev.map((l) => (selectedIds.has(l.id) ? { ...l, opacity } : l)),
    );
    setHasUnsavedChanges(true);

    // STATE-03: delegate the per-layer live-map sync to the SAME shared
    // side-effect handleOpacityChange uses, so getCompoundOpacity wrapping and
    // the dedicated cluster branch cannot diverge between single and bulk. The
    // single setLocalLayers write above owns React state; this only repaints.
    const map = mapInstanceRef.current;
    if (map && map.isStyleLoaded()) {
      for (const l of selectedLayers) {
        applyLayerOpacityToMap(map, l, opacity);
      }
    }
  }, [layersRef, setLocalLayers, setHasUnsavedChanges, mapInstanceRef]);

  // B-004d / LM-04: returns true only when a group was actually created, so the
  // caller (MapBuilderPage) can clear the multi-selection ONLY on success — a
  // no-op must never silently eat the user's selection.
  const handleBulkGroup = useCallback((selectedIds: Set<string>): boolean => {
    const current = layersRef.current;
    const selectedLayers = current.filter((l) => selectedIds.has(l.id));
    // Defense-in-depth: all selected must be loose vector layers (not already
    // grouped, not group rows themselves, not raster/DEM/basemap).
    const groupableLayers = selectedLayers.filter((l) =>
      l.dataset_record_type === 'vector_dataset' &&
      !(l as GroupedLayer).parent_group_id &&
      (l as GroupedLayer).layer_type !== 'group:folder',
    );

    // fix(#1280): B-004d / LM-04 — surface WHY the group action no-op'd instead
    // of returning silently while the caller clears the selection anyway.
    if (groupableLayers.length !== selectedLayers.length) {
      // fix(#1280 WR-01): the toast previously always said "already grouped,"
      // which is wrong when the real disqualifier is a raster/DEM layer or a
      // group row in the selection. Pick the message that matches the actual
      // reason. Priority: a group row in the selection is the most distinct
      // mistake, then an ineligible (non-vector) layer type, and only then
      // fall back to the "already grouped" message.
      const hasGroupRow = selectedLayers.some(
        (l) => (l as GroupedLayer).layer_type === 'group:folder',
      );
      const hasIneligibleType = selectedLayers.some(
        (l) => l.dataset_record_type !== 'vector_dataset',
      );
      if (hasGroupRow) {
        toast.info(t('toasts.bulkGroupSkippedGroupRow'));
      } else if (hasIneligibleType) {
        toast.info(t('toasts.bulkGroupSkippedType'));
      } else {
        toast.info(t('toasts.bulkGroupSkipped'));
      }
      return false;
    }
    if (groupableLayers.length < 2) {
      toast.info(t('toasts.bulkGroupNeedTwo'));
      return false;
    }

    // Phase 1051 WR-01: crypto.randomUUID is collision-safe — see
    // handleCreateGroupWithLayer for the bulk + single race rationale.
    const groupId = `group-${crypto.randomUUID()}`;
    const existingGroupCount = current.filter(
      (l) => (l as GroupedLayer).layer_type === 'group:folder',
    ).length;
    const groupName = `Group ${existingGroupCount + 1}`;
    const minSortOrder = Math.min(...groupableLayers.map((l) => l.sort_order));

    const groupRow: GroupedLayer = {
      ...(groupableLayers[0] as GroupedLayer),
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
    return true;
  }, [layersRef, setLocalLayers, setGroupMeta, setHasUnsavedChanges, t]);

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
  }, [layersRef, setLocalLayers, setHasUnsavedChanges]);

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

    // Phase 999.17 Fix 2 (D-05/A2): if the batch removes the last DEM layer
    // backing active 3D terrain, auto-clear terrain_config + non-blocking toast.
    // Keyed on dataset identity so unrelated DEM/vector deletes leave it intact.
    // HI-01 (999.17 gap-closure): snapshot the prior terrain_config so any
    // failure/rollback branch below can restore it. Without this, a failed bulk
    // delete leaves the DEM layer restored but 3D terrain silently disabled.
    const previousTerrainConfig = localTerrainConfig;
    const remainingAfterBulk = previousLayers.filter((l) => !idsToDeleteSet.has(l.id));
    const clearedTerrainOnBulk = shouldClearTerrainOnDelete(remainingAfterBulk, localTerrainConfig);
    if (clearedTerrainOnBulk) {
      setLocalTerrainConfig((prev) => ({
        enabled: false,
        source_dataset_id: null,
        exaggeration: normalizeTerrainExaggeration(prev?.exaggeration),
      }));
      setHasUnsavedChanges(true);
      toast.success(t('toasts.terrainDisabledSourceRemoved'));
    }

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
        // HI-01: nothing was actually deleted, so restore terrain_config too.
        if (clearedTerrainOnBulk) {
          setLocalTerrainConfig(previousTerrainConfig);
        }
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
      // HI-01: the optimistic terrain clear assumed the WHOLE batch was deleted.
      // Re-evaluate against the layers that ACTUALLY remain after restoring the
      // failed ones; if terrain is still backed (its source DEM was among the
      // failures), restore terrain_config so it is not silently disabled.
      if (clearedTerrainOnBulk) {
        const deletedIds = new Set(result.deleted);
        const remainingAfterPartial = previousLayers.filter((l) => !deletedIds.has(l.id));
        if (!shouldClearTerrainOnDelete(remainingAfterPartial, previousTerrainConfig)) {
          setLocalTerrainConfig(previousTerrainConfig);
        }
      }
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
  }, [
    mapId,
    layersRef,
    setExpandedLayerId,
    setLocalLayers,
    localTerrainConfig,
    setLocalTerrainConfig,
    setHasUnsavedChanges,
    mapInstanceRef,
    savedLayerBaselineRef,
    t,
    queryClient,
  ]);

  return {
    handleBulkApplyStyle,
    handleBulkVisibility,
    handleBulkOpacity,
    handleBulkGroup,
    handleBulkUngroup,
    handleBulkDelete,
    isDeleting,
  };
}
