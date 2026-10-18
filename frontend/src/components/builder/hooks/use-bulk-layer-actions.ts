import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { MapLayerResponse, MapTerrainConfig } from '@/types/api';
import { normalizeTerrainExaggeration } from '@/components/builder/map-sync';
import {
  resolveFillExclusions,
  stashExcludedFillColor,
  writeBuilderLayer,
} from '@/components/builder/hooks/use-layer-map-sync';
import {
  removePerLayerCompanions,
  shouldClearTerrainOnDelete,
} from '@/components/builder/hooks/builder-layer-mutations';
import type { SaveBaselineSync } from '@/components/builder/hooks/use-builder-save';
import {
  type GroupedLayer,
  clearPersistedFolderGroup,
  pruneEmptyFolderGroups,
} from '@/components/builder/folder-groups';
import { reconcileColorClassification } from '@/lib/color-ramps';
import { bulkDeleteLayersApi } from '@/api/maps';
import {
  extractCopyableStyle,
  isStyleCompatible,
  applyCopiedStyleToLayer,
  type CopiedStyle,
} from '@/lib/builder/layer-style-clipboard';
import { randomId } from '@/lib/random-id';

/**
 * Bulk apply-style under the fill exclusions, since bulk apply reaches neither
 * `handleStyleConfigChange` nor `handlePasteStyle`. It also stashes the
 * displaced colour and drops a classification the resolved paint no longer backs.
 */
function applyStyleExcludingFillCollisions(
  layer: MapLayerResponse,
  source: CopiedStyle,
): MapLayerResponse {
  const merged = applyCopiedStyleToLayer(layer, source);
  // The target's paint is the provenance baseline: whichever fill key the merge
  // just introduced is the one the copied style asserted.
  const exclusions = resolveFillExclusions(
    merged.style_config ?? null,
    merged.paint ?? {},
    layer.paint ?? {},
  );
  return {
    ...merged,
    paint: exclusions.paint,
    style_config: reconcileColorClassification(
      stashExcludedFillColor(merged.style_config ?? null, exclusions),
      exclusions.paint,
      merged.dataset_geometry_type,
    ),
  };
}

// Bulk-operation handlers (apply-style / visibility / opacity / group /
// ungroup / delete). Shared state (layersRef, setters, clipboard ref) is
// threaded in as params. Visibility, opacity, group and ungroup are pure local
// state mutations (one setLocalLayers call each, persisted via the Save gate);
// only handleBulkDelete calls the per-layer DELETE endpoint. The hook owns the
// in-flight isDeleting state.
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
  /** The save-diff baseline bridge; its `remove` half is called alongside the
   *  savedLayerBaselineRef prune below. */
  saveBaselineSyncRef: React.MutableRefObject<SaveBaselineSync>;
  copiedStyleRef: React.RefObject<CopiedStyle | null>;
}

// Failure-path restore that doesn't clobber concurrent edits. Restoring the
// pre-delete snapshot wholesale would discard anything that landed during the
// await (e.g. a handleAddDataset onSuccess), and the next save's removed
// computation would ask the server to DELETE the just-added layer. Instead,
// recompute from current state: re-insert only the rows whose deletes failed
// (at their old relative positions when cheap), plus any pruned group container
// a failed child still points at, and leave every other row untouched.
export function restoreFailedLayers(
  current: MapLayerResponse[],
  previous: MapLayerResponse[],
  failedIds: Set<string>,
): MapLayerResponse[] {
  const currentIds = new Set(current.map((l) => l.id));
  const toRestore = previous.filter((l) => {
    if (currentIds.has(l.id)) return false;
    if (failedIds.has(l.id)) return true;
    // Restore a pruned empty-group container whose failed child is returning.
    return (
      (l as GroupedLayer).layer_type === 'group:folder' &&
      previous.some(
        (child) =>
          failedIds.has(child.id) &&
          !currentIds.has(child.id) &&
          (child as GroupedLayer).parent_group_id === l.id,
      )
    );
  });
  if (toRestore.length === 0) return current;

  const prevIndex = new Map(previous.map((l, i) => [l.id, i] as const));
  const next = [...current];
  // Insert in previous-order so earlier restores anchor later ones.
  toRestore.sort((a, b) => (prevIndex.get(a.id) ?? 0) - (prevIndex.get(b.id) ?? 0));
  for (const row of toRestore) {
    const rowPrevIdx = prevIndex.get(row.id) ?? Number.MAX_SAFE_INTEGER;
    // Old position ≈ before the first current row that followed it in the
    // previous order. Rows unknown to `previous` (concurrent additions) have no
    // index and never force a displacement.
    let insertAt = next.length;
    for (let i = 0; i < next.length; i++) {
      const idx = prevIndex.get(next[i].id);
      if (idx !== undefined && idx > rowPrevIdx) {
        insertAt = i;
        break;
      }
    }
    next.splice(insertAt, 0, row);
  }
  return next.map((l, i) => ({ ...l, sort_order: i }));
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
  saveBaselineSyncRef,
  copiedStyleRef,
}: UseBulkLayerActionsParams) {
  const { t } = useTranslation('builder');
  const queryClient = useQueryClient();

  // Tracks in-flight bulk-delete to gate BulkActionBar spinner
  const [isDeleting, setIsDeleting] = useState(false);
  // Batch size captured synchronously in handleBulkDelete before the optimistic
  // removal commits: afterwards the bar's selection-derived deletableCount is
  // 0, so the deleting state must render this count.
  const [deletingCount, setDeletingCount] = useState(0);

  // Apply one source style to every other compatible selected layer in a single
  // setLocalLayers pass. Source = the copied style if present, else the
  // lowest-sort_order selected layer. Incompatible-geometry targets are skipped
  // and surfaced via a count toast. No-ops when fewer than 2 compatible targets
  // would be written.
  const handleBulkApplyStyle = useCallback((selectedIds: Set<string>) => {
    const current = layersRef.current;
    const selected = current
      .filter((l) => selectedIds.has(l.id))
      .sort((a, b) => a.sort_order - b.sort_order);
    if (selected.length === 0) return;

    const copied = copiedStyleRef.current;
    // The source style, and which selected layer (if any) authored it, so a
    // layer's own style is never re-applied onto itself.
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
    // Count selected layers skipped for geometry incompatibility (excluding the
    // source layer).
    const skipped = selected.filter(
      (l) => l.id !== sourceLayerId && !targetIds.has(l.id),
    ).length;

    // One atomic write for every compatible target (never field-by-field).
    setLocalLayers((prev) =>
      prev.map((l) => (targetIds.has(l.id) ? applyStyleExcludingFillCollisions(l, source) : l)),
    );
    setHasUnsavedChanges(true);

    const map = mapInstanceRef.current;
    if (map && map.isStyleLoaded()) {
      for (const target of targets) writeBuilderLayer(map, applyStyleExcludingFillCollisions(target, source));
    }

    toast.success(t('toasts.bulkStyleApplied', { count: targets.length }));
    if (skipped > 0) {
      toast.info(t('toasts.bulkStyleSkipped', { count: skipped }));
    }
  }, [layersRef, copiedStyleRef, setLocalLayers, setHasUnsavedChanges, mapInstanceRef, t]);

  const handleBulkVisibility = useCallback((selectedIds: Set<string>) => {
    const current = layersRef.current;
    const selectedLayers = current.filter((l) => selectedIds.has(l.id));
    if (selectedLayers.length === 0) return;

    const visibleCount = selectedLayers.filter((l) => l.visible !== false).length;
    const majorityVisible = visibleCount > selectedLayers.length / 2;
    const nextVisible = !majorityVisible;

    // One setState call for the entire batch
    setLocalLayers((prev) =>
      prev.map((l) => (selectedIds.has(l.id) ? { ...l, visible: nextVisible } : l)),
    );
    setHasUnsavedChanges(true);

    const map = mapInstanceRef.current;
    if (map && map.isStyleLoaded()) {
      for (const l of selectedLayers) writeBuilderLayer(map, { ...l, visible: nextVisible });
    }
  }, [layersRef, setLocalLayers, setHasUnsavedChanges, mapInstanceRef]);

  const handleBulkOpacity = useCallback((selectedIds: Set<string>, opacity: number) => {
    const current = layersRef.current;
    const selectedLayers = current.filter((l) => selectedIds.has(l.id));
    if (selectedLayers.length === 0) return;

    // One setState call for the entire batch
    setLocalLayers((prev) =>
      prev.map((l) => (selectedIds.has(l.id) ? { ...l, opacity } : l)),
    );
    setHasUnsavedChanges(true);

    const map = mapInstanceRef.current;
    if (map && map.isStyleLoaded()) {
      for (const l of selectedLayers) writeBuilderLayer(map, { ...l, opacity });
    }
  }, [layersRef, setLocalLayers, setHasUnsavedChanges, mapInstanceRef]);

  // Returns true only when a group was created, so the caller can clear the
  // multi-selection only on success; a no-op must not eat the selection.
  const handleBulkGroup = useCallback((selectedIds: Set<string>): boolean => {
    const current = layersRef.current;
    const selectedLayers = current.filter((l) => selectedIds.has(l.id));
    // Defense-in-depth: all selected must be loose layers (not grouped, not
    // group rows). Not restricted to vector_dataset, which would disagree with
    // StackRow's "Add to group…" and drag-and-drop, both of which accept
    // raster/DEM rows.
    const groupableLayers = selectedLayers.filter((l) =>
      !(l as GroupedLayer).parent_group_id &&
      (l as GroupedLayer).layer_type !== 'group:folder',
    );

    // Surface why the group action no-op'd rather than returning silently while
    // the caller clears the selection anyway.
    if (groupableLayers.length !== selectedLayers.length) {
      // Match the actual reason: a group row in the selection is the most
      // distinct mistake, otherwise "already grouped".
      const hasGroupRow = selectedLayers.some(
        (l) => (l as GroupedLayer).layer_type === 'group:folder',
      );
      if (hasGroupRow) {
        toast.info(t('toasts.bulkGroupSkippedGroupRow'));
      } else {
        toast.info(t('toasts.bulkGroupSkipped'));
      }
      return false;
    }
    if (groupableLayers.length < 2) {
      toast.info(t('toasts.bulkGroupNeedTwo'));
      return false;
    }

    // randomId() is collision-safe; see handleCreateGroupWithLayer for the bulk
    // + single race rationale.
    const groupId = `group-${randomId()}`;
    const existingGroupCount = current.filter(
      (l) => (l as GroupedLayer).layer_type === 'group:folder',
    ).length;
    const groupName = t('folderGroup.defaultName', { n: existingGroupCount + 1 });
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
      // Compact the selected block adjacent to the group row. Stamping
      // parent_group_id in place would strand a non-selected layer sitting
      // between selected ones below the group, leaving stack order and map draw
      // order diverged, even after save+reload.
      const insertIdx = prev.findIndex((l) => selectedIds.has(l.id));
      const grouped = prev
        .filter((l) => selectedIds.has(l.id))
        .map((l) => ({ ...l, parent_group_id: groupId } as unknown as MapLayerResponse));
      const rest = prev.filter((l) => !selectedIds.has(l.id));
      const next = [...rest];
      // Every row before the first selected one is unselected, so the prev
      // index of the first selected row is also its insertion index in `rest`.
      const at = insertIdx >= 0 ? Math.min(insertIdx, rest.length) : rest.length;
      next.splice(at, 0, groupRow as unknown as MapLayerResponse, ...grouped);
      return next.map((l, i) => ({ ...l, sort_order: i }));
    });
    setGroupMeta((prev) => ({ ...prev, [groupId]: { expanded: true } }));
    setHasUnsavedChanges(true);
    // Success is toasted, as delete and apply-style are.
    toast.success(t('toasts.bulkGrouped', { count: groupableLayers.length, name: groupName }));
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
            // Clear the persisted folderGroupId with the frontend-only
            // parent_group_id, as handleUngroup / handleMoveLayerOutOfGroup
            // (use-folder-group-layers.ts) do; otherwise a child duplicated
            // before Save carries the stale pointer and is re-grouped on the next
            // server resync.
            return {
              ...gl,
              parent_group_id: null,
              style_config: clearPersistedFolderGroup(gl.style_config),
            } as MapLayerResponse;
          }
          return l;
        });
      return next.map((l, i) => ({ ...l, sort_order: i }));
    });
    setHasUnsavedChanges(true);
    toast.success(t('toasts.bulkUngrouped', { count: selectedGroups.length }));
  }, [layersRef, setLocalLayers, setHasUnsavedChanges, t]);

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
    if (idsToDelete.length === 0) {
      // A selection of only group rows would otherwise no-op silently after the
      // bar promised "Delete N layers". Say why nothing was deletable.
      toast.info(t('toasts.bulkDeleteOnlyGroupRows'));
      return false;
    }

    // Clear expanded layer if it's being deleted
    setExpandedLayerId((prev) => (prev && selectedIds.has(prev) ? null : prev));

    // Optimistic update: remove only layers actually sent to the backend
    // (idsToDelete), not selectedIds, which may include frontend-only group
    // folder rows. Deleting every child of a folder group also prunes the empty
    // group row, which has no persisted carrier.
    const idsToDeleteSet = new Set(idsToDelete);
    setLocalLayers((prev) =>
      pruneEmptyFolderGroups(prev.filter((l) => !idsToDeleteSet.has(l.id)))
        .map((l, i) => ({ ...l, sort_order: i })),
    );

    // If the batch removes the last DEM layer backing active 3D terrain,
    // auto-clear terrain_config and toast. Keyed on dataset identity so
    // unrelated deletes leave it intact. The prior terrain_config is
    // snapshotted so rollback can restore it; otherwise a failed bulk delete
    // leaves the DEM layer back but 3D terrain disabled.
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

    // Clean per-layer companions for every id in the batch so visual artifacts
    // vanish with the optimistic update. removeStaleSourcesAndLayers can't
    // derive these ids under the dedupe contract: the stripped source id
    // produces `data-${dataset_table_name}`, not the real per-layer id.
    removePerLayerCompanions(mapInstanceRef.current, idsToDelete);

    // One batched call replaces N sequential DELETEs. Capture the batch size
    // for the bar's deleting label before isDeleting flips: the optimistic
    // removal already emptied the selection-derived count.
    setDeletingCount(idsToDelete.length);
    setIsDeleting(true);
    try {
      const result = await bulkDeleteLayersApi(mapId, idsToDelete);

      if (result.failed.length === 0) {
        // Full success: sync the baseline now so the invalidateQueries refetch
        // isn't blocked by a stale savedLayerBaselineRef. Emptied group rows are
        // pruned too, so the baseline can't retain a row localLayers no longer renders.
        savedLayerBaselineRef.current = pruneEmptyFolderGroups(
          savedLayerBaselineRef.current.filter((l) => !idsToDeleteSet.has(l.id)),
        );
        // The save-diff baseline needs the same prune. It refreshes only while the
        // map is clean, so on a dirty map the next save's diff.removed would name
        // rows the server already dropped.
        saveBaselineSyncRef.current?.remove(idsToDeleteSet);
        await queryClient.invalidateQueries({ queryKey: ['map', mapId] });
        toast.success(t('bulkActions.deleteSuccess', { count: idsToDelete.length }));
        return true;
      }

      if (result.deleted.length === 0) {
        // Full failure: restore the failed batch, not a wholesale snapshot
        // write; a concurrent edit (e.g. handleAddDataset during the await) must
        // survive, or the next save diff would DELETE the just-added layer.
        setLocalLayers((current) =>
          restoreFailedLayers(current, previousLayers, idsToDeleteSet),
        );
        // Nothing was actually deleted, so restore terrain_config too.
        if (clearedTerrainOnBulk) {
          setLocalTerrainConfig(previousTerrainConfig);
        }
        toast.error(t('bulkActions.deleteRollback'));
        return false;
      }

      // Partial failure: keep deleted layers removed, restore failed ones.
      // Recompute from current state, not a stale previousLayers array, so a
      // concurrent edit during the await survives; only the rows whose deletes
      // failed are re-inserted and confirmed-deleted rows are dropped. Empty
      // groups stay pruned as on the optimistic path, since restoreFailedLayers
      // revives a group container only when a failed child is returning.
      const deletedIds = new Set(result.deleted);
      const failedIds = new Set(result.failed.map((f) => f.id));
      // Confirmed-deleted rows leave local state as on the full-success path, so
      // both baselines need the same prune; otherwise the next Save re-emits them
      // in diff.removed, trips the stale-conflict recovery and fails outright
      // when the refetch is unavailable. Only groups whose every child was
      // deleted are pruned: a failed child isn't in deletedIds, so its
      // container survives.
      savedLayerBaselineRef.current = pruneEmptyFolderGroups(
        savedLayerBaselineRef.current.filter((l) => !deletedIds.has(l.id)),
      );
      saveBaselineSyncRef.current?.remove(deletedIds);
      setLocalLayers((current) =>
        restoreFailedLayers(
          current.filter((l) => !deletedIds.has(l.id)),
          previousLayers,
          failedIds,
        ),
      );
      // The optimistic terrain clear assumed the whole batch was deleted.
      // Re-evaluate against the layers that actually remain; if terrain is still
      // backed (its source DEM was among the failures), restore terrain_config.
      if (clearedTerrainOnBulk) {
        const remainingAfterPartial = previousLayers.filter((l) => !deletedIds.has(l.id));
        if (!shouldClearTerrainOnDelete(remainingAfterPartial, previousTerrainConfig)) {
          setLocalTerrainConfig(previousTerrainConfig);
        }
      }
      // Partial state differs from the server: prevent a silent refetch wipe
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
    saveBaselineSyncRef,
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
    // Batch size for the bar's "Deleting N layers…" label.
    deletingCount,
  };
}
