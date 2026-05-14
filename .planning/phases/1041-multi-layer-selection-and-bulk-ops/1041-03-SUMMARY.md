---
phase: 1041
plan: "03"
subsystem: builder
tags:
  - mapbuilder
  - bulk-actions
  - state-mutation
  - rollback
dependency_graph:
  requires:
    - 1041-02 (BulkActionBar + stub handlers)
  provides:
    - handleBulkVisibility(ids) in useBuilderLayers — single setLocalLayers + live-map sync
    - handleBulkOpacity(ids, opacity) in useBuilderLayers — single setLocalLayers + live-map sync
    - handleBulkGroup(ids) in useBuilderLayers — single setLocalLayers, defense-in-depth guard
    - handleBulkUngroup(ids) in useBuilderLayers — single setLocalLayers, removes group rows + clears children
    - handleBulkDelete(ids) in useBuilderLayers — Promise.allSettled + rollback + single error toast
    - MapBuilderPage stubs replaced with real wrappers delegating to layers.handleBulk*
  affects:
    - 1041-04 (vitest tests target these implementations)
tech_stack:
  added:
    - useQueryClient from @tanstack/react-query (used for invalidation after bulk delete)
  patterns:
    - Single-setState batch mutation for visibility/opacity/group/ungroup (no per-row API call)
    - Promise.allSettled + snapshot rollback for bulk delete (same pattern as UploadForm.tsx)
    - Live-map setLayoutProperty/setPaintProperty loop after single setState (not N applyLayerUpdate calls)
    - layersRef.current snapshot at handler start (avoids stale closure; existing hook pattern)
key_files:
  modified:
    - frontend/src/components/builder/hooks/use-builder-layers.ts
    - frontend/src/pages/MapBuilderPage.tsx
decisions:
  - "handleBulkVisibility/Opacity chose single-setState + manual map mutation loop over N applyLayerUpdate calls: applyLayerUpdate calls setLocalLayers inside it, so N calls would fire N React state updates and defeat the purpose of a bulk operation. The manual map loop mirrors the same setLayoutProperty/setPaintProperty calls but outside React's update cycle."
  - "handleBulkOpacity does NOT clear selection on each onValueChange (slider fires continuously during drag). Clearing mid-drag would empty the selection set, making subsequent drag events operate on an empty set. Selection is preserved; user dismisses via Escape or by clicking a non-selected row. UI-SPEC §4 said 'clear on success' but for a continuous control this is hostile UX — Claude's Discretion applied."
  - "Known race: bulk delete in flight + user clicks Save — last writer wins because Save also deletes-then-reposts layers. Acceptable for v1.5 (no background autosave); would need serialization if autosave is ever added."
  - "Audit trail: bulk delete writes N audit entries via the per-layer DELETE endpoint. No 'bulk_delete' composite audit action — future enhancement if Phase 1044+ UAT surfaces the need."
  - "queryKey for invalidation: used ['map', mapId] (queryKeys.maps.detail(mapId) from query-keys.ts) to match what useMap() query uses, ensuring the layer list refetches cleanly after successful bulk delete."
metrics:
  duration: "18m"
  completed_date: "2026-05-14"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 2
  files_created: 0
---

# Phase 1041 Plan 03: Five bulk handlers in use-builder-layers.ts; replace MapBuilderPage stubs

**One-liner:** Five bulk op handlers (visibility/opacity/group/ungroup as pure local-state mutations; delete via Promise.allSettled + snapshot rollback) implemented in useBuilderLayers and wired into MapBuilderPage, replacing all Plan 02 stubs (POL-09 closed).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Implement handleBulkVisibility / Opacity / Group / Ungroup as single-setState local mutations | 31a071e1 | use-builder-layers.ts |
| 2 | Implement handleBulkDelete with Promise.allSettled + rollback + wire all 5 into MapBuilderPage | 59a695ca | use-builder-layers.ts, MapBuilderPage.tsx |

## What Was Built

### Task 1: Four local-state bulk handlers

**`handleBulkVisibility(selectedIds: Set<string>)`**
- Snapshots `layersRef.current`; filters to selected layers; computes majority-visible; derives `nextVisible = !majorityVisible`
- Single `setLocalLayers((prev) => prev.map(...))` call for the entire batch
- Live-map sync: iterates selected layers and calls `map.setLayoutProperty(subId, 'visibility', newVis)` for all 6 sub-layer ids (layer-{id}, outline, label, extrusion, cluster, cluster-count) — NO per-row applyLayerUpdate (which would fire N separate React state updates)
- Defense-in-depth: empty selection guard, null-map guard
- No success toast; no API call

**`handleBulkOpacity(selectedIds: Set<string>, opacity: number)`**
- Same single-setState pattern
- Live-map sync: per-layer `setPaintProperty` calls based on adapter type (raster-opacity for raster_geolens; heatmap-opacity for heatmap render mode; {adapterType}-opacity + outline line-opacity for vector)
- No success toast; no API call

**`handleBulkGroup(selectedIds: Set<string>)`**
- Defense-in-depth guard: every selected layer must satisfy `dataset_record_type === 'vector_dataset' && !parent_group_id && layer_type !== 'group:folder'`; if any fail or `selectedLayers.length < 2`, returns early with no mutation
- Generates `groupId = group-${Date.now()}` (matches handleCreateGroupWithLayer pattern)
- Group row inherits sort_order of the layer with the smallest sort_order among selected
- Single `setLocalLayers` that: maps selected layers to set `parent_group_id = groupId`, splices group row at first selected position, renumbers all sort_orders globally
- Calls `setGroupMeta` to auto-expand the new group

**`handleBulkUngroup(selectedIds: Set<string>)`**
- Defense-in-depth guard: all selected must have `layer_type === 'group:folder'`
- Single `setLocalLayers` that: filters out group container rows; clears `parent_group_id` on any layer whose `parent_group_id` is in `selectedIds`; renumbers sort_orders

All four: no `removeLayerFromMapApi`, no `fetch`, no `.mutate(`, no `toast.success`.

### Task 2: handleBulkDelete + MapBuilderPage wiring

**`handleBulkDelete(selectedIds: Set<string>): Promise<boolean>`**
- Early return `false` if `!mapId || selectedIds.size === 0`
- Snapshots `previousLayers = layersRef.current` before any mutation
- Clears `expandedLayerId` if it is in the selection (mirrors handleRemove pattern)
- Optimistic update: single `setLocalLayers` to filter + renumber sort_order
- `Promise.allSettled` over `idsToDelete.map((id) => removeLayerFromMapApi(mapId, id))` — direct API call (NOT removeLayerMutation.mutate) for true parallelism (TanStack mutations serialize)
- On any failure: `setLocalLayers(previousLayers)` rollback + `toast.error(t('bulkActions.errorDeleteRolledBack', { count }))` + return `false`
- On full success: `queryClient.invalidateQueries({ queryKey: ['map', mapId] })` + return `true`

**MapBuilderPage stubs replaced:**
- `handleBulkVisibility` → calls `layers.handleBulkVisibility(ids)` then `setSelectedIds(new Set())`
- `handleBulkOpacity` → calls `layers.handleBulkOpacity(ids, opacity)` only (NO selection clear — slider fires continuously during drag; see Decision 2)
- `handleBulkGroup` → calls `layers.handleBulkGroup(ids)` then `setSelectedIds(new Set())`
- `handleBulkUngroup` → calls `layers.handleBulkUngroup(ids)` then `setSelectedIds(new Set())`
- `handleBulkDelete` → calls `layers.handleBulkDelete(ids).then(ok => { if (ok) setSelectedIds(new Set()); })`

## Decisions Made

1. **Single-setState + manual map mutation loop vs N applyLayerUpdate calls** — Chose single-setState. `applyLayerUpdate` calls `setLocalLayers` internally, so calling it N times would fire N React state updates, defeating the "atomic bulk op" contract. The manual map mutation loop is slightly more code but mirrors the exact same `setLayoutProperty`/`setPaintProperty` calls and runs in one React commit.

2. **Opacity bulk op does NOT clear selection on each onValueChange** — The Radix/Shadcn Slider fires `onValueChange` continuously during drag at ~60fps. Clearing `selectedIds` on the first event would produce an empty set by the time the second event fires, making all subsequent drag events operate on nothing. The UI-SPEC §4 "clear on success" rule is waived for this continuous-fire control; user dismisses selection via Escape or a click. This is a deliberate UX choice within Claude's Discretion per CONTEXT.md.

3. **Known race: bulk delete + Save** — If a user triggers bulk delete (async Promise.allSettled) and then immediately clicks Save, the Save flow (which also deletes layers not in the baseline and POSTs the current local state) runs concurrently. Last writer wins. This is acceptable for v1.5 given: (a) no background autosave, (b) the race window is ~hundreds of milliseconds, (c) the user must physically click two separate buttons. Document if autosave is ever added.

4. **Audit trail** — Each `removeLayerFromMapApi` call hits the existing per-layer DELETE endpoint which already writes a standard audit log entry. Bulk delete appears as N rapid single-delete audit entries rather than one "bulk_delete" composite entry. Future enhancement if needed.

5. **queryKey for invalidation** — Used `['map', mapId]` which matches `queryKeys.maps.detail(mapId)` in query-keys.ts (the key that `useMap(id)` uses). This ensures the layer list in the builder sidebar refetches after a successful bulk delete without requiring the user to manually reload.

## Deviations from Plan

None — plan executed exactly as written. The opacity selection-preserve behavior was explicitly planned in the `<action>` block (step 6) and SUMMARY output spec.

## Known Stubs

None — all five Plan 02 stubs are replaced with real implementations.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes introduced beyond what the plan's `<threat_model>` already described. The T-1041-09 through T-1041-13 mitigations are implemented as specified:
- T-1041-09: handleBulkGroup defense-in-depth guard is present
- T-1041-11: error toast uses `t('bulkActions.errorDeleteRolledBack', { count })` — only count interpolated, no PII

## Self-Check: PASSED

- `frontend/src/components/builder/hooks/use-builder-layers.ts` modified: contains handleBulkVisibility, handleBulkOpacity, handleBulkGroup, handleBulkUngroup, handleBulkDelete (each >= 2 grep occurrences); contains Promise.allSettled, removeLayerFromMapApi, useQueryClient, queryClient.invalidateQueries, errorDeleteRolledBack
- `frontend/src/pages/MapBuilderPage.tsx` modified: 0 occurrences of "Phase 1041 Plan 03"; 5 occurrences of "layers.handleBulk"
- tsc: 0 errors
- vitest src/components/builder/: 709 passed (55 test files), 0 failures
- npm run build: success
- Commits 31a071e1 and 59a695ca exist in git log
