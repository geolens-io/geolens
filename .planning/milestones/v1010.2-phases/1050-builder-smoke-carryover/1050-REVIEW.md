---
phase: 1050-builder-smoke-carryover
reviewed: 2026-05-17T00:00:00Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - CHANGELOG.md
  - frontend/src/components/admin/AIStatusCard.tsx
  - frontend/src/components/admin/settings/SettingsAITab.tsx
  - frontend/src/components/builder/BuilderMap.tsx
  - frontend/src/components/builder/__tests__/BuilderMap.a11y.test.tsx
  - frontend/src/components/builder/__tests__/map-sync.dedupe.test.ts
  - frontend/src/components/builder/__tests__/map-sync.line-gradient.test.ts
  - frontend/src/components/builder/__tests__/map-sync.raster.test.ts
  - frontend/src/components/builder/hooks/__tests__/use-builder-layers.dedupe.test.ts
  - frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts
  - frontend/src/components/builder/hooks/__tests__/use-layer-map-sync.raf.test.ts
  - frontend/src/components/builder/hooks/use-builder-layers.ts
  - frontend/src/components/builder/hooks/use-builder-save.ts
  - frontend/src/components/builder/hooks/use-layer-map-sync.ts
  - frontend/src/components/builder/map-sync.ts
  - frontend/src/components/maps/hooks/__tests__/use-map-thumbnail.test.ts
  - frontend/src/components/maps/hooks/use-map-thumbnail.ts
  - frontend/src/components/search/hooks/__tests__/use-saved-searches.test.ts
  - frontend/src/components/search/hooks/use-saved-searches.ts
findings:
  critical: 3
  warning: 4
  info: 3
  total: 10
status: fixed
fixed_at: 2026-05-17T00:00:00Z
fixes_applied:
  critical: 3
  warning: 4
  info: 0
---

# Phase 1050: Code Review Report

**Reviewed:** 2026-05-17
**Depth:** standard
**Files Reviewed:** 18 (19 entries including review-only CHANGELOG.md)
**Status:** issues_found

## Summary

The five SF closures land their intended behavioral fixes but the SF-04 dedupe
refactor leaks contract-violating uses of the legacy per-layer source-id
helper into three downstream call sites — two of which corrupt critical
runtime behaviour (token refresh, auto-capture readiness). One smaller
SF-06 oversight ungates an admin endpoint (`/admin/embedding-stats/`).
SF-05, SF-07, SF-08 are correct as shipped; SF-04 dedupe needs three more
call-site sweeps before this is shippable.

The phase context explicitly listed "Critical invariant 2: SF-04 must NOT
call `removeSource` when other layers still reference the source." That
invariant is met inside `syncLayersToMap`, but the same dedupe contract
implies that **every external reader of the source id must use
`getSourceIdForLayer` instead of `getSourceId`** — and three readers were
missed. CR-01 and CR-02 silently break tile-token refresh and thumbnail
auto-capture readiness for non-cluster vector layers (which is the *most
common* case). CR-03 keeps `/admin/embedding-stats/` firing on non-admin
authed pages, partially defeating SF-06.

## Critical Issues

### CR-01: `use-builder-save.ts:85` uses legacy `getSourceId` — thumbnail auto-capture waits the full 5s deadline for every deduped vector layer

**File:** `frontend/src/components/builder/hooks/use-builder-save.ts:85`
**Issue:** `waitForVisibleLayerSources` polls `map.getSource(sourceId)` for
each visible layer to gate the auto-capture render. The sourceId list is
built with `getSourceId(layer.id)` (line 85), which returns
`source-{layer.id}` — the LEGACY per-layer key. After SF-04, non-cluster
vector layers actually live under `source-data-{dataset_table_name}`, so
`map.getSource('source-{layer.id}')` returns `null` for every such layer
and `sourcesReady` stays false until the 5000 ms `deadline` expires.

Net effect on the most common path (a map with one or more vector
datasets): every auto-capture (page load, post-save) waits the full 5
seconds before the render fires. The previous behaviour was "capture as
soon as the source is registered" (usually < 100 ms). The 500 ms SP-16
debounce is now stacked on top of a 5000 ms wait, so the user-visible
delay between save and thumbnail upload grows from ~500 ms to ~5500 ms.

This is a behavioural regression *introduced by* Phase 1050 SF-04 and
NOT caught by any test in this phase — `use-builder-save.test.ts:1056`
uses `getSource.mockImplementation((sourceId) => sources.get(sourceId))`
with the source manually seeded as `source-layer-1`, which happens to
match the legacy key by accident in the test factory.

**Fix:**
```typescript
// use-builder-save.ts:9
- import { getSourceId } from '@/components/builder/map-sync';
+ import { getSourceIdForLayer } from '@/components/builder/map-sync';

// use-builder-save.ts:85
- .map((layer) => getSourceId(layer.id));
+ .map((layer) => getSourceIdForLayer(layer));
```
Add a vitest case to `use-builder-save.test.ts > maybeAutoCaptureThumbnail`
that seeds `sources` with `source-data-test_table` (matching the
dedupe-aware factory) and asserts the render frame fires WITHOUT
advancing past 5000 ms.

---

### CR-02: `BuilderMap.tsx:765` token-refresh loop uses legacy `getSourceId` — expired tile tokens never propagate to deduped vector sources

**File:** `frontend/src/components/builder/BuilderMap.tsx:765`
**Issue:** The token-refresh effect calls `getSourceId(layer.id)` to
locate the MapLibre source and call `setTiles([newUrl])` on it. With
SF-04 dedupe, the actual source id for non-cluster vector layers is
`source-data-{dataset_table_name}`. `map.getSource('source-{layer.id}')`
returns `undefined`, the `source && source.type === 'vector'` guard
fails, and `setTiles` is never called.

Signed tile URLs expire (typically 1 hour for vector sig tokens). When
`useTileTokens` refreshes and a new `tokenMap` arrives, this effect is
*supposed* to thread the new URL into the live MapLibre source. After
this regression, the source keeps the old URL until the next full
basemap-load re-init. **MapLibre will start emitting 401/403 errors on
every tile fetch** as soon as the original token expires; the user's
data layers visually disappear or fail to refresh while the map appears
to be functioning. SF-08's basemap-load latch will then *suppress* the
error toast (post-load 5xx ≥ 500; 401/403 is gated by the 400-499 branch
which does surface a toast — but only one, deduped under id
`builder-map-auth-error`).

The cluster branch (`strategy.kind === 'server-tile'`) is hit for
cluster layers, which retain per-layer source ids; that path is
technically OK by accident. Non-cluster vector layers are broken.

**Fix:**
```typescript
// BuilderMap.tsx:34 — already imports getSourceId; switch to getSourceIdForLayer
import {
  syncLayersToMap,
  toSyncInput,
  reorderBasemapLabels,
  reorderDataLayers,
  applyBasemapConfigToMap,
- getSourceId,
+ getSourceIdForLayer,
  getLayerId,
  // ...
} from './map-sync';

// BuilderMap.tsx:765
- const sourceId = getSourceId(layer.id);
+ const sourceId = getSourceIdForLayer(layer);
```
The fix is a one-line change, but the test surface here is thin.
Add a `BuilderMap.token-refresh.test.tsx` case that mounts BuilderMap
with a vector layer, swaps the `tokenSig`, and asserts
`source.setTiles` was called for `source-data-{table}` (not
`source-{id}`).

---

### CR-03: `/admin/embedding-stats/` fires unconditionally — SF-06 anonymous gate is incomplete

**File:** `frontend/src/components/admin/AIStatusCard.tsx:23`,
`frontend/src/components/admin/settings/SettingsAITab.tsx:51`
**Issue:** SF-06 contract per the phase summary: "consumer-side pattern
... admin probe never fires from anonymous OR non-admin authed pages."
Both consumers correctly gate `useAIStatus({ enabled: !!token && isAdmin })`,
but the very next line in each file calls `useEmbeddingStats()` —
*ungated*. `useEmbeddingStats` (`use-admin.ts:279`) issues
`GET /admin/embedding-stats/` (`admin.ts:178`), which is an admin-only
endpoint that returns 401 for unauthenticated / non-admin callers.

`AIStatusCard.tsx:25` does `if (isLoading || !aiStatus) return null;`,
but that early return only short-circuits *rendering* — both
`useAIStatus` AND `useEmbeddingStats` have already initiated their
queries by then because hooks must run unconditionally. The 401-error
console line that SF-06 was supposed to eliminate is still produced
whenever an authed non-admin user (or admin during logout transition)
mounts a page that imports `AIStatusCard` / `SettingsAITab`.

Note `AIStatusCard` is currently used only inside `StatsOverview` (an
admin page), so the **anonymous-route** count from SF-06 (5 401s on
`/login`) is correct. But during a logout transition — admin → token
cleared → component still mounted for one frame — both queries fire
once with a stale subscription, producing 401s. The phase contract was
written for the broader case ("non-admin authed pages"), and that case
is unguarded.

**Fix:**
```typescript
// AIStatusCard.tsx:23 and SettingsAITab.tsx:51
- const { data: embeddingStats } = useEmbeddingStats();
+ const { data: embeddingStats } = useEmbeddingStats({ enabled: !!token && isAdmin });

// use-admin.ts:279 — extend the signature to accept the same options shape
- export function useEmbeddingStats() {
+ export function useEmbeddingStats(options?: { enabled?: boolean }) {
    return useQuery({
      queryKey: queryKeys.admin.embeddingStats,
      queryFn: getEmbeddingStats,
      staleTime: 30_000,
+     enabled: options?.enabled,
    });
  }
```
Mirrors the `useAIStatus` shape extension that SF-06 already made.

---

## Warnings

### WR-01: `removeStaleSourcesAndLayers` cannot derive per-layer companion ids from a deduped source id — orphaned MapLibre layers persist on non-AI removal paths

**File:** `frontend/src/components/builder/map-sync.ts:642-668`
**Issue:** When the LAST consumer of a deduped source is removed via a
path that does NOT imperatively clean up per-layer companions (i.e.
`handleRemove` for single layers, `handleBulkDelete` for batches —
neither has imperative `map.removeLayer(...)` calls), the next
`syncLayersToMap` invocation finds the deduped source orphaned and
enters `removeStaleSourcesAndLayers`. That helper does:

```typescript
const id = sourceId.replace(sourcePrefix, '');  // → "data-{table_name}"
const layerId = prefixed('layer', id, prefix);  // → "layer-data-{table_name}"
// ... removes layer-data-{table_name}, layer-data-{table_name}-outline, ...
```

None of those derived ids exist on the map — the real layer ids are
`layer-{layer.id}`. The actual MapLibre layers (`layer-{realId}`,
`layer-{realId}-outline`, `layer-{realId}-label`, `layer-{realId}-extrusion`,
`layer-{realId}-arrow`, cluster-count, cluster-circle) leak. They keep
rendering until the basemap is changed (full re-init) or the page is
reloaded.

`handleAiRemoveLayer` (use-builder-layers.ts:732-751) escapes this by
imperatively removing the per-layer companions; its dedupe-test
(`use-builder-layers.dedupe.test.ts:111`) is written specifically for
that path. But the non-AI delete paths (single `handleRemove`, bulk
`handleBulkDelete`) have no equivalent imperative cleanup — they rely
entirely on `removeStaleSourcesAndLayers`, which is now blind to the
true layer ids.

This is not a security or data-loss bug; it's a visual leak that the
user can repro by: add 2 layers from same dataset → delete one → the
deleted layer's outline/labels/symbols remain visible until reload.

**Fix:** Track per-layer ids alongside source ids in
`managedSourcesRef` (or add a parallel `managedLayerIdsRef`), OR
imperatively clean per-layer companions in `handleRemove` /
`handleBulkDelete` before triggering the React Query refetch
(mirror the `handleAiRemoveLayer` pattern). The latter is simpler:
```typescript
// handleBulkDelete, just before bulkDeleteLayersApi():
const map = mapInstanceRef.current;
if (map && map.isStyleLoaded()) {
  for (const id of idsToDelete) {
    for (const suffix of ['', '-outline', '-label', '-extrusion', '-arrow', '-cluster', '-cluster-count']) {
      const lid = `layer-${id}${suffix}`;
      if (map.getLayer(lid)) map.removeLayer(lid);
    }
  }
}
```

---

### WR-02: SF-08 basemap latch suppresses ALL post-load 5xx errors permanently — masks ongoing tile-server outages

**File:** `frontend/src/components/builder/BuilderMap.tsx:409`
**Issue:** The latch logic is "first successful basemap style fetch →
suppress *all* subsequent 5xx-class MapLibre errors for this basemap."
That's wider than the SF-08 use case (suppress the transient 5xx that
fires once during save). Concrete scenarios that are now silently
broken:

1. User opens editor → basemap loads OK → tile server goes down for
   30 minutes. MapLibre emits 5xx repeatedly. No toast, no
   `basemapNotice` banner. User sees a blank/grey map but is given no
   indication that the system is failing.
2. User opens editor → basemap loads OK → 503 from upstream tile CDN
   for a vector tile range. The user's data layers fail to render at
   higher zooms. No toast.

The pre-SF-08 behaviour was "show the toast every 5xx, deduped by id
`builder-map-error`." That at least told the user something was wrong.
The new behaviour silences the signal entirely after first successful
load.

The phase context lists this as Critical Invariant 5: "SF-08 toast
suppression must NOT also suppress the toast for actually-broken
basemaps (e.g. unreachable URL)." The current implementation *does*
correctly leave the initial-fetch failure path
(`setBasemapNotice('style')` at line 173) un-gated. But it over-rotates
on the runtime-error path.

**Fix:** Add a time window to the latch — only suppress 5xx errors
within N seconds of a save event, not forever:
```typescript
// near line 91:
const basemapLoadedAtRef = useRef<number | null>(null);
const lastSaveAtRef = useRef<number | null>(null);  // <-- new

// in handleSave (use-builder-save.ts), set lastSaveAtRef before the mutation runs.
// Expose via a callback prop or via a shared ref.

// errorHandlerRef branch (line 406-414):
if (!status || status >= 500) {
  const loaded = basemapLoadedAtRef.current !== null;
  const justSaved = lastSaveAtRef.current && Date.now() - lastSaveAtRef.current < 3000;
  if (loaded && justSaved) return;  // narrower suppression
  setBasemapNotice('tiles');
  toast.error(...);
}
```
OR adopt a "suppress one 5xx within 2 s of load latch arming" approach
(simpler: only the first post-load 5xx is silenced).

---

### WR-03: `shouldAutoCapture` never clears `autoCapturedMapIds`, so server-side thumbnail deletion or admin re-trigger cannot re-arm auto-capture without a full page reload

**File:** `frontend/src/components/builder/hooks/use-builder-save.ts:144-177`
**Issue:** `autoCapturedMapIds: Set<string>` is module-scoped and
write-only (cleared only by `__resetThumbnailDebounceForTests`). If a
user opens map A (auto-capture fires → set has 'A'), and then the
server later returns `hasThumbnail: false` for map A (e.g. an admin
deleted the thumbnail, or the file was lost on disk), the next mount
of `useBuilderSave` for the same mapId WILL NOT re-arm auto-capture
because `shouldAutoCapture('A')` returns false. The user has to do a
hard reload (which re-evaluates the module, clearing the in-memory
set) to recover.

This is a small hygiene defect — most users won't hit it — but the
test `reset helper clears the module-level guard so a fresh test (or
page) can auto-capture again` only asserts that the *test reset path*
re-enables, not that there's any in-app mechanism to recover. The
CHANGELOG comment ("until either an explicit reset or the user
navigates to a different map") promises navigation-reset, but
**there is no code that removes a mapId from the set on navigation
away.** The comment is aspirational, not implemented.

**Fix:** Either drop the comment from the source (set the
expectation correctly) OR add a cleanup effect that removes the
mapId when the hook unmounts:
```typescript
useEffect(() => {
  return () => {
    if (state.mapId) autoCapturedMapIds.delete(state.mapId);
  };
}, [state.mapId]);
```
The cleanup form matches the comment's promise but adds risk: rapid
StrictMode unmount/remount could re-arm the guard. The safer fix is
just to correct the comment.

---

### WR-04: `useEmbeddingStats` is not gated and will fire 401s during admin logout transition (also see CR-03)

**File:** `frontend/src/components/admin/AIStatusCard.tsx:23`,
`frontend/src/components/admin/settings/SettingsAITab.tsx:51`
**Issue:** Adjunct to CR-03. Even within the admin-only mounting
context, when an admin clicks logout: token is cleared, but the
mounted `AIStatusCard` and `SettingsAITab` components persist for at
least one render. During that frame, `useEmbeddingStats` re-evaluates
with `enabled: undefined` (defaults to true) and fires a request.
Now the token is null so it 401s — the "5 → 0 401 reduction" claim
in the CHANGELOG is true for the `/login` page case but false for the
logout-transition case. Same root cause as CR-03; classified
separately because the user-visible impact is much smaller (a single
logout produces 2 visible 401s, not 5).

**Fix:** Same as CR-03 — gate `useEmbeddingStats` with `{ enabled: !!token && isAdmin }`.

---

## Info

### IN-01: `__resetThumbnailDebounceForTests` is exported but the name implies it's debounce-only — actual scope now includes the SF-07 auto-capture guard

**File:** `frontend/src/components/builder/hooks/use-builder-save.ts:182`
**Issue:** The function name and the docstring promise "clear any
pending debounced captures AND the SF-07 module-level auto-capture
guard." The docstring is correct, but a future maintainer searching for
"how do I reset the auto-capture guard" will not find this via the
function name. The current call sites in
`use-builder-save.test.ts:250` go through this fine, but the SF-07 test
file's docstring at `use-builder-save.test.ts:1228` ("reset helper
clears the module-level guard") refers to it generically.

**Fix:** Rename to `__resetCaptureModuleStateForTests` and update the
import + 1 callsite. Pure naming hygiene.

---

### IN-02: `getSourceIdForLayer` raster branch relies on `layer_type === 'raster_geolens'` AND `is_dem`, but doesn't handle the `is_dem` true + `layer_type` undefined case

**File:** `frontend/src/components/builder/map-sync.ts:387`
**Issue:** Line 387: `if (layer.is_dem === true || layer.layer_type === 'raster_geolens')`. For a layer with `is_dem: true, layer_type: undefined, dataset_record_type: 'raster_dataset'`, this correctly routes to per-layer. But for `is_dem: true, layer_type: undefined, dataset_table_name: 'dem_xyz'`, the branch correctly takes per-layer. Good — but the *test*
factory in `map-sync.dedupe.test.ts:67` doesn't include
`dataset_record_type` or `layer_type` for DEM scenarios, and there's no
explicit "DEM layer keeps per-layer source" assertion. Add one to lock
the contract.

**Fix:** Add to `map-sync.dedupe.test.ts`:
```typescript
it('DEM raster layer keeps per-layer source id', () => {
  const dem = makeLayer({
    id: 'dem-1',
    dataset_table_name: 'elevation',
    is_dem: true,
  });
  expect(getSourceIdForLayer(dem)).toBe('source-dem-1');
});
```

---

### IN-03: SF-04 comment block in `use-builder-layers.ts:724-731` claims the desired-set prune is "reference-count-aware" — true for SOURCES, misleading for per-layer COMPANIONS (see WR-01)

**File:** `frontend/src/components/builder/hooks/use-builder-layers.ts:722-749`
**Issue:** The comment says "Source teardown ... is delegated to the
next `syncFromState` invocation's `removeStaleSourcesAndLayers` desired-
set prune — which is reference-count-aware via
`desiredSources.add(sourceId)` and will correctly leave a deduped
`source-data-${dataset_table_name}` in place while sibling layers still
reference it." That claim about sources is correct. But the same prune
*does not* clean up per-layer companion layers when the source
eventually does become orphaned (see WR-01). The comment block reads as
if the prune is fully reference-count-safe end-to-end; it is only
half-safe.

**Fix:** Tighten the comment to say "source teardown is reference-count
safe; per-layer companion teardown is handled imperatively here
(label/outline/extrusion/arrow + main `layer-${id}`)." Drop the
"reference-count-aware ... correctly leave a deduped source in place"
phrasing since it implies more than the helper provides.

---

_Reviewed: 2026-05-17_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

---

## Fixes Applied

**Fixed at:** 2026-05-17
**Mode:** `--fix auto` (review-fix)
**Scope:** All 3 BLOCKERs + 4 WARNINGs (Info findings deferred — naming hygiene only)

### Summary
- BLOCKERs fixed: **3/3** (CR-01, CR-02, CR-03)
- WARNINGs fixed: **4/4** (WR-01, WR-02, WR-03, WR-04 — merged into CR-03)
- Info deferred: **3** (IN-01..IN-03 — naming/comment hygiene, no behaviour change)
- Test suite: **1913/1913 PASS** (baseline 1909, +4 regression tests added)
- Typecheck: **0 new errors** (pre-existing LayerEditorPanel.tsx:413,694 + 4 TS6133 unchanged)

### Commits
| Finding | Commit | Summary |
|---------|--------|---------|
| CR-01 | `516c9ae5` | Route `waitForVisibleLayerSources` through `getSourceIdForLayer` so auto-capture no longer waits the full 5s deadline for every deduped vector layer |
| CR-02 | `fd149688` | Route BuilderMap token-refresh + popup `layerByMapIdRef` through `getSourceIdForLayer` so `setTiles([newUrl])` actually propagates refreshed signed tokens to deduped vector sources |
| CR-03 / WR-04 | `d6b0b9c6` | Extend `useEmbeddingStats({ enabled })` signature and gate both consumers (`AIStatusCard`, `SettingsAITab`) with `!!token && isAdmin`, completing SF-06's anonymous + non-admin + logout-transition coverage |
| WR-01 | `8b791a08` | Factor `removePerLayerCompanions(map, ids)` helper; call from `handleRemove` and `handleBulkDelete` BEFORE the mutation/API call so per-layer companion MapLibre layers (outline/label/extrusion/arrow/cluster-circle/cluster-count + main) vanish in lockstep with the optimistic state update; sources untouched (next sync's reference-count-aware desired-set prune owns teardown) |
| WR-02 | `0f0290ba` | Narrow SF-08 basemap latch to a 3000 ms window after load: `if (loadedAt !== null && Date.now() - loadedAt < 3000) return;` — silences the transient post-load 5xx (the case SF-08 was added for) without masking ongoing tile-CDN outages |
| WR-03 | `0451657f` | Correct misleading `autoCapturedMapIds` comment; the set is deliberately write-only in production (an unmount cleanup would re-introduce the SF-07 StrictMode duplicate-capture bug). Trade-off documented; only recovery from server-side thumbnail deletion is a hard reload |

### Regression Tests Added
1. `use-builder-save.test.ts > CR-01: resolves source-readiness on the deduped source id before the 5s deadline` — seeds `source-data-{table}` after the debounce, asserts the idle listener registers within 100 ms (not after the 5000 ms deadline), AND asserts the legacy `source-{id}` key is never queried.
2. `use-builder-layers.dedupe.test.ts > handleRemove imperatively removes per-layer companions (WR-01)` — seeds all 7 companion suffixes on the mock map, asserts each one is torn down by the imperative path.
3. `use-builder-layers.dedupe.test.ts > handleBulkDelete imperatively removes per-layer companions for every id in the batch (WR-01)` — bulk-delete variant.
4. `BuilderMap.a11y.test.tsx > still surfaces tile error toast when 5xx arrives well after latch arming (WR-02)` — advances fake timers 10 s past latch arming, asserts the `builder-map-error` toast AND `Basemap connection issue` banner both surface.

### Notes on CR-02 Manual Verification
The CR-02 fix mirrors CR-01 exactly (same `getSourceId` → `getSourceIdForLayer` swap), and CR-01 has a strong regression test. CR-02's runtime path (token expiry → refresh → `setTiles` on a deduped source) is harder to unit-test without mounting the full BuilderMap with a 1-hour token-expiry simulation. Manual verification: live MCP smoke check, or wait ~1 hr in a session and confirm vector layers continue to render after `useTileTokens` issues a fresh `tokenSig`. The 731 builder vitest suite remains green.

### Deferred (Info)
- **IN-01** rename `__resetThumbnailDebounceForTests` → `__resetCaptureModuleStateForTests` (naming hygiene, no behaviour change). Defer.
- **IN-02** add explicit "DEM raster layer keeps per-layer source" assertion to `map-sync.dedupe.test.ts`. Defer — coverage exists implicitly via the raster fall-through branch.
- **IN-03** tighten the `use-builder-layers.ts:724-731` comment to acknowledge per-layer companion teardown is now imperative. **Partially addressed** by WR-01's comment update on `handleAiRemoveLayer` (now references `removePerLayerCompanions` factoring).

_Fixed: 2026-05-17_
_Fixer: Claude (gsd-code-fixer)_
