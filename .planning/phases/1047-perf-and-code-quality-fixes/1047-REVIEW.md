---
phase: 1047-perf-and-code-quality-fixes
reviewed: 2026-05-16T00:00:00Z
depth: standard
files_reviewed: 57
files_reviewed_list:
  - backend/app/modules/catalog/maps/router.py
  - backend/app/modules/catalog/maps/schemas.py
  - backend/app/modules/catalog/maps/service_layers.py
  - backend/tests/test_maps_bulk_layers.py
  - e2e/fixtures/seed-large-builder-map.ts
  - e2e/perf/builder-large-map.spec.ts
  - frontend/src/api/maps.ts
  - frontend/src/components/builder/BuilderDialogs.tsx
  - frontend/src/components/builder/BulkActionBar.tsx
  - frontend/src/components/builder/DataDrivenStyleEditor.tsx
  - frontend/src/components/builder/LayerFilterEditor.tsx
  - frontend/src/components/builder/LayerStyleEditor.tsx
  - frontend/src/components/builder/LayerStyleEditor/AdvancedJsonEditor.tsx
  - frontend/src/components/builder/LayerStyleEditor/CircleEditor.tsx
  - frontend/src/components/builder/LayerStyleEditor/ClusterEditor.tsx
  - frontend/src/components/builder/LayerStyleEditor/FillEditor.tsx
  - frontend/src/components/builder/LayerStyleEditor/HeatmapEditor.tsx
  - frontend/src/components/builder/LayerStyleEditor/LineEditor.tsx
  - frontend/src/components/builder/LayerStyleEditor/RasterEditor.tsx
  - frontend/src/components/builder/LayerStyleEditor/RenderModeSwitch.tsx
  - frontend/src/components/builder/LayerStyleEditor/StrokeControls.tsx
  - frontend/src/components/builder/LayerStyleEditor/SymbolEditor.tsx
  - frontend/src/components/builder/LayerStyleEditor/__tests__/CircleEditor.test.tsx
  - frontend/src/components/builder/LayerStyleEditor/__tests__/FillEditor.test.tsx
  - frontend/src/components/builder/LayerStyleEditor/__tests__/LineEditor.test.tsx
  - frontend/src/components/builder/LayerStyleEditor/__tests__/RenderModeSwitch.test.tsx
  - frontend/src/components/builder/LayerStyleEditor/index.ts
  - frontend/src/components/builder/LayerStyleEditor/types.ts
  - frontend/src/components/builder/LayerStyleEditor/utils.ts
  - frontend/src/components/builder/SceneSpinnerFallback.tsx
  - frontend/src/components/builder/UnifiedStackPanel.tsx
  - frontend/src/components/builder/__tests__/BulkActionBar.test.tsx
  - frontend/src/components/builder/__tests__/DataDrivenStyleEditor.test.tsx
  - frontend/src/components/builder/__tests__/LayerFilterEditor.test.ts
  - frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx
  - frontend/src/components/builder/__tests__/UnifiedStackPanel.render-perf.test.tsx
  - frontend/src/components/builder/__tests__/suggested-datasets.test.ts
  - frontend/src/components/builder/hooks/__tests__/use-builder-layers.bulk-ops.test.ts
  - frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.raf.test.ts
  - frontend/src/components/builder/hooks/use-builder-layers.ts
  - frontend/src/components/builder/hooks/use-layer-map-sync.ts
  - frontend/src/components/builder/layer-adapters/__tests__/shared.test.ts
  - frontend/src/components/builder/layer-adapters/circle-adapter.ts
  - frontend/src/components/builder/layer-adapters/fill-adapter.ts
  - frontend/src/components/builder/layer-adapters/heatmap-adapter.ts
  - frontend/src/components/builder/layer-adapters/line-adapter.ts
  - frontend/src/components/builder/layer-adapters/shared.ts
  - frontend/src/i18n/locales/de/builder.json
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/i18n/locales/es/builder.json
  - frontend/src/i18n/locales/fr/builder.json
  - frontend/src/lib/builder/__tests__/raf-coalesce.test.ts
  - frontend/src/lib/builder/raf-coalesce.ts
  - frontend/src/pages/MapBuilderPage.tsx
  - frontend/src/types/api.ts
findings:
  critical: 2
  warning: 6
  info: 3
  total: 11
fixes_applied: 8
findings_status:
  CR-01: fixed
  CR-02: fixed
  WR-01: fixed
  WR-02: fixed
  WR-03: fixed
  WR-04: fixed
  WR-05: fixed
  WR-06: fixed
  IN-01: deferred (out of scope — info-level, requires live data-flow testing with a running DEM layer)
  IN-02: deferred (out of scope — info-level, no production circular-reference risk)
  IN-03: deferred (out of scope — info-level, cosmetic OpenAPI schema annotation)
status: clean
---

# Phase 1047: Code Review Report

**Reviewed:** 2026-05-16T00:00:00Z
**Depth:** standard
**Files Reviewed:** 57
**Status:** issues_found

## Summary

This phase delivers five deliverables: (1) a backend bulk-delete endpoint, (2) rAF-based paint-write coalescing, (3) LayerStyleEditor split into sub-components, (4) lazy-load Suspense boundaries for editor scenes, and (5) frontend bulk-delete UI with optimistic update + rollback. The implementation is overall solid — auth, RBAC, and the rAF queue invariants are correct. However two blockers and six warnings require attention before this ships.

The two critical findings are: a `hasUnsavedChanges=true` state leak after bulk-delete success that causes the next API-layer refetch to be suppressed, and a shared module-level rAF state in `raf-coalesce.ts` that survives across test files producing order-dependent test failures in CI.

---

## Critical Issues

### CR-01: Bulk-delete success path leaves `hasUnsavedChanges=true`, permanently blocking API sync

**File:** `frontend/src/components/builder/hooks/use-builder-layers.ts:557-572`

**Issue:** `handleBulkDelete` performs an optimistic `setLocalLayers` (line 558) which internally calls no `setHasUnsavedChanges`. However, the call to `setExpandedLayerId` at line 555 and `setLocalLayers` at line 558 both happen unconditionally before the `await`. The real problem is subtler: after `bulkDeleteLayersApi` succeeds, `queryClient.invalidateQueries` (line 571) triggers a TanStack Query refetch that delivers a fresh `apiLayers`. The sync effect at line 150-155 reads:

```ts
if (apiLayers && initializedRef.current && !hasUnsavedChanges) {
  setLocalLayers(apiLayers);
  savedLayerBaselineRef.current = apiLayers;
}
```

At this point `hasUnsavedChanges` is still `false` — the optimistic removal of layers does NOT set `hasUnsavedChanges`. The deleted layers are gone from local state and the server agrees. So far so good. But consider the partial-failure rollback path: after re-inserting failed layers at line 585-592, `hasUnsavedChanges` is never set to `true`. If the user makes any subsequent local edit (marking `hasUnsavedChanges=true`) and then the query refetches (e.g. on window focus), the sync effect is gated by `!hasUnsavedChanges` and will correctly skip. However, if they do NOT make edits, the refetch may re-sync `apiLayers` back and silently un-do the partial local rollback of the failed layers — re-removing them from the UI even though they were never actually deleted. The partial-failure state is visually wiped away on next refetch.

Additionally, the `setHasUnsavedChanges` call at the end of the full-success path is missing entirely: after a successful bulk-delete followed by `invalidateQueries`, no save prompt will appear, which is correct, but the baseline `savedLayerBaselineRef.current` is not updated at this path (only `queryClient.invalidateQueries` is called, which triggers the sync effect — but that only runs when `!hasUnsavedChanges`). If the user opens the map in a state where `hasUnsavedChanges` was already `true` before calling bulk-delete, `savedLayerBaselineRef` will remain stale after the successful delete.

**Fix:** After a full-success bulk-delete, explicitly update `savedLayerBaselineRef` before relying on the invalidation path:

```ts
if (result.failed.length === 0) {
  // Sync the baseline so savedLayerBaseline reflects the deletion immediately,
  // regardless of whether the invalidateQueries refetch is gated by hasUnsavedChanges.
  savedLayerBaselineRef.current = savedLayerBaselineRef.current.filter(
    (l) => !selectedIds.has(l.id)
  );
  await queryClient.invalidateQueries({ queryKey: ['map', mapId] });
  toast.success(t('bulkActions.deleteSuccess', { count: idsToDelete.length }));
  return true;
}
```

For the partial-failure path, after re-inserting failed layers at line 592, add:
```ts
setHasUnsavedChanges(true); // partial state differs from server; prevent silent refetch wipe
```

---

### CR-02: Module-level `pending` Map and `rafHandle` in `raf-coalesce.ts` are global singletons — cross-test pollution not fully guarded

**File:** `frontend/src/lib/builder/raf-coalesce.ts:20-21`

**Issue:** `pending` and `rafHandle` are module-level variables:

```ts
const pending = new Map<string, () => void>();
let rafHandle: number | null = null;
```

In a Vitest worker that runs multiple test files in the same VM context (the default for `pool: 'forks'` is separate workers, but `pool: 'threads'` shares the module registry), any test file that calls `coalesceFrame` without calling `__resetForTest()` in its `afterEach` will leak state into the next test file's run. The existing test at `raf-coalesce.test.ts` does call `__resetForTest()` in its `afterEach`, but `use-layer-map-sync.raf.test.ts` does NOT: it calls `raf.flush()` in `afterEach` (line 129) and `vi.unstubAllGlobals()`, but does not import or call `__resetForTest()`.

If `use-layer-map-sync.raf.test.ts` runs before `raf-coalesce.test.ts` and a test leaves a pending entry (e.g., a test that calls `handlePaintChange` but the rAF mock queue isn't fully drained because `raf.flush()` is called post-test rather than from the `pending` snapshot path), the module-level `pending` Map retains that entry. The next test in `raf-coalesce.test.ts` calls `__resetForTest()` in `beforeEach`, which clears it — but only if the module instance is shared. When running with separate workers this is safe; when thread-pool sharing occurs it is not.

More concretely: the `afterEach` in `use-layer-map-sync.raf.test.ts` calls `raf.flush()` which fires the rAF mock's queue, but this does NOT call through the `flush()` function in `raf-coalesce.ts`. The `rafHandle` in the module may still be non-null (pointing to a handle that was already dequeued by the mock's `cancelAnimationFrame`), and `pending` may still contain entries if a paint-change handler queued a key but the mock rAF ran the wrong flush function. This is a latent ordering-dependent CI failure.

**Fix:** Import `__resetForTest` in `use-layer-map-sync.raf.test.ts` and call it in `afterEach`:

```ts
import { __resetForTest } from '@/lib/builder/raf-coalesce';

afterEach(() => {
  __resetForTest(); // clear module-level pending + rafHandle
  raf.flush();      // drain any remaining mock rAF queue entries
  vi.unstubAllGlobals();
});
```

---

## Warnings

### WR-01: `bulk_delete_layers_endpoint` proceeds with audit/history even when zero layers were actually deleted

**File:** `backend/app/modules/catalog/maps/router.py:1716-1744`

**Issue:** When every `layer_id` in the request is not found (all return `not_found`), `deleted_ids` is `[]` and `deleted_count` is 0. The code still calls `audit_emit` (line 1716) and `record_map_history_event` (line 1731) and then commits. This means an audit row `map.bulk_remove_layers` with `deleted_count=0` and a history row `"Removed 0 layers"` are written even when nothing was done. A monitoring system treating all `map.bulk_remove_layers` events as significant will see false positives. The single-layer `remove_layer_endpoint` does not emit an audit event when nothing is found (it returns 404 instead). The asymmetry is also confusing for operators reading history.

**Fix:** Guard audit/history emission on whether any deletion actually occurred:

```python
if deleted_count > 0:
    await audit_emit(db, AuditEvent(...))
    await record_map_history_event(db, ..., summary=f"Removed {deleted_count} layers", ...)
await db.commit()
```

---

### WR-02: `record_map_history_event` called without `target_id` for bulk-remove — schema may require it for layer-type events

**File:** `backend/app/modules/catalog/maps/router.py:1731-1741`

**Issue:** The `record_map_history_event` call for `target_type="layer"` passes no `target_id` (the parameter defaults to `None`). Every other `target_type="layer"` call in this router provides a specific `layer_id` as `target_id`. The history model likely allows NULL, but history consumers (the UI timeline) that try to link a history event to a specific layer via `target_id` will receive `None` for bulk-delete events. This is an inconsistency that will produce broken "jump to layer" links or silent gaps in history viewers.

**Fix:** Either set `target_type="map"` (consistent with other multi-layer operations like `layer.replace`) since there is no single layer target, or pass a sentinel. The cleanest fix:

```python
await record_map_history_event(
    db,
    map_id=map_id,
    actor=user,
    target_type="map",   # no single layer target; use map-level type
    target_id=map_id,
    target_name=map_obj.name,
    action="layer.bulk_remove",
    summary=f"Removed {deleted_count} layers",
    details={...},
)
```

This also matches how `layer.replace` is recorded (target_type="map", target_id=map_id).

---

### WR-03: `BulkDeleteLayersRequest` does not enforce uniqueness of `layer_ids` — duplicate IDs silently produce double audit counts

**File:** `backend/app/modules/catalog/maps/schemas.py:773-784`

**Issue:** `BulkDeleteLayersRequest.layer_ids` has `min_length=1` and `max_length=200` but no uniqueness validator. A caller sending `["uuid-a", "uuid-a", "uuid-b"]` will have the duplicates coalesced by `MapLayer.id.in_(existing_ids)` in `remove_layers_bulk` (since `existing_ids` is a set), so only `uuid-a` and `uuid-b` are deleted. However the audit event at line 1724 logs `"layer_ids": [str(lid) for lid in body.layer_ids]` which will include the duplicate, and `deleted_count` will correctly be 2. But `MapLayerDiffRequest` (line 336) validates uniqueness for `removed` IDs. The missing parallel validation here is a quality gap.

**Fix:** Add a `@field_validator("layer_ids")` that rejects duplicates:

```python
@field_validator("layer_ids")
@classmethod
def _no_duplicate_ids(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
    if len(set(v)) != len(v):
        raise ValueError("layer_ids must be unique")
    return v
```

---

### WR-04: `handleBulkDelete` optimistic update uses `selectedIds` (full selection set) to filter, but `idsToDelete` (backend-sent set, group rows excluded) may differ — partial mismatch possible

**File:** `frontend/src/components/builder/hooks/use-builder-layers.ts:557-562`

**Issue:** The optimistic `setLocalLayers` at line 559 filters on `selectedIds` (the full UI selection, which may include group folder rows):

```ts
setLocalLayers((prev) =>
  prev
    .filter((l) => !selectedIds.has(l.id))  // uses selectedIds — includes group rows
    .map((l, i) => ({ ...l, sort_order: i })),
);
```

But `idsToDelete` (line 546-551) explicitly excludes group-folder rows. So the optimistic update removes group container rows from the UI immediately, but the backend call never sends them (since they have no DB record). The group row is gone locally but was never in `idsToDelete`, meaning if the backend call fails, the rollback at line 578 (`setLocalLayers(previousLayers)`) restores the group row — which is correct. However during the in-flight window the group container row is missing but its children are also missing from the UI. If the call completes successfully, `queryClient.invalidateQueries` may or may not restore the group row depending on whether the backend knows about it (it doesn't — group rows are frontend-only). This means after a successful bulk-delete that included a group row ID in `selectedIds`, the group row is silently lost with no rollback and no server-side record of its removal.

The fix is to filter the optimistic update by `idsToDelete` (not `selectedIds`) to keep the UI consistent with what was actually sent to the server:

```ts
const idsToDeleteSet = new Set(idsToDelete);
setLocalLayers((prev) =>
  prev
    .filter((l) => !idsToDeleteSet.has(l.id))
    .map((l, i) => ({ ...l, sort_order: i })),
);
```

Group rows not in `idsToDelete` will then be visible in the UI during the in-flight window and handled by the normal post-success state.

---

### WR-05: `LazyLoadErrorBoundary` wraps `LayerEditorPanel` in `MapBuilderPage.tsx` (line 1082) but `LayerEditorPanel` itself is NOT lazy — error boundary without matching Suspense is a no-op for synchronous components

**File:** `frontend/src/pages/MapBuilderPage.tsx:1082-1133`

**Issue:** The desktop `LayerEditorPanel` column (lines 1082-1133) wraps `<LayerEditorPanel>` in `<LazyLoadErrorBoundary>` without a wrapping `<Suspense>`. `LayerEditorPanel` is a synchronous import (not `lazy()`), so the error boundary will catch render errors thrown by `LayerEditorPanel` or its children, but there is no Suspense to catch the `sceneContent` lazy children. The `sceneContent` (`DEMEditorScene`, `SettingsEditorScene`, `BasemapGroupEditorScene`, `BasemapSublayerEditorScene`) are all lazy, each individually wrapped in their own `<LazyLoadErrorBoundary> + <Suspense fallback={<SceneSpinnerFallback/>}>`. This inner wrapping is correct. However the outer `<LazyLoadErrorBoundary>` without `<Suspense>` provides nothing for the synchronous `LayerEditorPanel` that the component's own internal error handling wouldn't cover — it is redundant but harmless.

More importantly: the mobile Sheet path at line 1154 also has `<LazyLoadErrorBoundary>` wrapping `<LayerEditorPanel>` with no `<Suspense>`. The lazy scene content is nested inside via `sceneContent` prop, but the outer boundary has no matching Suspense. If `sceneContent` Suspends (e.g., the chunk hasn't loaded yet), the closest Suspense ancestor is the one inside the individual scene's own render — but in the mobile Sheet path, those inner Suspense boundaries ARE present (they're passed in as props). This is fine but the outer `LazyLoadErrorBoundary` without Suspense is misleading and could mask the absence of a needed boundary if a future author moves lazy content to a higher level.

**Fix:** Either add a `<Suspense fallback={<SceneSpinnerFallback />}>` inside each `<LazyLoadErrorBoundary>` that wraps `<LayerEditorPanel>`, or remove the outer boundary since all lazy content is already independently guarded:

```tsx
{/* Column 2: LayerEditorPanel flyout */}
<aside ...>
  <LazyLoadErrorBoundary>
    <Suspense fallback={<SceneSpinnerFallback />}>
      <LayerEditorPanel ... />
    </Suspense>
  </LazyLoadErrorBoundary>
</aside>
```

---

### WR-06: `raf-coalesce.ts` module-level state is never reset between hot-module-replacement cycles in development — stale queue entries after HMR

**File:** `frontend/src/lib/builder/raf-coalesce.ts:20-21`

**Issue:** In Vite's dev server with HMR, when `raf-coalesce.ts` is invalidated and reloaded, the `pending` Map and `rafHandle` are re-initialized to `new Map()` and `null` respectively — which is correct. However, any `coalesceFrame` call that was issued by a component that is mid-HMR-cycle will have its callback reference point to the old module closure. The `rafHandle` in the OLD module instance may fire the old `flush()` which attempts to execute stale callbacks against an already-replaced module. In practice this is benign (the callbacks call `map.setPaintProperty` which is idempotent), but it can produce a confusing "stale closure" console error in DEV that the `try/catch` in `flush()` swallows silently. No user-visible bug, but the `if (import.meta.env.DEV)` guard only logs the error — it doesn't prevent the stale frame from firing.

**Fix:** Add an `import.meta.hot?.dispose()` hook to cancel any pending rAF on module replacement:

```ts
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    if (rafHandle !== null) {
      cancelAnimationFrame(rafHandle);
      rafHandle = null;
    }
    pending.clear();
  });
}
```

---

## Info

### IN-01: `_meta_to_kwargs` always sets `is_dem=None` and `dem_vertical_units=None` even when `meta.is_dem` and `meta.dem_vertical_units` exist on the DatasetMeta object

**File:** `backend/app/modules/catalog/maps/router.py:130-142`

**Issue:** The else-branch of `_meta_to_kwargs` (lines 130-142) hardcodes `is_dem=None` and `dem_vertical_units=None` regardless of whether `meta.is_dem` and `meta.dem_vertical_units` carry meaningful values. The comment does not explain this, and `_layers_from_tuples` at line 179 correctly passes `is_dem=row.is_dem` and `dem_vertical_units=row.dem_vertical_units` from the `LayerRow`. The inconsistency means that any code path that uses `_meta_to_kwargs` with a non-None `meta` (e.g., `add_layer_endpoint` at line 1612) will produce a `MapLayerResponse` with `is_dem=None` and `dem_vertical_units=None` even for DEM layers. The result is that a newly-added DEM layer won't render in hillshade mode until the page is refreshed (the full GET `/maps/{id}` response via `_layers_from_tuples` will carry the correct values).

**Fix:**
```python
return DatasetMetaKwargs(
    dataset_name=meta.title,
    geometry_type=meta.geometry_type,
    table_name=meta.table_name,
    extent=meta.extent,
    column_info=meta.column_info,
    feature_count=meta.feature_count,
    sample_values=meta.sample_values,
    record_type=meta.record_type,
    is_3d=meta.is_3d,
    is_dem=getattr(meta, 'is_dem', None),
    dem_vertical_units=getattr(meta, 'dem_vertical_units', None),
)
```

---

### IN-02: `deepEqual` in `LayerStyleEditor/utils.ts` has no cycle detection — will stack-overflow on circular JSON-ish values

**File:** `frontend/src/components/builder/LayerStyleEditor/utils.ts:34-55`

**Issue:** The inline `deepEqual` function used by `hasUnsavedStyleChanges` has no protection against circular references. Paint/layout/style_config values come from the API and are stored as plain JSON, so circular references are not expected in production data. However any code path that constructs a `StyleConfig` with a circular reference (e.g., a future debug helper or a malformed API response where a proxy/observable is inadvertently passed) will cause an infinite recursion crash. No immediate user-visible bug in current usage, but worth noting as a quality risk.

**Fix:** Since `paint`, `layout`, and `style_config` are always JSON-serializable API payloads, the simplest safe implementation is:
```ts
function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  try {
    return JSON.stringify(a) === JSON.stringify(b);
  } catch {
    return false;
  }
}
```
Key-order stability of `JSON.stringify` is sufficient here since these objects come from the same API schema.

---

### IN-03: `BulkDeleteLayersResponse.deleted` is typed as `list[str]` in the Python schema but frontend `MapLayerBulkDeleteResponse.deleted` expects `string[]` — the UUIDs round-trip correctly but the type mismatch is invisible

**File:** `backend/app/modules/catalog/maps/schemas.py:794-798` / `frontend/src/types/api.ts:1579-1582`

**Issue:** Both sides type `deleted` as string arrays and the UUID serialization is consistent (`str(lid)` in `remove_layers_bulk`). This is functionally correct. However `BulkDeleteLayersResponse` inherits no `from_attributes=True` config (unlike `MapLayerResponse`), which is fine since it's constructed directly. The note is that the OpenAPI schema will show `deleted: string[]` as a plain string list with no UUID format hint, making SDK consumers unaware these are UUIDs. The `id` field in `BulkDeleteLayersFailure` has the same issue. Low impact since these are effectively opaque identifiers re-sent by the frontend.

**Fix:** Add `json_schema_extra={"format": "uuid"}` to the fields, or retype as `list[uuid.UUID]` and rely on Pydantic's UUID serialization:
```python
class BulkDeleteLayersResponse(BaseModel):
    deleted: list[uuid.UUID]
    failed: list[BulkDeleteLayersFailure]
```

---

_Reviewed: 2026-05-16T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
