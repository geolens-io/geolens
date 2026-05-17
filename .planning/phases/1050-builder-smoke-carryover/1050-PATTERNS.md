# Phase 1050: builder-smoke-carryover - Pattern Map

**Mapped:** 2026-05-17
**Files analyzed:** 5 SF closures touching ~7 source files + 5 test files
**Analogs found:** 7 / 7 (every touch point has a working precedent in the same repo)

## Phase shape

Single-phase hygiene close (mirrors v1009.1 Phase 1045 + v1010.1 Phase 1049). Each SF closure maps 1:1 to an existing file the executor must edit — the analog and the touch point are usually the SAME file (the bug lives at the analog's existing call site). PATTERNS.md therefore highlights the **specific lines** to compare against and the **shape** of fix the executor should mirror.

---

## File Classification

| Touched file | Role | Data flow | Closest analog (or self) | Match quality |
|---|---|---|---|---|
| `frontend/src/components/builder/hooks/use-builder-layers.ts` | builder hook (imperative MapLibre orchestration) | event-driven / imperative state | self — `swapLayerOnMap` (lines 752–835) + `handleAiRemoveLayer` (lines 723–740) for per-layer source lifecycle | exact (file IS the touch point) |
| `frontend/src/components/builder/map-sync.ts` | sync engine (vector/raster source add/remove + zoom/visibility/labels) | imperative paint + diff | self — `syncVectorLayer` (lines 406–562) + `removeStaleSourcesAndLayers` (lines 564–591) for the dedupe rewrite; `syncTerrainSource` (lines 86–124) for the **idempotent reuse pattern** to copy | exact + role-match analog inside the file |
| `frontend/src/components/builder/cluster-source.ts` | pure selector (cluster eligibility) | request-response (function) | self — per-layer is intentional; PATTERNS reminder is "do not dedupe cluster sources" | constraint, not bug |
| `frontend/src/components/maps/hooks/use-map-thumbnail.ts` | React Query hook (blob fetch + URL.createObjectURL) | CRUD (cached query) | `frontend/src/components/maps/hooks/use-quicklook.ts` (`useEffect` revoke-on-data-change at lines 67–74) | exact (sibling hook in same directory) |
| `frontend/src/hooks/use-auth.ts`, `frontend/src/hooks/use-permissions.ts`, `frontend/src/hooks/use-admin.ts`, `frontend/src/components/search/hooks/use-saved-searches.ts` | React Query auth/admin/search hooks | CRUD (gated query) | `use-auth.ts:20–27` + `use-permissions.ts:7–15` (existing `enabled: !!token` gate); `use-admin.ts:186–194` (existing `enabled: options?.enabled` opt-in gate) | exact (same file family) |
| `frontend/src/components/builder/hooks/use-builder-save.ts` | builder save hook (debounce + capture) | event-driven (effect-triggered) | self — `captureThumbnail` module-level debounce (lines 123–150) + `maybeAutoCaptureThumbnail` caller (lines 534–539) | exact (file IS the touch point) |
| `frontend/src/components/builder/BuilderMap.tsx` | imperative MapLibre wrapper + basemap loader | event-driven (`map.on('error')`) | self — basemap style-fetch effect (lines ~115–173) + `errorHandlerRef` registration (lines 384–404) for the gate; `mapReady` state pattern for the "load latch" | exact (file IS the touch point) |

---

## Pattern Assignments

### Plan 01 — SF-04: Dedupe MapLibre vector tile sources

**Touch points:**
- `frontend/src/components/builder/map-sync.ts:318-324` — `getSourceId(layerId)` / `getLayerId(layerId)` — the **per-layer keying contract** to change
- `frontend/src/components/builder/map-sync.ts:493-511` — `syncVectorLayer` where `addSource` is called per layer
- `frontend/src/components/builder/map-sync.ts:564-591` — `removeStaleSourcesAndLayers` where unreferenced sources are pruned
- `frontend/src/components/builder/hooks/use-builder-layers.ts:737` — `handleAiRemoveLayer` calls `removeSource(\`source-${layerId}\`)` (ai-remove path that MUST keep working)
- `frontend/src/components/builder/hooks/use-builder-layers.ts:760-783` — `swapLayerOnMap` source-id contract: derives `sourceId = \`source-${layer.id}\`` and conditionally `removeSource` for raster/hillshade transitions
- `frontend/src/components/builder/cluster-source.ts` — **preserve per-layer cluster sources** (cluster radius/minPoints are per-layer settings; `clusterSourceSignature` in map-sync.ts:310-316 already keys per-source for the bounded-geojson + server-tile strategies)

**Analog #1 (idempotent reuse pattern) — `map-sync.ts:86-124` (`syncTerrainSource`):**
```typescript
// COPY THIS SHAPE for the new per-dataset source registration
const existing = map.getSource(sourceId) as { type?: string } | undefined;
const existingSpec = existing ? sourceSpec(existing) : {};
const existingTiles = Array.isArray(existingSpec.tiles) ? existingSpec.tiles : [];
const shouldReplace = existing
  && (
    existing.type !== 'raster-dem'
    || existingTiles[0] !== absoluteTileUrl
    // ... shape mismatch checks
  );

if (shouldReplace) {
  map.setTerrain(null);
  map.removeSource(sourceId);
}

if (!map.getSource(sourceId)) {
  map.addSource(sourceId, { /* spec */ });
}
```
This is the local pattern for "check before add, replace only on shape mismatch." Already does what SF-04 wants — just per-source not per-dataset.

**Analog #2 (raster dedupe-by-tileUrl) — `map-sync.ts:480-490` `__tests__/map-sync.raster.test.ts`:**
```typescript
// Tests already assert addSource is NOT called when an existing source matches
expect(map.addSource).not.toHaveBeenCalled();   // line 368, 403
expect(map.addSource).toHaveBeenCalledTimes(2); // line 490 — 2 distinct sources, not N
```
The raster path already proves the test shape. Vector dedupe needs the same test asserting `addSource` is called **M times for M datasets, not N times for N layers**.

**Constraint — `cluster-source.ts`:**
Cluster sources are per-layer by design (different cluster radius / minPoints per layer). The dedupe logic MUST scope by **dataset_table_name AND non-cluster status**. Two layers on the same dataset but with different render modes (one cluster, one non-cluster) must keep separate sources. Use `getClusterSourceStrategy(layer)` (lines 86–108) to gate dedupe eligibility:
```typescript
import { getClusterSourceStrategy } from '@/components/builder/cluster-source';
const isClusterLayer = getClusterSourceStrategy(layer).kind !== 'fallback';
// Only dedupe if NOT a cluster-source layer.
```

**Reference-count / desired-set pattern — `map-sync.ts:611-612, 489 (`desiredSources` accumulator)`:**
```typescript
const currentSources = new Set(managedSourcesRef.current);
const desiredSources = new Set<string>();
// ... for each layer: desiredSources.add(sourceId);
// After loop, prune sources in currentSources but not in desiredSources:
removeStaleSourcesAndLayers(map, currentSources, desiredSources, sourcePrefix, prefix);
```
This is the existing "compute desired set, prune what's not in it" pattern. The new code only needs to switch the keying function — the prune contract already handles "source is still referenced by another layer" by virtue of `desiredSources.add(sourceId)` being called once per consumer.

**Source-id derivation choices to lock down in the plan (these are gray areas):**
- Option A: `sourceId = \`source-data-${dataset_table_name}\`` (no clusters) — simplest, breaks the existing 1:1 `layer.id ↔ source.id` invariant
- Option B: keep `source-${layer.id}` for cluster layers, switch to `source-data-${dataset_table_name}` for everyone else — minimal blast radius
- Option C: introduce `getSourceIdForLayer(layer)` that branches on cluster strategy — preserves `getSourceId(layerId)` for cluster + tests
- `swapLayerOnMap` (use-builder-layers.ts:760-783) reads from `map.getSource(sourceId)` to inherit the tile URL — must be updated to use the new key

**Imports pattern (existing — match in any new helpers):**
```typescript
import type { Map as MaplibreMap } from 'maplibre-gl';
import type { FilterSpecification, StyleSpecification, GeoJSONSource, VectorSourceSpecification } from 'maplibre-gl';
import { getClusterSourceStrategy, isClusterRenderMode } from '@/components/builder/cluster-source';
```

**Test analogs:**
- `frontend/src/components/builder/__tests__/map-sync.raster.test.ts:368,403,490` — assertion shape for "addSource NOT called when reused"
- `frontend/src/components/builder/__tests__/map-sync.cluster.test.ts:113,137,223,246` — cluster source-id (`source-cluster-1`) is the prototype that should be preserved (one cluster signature → one source)
- `frontend/src/components/builder/__tests__/BuilderMap.unit.test.ts:18` — `addSource: vi.fn((id: string, spec: ...))` map mock prototype

---

### Plan 02 — SF-05: Defer blob revoke until image loads

**Touch points (primary leak — confirmed):**
- `frontend/src/components/maps/hooks/use-map-thumbnail.ts:21-30` — `useMapThumbnail` calls `URL.createObjectURL(blob)` but has **NO `URL.revokeObjectURL` cleanup** (compare to `use-quicklook.ts:67-74` sibling which does)

**Analog (exact — sibling hook in same directory) — `use-quicklook.ts:67-74`:**
```typescript
// Revoke blob URL when data changes (new dataset) or on unmount
useEffect(() => {
  if (typeof data === 'string') {
    return () => {
      URL.revokeObjectURL(data);
    };
  }
}, [data]);
```
And the existing doc comment at `use-quicklook.ts:26-28`:
```typescript
 * Blob URL lifecycle: URL.revokeObjectURL is called on unmount AND on
 * datasetId change (via the useEffect cleanup on [data]) to prevent memory
 * leaks.
```
**Copy this exact pattern into `use-map-thumbnail.ts`** — same `useEffect(() => { if (typeof data === 'string') return () => URL.revokeObjectURL(data); }, [data]);` block, same doc comment update.

**Why this fixes SF-05:** On post-login redirect, React Query refetches `/api/maps/` → re-creates blob URLs → old blobs are GC'd from cache → `<img>` elements still pointing at the old URL fire `ERR_FILE_NOT_FOUND`. Adding the cleanup ensures revoke fires on unmount (component leaves tree, `<img>` gone), not on cache-eviction without `<img>` teardown.

**Other createObjectURL callsites to AUDIT but NOT fix in this plan (per CONTEXT — out of scope for the SF-05 noise):**
- `frontend/src/api/datasets.ts:87-94` — already revokes immediately after `a.click()` synchronously inside a download flow; not on post-login redirect path
- `frontend/src/components/admin/ExportSplitButton.tsx:24-31` — same shape; admin-only
- `frontend/src/components/admin/saml/SamlProvidersSection.tsx:230-237` — same shape; admin-only
- `frontend/src/components/builder/StyleJsonDialog.tsx:33-38` — same shape (download-then-revoke); only runs on user click
- `frontend/src/components/builder/hooks/use-builder-save.ts:486-493` — same shape; runs on `handleExportPNG` user click
- `frontend/src/hooks/use-config-ops.ts:24-31` — same shape

**Imports pattern (already present in `use-map-thumbnail.ts`, just add `useEffect`):**
```typescript
import { useEffect } from 'react';                  // ADD
import { useQuery } from '@tanstack/react-query';
import { apiFetchBlob } from '@/api/client';
```

**Test analog — `use-quicklook.test.ts:153,173-174`:**
```typescript
expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:http://localhost/quicklook');
// revokeObjectURL was called when the query key changed (data changed)
expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:http://localhost/quicklook');
```
Mirror this in `__tests__/use-map-thumbnail.test.ts` (the spy is already set up at line 28: `vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});`).

---

### Plan 03 — SF-06: Gate anonymous pre-auth probes

**Touch points (5 separate hooks — 1 already correctly gated as a reference):**
- `frontend/src/hooks/use-auth.ts:20-27` — **already correctly gated** (`enabled: !!token`) — this IS the analog
- `frontend/src/hooks/use-permissions.ts:7-15` — **already correctly gated** (`enabled: !!token`) — secondary analog
- `frontend/src/hooks/use-admin.ts:186-194` — `useAIStatus` accepts `options?: { enabled?: boolean }` but **defaults to `enabled: undefined` (=true)** when consumer doesn't pass — must change the default OR fix consumers
- `frontend/src/components/admin/AIStatusCard.tsx:16` — `useAIStatus()` called without `enabled`
- `frontend/src/components/admin/settings/SettingsAITab.tsx:44` — `useAIStatus()` called without `enabled`
- `frontend/src/components/search/hooks/use-saved-searches.ts:9-15` — `useSavedSearches` has **NO `enabled` gate**

**Analog #1 (token-gate) — `use-auth.ts:20-27`:**
```typescript
const meQuery = useQuery({
  queryKey: queryKeys.auth.me,
  queryFn: getMe,
  enabled: !!token,                       // <-- this is the pattern
  retry: false,
  staleTime: 5 * 60 * 1000,
  meta: { skipGlobalError: true },
});
```

**Analog #2 (token-gate via store selector) — `use-permissions.ts:7-15`:**
```typescript
export function usePermissions() {
  const token = useAuthStore((s) => s.token);   // <-- read once via selector

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.auth.permissions,
    queryFn: getMyPermissions,
    enabled: !!token,                          // <-- gate here
    staleTime: 60_000,
  });
  // ...
}
```

**Analog #3 (caller-provided enabled flag) — `use-admin.ts:186-194` already has the right shape:**
```typescript
export function useAIStatus(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.admin.aiStatus,
    queryFn: getAIStatus,
    staleTime: 60_000,
    gcTime: 5 * 60_000,
    enabled: options?.enabled,        // <-- but undefined === true in React Query
  });
}
```

**Analog #4 (admin-only consumer gating) — `use-ai-availability.ts:5-16` (existing working pattern):**
```typescript
export function useAIAvailability() {
  const token = useAuthStore((s) => s.token);
  const aiStatus = useAIStatus({ enabled: !!token });   // <-- caller gates on token
  const { can } = usePermissions();
  // ...
}
```
This is the GOOD analog for the AIStatusCard / SettingsAITab fix. Each consumer should pass `enabled: !!token && isAdmin` (admin endpoints also gate on `useAuthStore((s) => s.isAdmin())`).

**Decision points to surface in the plan:**
- `useAIStatus` default: change from `enabled: options?.enabled` (undefined→true) to `enabled: options?.enabled ?? false` — explicit opt-in. OR: change consumers (`AIStatusCard`, `SettingsAITab`) to always pass `{ enabled: !!token && isAdmin }`. The PR-safer pattern is **change consumers**, because the hook's contract is already documented (line 182–185 comment) as caller-controlled.
- `useSavedSearches` is mounted from `SavedSearches.tsx` which is rendered inside `FilterPanel.tsx` + `FilterSheet.tsx` — these mount on dataset-search pages (authed). The probe firing on `/login` indicates `FilterPanel` is being lazily-imported (Suspense?) or there's a stale-token-then-401-then-logout cascade.
- Admin endpoint gate: `useAuthStore((s) => s.isAdmin())` returns false for `user === null`, so `enabled: !!token && isAdmin` is safe.

**Auth store contract — `frontend/src/stores/auth-store.ts:5-15, 77`:**
```typescript
interface AuthState {
  token: string | null;        // <-- !!token is the "is authenticated" gate
  user: UserResponse | null;
  isAdmin: () => boolean;      // <-- selector for the admin gate
  isEditor: () => boolean;
}
// usage:
isAdmin: () => get().user?.roles.includes('admin') ?? false,
```
Note: there is **no `isAuthenticated` field** — the convention is `!!token`. CONTEXT.md mentions `auth.isAuthenticated` as shorthand; the actual code uses `useAuthStore((s) => s.token)` + `!!token`.

**Imports pattern (for adding the gate to `use-saved-searches.ts`):**
```typescript
import { useAuthStore } from '@/stores/auth-store';
// then in the hook:
const token = useAuthStore((s) => s.token);
return useQuery({ ..., enabled: !!token, staleTime: 60_000 });
```

**Test analogs:**
- `frontend/src/hooks/__tests__/use-ai-availability.test.tsx` — verifies token-gating shape
- `frontend/src/components/auth/__tests__/EditorRoute.test.tsx:34,38` — `useAuthStore.setState({ token: null, user: null })` to test anonymous

---

### Plan 04 — SF-07: Debounce thumbnail PUT on effect, not click handler

**Touch points:**
- `frontend/src/components/builder/hooks/use-builder-save.ts:123-150` — `captureThumbnail` debounce wrapper (already correct shape)
- `frontend/src/components/builder/hooks/use-builder-save.ts:534-539` — `maybeAutoCaptureThumbnail` (called from `MapBuilderPage` ref callback on map mount)
- `frontend/src/components/builder/hooks/use-builder-save.ts:438-442` — handleSave thumbnail capture call
- `frontend/src/components/builder/hooks/use-builder-save.ts:427` — fallback-replacement path also calls `captureThumbnail`

**Analog (existing debounce pattern — same file, lines 123-150):**
```typescript
const THUMBNAIL_DEBOUNCE_MS = 500;
const pendingCaptures = new Map<string, ReturnType<typeof setTimeout>>();

function captureThumbnail(map, mapId, queryClient, layers, signal?) {
  // SP-16: clear any prior pending capture for this mapId; the latest call
  // wins (trailing edge), reflecting the final state once the window settles.
  const existing = pendingCaptures.get(mapId);
  if (existing) clearTimeout(existing);

  const timer = setTimeout(() => {
    pendingCaptures.delete(mapId);
    runCaptureNow(map, mapId, queryClient, layers, signal);
  }, THUMBNAIL_DEBOUNCE_MS);

  pendingCaptures.set(mapId, timer);
}
```
This **is** the existing trailing-edge debounce. The bug is upstream: two distinct callers fire within the same render cycle but **before** the first `setTimeout(…, 500)` clears (i.e. `pendingCaptures.get(mapId)` returns `undefined` on the second call because the map is keyed by mapId and the prior setTimeout has already been registered but `clearTimeout` only fires when `existing` is truthy on the second call — which it should be).

**The likely actual mechanism (from SF-07 evidence):**
Two PUTs at network log entries 395 & 396 (consecutive). The debounce is module-level + keyed by mapId — so two captures keyed by the SAME mapId should collapse. Inspect:
1. Are there two **distinct** mapIds passed (e.g. one with trailing slash, one without)? Unlikely.
2. Is `maybeAutoCaptureThumbnail` triggered by an effect that fires twice in `StrictMode`? Vite dev mode has StrictMode → effects run twice → `thumbCaptured.current` should guard, but `captureSignalRef.current = { cancelled: false }` (line 537) is re-assigned each invocation.
3. The `thumbCaptured` ref guard at line 535 should prevent re-entry: `if (thumbCaptured.current || state.hasThumbnail !== false || !state.mapId) return;` — but the auto-capture **AND** the handleSave-capture both fire on first load if `hasThumbnail === false` AND the user immediately saves.

**Plan recommendation — wrap the EFFECT, not the handler:**
- Audit which effect in MapBuilderPage / use-builder-save fires the auto-capture. If `maybeAutoCaptureThumbnail` is called from a `useEffect`, the StrictMode double-mount could double-fire it before `thumbCaptured.current = true` settles. Move the `thumbCaptured.current = true` BEFORE the `captureThumbnail` call (it already is at line 536). Verify mapId stability.
- If the second PUT comes from a paint-settle / tile-loaded MapLibre event, ensure those event handlers route through `captureThumbnail` (debounced) not `runCaptureNow` (immediate).

**Imports pattern (already present):**
```typescript
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Map as MaplibreMap } from 'maplibre-gl';
import { useQueryClient } from '@tanstack/react-query';
```

**Existing rAF coalesce helper to reference — `frontend/src/lib/builder/raf-coalesce.ts`:**
This is v1010's general rAF coalesce utility (PB-01/PB-02 territory). If the thumbnail double-fire is paint-settle-keyed, the same `coalesceFrame` helper may be the right abstraction for the effect-level debounce.

**Test analog — `frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts` exists** — add a test that mounts the hook, calls `maybeAutoCaptureThumbnail` twice synchronously, advances vitest fake timers by 500ms, asserts `runCaptureNow` (or its effect: the `PUT /thumbnail/`) fires exactly once. Use `__resetThumbnailDebounceForTests()` (line 154) in beforeEach.

---

### Plan 05 — SF-08: Don't fire basemap-issue toast when basemap loaded successfully

**Touch points:**
- `frontend/src/components/builder/BuilderMap.tsx:94` — `const [basemapNotice, setBasemapNotice] = useState<'style' | 'tiles' | null>(null);`
- `frontend/src/components/builder/BuilderMap.tsx:155-167` — basemap style-fetch effect (on successful load: `setBasemapNotice(null)`; on error: `setBasemapNotice('style')`)
- `frontend/src/components/builder/BuilderMap.tsx:384-404` — `errorHandlerRef.current` — `map.on('error')` handler that fires `setBasemapNotice('tiles')` on 5xx
- `frontend/src/components/builder/BuilderMap.tsx:850-865` — the toast UI (a div role="status", NOT a sonner toast — the smoke evidence referring to "toast" may be the in-DOM status banner OR a separate toast registered elsewhere)
- Note: SF-08's evidence (`Pass E evaluate(toasts)`) returns the message — so this is being read as a toast. Check whether the banner doubles as a toast OR there's a separate `toast.error(...)` path

**Re-grep for the actual toast path:**
The `errorHandlerRef` at line 399 fires `toast.error(t('builderMap.mapError'), { id: 'builder-map-error' })` — that's the toast SF-08 caught. The basemap-issue title text at line 857 is in the inline banner. So either:
- The map error 5xx fires `toast.error('Map tile error — some layers may not render correctly.')`
- OR a tile fetch on save's revalidation triggers the same handler

**Analog #1 (load-latch pattern) — `frontend/src/components/builder/BuilderMap.tsx:155-158`:**
```typescript
.then((style) => {
  if (!cancelled) {
    setMapStyle(sanitizeMaplibreStyle(style));
    setBasemapNotice(null);          // <-- already clears the banner on successful load
  }
})
```
**Add a sibling state — `basemapLoadedAt: number | null`** — that's set on this success branch and consulted in `errorHandlerRef` before re-arming `setBasemapNotice('tiles')`:
```typescript
const basemapLoadedAtRef = useRef<number | null>(null);

// In success branch (line 156-158):
basemapLoadedAtRef.current = Date.now();
setBasemapNotice(null);

// In errorHandlerRef (line 397-401):
if (!status || status >= 500) {
  // SF-08: suppress transient connection-issue toast if the basemap
  // already loaded successfully in this session.
  if (basemapLoadedAtRef.current !== null) return;
  setBasemapNotice('tiles');
  toast.error(...);
}
```

**Analog #2 (ref-based latch in same file) — `frontend/src/components/builder/BuilderMap.tsx:90-94`:**
```typescript
const errorHandlerRef = useRef<((e: { error: { message?: string; status?: number } }) => void) | null>(null);
// ...
const [basemapNotice, setBasemapNotice] = useState<'style' | 'tiles' | null>(null);
```
The `useRef` pattern is already established for cross-effect state. Add `basemapLoadedAtRef` next to `errorHandlerRef`.

**Decision points to surface:**
- Should the latch reset on basemap CHANGE (user picks a different basemap)? Yes — set back to `null` in the style-fetch effect's beginning (line 137-147 where the new style is being fetched).
- Should real 5xx outages (not transient) still warn? Yes — the recommended fix preserves that for the **first** load attempt; once loaded, transient tile-fetch 5xx during save are suppressed. This matches Success Criteria #2 ("basemap actually IS broken still fires").
- What about `setBasemapNotice('style')` at line 164 (style fetch failure)? That's a first-load failure path; latch shouldn't suppress it. Only suppress the **tiles** notice once style-load has succeeded.

**Imports pattern (already present):**
```typescript
import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { toast } from 'sonner';
```

**Test analog — `frontend/src/components/builder/__tests__/BuilderMap.a11y.test.tsx:50`:**
```typescript
expect(screen.getByRole('status')).toHaveTextContent('Basemap connection issue');
```
Mirror this in a new test: load style successfully (setBasemapNotice null), fire `map.emit('error', { error: { status: 503 } })`, assert the banner is NOT shown. Then test the reverse: never load style, fire same error, assert banner IS shown.

---

### Plan 06 — CTRL-01: Smoke gate + CHANGELOG + MCP re-verify

No source touches — gate plan. Re-uses smoke commands from v1010 / v1010.1:
- `npm --prefix frontend run typecheck`
- `npm --prefix frontend run test -- --run` (or targeted vitest suites)
- `npm --prefix frontend run e2e:smoke:builder`
- Playwright MCP re-verify against `docker compose down -v && up -d --build` stack

CHANGELOG entry — see v1010 / v1010.1 / v1009.1 `[Unreleased]` populate pattern (commits referenced as `c4576717` style 8-char SHAs; per-SF measurable evidence: tile-request counts before/after for SF-04, console-error count delta for SF-05/06, PUT count for SF-07, toast inventory for SF-08).

---

## Shared Patterns

### MapLibre source/layer imperative API
**Source:** `frontend/src/components/builder/map-sync.ts:493-511, 564-591`
**Apply to:** SF-04 plan (Plan 01)

The MapLibre source lifecycle in this codebase follows a **desired-set + prune** model:
1. For each layer, compute desired sourceId and call `desiredSources.add(sourceId)` + `addSource()` (if not already present)
2. After the loop, walk `currentSources` and remove any source not in `desiredSources`
3. Each call to `addSource` is idempotency-guarded by `if (!map.getSource(sourceId))`

This pattern naturally handles reference-counting: a source is kept alive as long as it's in `desiredSources`, which happens once per layer that wants it. The SF-04 fix only needs to change the **keying function** for non-cluster vector layers; the prune contract already works.

### React Query auth/token gating
**Source:** `frontend/src/hooks/use-auth.ts:23` + `frontend/src/hooks/use-permissions.ts:13`
**Apply to:** SF-06 plan (Plan 03)

```typescript
const token = useAuthStore((s) => s.token);
const query = useQuery({ ..., enabled: !!token });
```
For admin-only endpoints, additionally gate on `useAuthStore((s) => s.isAdmin())`:
```typescript
const token = useAuthStore((s) => s.token);
const isAdmin = useAuthStore((s) => s.isAdmin());
const query = useQuery({ ..., enabled: !!token && isAdmin });
```
**Do NOT** rely on the React Query global error handler to suppress 401s — gate the request itself so the network never fires.

### Blob URL lifecycle in cached React Query hooks
**Source:** `frontend/src/components/maps/hooks/use-quicklook.ts:67-74`
**Apply to:** SF-05 plan (Plan 02)

```typescript
useEffect(() => {
  if (typeof data === 'string') {
    return () => {
      URL.revokeObjectURL(data);
    };
  }
}, [data]);
```
Cleanup fires on `data` change AND component unmount. For one-shot download flows (datasets.ts, ExportSplitButton.tsx, StyleJsonDialog.tsx), the synchronous-revoke-after-`a.click()` pattern is fine.

### Trailing-edge debounce keyed by entity ID
**Source:** `frontend/src/components/builder/hooks/use-builder-save.ts:123-150`
**Apply to:** SF-07 plan (Plan 04)

```typescript
const pendingCaptures = new Map<string, ReturnType<typeof setTimeout>>();
function captureThumbnail(map, mapId, ...) {
  const existing = pendingCaptures.get(mapId);
  if (existing) clearTimeout(existing);
  const timer = setTimeout(() => {
    pendingCaptures.delete(mapId);
    runCaptureNow(...);
  }, THUMBNAIL_DEBOUNCE_MS);
  pendingCaptures.set(mapId, timer);
}
```
Module-level state means **all callers** route through the same debounce queue — fix the bug by ensuring all PUT-firing paths call this wrapper, not the inner `runCaptureNow`.

### Load-latch via `useRef`
**Source:** `frontend/src/components/builder/BuilderMap.tsx:90,94,384-404`
**Apply to:** SF-08 plan (Plan 05)

```typescript
const someLatchRef = useRef<number | null>(null);
// In success path:
someLatchRef.current = Date.now();
// In error path:
if (someLatchRef.current !== null) return;  // suppress
```
Mirrors `errorHandlerRef` + `mapReady` patterns already in the same file.

### Toast / banner conventions
**Source:** `frontend/src/components/builder/BuilderMap.tsx:399-401`, `frontend/src/components/builder/hooks/use-builder-save.ts:425,435,461,465`

```typescript
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
// ...
toast.success(t('toasts.mapSaved'));
toast.error(t('builderMap.mapError', { defaultValue: '...' }), { id: 'builder-map-error' });
```
Always use the `sonner` `toast` + i18n key with defaultValue fallback. Use `{ id: '...' }` to dedupe repeated toasts.

---

## No Analog Found

None. Every touch point has a working precedent in the same file or a sibling file.

## Metadata

**Analog search scope:**
- `frontend/src/components/builder/` (all)
- `frontend/src/hooks/` (auth, permissions, admin, ai-availability)
- `frontend/src/components/maps/hooks/` (thumbnail, quicklook)
- `frontend/src/components/search/hooks/` (saved-searches)
- `frontend/src/stores/auth-store.ts`
- `frontend/src/api/client.ts`, `frontend/src/api/auth.ts`, `frontend/src/api/admin.ts`, `frontend/src/api/saved-searches.ts`

**Files scanned:** ~25 source files + tests
**Pattern extraction date:** 2026-05-17
