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
  resolveFillExclusions,
  stashExcludedFillColor,
  clearExcludedPaintOnMap,
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

type SyncStyleConfigToMap = (
  map: MaplibreMap,
  layer: MapLayerResponse,
  paint: Record<string, unknown>,
) => void;

/**
 * fix(#910/#918, codex P2): bulk apply-style, with the EDIT-05 fill exclusions the
 * style-editor funnel applies.
 *
 * Bulk apply reaches neither `handleStyleConfigChange` nor `handlePasteStyle`, so this
 * is the only boundary the rule can be enforced at for this path: without it, the pair
 * EDIT-05 forbids persisted and MapLibre drew one key while the legend and saved JSON
 * claimed the other. Returns the exclusions alongside the layer because the live map
 * needs them for the imperative clear.
 *
 * fix(#923): `applyCopiedStyleToLayer` now resolves the fill pair inside the merge, so
 * the paint arriving here can no longer carry both keys — re-running the resolver is
 * idempotent. The wrapper stays because the exclusions are more than the paint: this is
 * where the displaced colour is stashed (read off the target's previous paint) and where
 * a classification the resolved paint no longer backs is reconciled away.
 */
function applyStyleExcludingFillCollisions(
  layer: MapLayerResponse,
  source: CopiedStyle,
): { layer: MapLayerResponse; exclusions: ReturnType<typeof resolveFillExclusions> } {
  const merged = applyCopiedStyleToLayer(layer, source);
  // The TARGET's paint is the provenance baseline: whichever fill key the merge just
  // introduced is the one the copied style asserted.
  const exclusions = resolveFillExclusions(
    merged.style_config ?? null,
    merged.paint ?? {},
    layer.paint ?? {},
  );
  return {
    layer: {
      ...merged,
      paint: exclusions.paint,
      style_config: reconcileColorClassification(
        stashExcludedFillColor(merged.style_config ?? null, exclusions),
        exclusions.paint,
        merged.dataset_geometry_type,
      ),
    },
    exclusions,
  };
}

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
  /** fix(#1778): the save-diff baseline bridge; its `remove` half is called
   *  alongside the savedLayerBaselineRef prune below. */
  saveBaselineSyncRef: React.MutableRefObject<SaveBaselineSync>;
  copiedStyleRef: React.RefObject<CopiedStyle | null>;
  syncStyleConfigToMap: SyncStyleConfigToMap;
  mvtSourceLayerPrefix?: string | null;
}

// fix(v1.6.0 audit B6): failure-path restore that does NOT clobber concurrent
// edits. Restoring the pre-delete snapshot wholesale discarded anything that
// landed during the await (e.g. a handleAddDataset onSuccess), and the next
// save's removed-computation then asked the server to DELETE the just-added
// layer. Instead, recompute from CURRENT state: re-insert only the rows whose
// deletes failed (at their old relative positions when cheap), plus any pruned
// group container a failed child still points at, and leave every other
// current row — including concurrent additions — untouched.
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
    // previous order. Rows unknown to `previous` (concurrent additions) have
    // no index and never force a displacement.
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
  syncStyleConfigToMap,
  mvtSourceLayerPrefix,
}: UseBulkLayerActionsParams) {
  const { t } = useTranslation('builder');
  const queryClient = useQueryClient();

  // Phase 1047-04 (PERF-03): tracks in-flight bulk-delete to gate BulkActionBar spinner
  const [isDeleting, setIsDeleting] = useState(false);
  // fix(v1.6.0 audit A5): batch size captured synchronously in handleBulkDelete
  // BEFORE the optimistic removal commits. Once that removal lands, the bar's
  // selection-derived deletableCount is 0, so the deleting state must render
  // this count instead ("Deleting 0 layers…" regression).
  const [deletingCount, setDeletingCount] = useState(0);

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
      prev.map((l) => (targetIds.has(l.id) ? applyStyleExcludingFillCollisions(l, source).layer : l)),
    );
    setHasUnsavedChanges(true);

    // Live-map sync: repaint each target via the map-ONLY adapter sync (it does
    // NOT re-write React state — the single setLocalLayers above owns state).
    // Gated internally on map.isStyleLoaded().
    const map = mapInstanceRef.current;
    if (map && map.isStyleLoaded()) {
      for (const target of targets) {
        const { layer: merged, exclusions } = applyStyleExcludingFillCollisions(target, source);
        // fix(#910/#918, codex P2): the excluded key has to leave the live map too —
        // omitting it from the paint object leaves the old value painted.
        clearExcludedPaintOnMap(map, target.id, exclusions);
        syncStyleConfigToMap(map, merged, merged.paint ?? {});
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
    // side-effect handleOpacityChange uses, so applyMasterOpacity split and
    // the dedicated cluster branch cannot diverge between single and bulk. The
    // single setLocalLayers write above owns React state; this only repaints.
    const map = mapInstanceRef.current;
    if (map && map.isStyleLoaded()) {
      for (const l of selectedLayers) {
        applyLayerOpacityToMap(map, l, opacity, mvtSourceLayerPrefix);
      }
    }
  }, [layersRef, setLocalLayers, setHasUnsavedChanges, mapInstanceRef, mvtSourceLayerPrefix]);

  // fix(#392): returns true only when a group was actually created, so the
  // caller (MapBuilderPage) can clear the multi-selection ONLY on success — a
  // no-op must never silently eat the user's selection. (audit B-004d/LM-04)
  const handleBulkGroup = useCallback((selectedIds: Set<string>): boolean => {
    const current = layersRef.current;
    const selectedLayers = current.filter((l) => selectedIds.has(l.id));
    // Defense-in-depth: all selected must be loose layers (not already
    // grouped, not group rows themselves). fix(#585): the extra
    // vector_dataset requirement disagreed with StackRow's "Add to group…"
    // and drag-and-drop membership, both of which accept raster/DEM rows.
    const groupableLayers = selectedLayers.filter((l) =>
      !(l as GroupedLayer).parent_group_id &&
      (l as GroupedLayer).layer_type !== 'group:folder',
    );

    // fix(#392): surface WHY the group action no-op'd instead
    // of returning silently while the caller clears the selection anyway. (audit B-004d/LM-04)
    if (groupableLayers.length !== selectedLayers.length) {
      // fix(#392): pick the message that matches the actual reason — a group
      // row in the selection is the most distinct mistake, otherwise
      // "already grouped". (audit WR-01)
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

    // Phase 1051 WR-01: crypto.randomUUID is collision-safe — see
    // handleCreateGroupWithLayer for the bulk + single race rationale.
    const groupId = `group-${crypto.randomUUID()}`;
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
      // fix(#525 B-040): compact the selected block adjacent to the group row.
      // Stamping parent_group_id in place stranded any non-selected layer that
      // sat between selected ones below the group — stack order and map draw
      // order diverged for it, persistently (not self-healed by save+reload).
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
    // fix(v1.6.0 audit D13): the group action only toasted its skip paths —
    // success was silent while delete and apply-style both confirm.
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
            // fix(#392): clear the persisted folderGroupId alongside the
            // frontend-only parent_group_id — mirrors handleUngroup /
            // handleMoveLayerOutOfGroup (use-folder-group-layers.ts), otherwise a
            // child duplicated before Save carries the stale group pointer and
            // gets silently re-grouped on the next server resync. (audit CR-01)
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
    // fix(v1.6.0 audit D13): ungroup had no success feedback at all.
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
      // fix(#771): a selection of only group rows used to no-op silently — the
      // bar promised "Delete N layers", nothing happened, no toast, selection
      // preserved. Say why nothing was deletable.
      toast.info(t('toasts.bulkDeleteOnlyGroupRows'));
      return false;
    }

    // Clear expanded layer if it's being deleted
    setExpandedLayerId((prev) => (prev && selectedIds.has(prev) ? null : prev));

    // Optimistic update — remove only layers actually sent to the backend (idsToDelete),
    // not the full selectedIds which may include frontend-only group folder rows (WR-04).
    // fix(#767): deleting every child of a folder group also prunes the now-empty
    // group row — it has no persisted carrier and would vanish on save+reload anyway.
    const idsToDeleteSet = new Set(idsToDelete);
    setLocalLayers((prev) =>
      pruneEmptyFolderGroups(prev.filter((l) => !idsToDeleteSet.has(l.id)))
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
    // fix(v1.6.0 audit A5): capture the batch size for the bar's deleting label
    // BEFORE isDeleting flips — the optimistic removal above already emptied
    // the selection-derived count the bar would otherwise render.
    setDeletingCount(idsToDelete.length);
    setIsDeleting(true);
    try {
      const result = await bulkDeleteLayersApi(mapId, idsToDelete);

      if (result.failed.length === 0) {
        // Full success — sync baseline immediately so the subsequent invalidateQueries
        // refetch is not blocked by a stale savedLayerBaselineRef (CR-01).
        // fix(#767): prune emptied group rows here too so the baseline cannot
        // retain a group row localLayers no longer renders.
        savedLayerBaselineRef.current = pruneEmptyFolderGroups(
          savedLayerBaselineRef.current.filter((l) => !idsToDeleteSet.has(l.id)),
        );
        // fix(#1778): the save-diff baseline needs the same prune. It only
        // refreshes while the map is clean, so a bulk delete on an already-dirty
        // map otherwise left these ids in it and the next save's diff.removed
        // named rows the server had already dropped.
        saveBaselineSyncRef.current?.remove(idsToDeleteSet);
        await queryClient.invalidateQueries({ queryKey: ['map', mapId] });
        toast.success(t('bulkActions.deleteSuccess', { count: idsToDelete.length }));
        return true;
      }

      if (result.deleted.length === 0) {
        // Full failure — restore the failed batch. fix(v1.6.0 audit B6): NOT a
        // wholesale snapshot write — a concurrent edit (e.g. handleAddDataset
        // landing during the await) must survive the rollback, otherwise the
        // next save diff would DELETE the just-added layer.
        setLocalLayers((current) =>
          restoreFailedLayers(current, previousLayers, idsToDeleteSet),
        );
        // HI-01: nothing was actually deleted, so restore terrain_config too.
        if (clearedTerrainOnBulk) {
          setLocalTerrainConfig(previousTerrainConfig);
        }
        toast.error(t('bulkActions.deleteRollback'));
        return false;
      }

      // Partial failure: keep deleted layers removed, restore failed layers.
      // fix(#805): survivors return at their previous relative positions, not
      // interleaved between two numbering schemes.
      // fix(v1.6.0 audit B6): recompute from CURRENT state instead of writing a
      // stale previousLayers-derived array — a concurrent edit that landed
      // during the await (e.g. handleAddDataset) must survive; only the rows
      // whose deletes FAILED are re-inserted, and confirmed-deleted rows are
      // dropped. Empty groups stay pruned like the optimistic path (#767)
      // because restoreFailedLayers only revives a group container whose failed
      // child is returning.
      const deletedIds = new Set(result.deleted);
      const failedIds = new Set(result.failed.map((f) => f.id));
      // fix(#1778 codex round 1): the confirmed-deleted rows leave local state
      // here just as they do on the full-success path, so BOTH baselines need
      // the same prune. Without it the next Save re-emitted them in
      // diff.removed, tripped the stale-conflict recovery and its warning, and
      // failed outright whenever the refetch was unavailable. Only groups whose
      // every child was actually deleted are pruned: a failed child is not in
      // deletedIds, so its container still has a member and survives.
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
      // HI-01: the optimistic terrain clear assumed the WHOLE batch was deleted.
      // Re-evaluate against the layers that ACTUALLY remain after restoring the
      // failed ones; if terrain is still backed (its source DEM was among the
      // failures), restore terrain_config so it is not silently disabled.
      if (clearedTerrainOnBulk) {
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
    // fix(v1.6.0 audit A5): batch size for the bar's "Deleting N layers…" label.
    deletingCount,
  };
}
