---
phase: 1051
plan: 02
type: execute
wave: 2
depends_on: ["1051-01"]
files_modified:
  - frontend/src/components/builder/hooks/use-builder-layers.ts
  - frontend/src/hooks/use-maps.ts
  - frontend/src/components/builder/hooks/__tests__/use-builder-layers.delete.test.ts
autonomous: false
requirements: [BUG-02]
tags: [builder, bugfix, delete-layer]

must_haves:
  truths:
    - "User can click the delete action on a regular layer and the layer is removed from the sidebar list immediately (optimistic update)"
    - "MapLibre layer + companion suffixes are removed from the map render"
    - "Reload of the map confirms the deletion persisted to the saved-map JSON via the DELETE /api/maps/{mapId}/layers/{layerId} mutation"
    - "On API failure, the optimistic state is rolled back (layer reappears in sidebar)"
    - "No regression to bulk-delete behavior (v1010 PERF-03 batched delete)"
  artifacts:
    - path: "frontend/src/components/builder/hooks/use-builder-layers.ts"
      provides: "handleRemove with optimistic setLocalLayers + rollback on error, mirroring handleBulkDelete (lines 580-661)"
      contains: "setLocalLayers"
    - path: "frontend/src/components/builder/hooks/__tests__/use-builder-layers.delete.test.ts"
      provides: "regression case asserting optimistic removal + map.removeLayer dispatch + rollback on error"
      contains: "handleRemove"
  key_links:
    - from: "frontend/src/components/builder/hooks/use-builder-layers.ts"
      to: "frontend/src/hooks/use-maps.ts (useRemoveLayer)"
      via: "removeLayerMutation.mutate({ mapId, layerId })"
      pattern: "removeLayerMutation"
    - from: "frontend/src/components/builder/hooks/use-builder-layers.ts handleRemove"
      to: "frontend/src/components/builder/map-sync.ts removeStaleSourcesAndLayers (line 642-668)"
      via: "removePerLayerCompanions imperative cleanup"
      pattern: "removePerLayerCompanions"
---

<objective>
Fix BUG-02: delete-layer is a no-op. User can click the delete action on a layer in the sidebar and the layer is removed from both the sidebar list AND the map render. Deletion persists across reload.

Purpose: Delete is a fundamental row action; broken since unknown commit. Per PATTERNS.md finding #3, the existing `handleRemove` is missing the optimistic `setLocalLayers(prev => prev.filter(...))` step that `handleBulkDelete` (lines 580-661) already implements — this is the canonical fix template.
Output: Add optimistic state update + rollback to `handleRemove`; confirm `useRemoveLayer` mutation invalidates the map query on success; regression test asserts the full optimistic round-trip.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/1051-map-builder-polish-bug-sweep/1051-CONTEXT.md
@.planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md
@.planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md

<interfaces>
<!-- From PATTERNS.md — current handleRemove implementation (likely missing optimistic step). -->

From frontend/src/components/builder/hooks/use-builder-layers.ts (lines 316-336 — current handleRemove):
```ts
const handleRemove = useCallback((layerId: string) => {
  if (!mapId) return;
  setExpandedLayerId((prev) => prev === layerId ? null : prev);
  // WR-01 (Phase 1050-rev): imperatively clean per-layer companions
  removePerLayerCompanions(mapInstanceRef.current, [layerId]);
  removeLayerMutation.mutate(
    { mapId, layerId },
    {
      onSuccess: () => { toast.success(t('toasts.layerRemoved')); },
      onError: () => { toast.error(t('toasts.layerRemoveFailed')); },
    },
  );
}, [mapId, mapInstanceRef, removeLayerMutation, t]);
```

From frontend/src/components/builder/hooks/use-builder-layers.ts (lines 580-661 — reference handleBulkDelete with optimistic pattern):
```ts
const previousLayers = layersRef.current;
const idsToDeleteSet = new Set(idsToDelete);
setLocalLayers((prev) =>
  prev
    .filter((l) => !idsToDeleteSet.has(l.id))
    .map((l, i) => ({ ...l, sort_order: i })),
);
// ... call API; on error, setLocalLayers(previousLayers)
```

From frontend/src/hooks/use-maps.ts (around line 182-188 — useRemoveLayer to verify):
```ts
export function useRemoveLayer() {
  return useMutation({
    mutationFn: ({ mapId, layerId }) => removeLayerFromMapApi(mapId, layerId),
    // CHECK: does this have onSuccess with queryClient.invalidateQueries(['map', mapId])?
  });
}
```
</interfaces>
</context>

<tasks>

<task type="checkpoint:orchestrator">
  <name>Task 1: Playwright MCP pre-fix repro</name>
  <files>(no files modified)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 02 — Hypothesis B re missing optimistic update)
  </read_first>
  <action>
    Orchestrator drives Playwright MCP. Steps: (1) Open a map with ≥2 layers (use `http://localhost:8080/maps/c868cc3a-a3a0-4714-b559-67b3f2b478e2` or any saved map). (2) Open the kebab on a regular (non-basemap) layer row and select "Delete layer" (or click the delete affordance). (3) Confirm the destructive action via the inline confirm. (4) Capture: sidebar row state (does the row remain? does it disappear?), network call (was DELETE /api/maps/{id}/layers/{id} fired? response status?), MapLibre `map.getLayer('layer-{id}')` state (does the layer still exist?). (5) Reload the page; confirm whether deletion persisted. Record observed pre-fix behavior (most likely: sidebar row remains visible; API call may or may not fire; on reload the layer is sometimes back — indicating a sync race). Add incidental issues to scratch list for EMRG-01.
  </action>
  <verify>
    <automated>Playwright MCP screenshot of sidebar after delete attempt; orchestrator records: row-still-present yes/no, DELETE request fired yes/no, post-reload presence.</automated>
  </verify>
  <acceptance_criteria>
    - Pre-fix behavior confirmed: delete is observably a no-op (row stays, or row disappears but reload restores it)
    - Network trace of the DELETE call (if fired) captured
    - Layer ID + map ID captured for regression test fixture
  </acceptance_criteria>
  <done>Pre-fix behavior confirmed; orchestrator decides which hypothesis (A/B/C from PATTERNS.md) applies.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Add optimistic delete + rollback; confirm mutation invalidation</name>
  <files>frontend/src/components/builder/hooks/use-builder-layers.ts, frontend/src/hooks/use-maps.ts, frontend/src/components/builder/hooks/__tests__/use-builder-layers.delete.test.ts</files>
  <read_first>
    - frontend/src/components/builder/hooks/use-builder-layers.ts (handleRemove around lines 316-336 AND handleBulkDelete around lines 580-661 for the reference pattern)
    - frontend/src/hooks/use-maps.ts (useRemoveLayer hook around lines 182-188)
    - frontend/src/components/builder/map-sync.ts (removePerLayerCompanions + removeStaleSourcesAndLayers around lines 642-668)
    - frontend/src/components/builder/hooks/__tests__/use-builder-layers.bulk-ops.test.ts (test harness reference for use-builder-layers tests)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 02 — Pattern B Optimistic state update + API mutation + rollback)
  </read_first>
  <behavior>
    - Test 1: handleRemove immediately filters the layer out of localLayers (optimistic)
    - Test 2: After optimistic filter, remaining layers' sort_order values are re-indexed contiguously (0, 1, 2...) matching handleBulkDelete pattern
    - Test 3: removePerLayerCompanions is invoked with [layerId] (companion suffix sweep)
    - Test 4: removeLayerMutation.mutate fires with { mapId, layerId }
    - Test 5: On mutation onError, setLocalLayers is restored to previousLayers (rollback)
    - Test 6: useRemoveLayer onSuccess invalidates the map query (queryClient.invalidateQueries) so subsequent reads reflect the deletion
  </behavior>
  <action>
    Modify `handleRemove` in `frontend/src/components/builder/hooks/use-builder-layers.ts` (current lines ~316-336) to mirror the optimistic + rollback pattern from `handleBulkDelete` (current lines ~580-661): capture `previousLayers = layersRef.current` BEFORE the API call; call `setLocalLayers(prev => prev.filter(l => l.id !== layerId).map((l, i) => ({ ...l, sort_order: i })))` BEFORE `removeLayerMutation.mutate`; on `onError`, restore via `setLocalLayers(previousLayers)` AND surface the existing `toasts.layerRemoveFailed` toast. Keep the existing `removePerLayerCompanions` call (line 320 — already present) ordered before the mutation as in current code. Verify `useRemoveLayer` in `frontend/src/hooks/use-maps.ts` invalidates `['map', mapId]` (or whatever the canonical key is — grep for `queryClient.invalidateQueries` in sibling map mutations like `useUpdateLayer`); if missing, add the invalidation in `onSuccess`. Do NOT refactor the hook architecture or rename any handlers. Create `frontend/src/components/builder/hooks/__tests__/use-builder-layers.delete.test.ts` mirroring the harness from `use-builder-layers.bulk-ops.test.ts` (renderHook + mock removeLayerMutation + assert localLayers state transitions). Tests must fail BEFORE the fix and pass AFTER.
  </action>
  <verify>
    <automated>cd frontend && npx vitest run src/components/builder/hooks/__tests__/use-builder-layers.delete.test.ts</automated>
  </verify>
  <acceptance_criteria>
    - `grep -n 'setLocalLayers' frontend/src/components/builder/hooks/use-builder-layers.ts` includes at least one call inside handleRemove (currently 0)
    - `grep -n 'previousLayers' frontend/src/components/builder/hooks/use-builder-layers.ts` shows the rollback variable referenced inside handleRemove
    - useRemoveLayer in use-maps.ts has `queryClient.invalidateQueries` in its `onSuccess` (or equivalent at consumer site)
    - New regression test asserts: optimistic filter, sort_order re-index, removePerLayerCompanions call, mutation.mutate args, rollback-on-error
    - `cd frontend && npx tsc --noEmit` returns 0 errors
    - Diff is minimal: only handleRemove block in use-builder-layers.ts, useRemoveLayer in use-maps.ts (only if invalidation was missing), and the new test file
    - No regression to handleBulkDelete: bulk-ops test file passes unchanged
  </acceptance_criteria>
  <done>handleRemove now optimistically filters localLayers + rolls back on error; useRemoveLayer invalidates the map query; regression test green.</done>
</task>

<task type="checkpoint:orchestrator">
  <name>Task 3: Playwright MCP post-fix re-verify + atomic commit</name>
  <files>(no files modified beyond commit)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md
  </read_first>
  <action>
    Orchestrator drives Playwright MCP on fresh page reload. Steps: (1) Open a map with ≥2 layers. (2) Delete a non-basemap layer via the row kebab. (3) Confirm: sidebar row disappears IMMEDIATELY (optimistic, before network response). (4) Confirm: tiles for that layer disappear from the map. (5) Confirm: DELETE /api/maps/{id}/layers/{id} returned 200/204. (6) Reload the page. (7) Confirm: layer remains deleted (sidebar list reflects DB state). (8) Spot-check: bulk-delete still works — select ≥2 layers, bulk delete, confirm v1010 PERF-03 batched HTTP behavior unaffected. After MCP verify passes, create atomic commit with subject: `fix(builder): delete layer removes from stack and map (BUG-02)`. Stage only the in-scope files.
  </action>
  <verify>
    <automated>git log --oneline -1 && git show --stat HEAD</automated>
  </verify>
  <acceptance_criteria>
    - Playwright MCP confirms delete-layer optimistically removes row + map layer
    - Reload preserves the deletion
    - Bulk-delete regression check passes
    - Commit exists with subject `fix(builder): delete layer removes from stack and map (BUG-02)`
    - `git diff HEAD~1 HEAD --stat` shows only the in-scope files modified
  </acceptance_criteria>
  <done>BUG-02 fix verified live + committed atomically.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| client→API DELETE | Client sends DELETE /api/maps/{mapId}/layers/{layerId}; backend authorizes user can edit the map |
| client→MapLibre | Client calls map.removeLayer on layer-{id}; layerId from in-app state |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1051-02 | Tampering | DELETE /api/maps/{mapId}/layers/{layerId} | accept | Backend already enforces ownership/permission check; no new attack surface |
| T-1051-02-IDOR | Information Disclosure | Rolling back on 403 | accept | Optimistic UI reverts cleanly on error; backend rejects unauthorized deletes |
</threat_model>

<verification>
- Playwright MCP confirms delete removes row + map tiles + persists on reload
- Vitest regression case fails before fix and passes after
- `npx tsc --noEmit` returns 0 errors
- No regression to bulk-delete (v1010 PERF-03)
</verification>

<success_criteria>
- Deleting a layer removes it from the sidebar StackRow list immediately (optimistic)
- Deleting a layer removes the corresponding MapLibre layer + companion suffixes
- Reload of the map confirms the deletion persisted to the saved-map JSON
- On API failure, the layer reappears in the sidebar (rollback)
- Vitest regression case fails before fix and passes after fix
- No regression to bulk-delete behavior (v1010 PERF-03 batched delete)
- Atomic commit on main with subject `fix(builder): delete layer removes from stack and map (BUG-02)`
</success_criteria>

<output>
Create `.planning/phases/1051-map-builder-polish-bug-sweep/1051-02-SUMMARY.md` when done with: root-cause analysis (Hypothesis A/B/C from PATTERNS.md), fix description (optimistic + rollback diff), files modified, test result, MCP verification screenshots/notes.
</output>
