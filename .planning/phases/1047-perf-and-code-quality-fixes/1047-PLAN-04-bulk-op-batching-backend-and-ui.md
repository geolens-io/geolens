---
phase: 1047-perf-and-code-quality-fixes
plan: 04
type: execute
wave: 4
depends_on: [1047-01, 1047-02]
files_modified:
  - backend/app/modules/catalog/maps/router.py
  - backend/app/modules/catalog/maps/schemas.py
  - backend/app/modules/catalog/maps/service_layers.py
  - backend/tests/test_maps_bulk_layers.py
  - frontend/src/api/maps.ts
  - frontend/src/types/api.ts
  - frontend/src/components/builder/hooks/use-builder-layers.ts
  - frontend/src/components/builder/hooks/__tests__/use-builder-layers.bulk-ops.test.ts
  - frontend/src/components/builder/BulkActionBar.tsx
  - frontend/src/components/builder/__tests__/BulkActionBar.test.tsx
  - frontend/src/pages/MapBuilderPage.tsx
  - frontend/src/components/builder/UnifiedStackPanel.tsx
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/i18n/locales/de/builder.json
  - frontend/src/i18n/locales/es/builder.json
  - frontend/src/i18n/locales/fr/builder.json
  - e2e/perf/builder-large-map.spec.ts
autonomous: true
requirements: [PERF-02, PERF-03]
must_haves:
  truths:
    - "MILESTONE EXCEPTION (per REQUIREMENTS.md Out-of-Scope): one additive backend endpoint POST /api/maps/{map_id}/layers/bulk-delete ships in this plan with body { layer_ids: string[] } and response { deleted: string[], failed: [{ id: string, reason: string }] }"
    - "Frontend handleBulkDelete in use-builder-layers calls bulkDeleteLayersApi ONCE instead of N parallel removeLayerFromMapApi calls; reduces 50 sequential HTTP requests to 1 (PB-03)"
    - "BulkActionBar renders a Loader2 spinner in the Delete button when isDeleting=true; button disabled with aria-busy=true (UI-SPEC PERF-03)"
    - "Rollback toast for full failure + partial-failure toast with Retry action fire via sonner (UI-SPEC copywriting)"
    - "BulkActionBar uses useCallback on all action onClick handlers; component still wrapped in React.memo() — selectedIds prop changes do not invalidate handler refs (PB-08)"
    - "StackRow + UnifiedStackPanel render path memoizes selection-derived data such that hovering an unselected row in a 50-layer map does not trigger a full stack re-render (PB-05)"
    - "Playwright assertion in e2e/perf/builder-large-map.spec.ts proves bulk-delete(N=50) issues exactly 1 HTTP request and completes wall-clock < 600ms"
  artifacts:
    - path: "backend/app/modules/catalog/maps/router.py"
      provides: "bulk_delete_layers_endpoint"
      contains: "@router.post(\"/{map_id}/layers/bulk-delete\""
    - path: "backend/tests/test_maps_bulk_layers.py"
      provides: "Backend integration tests for bulk-delete"
      contains: "async def test_bulk_delete"
    - path: "frontend/src/api/maps.ts"
      provides: "bulkDeleteLayersApi(mapId, layerIds)"
      contains: "export async function bulkDeleteLayersApi"
    - path: "frontend/src/components/builder/BulkActionBar.tsx"
      provides: "isDeleting prop + Loader2 swap"
      contains: "isDeleting"
  key_links:
    - from: "frontend/src/components/builder/hooks/use-builder-layers.ts"
      to: "frontend/src/api/maps.ts bulkDeleteLayersApi"
      via: "single HTTP call replaces Promise.allSettled(...removeLayerFromMapApi)"
      pattern: "bulkDeleteLayersApi\\("
    - from: "frontend/src/components/builder/BulkActionBar.tsx"
      to: "useCallback wrappers on all on* props"
      via: "handlers stable across selectedIds.size changes"
      pattern: "useCallback"
---

<objective>
Three related goals:
1. **PERF-03 (PB-03) — backend batch endpoint.** Ship the SINGLE permitted additive backend endpoint `POST /api/maps/{map_id}/layers/bulk-delete` (Out-of-Scope exception called out in REQUIREMENTS.md + CONTEXT.md). Cuts bulk-delete(N=50) from 50 sequential DELETEs to 1 batched call.
2. **PERF-03 (PB-03) — frontend wiring + UI affordances.** Rewire `handleBulkDelete` in use-builder-layers to call the new endpoint; show in-flight spinner + rollback toast + partial-failure toast with Retry action per UI-SPEC.
3. **PERF-02 (PB-05 + PB-08) — input latency memoization.** Wrap BulkActionBar handlers in useCallback at the MapBuilderPage caller site; memoize selection-derived computations in UnifiedStackPanel so per-row hover does not invalidate the whole stack render.

Purpose: PERF-02 (input latency < 16ms) + PERF-03 (bulk batching, rollback, progress) share the bulk-op surface — single plan keeps the changes co-located. The backend endpoint is the documented milestone exception.

Output: One backend endpoint with tests, one frontend API client function, rewired handleBulkDelete with progress UI + i18n, memoized BulkActionBar + UnifiedStackPanel, Playwright assertion in the perf spec.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/STATE.md
@.planning/phases/1047-perf-and-code-quality-fixes/1047-CONTEXT.md
@.planning/phases/1047-perf-and-code-quality-fixes/1047-UI-SPEC.md
@.planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-PERF-BASELINE.md

<interfaces>
<!-- Existing per-layer delete endpoint (backend/app/modules/catalog/maps/router.py:1611) — the new bulk endpoint should mirror its auth + audit pattern -->
@router.delete("/{map_id}/layers/{layer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_layer_endpoint(map_id, layer_id, request, user, db):
  # check_map_ownership, remove_layer, audit_emit, record_map_history_event

<!-- Existing service layer for remove_layer (backend/app/modules/catalog/maps/service_layers.py — read it) -->
<!-- Pattern: remove_layer(db, layer_id, map_id) returns bool (whether the layer existed) -->

<!-- Existing frontend API client (frontend/src/api/maps.ts:143) -->
export async function removeLayerFromMapApi(mapId, layerId): Promise<void>

<!-- Existing handleBulkDelete in use-builder-layers.ts:538-580 -->
const handleBulkDelete = useCallback(async (selectedIds: Set<string>): Promise<boolean> => {
  ...
  const results = await Promise.allSettled(
    idsToDelete.map((id) => removeLayerFromMapApi(mapId, id)),
  );
  const anyFailed = results.some((r) => r.status === 'rejected');
  if (anyFailed) { setLocalLayers(previousLayers); toast.error(t('bulkActions.errorDeleteRolledBack', { count })); return false; }
  await queryClient.invalidateQueries({ queryKey: ['map', mapId] });
  return true;
}, [mapId, t, queryClient]);

<!-- Existing BulkActionBar props (frontend/src/components/builder/BulkActionBar.tsx:22-32) -->
export interface BulkActionBarProps {
  selectedIds: Set<string>;
  layers: MapLayerResponse[];
  onBulkVisibility: (ids: Set<string>) => void;
  onBulkOpacity: (ids: Set<string>, opacity: number) => void;
  onBulkGroup: (ids: Set<string>) => void;
  onBulkUngroup: (ids: Set<string>) => void;
  onBulkDelete: (ids: Set<string>) => void;
}
<!-- BulkActionBar is already memo()'d at line 45 -->

<!-- Existing i18n bulkActions namespace (frontend/src/i18n/locales/en/builder.json:766-794) -->
"bulkActions": {
  "selectedCount", "toolbarLabel", "liveAnnouncement", "visibility", "opacity",
  "group", "ungroup", "delete", "deleteAriaLabel", "deleteConfirmLabel",
  "deleteConfirmAction", "deleteConfirmCancel",
  "errorUpdateRolledBack", "errorDeleteRolledBack",
  ...
}

<!-- UI-SPEC copywriting (1047-UI-SPEC.md Copywriting Contract) — NEW i18n keys to add: -->
- bulkActions.deletingLayers: "Deleting {{count}} layers…"
- bulkActions.deleteSuccess: "{{count}} layers deleted"
- bulkActions.deletePartialFailure: "{{deleted}} of {{count}} layers deleted. {{failed}} failed."
- bulkActions.deleteRollback: "Delete failed — no changes were made."  (REPLACE existing "errorDeleteRolledBack" key OR add new — pick: keep existing, add NEW key, document in summary)
- bulkActions.retryAction: "Retry"
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Backend bulk-delete endpoint + schema + service + tests</name>
  <files>
    backend/app/modules/catalog/maps/router.py,
    backend/app/modules/catalog/maps/schemas.py,
    backend/app/modules/catalog/maps/service_layers.py,
    backend/tests/test_maps_bulk_layers.py
  </files>
  <read_first>
    backend/app/modules/catalog/maps/router.py (lines 1611-1685 — existing remove_layer_endpoint pattern: ownership check, history, audit),
    backend/app/modules/catalog/maps/service_layers.py (find remove_layer function — the bulk version reuses it or batches it),
    backend/app/modules/catalog/maps/schemas.py (existing layer schemas, MapLayer response shape),
    backend/tests/test_layers.py (existing layer test patterns: auth headers, dataset setup, cleanup),
    backend/tests/test_maps.py (existing maps test patterns)
  </read_first>
  <behavior>
    - Test 1: Authenticated editor POSTs `{"layer_ids": ["uuid-a", "uuid-b", "uuid-c"]}` for a map they own; all 3 layers exist; response is `{"deleted": ["uuid-a", "uuid-b", "uuid-c"], "failed": []}` with status 200
    - Test 2: One layer id is invalid (not in map); response is `{"deleted": [valid_ids], "failed": [{"id": "invalid-uuid", "reason": "not_found"}]}` with status 200 (partial success surfaces failures inline, not as HTTP error)
    - Test 3: Empty `layer_ids` array returns 400 with detail "layer_ids cannot be empty"
    - Test 4: layer_ids array exceeding 200 (mirror `_MAX_LAYERS_PER_MAP`) returns 400 with detail "too many layer_ids"
    - Test 5: User without `edit_metadata` permission (e.g., viewer role) gets 403
    - Test 6: Map not owned by user → 404 (mirror existing ownership pattern)
    - Test 7: Audit event `map.bulk_remove_layers` is emitted exactly once with `{"layer_ids": [...], "deleted_count": N}` details
    - Test 8: Single map_history event records the bulk action with target_type="layer", action="layer.bulk_remove", summary=f"Removed {N} layers"
  </behavior>
  <action>
    Add Pydantic schemas in `schemas.py`:
    - `class BulkDeleteLayersRequest(BaseModel): layer_ids: list[uuid.UUID]` with validator: `1 <= len(layer_ids) <= 200` (use `Field(..., min_length=1, max_length=200)`).
    - `class BulkDeleteLayersFailure(BaseModel): id: str; reason: str`.
    - `class BulkDeleteLayersResponse(BaseModel): deleted: list[str]; failed: list[BulkDeleteLayersFailure]`.

    Add service helper in `service_layers.py`:
    `async def remove_layers_bulk(db: AsyncSession, layer_ids: list[uuid.UUID], map_id: uuid.UUID) -> tuple[list[str], list[tuple[str, str]]]:` — fetch all matching MapLayer rows in one SELECT, delete via SQL `DELETE WHERE map_id=:m AND id=ANY(:ids)`, return (deleted_ids, failed_pairs). For ids that did not match (not in the SELECT result set), append `(str(id), "not_found")` to failures. Single DB transaction (do NOT commit inside; router commits once).

    Add router endpoint in `router.py` (mirror `remove_layer_endpoint` at line 1611 for structure):
    ```
    @router.post("/{map_id}/layers/bulk-delete", response_model=BulkDeleteLayersResponse, status_code=status.HTTP_200_OK)
    async def bulk_delete_layers_endpoint(
        map_id: uuid.UUID,
        body: BulkDeleteLayersRequest,
        request: Request,
        user: Identity = Depends(require_permission("edit_metadata")),
        db: AsyncSession = Depends(get_db),
    ) -> BulkDeleteLayersResponse:
    ```
    Body: get map, check_map_ownership, call service.remove_layers_bulk, emit audit event `map.bulk_remove_layers`, record_map_history_event with action="layer.bulk_remove" and target_type="layer", db.commit(), return response.

    Write `backend/tests/test_maps_bulk_layers.py` covering the 8 test cases above. Use existing fixtures from conftest.py (auth headers, db session, dataset factory). Follow the patterns from `test_layers.py`.

    Document in router docstring: "Milestone exception (v1010 Phase 1047): one additive endpoint permitted per REQUIREMENTS.md Out-of-Scope to reduce N sequential DELETEs to one batched call for bulk-delete UX (PB-03)."
  </action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_maps_bulk_layers.py -x</automated>
    <automated>cd backend && grep -c "bulk-delete" app/modules/catalog/maps/router.py | grep -v ':0'</automated>
    <automated>cd backend && uv run ruff check app/modules/catalog/maps/router.py app/modules/catalog/maps/schemas.py app/modules/catalog/maps/service_layers.py</automated>
    <automated>cd backend && uv run mypy app/modules/catalog/maps/router.py 2>&1 | tail -10 || true</automated>
  </verify>
  <acceptance_criteria>
    - `POST /maps/{map_id}/layers/bulk-delete` route registered and discoverable in OpenAPI (`curl /api/openapi.json | jq` finds it)
    - All 8 tests pass
    - Validation rejects empty list (400) and oversized list (400)
    - Audit event + map history event emit exactly once per call
    - Ruff + mypy clean (no new violations introduced)
  </acceptance_criteria>
  <done>Backend bulk-delete endpoint ships with full test coverage; milestone exception documented in router docstring.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Frontend API client + rewire handleBulkDelete + progress + rollback UI + i18n</name>
  <files>
    frontend/src/api/maps.ts,
    frontend/src/types/api.ts,
    frontend/src/components/builder/hooks/use-builder-layers.ts,
    frontend/src/components/builder/hooks/__tests__/use-builder-layers.bulk-ops.test.ts,
    frontend/src/components/builder/BulkActionBar.tsx,
    frontend/src/components/builder/__tests__/BulkActionBar.test.tsx,
    frontend/src/pages/MapBuilderPage.tsx,
    frontend/src/i18n/locales/en/builder.json,
    frontend/src/i18n/locales/de/builder.json,
    frontend/src/i18n/locales/es/builder.json,
    frontend/src/i18n/locales/fr/builder.json
  </files>
  <read_first>
    frontend/src/api/maps.ts (lines 140-152 — pattern for removeLayerFromMapApi, copy this shape),
    frontend/src/components/builder/hooks/use-builder-layers.ts (lines 538-580 — current handleBulkDelete),
    frontend/src/components/builder/hooks/__tests__/use-builder-layers.bulk-ops.test.ts (existing bulk-ops tests — patterns + mocks),
    frontend/src/components/builder/BulkActionBar.tsx (props at lines 22-32, Delete confirm at line 156-180),
    frontend/src/components/builder/__tests__/BulkActionBar.test.tsx,
    frontend/src/i18n/locales/en/builder.json (bulkActions keys at line 766),
    .planning/phases/1047-perf-and-code-quality-fixes/1047-UI-SPEC.md (PERF-03 interaction contract + copywriting)
  </read_first>
  <behavior>
    - Test 1: `bulkDeleteLayersApi(mapId, ['a','b','c'])` calls `apiFetch('/maps/{mapId}/layers/bulk-delete', { method: 'POST', body: JSON.stringify({ layer_ids: ['a','b','c'] }) })` exactly once and resolves with `{ deleted, failed }`
    - Test 2: `handleBulkDelete` with 50 selected ids issues exactly ONE network call (verified via mocked apiFetch call count)
    - Test 3: `handleBulkDelete` full-success path: BulkActionBar shows isDeleting=true during the call, then layers are removed and `toast.success` fires with copy `"50 layers deleted"`
    - Test 4: `handleBulkDelete` full-rollback path (response has all ids in `failed`): local state is rolled back to previousLayers and `toast.error` fires with copy `"Delete failed — no changes were made."`
    - Test 5: `handleBulkDelete` partial-failure path: deleted layers stay removed, failed layers remain in stack + selected; `toast.error` fires with action button labeled `"Retry"` and copy `"{deleted} of {count} layers deleted. {failed} failed."`
    - Test 6: BulkActionBar with `isDeleting={true}` renders Loader2 spinner in place of Trash2 icon; Delete button has `disabled` and `aria-busy="true"`
    - Test 7: BulkActionBar aria-live region announces `"Deleting {count} layers…"` when isDeleting=true
  </behavior>
  <action>
    **API client** (frontend/src/api/maps.ts): add `export async function bulkDeleteLayersApi(mapId: string, layerIds: string[]): Promise<{ deleted: string[]; failed: { id: string; reason: string }[] }>` that does `return apiFetch(\`/maps/${mapId}/layers/bulk-delete\`, { method: 'POST', body: JSON.stringify({ layer_ids: layerIds }) });`. Add the response type to `frontend/src/types/api.ts` if you'd prefer to centralize it — name it `MapLayerBulkDeleteResponse`.

    **i18n keys** — add the 5 new keys to `bulkActions` namespace in `frontend/src/i18n/locales/en/builder.json` AND mirror to de/es/fr (use translations consistent with existing `errorDeleteRolledBack` style — for non-en, use the same English placeholder with a clear TODO comment OR provide a best-effort translation; the project has a 770-key parity requirement so all four locales MUST stay in sync). Keys:
    - `bulkActions.deletingLayers`: "Deleting {{count}} layers…"
    - `bulkActions.deleteSuccess`: "{{count}} layers deleted"
    - `bulkActions.deletePartialFailure`: "{{deleted}} of {{count}} layers deleted. {{failed}} failed."
    - `bulkActions.deleteRollback`: "Delete failed — no changes were made."  (this REPLACES messaging for the existing `errorDeleteRolledBack` callsite; keep `errorDeleteRolledBack` as a deprecated alias for now to avoid breaking other call sites — Plan 06 P1 sweep can fully retire it)
    - `bulkActions.retryAction`: "Retry"

    **use-builder-layers.ts handleBulkDelete rewrite** (lines 538-580): replace the `Promise.allSettled(idsToDelete.map(id => removeLayerFromMapApi(mapId, id)))` block with a single call: `const result = await bulkDeleteLayersApi(mapId, idsToDelete);`. Handle three cases:
    1. `result.failed.length === 0`: full success. Stay optimistic. Invalidate `['map', mapId]` query. `toast.success(t('bulkActions.deleteSuccess', { count: idsToDelete.length }))`. Return true.
    2. `result.deleted.length === 0`: full rollback. `setLocalLayers(previousLayers)`. `toast.error(t('bulkActions.deleteRollback'))`. Return false.
    3. partial: keep deleted, restore failed back into localLayers (find each failed.id in previousLayers and re-insert at its sort_order; renumber sort_order). `toast.error(t('bulkActions.deletePartialFailure', { deleted: result.deleted.length, count: idsToDelete.length, failed: result.failed.length }), { action: { label: t('bulkActions.retryAction'), onClick: () => handleBulkDelete(new Set(result.failed.map(f => f.id))) } })`. Return false.
    Wrap the entire mutation in a `setIsDeleting(true) ... finally { setIsDeleting(false) }` pattern. Expose `isDeleting` from the hook's return.

    Add `const [isDeleting, setIsDeleting] = useState(false);` near the top of use-builder-layers.ts. Add `isDeleting` to the hook's returned object.

    **MapBuilderPage.tsx** wiring: extract `isDeleting` from `useBuilderLayers` return; pass `isDeleting={isDeleting}` to `<BulkActionBar>` and through `<UnifiedStackPanel>` if the panel re-exports the prop. Update both BulkActionBar render sites (MapBuilderPage AND UnifiedStackPanel — read the file to confirm both pass-through paths).

    **BulkActionBar.tsx** prop addition: add `isDeleting?: boolean` to `BulkActionBarProps`. Inside the component, when `isDeleting === true`: (a) the Delete button trash icon (`<Trash2 />`) is replaced with `<Loader2 className="size-4 animate-spin" />`; (b) the button has `disabled={isDeleting}` and `aria-busy={isDeleting}`; (c) the aria-live region announces `t('bulkActions.deletingLayers', { count: N })` instead of the existing selectedCount message. Import `Loader2` from `lucide-react`.

    **Tests**: extend `use-builder-layers.bulk-ops.test.ts` with the 5 handleBulkDelete tests (mock bulkDeleteLayersApi response shapes). Extend `BulkActionBar.test.tsx` with the 2 isDeleting tests (render with isDeleting={true}, assert spinner + disabled + aria-busy).
  </action>
  <verify>
    <automated>cd frontend && npm run test -- --run src/components/builder/hooks/__tests__/use-builder-layers.bulk-ops.test.ts src/components/builder/__tests__/BulkActionBar.test.tsx</automated>
    <automated>cd frontend && grep -c "bulkDeleteLayersApi" src/api/maps.ts src/components/builder/hooks/use-builder-layers.ts | grep -v ':0'</automated>
    <automated>cd frontend && rg -n "removeLayerFromMapApi" src/components/builder/hooks/use-builder-layers.ts | grep -v 'test' | wc -l | grep -E '^0$'</automated>
    <automated>cd frontend && npm run test:i18n</automated>
    <automated>cd frontend && for k in deletingLayers deleteSuccess deletePartialFailure deleteRollback retryAction; do for l in en de es fr; do grep -q "\"$k\"" src/i18n/locales/$l/builder.json || { echo "MISSING $k in $l"; exit 1; }; done; done; echo OK</automated>
    <automated>cd frontend && npm run typecheck</automated>
  </verify>
  <acceptance_criteria>
    - `bulkDeleteLayersApi` exported from frontend/src/api/maps.ts
    - `handleBulkDelete` issues exactly ONE network call (verified by mock call count in test)
    - `removeLayerFromMapApi` is no longer referenced in use-builder-layers.ts (rg count 0 in non-test code) — the function stays in api/maps.ts for the per-layer delete kebab-menu action; only the bulk path migrates
    - 5 new i18n keys present in all 4 locales (en/de/es/fr); test:i18n passes (parity check)
    - BulkActionBar isDeleting prop swaps icon + disables + sets aria-busy + announces "Deleting N layers…"
    - 7 behavior tests pass
    - Typecheck clean
  </acceptance_criteria>
  <done>One batched HTTP call replaces N parallel calls; user sees spinner + accurate toast copy in success/rollback/partial paths.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Memoize BulkActionBar handlers + UnifiedStackPanel selection state (PB-05, PB-08)</name>
  <files>
    frontend/src/pages/MapBuilderPage.tsx,
    frontend/src/components/builder/UnifiedStackPanel.tsx,
    frontend/src/components/builder/__tests__/BulkActionBar.test.tsx,
    e2e/perf/builder-large-map.spec.ts
  </files>
  <read_first>
    frontend/src/pages/MapBuilderPage.tsx (handleBulk* definitions around line 380-470, render site at line 1015-1030 — find where handleBulkVisibility/Opacity/Group/Ungroup/Delete are defined and ensure they're useCallback-wrapped),
    frontend/src/components/builder/UnifiedStackPanel.tsx (1037 LOC — find selectedIds usage, the BulkActionBar render at line 1024, the map of StackRow children, and any per-row computation that depends on selectedIds),
    frontend/src/components/builder/StackRow.tsx (memo'd at line 98 — confirm its memo comparison),
    frontend/src/components/builder/BulkActionBar.tsx (line 45 — already memo'd),
    .planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-PERF-BASELINE.md (PERF-02 + PB-05 + PB-08 sections)
  </read_first>
  <behavior>
    - Test 1: Hovering an unselected StackRow does NOT cause its sibling StackRows to re-render (verified via React DevTools profiler in a synthetic test using `Profiler` API + render counter)
    - Test 2: Toggling selection of one row in a 50-row stack causes only the toggled row AND BulkActionBar to re-render; other 49 rows do not re-render (Profiler assertion)
    - Test 3: Playwright assertion in e2e/perf/builder-large-map.spec.ts: open the 50-layer test map, measure `performance.mark('hover-start')` → `page.hover(stackRow[10])` → `performance.mark('hover-end')` → `performance.measure(...)` → assert duration < 30ms p50 (per PERF-02 Recommended Target)
    - Test 4: Playwright assertion: bulk-delete N=50 selects all → click Delete → assert exactly 1 network request to `/maps/*/layers/bulk-delete` AND wall-clock < 600ms (PERF-03 target)
  </behavior>
  <action>
    **MapBuilderPage.tsx**: read the handler definitions (around line 380-470). Each `handleBulkVisibility`, `handleBulkOpacity`, `handleBulkGroup`, `handleBulkUngroup`, `handleBulkDelete` MUST be defined via `useCallback(..., [stableDeps])` with dependency arrays that exclude `selectedIds` (the selectedIds is passed as an ARGUMENT, not closed over). The comment at line 391 says "Depending on `layers` defeats React.memo() on BulkActionBar / UnifiedStackPanel" — confirm the existing useCallback patterns already follow this; if any handler closes over `layers` directly, refactor to use `layersRef.current` (already established pattern in use-builder-layers.ts line ~100) so the callback identity stays stable.

    **UnifiedStackPanel.tsx**: this is the big one. Read the 1037 LOC file. Identify any computation that:
    1. Depends on `selectedIds` (a Set, identity changes every selection update)
    2. Is passed as a prop to every StackRow

    Such computations cause all 50 StackRows to re-render whenever `selectedIds` changes. The fix is to compute "is row selected" INSIDE each row (cheap O(1) Set.has lookup) rather than pre-computing per-row selection state in the parent.

    Specifically: if the panel passes `isSelected={selectedIds.has(layer.id)}` to each StackRow, that's already optimal (the boolean is computed per-row but StackRow's memo() with default shallow comparison won't re-render when its own isSelected is unchanged). BUT if there's a derived `selectedRowMap` or `selectionMeta` computed at the panel level, that derived value's identity changes on every selection, breaking the memo.

    Action: scan UnifiedStackPanel for any `useMemo` whose dep array contains `selectedIds`. For each one, verify it produces a STABLE output when the user's hover/click does not change the actual selection (e.g., a memo that returns `selectedIds.size > 0` is fine — the boolean is referentially equal across renders; but a memo that returns `Array.from(selectedIds)` is NOT fine, the array identity changes). Refactor as needed.

    Add `useCallback` to any inline arrow functions passed to StackRow (e.g., `onClick={() => handleClick(layer.id)}`). Hoist these to stable per-row callbacks using a per-id factory pattern OR pass `onClick={handleRowClick}` and let StackRow destructure `layer.id` from its own props to call back with.

    Specifically check the BulkActionBar render at line 1024 of UnifiedStackPanel: `<BulkActionBar selectedIds={selectedIds} layers={layers} onBulkVisibility={onBulkVisibility} ... />`. `selectedIds` is a new Set each toggle, so memo will always re-render BulkActionBar — that's CORRECT behavior, BulkActionBar legitimately needs the new selection. PB-08 wanted memoization on `handlers`, not on selectedIds. Confirm: all 5 `onBulk*` props are stable refs from MapBuilderPage's useCallbacks (Task 3 first paragraph already covers this). The remaining concern: BulkActionBar internally re-renders fully on every selection change. That's the design — accept it. The PERF-02 win comes from preventing StackRow re-renders, not BulkActionBar.

    **Test 3 + Test 4 (Playwright)**: extend `e2e/perf/builder-large-map.spec.ts` (the scaffold from Plan 01 Task 3). Add two assertions:
    1. Input-latency test using `performance.mark()` + `performance.measure()` via `page.evaluate()`. Hover an inner StackRow, measure, assert duration < 30ms p50 across 10 hovers (report p95 too for observability).
    2. Bulk-delete throughput test: select all 50 layers (use the Select-All affordance if it exists, OR ctrl-click each row), click Delete, click Confirm. Use `page.route('**/layers/bulk-delete', ...)` to count requests; assert exactly 1. Measure wall-clock from confirm click to optimistic UI update; assert < 600ms.

    Add a render-counter test for Tests 1 + 2 using React Profiler — file: `frontend/src/components/builder/__tests__/UnifiedStackPanel.render-perf.test.tsx`. Mount a 50-layer panel, use `<Profiler onRender={mockOnRender}>`, trigger selection toggle, assert `mockOnRender` was called for ≤ 2 components per toggle (the toggled row + BulkActionBar mounting). Note: React's render-batching means this test is fragile; prefer asserting CALL COUNT relative to the 50-row baseline rather than absolute counts.
  </action>
  <verify>
    <automated>cd frontend && npm run test -- --run src/components/builder/__tests__/BulkActionBar.test.tsx</automated>
    <automated>cd frontend && npm run test -- --run src/components/builder/__tests__/UnifiedStackPanel.render-perf.test.tsx 2>&1 | tail -20 || echo "render-perf test optional"</automated>
    <automated>cd frontend && npm run typecheck</automated>
    <automated>cd frontend && rg -n "useMemo.*selectedIds" src/components/builder/UnifiedStackPanel.tsx</automated>
    <automated>npx playwright test e2e/perf/builder-large-map.spec.ts --list --project=chromium 2>&1 | grep -E "input-latency|bulk-delete"</automated>
  </verify>
  <acceptance_criteria>
    - All `handleBulk*` definitions in MapBuilderPage are wrapped in useCallback with stable deps (selectedIds NOT in dep arrays)
    - Any UnifiedStackPanel `useMemo([..., selectedIds])` that produces a non-primitive derived value is reviewed; documentation comment added or refactored to return primitives
    - Playwright spec has two new assertions: input-latency < 30ms p50; bulk-delete = 1 request + < 600ms wall-clock
    - Render-perf test exists OR an explicit deferral comment in PLAN-04-SUMMARY explains why (Profiler API tests are notoriously fragile)
    - Typecheck clean
  </acceptance_criteria>
  <done>Hovers don't cascade through 50 rows; bulk-delete e2e proves 1-request + < 600ms wall-clock.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Client → backend bulk-delete | Untrusted layer_ids array crosses the boundary; backend validates ownership before deletion. |
| User → optimistic UI | Local stack mutates before backend confirms; failure path must restore exact prior order. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1047-04-01 | Tampering | bulk_delete_layers endpoint payload | mitigate | Pydantic schema validates UUID format + length cap (1-200) at route entry; service queries with `WHERE map_id=:m AND id=ANY(:ids)` so cross-map deletion is impossible. |
| T-1047-04-02 | Elevation of Privilege | Cross-map delete via crafted layer_ids | mitigate | `check_map_ownership` runs BEFORE the bulk delete; the SQL filter binds map_id explicitly, so foreign layer_ids return "not_found" in the failed array rather than being deleted. |
| T-1047-04-03 | Repudiation | Bulk delete without audit | mitigate | Single audit event `map.bulk_remove_layers` + single map_history record with `target_type="layer"` + action="layer.bulk_remove" — covered by Test 7/8 in Task 1. |
| T-1047-04-04 | DoS | Oversized layer_ids array | mitigate | Schema rejects len > 200 (matches `_MAX_LAYERS_PER_MAP` in schemas.py). |
| T-1047-04-05 | Tampering | Race: layer added between optimistic remove and server response | accept | Optimistic UI invalidates `['map', mapId]` on completion, refetching server truth. If race occurs, refetch reveals the late-added layer. Acceptable for v1. |
| T-1047-04-SC | Tampering | npm/pip installs | mitigate | No new packages introduced in this plan. |
</threat_model>

<verification>
- Backend: `cd backend && uv run pytest tests/test_maps_bulk_layers.py -x` — green
- Backend: `cd backend && uv run ruff check app/modules/catalog/maps/` — clean
- Frontend: `cd frontend && npm run test` — green
- Frontend: `cd frontend && npm run typecheck` — clean
- i18n parity: `cd frontend && npm run test:i18n` — pass
- Playwright spec compiles: `npx playwright test e2e/perf/builder-large-map.spec.ts --list` includes the two new test names
- Full e2e:smoke run deferred to Plan 06
</verification>

<success_criteria>
1. `POST /api/maps/{map_id}/layers/bulk-delete` ships with 8 backend tests passing.
2. `bulkDeleteLayersApi` frontend client exists and `handleBulkDelete` issues exactly ONE network call for N selected layers.
3. BulkActionBar `isDeleting` prop swaps Trash2 → Loader2, disables button, sets aria-busy=true, announces "Deleting N layers…".
4. Toast copy matches UI-SPEC: success / partial-failure (with Retry action) / full-rollback. All 5 new keys in en/de/es/fr.
5. PERF-02 + PERF-03 Playwright assertions exist: input-latency < 30ms p50; bulk-delete = 1 request + < 600ms wall-clock.
</success_criteria>

<output>
Create `.planning/phases/1047-perf-and-code-quality-fixes/1047-04-SUMMARY.md` when done. Include:
- Backend endpoint contract (route + request/response shape)
- Single-call HTTP cutover: 50 requests → 1 (cite test name proving this)
- New i18n keys list + locale parity confirmation
- Playwright before/after timing measurements (if Docker available; else mark "measured by user during final smoke")
- BulkActionBar isDeleting prop addition (note any consumers besides MapBuilderPage)
</output>
