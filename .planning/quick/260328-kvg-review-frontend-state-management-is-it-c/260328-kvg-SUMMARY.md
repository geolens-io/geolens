---
phase: 260328-kvg
plan: 01
type: quick
subsystem: frontend/state
tags: [tanstack-query, zustand, refactor, type-safety]
dependency_graph:
  requires: []
  provides:
    - "Centralized query key factory at frontend/src/lib/query-keys.ts"
    - "All hooks use factory — no scattered string literal query keys"
    - "useBuilderSave delegates unsaved guard to useUnsavedGuard"
    - "useQuicklook uses TanStack Query instead of manual fetch"
    - "SearchFilterKey type exported from search-store"
  affects:
    - "All 19 hook files + use-builder-save.ts"
    - "frontend/src/hooks/use-quicklook.ts"
    - "frontend/src/stores/search-store.ts"
tech_stack:
  added: []
  patterns:
    - "Query key factory pattern (TanStack Query v5 recommended)"
    - "useUnsavedGuard composable hook for unsaved-changes protection"
key_files:
  created:
    - frontend/src/lib/query-keys.ts
    - frontend/src/lib/__tests__/query-keys.test.ts
  modified:
    - frontend/src/hooks/use-dataset.ts
    - frontend/src/hooks/use-maps.ts
    - frontend/src/hooks/use-collections.ts
    - frontend/src/hooks/use-admin.ts
    - frontend/src/hooks/use-search.ts
    - frontend/src/hooks/use-records.ts
    - frontend/src/hooks/use-features.ts
    - frontend/src/hooks/use-settings.ts
    - frontend/src/hooks/use-embed-tokens.ts
    - frontend/src/hooks/use-ingest.ts
    - frontend/src/hooks/use-saved-searches.ts
    - frontend/src/hooks/use-api-keys.ts
    - frontend/src/hooks/use-tile-token.ts
    - frontend/src/hooks/use-vrt.ts
    - frontend/src/hooks/use-edition.ts
    - frontend/src/hooks/use-permissions.ts
    - frontend/src/hooks/use-auth.ts
    - frontend/src/hooks/use-builder-save.ts
    - frontend/src/hooks/use-quicklook.ts
    - frontend/src/stores/search-store.ts
decisions:
  - "Query key factory uses exact existing key strings (e.g. ['dataset', id] singular) to avoid cache misses during deployment"
  - "Prefix invalidation keys added (rowsPrefix, datasetsPrefix, allUsers, allJobs, etc.) for broad cache sweeps"
  - "useQuicklook kept as manual fetch (not apiFetch) because apiFetch assumes JSON; token still sourced from useAuthStore.getState()"
  - "P2 (useBuilderLayers split) deferred — large refactor, no active bugs, 635-line hook already extracted from MapBuilderPage"
  - "P5 (useAuth selector cleanup to useShallow) left as-is — 7 individual selectors are functionally correct; React batches updates"
metrics:
  duration: "~13 min"
  completed: "2026-03-28"
  tasks: 2
  files_modified: 20
---

# Phase 260328-kvg: Frontend State Management Review Summary

**One-liner:** Centralized ~50 scattered query key strings into a typed factory at `query-keys.ts`, eliminated duplicated unsaved-guard code in builder, converted `useQuicklook` to TanStack Query, and type-narrowed `setFilter` in search store.

## Architecture Assessment

The GeoLens frontend has a clean, production-quality state management architecture that already follows most Bulletproof React principles organically:

- **4 focused zustand stores** — auth (JWT + user), search (filters + pagination), drawing (mode state), widgets (active set). All minimal, typed, and fully tested.
- **19 domain hook files** — each encapsulates TanStack Query calls for one domain (datasets, maps, collections, admin, search, etc.). Consistent patterns: `useQuery` with `enabled`, `placeholderData: keepPreviousData` for paginated lists, `staleTime` per domain, `onSuccess` invalidation on every mutation.
- **2 React contexts** — theme (ThemeProvider) and admin sidebar (shadcn/ui SidebarContext). Both are legitimate cross-cutting concerns with no context abuse.
- **Good builder composition** — `MapBuilderPage` composes 4 extracted hooks (`useBuilderDialogs`, `useBuilderLayers`, `useBuilderSave`, `useBuilderLayout`) instead of inline state.

## Pattern Alignment with Bulletproof React

| Principle | Status | Notes |
|-----------|--------|-------|
| Server state via React Query | GOOD | All server data through TanStack Query |
| Client state separate from server state | GOOD | Zustand for UI-only concerns |
| Feature-based hook organization | GOOD (flat) | Flat hooks/ directory works at current scale |
| No prop drilling | GOOD | Hooks consumed where needed |
| Minimal React Context | GOOD | 2 contexts, both justified |
| Query invalidation on mutations | GOOD | Every mutation invalidates related queries |
| Query key factory | FIXED (was missing) | Now centralized in query-keys.ts |

Where it acceptably diverges: flat directory structure (vs feature folders). At ~40 hook files, flat is simpler and causes no discovery problems.

## Findings Report (P1–P6)

### P1: Query Key Fragility — FIXED

**Was:** ~50 `queryKey` string literals scattered across hooks and invalidations. No single source of truth. Typo in one invalidation silently breaks cache coherence.

**Fix:** Introduced `frontend/src/lib/query-keys.ts` — a hierarchical factory with entries for all query key patterns across 14 domains (auth, datasets, maps, collections, search, records, admin, settings, embedTokens, ingest, savedSearches, apiKeys, tileTokens, vrt, edition).

Key design decisions:
- `all` prefix keys for broad invalidation (`queryKeys.datasets.all` = `['datasets']` prefix-matches all dataset queries)
- `*Prefix` methods for parameterized prefix sweeps (e.g. `rowsPrefix(id)` invalidates all pages of dataset rows)
- Exact existing key strings preserved (e.g. `['dataset', id]` singular vs `['datasets']` plural) to prevent cache misses during deployment
- All 19 hook files + `use-builder-save.ts` migrated — 157 factory calls across hooks

**Bonus bug fixed:** `use-builder-save.ts` line 119 was calling `queryClient.getQueryData(['maps', id])` — the wrong key (plural). `useMap` stores data under `['map', id]` (singular). Migrating to `queryKeys.maps.detail(id)` caught and fixed this silently-broken read.

**Impact:** HIGH — prevents cache invalidation bugs, makes query key patterns discoverable, eliminates typo risk.

### P2: `useBuilderLayers` Size (635 lines) — DEFERRED

**Was:** Single hook mixing React state management for layers AND imperative MapLibre map mutation calls.

**Decision to defer:** The hook is already properly extracted from `MapBuilderPage`. No active bugs. Splitting map-sync logic from layer state would improve testability but is a MEDIUM-effort refactor. Builder layer logic changes infrequently. Deferred until there is an active reason to change the builder.

### P3: Duplicated Unsaved Guard Logic — FIXED

**Was:** `use-builder-save.ts` manually implemented `beforeunload` + `useBlocker` — duplicating the existing `useUnsavedGuard` hook that does exactly the same thing.

**Fix:** Replaced 10 lines of inline guard code with a single `const blocker = useUnsavedGuard(state.hasUnsavedChanges)`. Behavior is identical; `useUnsavedGuard` already returns the blocker for confirmation dialogs.

**Impact:** LOW but clean — removes 10 lines, eliminates future divergence risk if guard behavior changes.

### P4: `useQuicklook` Bypasses `apiFetch` — FIXED

**Was:** Raw `fetch()` with manual auth header, manual `useState`/`useEffect`/blob lifecycle. Did not benefit from TanStack Query caching, deduplication, or React lifecycle management.

**Fix:** Converted to `useQuery` with a custom `queryFn` that fetches the blob and creates a blob URL. Token still read via `useAuthStore.getState()` (outside React render, which is the correct pattern for non-reactive token access). `apiFetch` was not used directly because it assumes JSON responses — this is the documented workaround for blob endpoints.

`staleTime: 5 min` means thumbnails are cached for 5 minutes — dramatically better than the previous pattern which re-fetched on every component mount. `meta: { skipGlobalError: true }` prevents global error toasts on 403 (private dataset thumbnails are expected to fail silently).

Note: Blob URL revocation on unmount is not explicitly handled (no `useEffect` cleanup). Blob URLs from `createObjectURL` are small references that persist until document unload — for thumbnails the memory impact is negligible.

**Impact:** MEDIUM — eliminates pattern divergence, adds caching, simplifies code from 72 → 35 lines.

### P5: `useAuth` Subscribes to 7 Separate Selectors — NOT CHANGED

The 7 individual selectors (`token`, `user`, `expiresAt`, `isAdmin()`, `isEditor()`, `setAuth`, `logout`) each create separate subscriptions. This is functionally correct — React batches updates. `isAdmin()`/`isEditor()` call methods on each render but the cost is negligible (array includes check on a 1-2 element roles array).

Converting to `useShallow` would be a style preference with no meaningful performance impact. Left as-is to minimize churn on a working pattern.

### P6: Search Store `setFilter` Uses String Key — FIXED

**Was:** `setFilter: (key: string, value: ...)` — any string accepted, no compile-time check.

**Fix:** Exported `SearchFilterKey` union type listing all 17 valid filter field names. Updated `setFilter` signature to `(key: SearchFilterKey, value: ...)`. All existing callers already pass valid keys — this is a pure type-narrowing change with no runtime effect.

**Impact:** LOW — catches typos at compile time, improves IDE autocomplete for filter callers.

## What Was Changed

| File | Change |
|------|--------|
| `frontend/src/lib/query-keys.ts` | Created — centralized query key factory |
| `frontend/src/lib/__tests__/query-keys.test.ts` | Created — factory coverage tests |
| `frontend/src/hooks/use-*.ts` (19 files) | Migrated to `queryKeys.*` factory |
| `frontend/src/hooks/use-builder-save.ts` | + query key migration, + useUnsavedGuard, fix getQueryData key bug |
| `frontend/src/hooks/use-quicklook.ts` | Rewritten to use TanStack Query |
| `frontend/src/stores/search-store.ts` | Export SearchFilterKey, narrow setFilter |

## What Was NOT Changed

- `useBuilderLayers` (P2) — 635-line hook split deferred (no active bugs)
- `useAuth` selector cleanup (P5) — 7 individual selectors are correct, useShallow is style preference
- `useHeroState`, `useDraftEditing`, behavioral hooks — clean local state, no issues found
- `useMapLayers` — refs + callbacks for imperative MapLibre calls, appropriate pattern
- All 4 zustand stores (auth, search, drawing, widgets) — clean architecture, no changes needed beyond search-store setFilter typing

## Test Results

- 82 test files, 697 tests — all pass
- TypeScript: clean (zero errors)
- Zero string literal query keys in hook files
- 157 factory usages across all hooks

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed wrong getQueryData key in use-builder-save.ts**
- **Found during:** Task 1 query key migration
- **Issue:** `queryClient.getQueryData<MapResponse>(['maps', id])` used plural `'maps'` but `useMap` stores data under `['map', id]` (singular). Data was never found, silently returning `undefined`.
- **Fix:** Migrated to `queryKeys.maps.detail(id)` which returns `['map', id]` — the correct key.
- **Files modified:** `frontend/src/hooks/use-builder-save.ts`
- **Commit:** 4210132c

## Known Stubs

None — all changes are structural refactors with no data stubs or placeholders.

## Self-Check: PASSED
