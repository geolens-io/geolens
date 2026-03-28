# Quick Task 260328-kvg: Frontend State Management Review - Research

**Researched:** 2026-03-28
**Domain:** React state management (zustand, TanStack Query, React context, local state)
**Confidence:** HIGH

## Summary

The GeoLens frontend has a clean, well-organized state management architecture that already follows most Bulletproof React principles without formally adopting the pattern. State is properly segmented by concern: zustand for client-only state (auth, search filters, drawing mode, widget visibility), TanStack Query for all server state, and React context limited to two legitimate cross-cutting concerns (theme and sidebar UI). The codebase avoids common anti-patterns -- there is no prop drilling crisis, no unnecessary global state, and no hand-rolled server cache.

The architecture is closest to what the community calls "feature-based hooks" -- each domain (datasets, maps, collections, admin, search, etc.) gets its own hook file that encapsulates TanStack Query calls, and zustand stores are minimal and purpose-specific. This is a mature, production-quality setup.

**Primary recommendation:** The architecture is sound. Findings are mostly polish-level. The largest structural improvement would be introducing query key factories to eliminate the ~50 scattered string literal query keys, which is the main maintenance risk.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Review ALL state management: zustand stores, TanStack Query usage, React context, local useState -- full picture across the entire frontend
- Full refactor OK -- willing to take larger changes if the payoff is clear
- Produce both a written findings report (in SUMMARY.md) AND actual code changes committed

### Claude's Discretion
- Specific best-practice framework to compare against (Bulletproof React, etc.) -- Claude to assess which patterns the codebase already follows and recommend alignment where beneficial
- Priority ordering of changes -- Claude to triage by impact

### Deferred Ideas (OUT OF SCOPE)
None specified.
</user_constraints>

## Current State Inventory

### Zustand Stores (4 files)

| Store | File | Persist? | Size | Purpose |
|-------|------|----------|------|---------|
| `useAuthStore` | `stores/auth-store.ts` | Yes (localStorage) | 46 lines | JWT tokens, user, role helpers |
| `useSearchStore` | `stores/search-store.ts` | No | 123 lines | Search filters, pagination, URL-sync helpers |
| `useDrawingStore` | `stores/drawing-store.ts` | No | 57 lines | Feature drawing mode state |
| `useWidgetStore` | `stores/widget-store.ts` | No | 30 lines | Active widget set |

All stores are 100% tested (`stores/__tests__/`).

### TanStack Query Hooks (19 hook files, ~80+ hooks)

| File | Queries | Mutations | Domain |
|------|---------|-----------|--------|
| `use-admin.ts` | 12 | 10 | Admin panel CRUD |
| `use-dataset.ts` | 6 | 7 | Dataset CRUD + versioning |
| `use-maps.ts` | 6 | 9 | Map CRUD + sharing |
| `use-collections.ts` | 3 | 4 | Collection CRUD |
| `use-settings.ts` | 7 | 3 | App settings + branding |
| `use-search.ts` | 3 | 0 | Catalog search + facets |
| `use-records.ts` | 4 | 4 | Contacts, keywords, distributions |
| `use-features.ts` | 0 | 5 | Feature + column CRUD |
| `use-embed-tokens.ts` | 1 | 3 | Embed token management |
| `use-ingest.ts` | 3 | 6 | Upload + import pipeline |
| `use-saved-searches.ts` | 1 | 2 | Saved search CRUD |
| `use-tile-token.ts` | 1 (+useQueries) | 0 | Signed tile tokens |
| `use-config-ops.ts` | 0 | 4 | Config export/import |
| `use-permissions.ts` | 1 | 0 | RBAC capability check |
| `use-edition.ts` | 1 | 0 | Enterprise edition detection |
| `use-auth.ts` | 1 | 0 | Auth orchestration + refresh |
| `use-ai-availability.ts` | 0 (composes) | 0 | AI feature gate |
| `use-api-keys.ts` | 1 | 2 | User API key management |

12 of 19 hook files are tested (`hooks/__tests__/`).

### React Context (2 providers)

| Context | File | Purpose |
|---------|------|---------|
| `ThemeProviderContext` | `components/theme-provider.tsx` | Dark/light/system theme |
| `SidebarContext` | `components/ui/sidebar.tsx` | Admin sidebar open/collapsed (shadcn/ui pattern) |

Both are legitimate cross-cutting concerns. No context abuse.

### Behavioral Hooks (no server state, no global store)

| Hook | Purpose | State Type |
|------|---------|------------|
| `useBuilderLayers` | Map builder layer editing | Local state (600+ lines) |
| `useBuilderSave` | Save orchestration, thumbnail, blocker | Local + mutations |
| `useBuilderDialogs` | Dialog open/close flags | Local state |
| `useBuilderLayout` | Responsive breakpoint detection | Local state |
| `useDraftEditing` | Inline metadata editing with dirty tracking | Local state |
| `useHeroState` | Raster/VRT preview loading state machine | Local state |
| `useUnsavedGuard` | beforeunload + router blocker | Local state |
| `useMapLayers` | Imperative MapLibre layer management | Refs + callbacks |
| `useUrlSearchSync` | Two-way URL <-> search store sync | Side effects |
| `useQuicklook` | Blob URL lifecycle for thumbnails | Local state |

## Assessment Against Best Practices

### Bulletproof React Alignment

The codebase naturally follows many Bulletproof React principles without formally declaring them:

| Principle | Status | Notes |
|-----------|--------|-------|
| Server state via React Query | GOOD | All server data flows through TanStack Query hooks |
| Client state separate from server state | GOOD | Zustand stores hold only client-side concerns |
| Feature-based hook organization | GOOD | Hooks grouped by domain in `hooks/` |
| No prop drilling | GOOD | Hooks consumed where needed; large pages compose hooks |
| Minimal React Context | GOOD | Only 2 contexts, both justified |
| Query invalidation on mutations | GOOD | Every mutation invalidates related queries |

Where it diverges (acceptably):
- **No feature folder structure.** Bulletproof React recommends `features/datasets/hooks/`, `features/datasets/api/`, etc. This project uses flat `hooks/`, `api/`, `stores/` directories. For a codebase this size (~40 hook files, 4 stores), flat is simpler and causes no discovery problems.
- **No query key factory.** Bulletproof React and TanStack Query docs both recommend centralized query key factories. This codebase uses string literals scattered across ~50 locations.

### Strengths

1. **Clean zustand usage.** Stores are minimal, typed, and focused. `useShallow` is used correctly where needed (search hook). `getState()` usage outside React is limited to legitimate cases (API client needs token synchronously, URL sync needs snapshot).

2. **Consistent TanStack Query patterns.** Every hook follows the same structure: `useQuery` with `queryKey`/`queryFn`/`enabled`, mutations with `onSuccess` invalidation. `keepPreviousData` used consistently for paginated lists. `staleTime` set appropriately per domain.

3. **Good separation of concerns in the builder.** `MapBuilderPage` composes 4 extracted hooks (`useBuilderDialogs`, `useBuilderLayers`, `useBuilderSave`, `useBuilderLayout`) instead of having 600+ lines of inline state. This is the right pattern.

4. **Auth is well-handled.** Token refresh has mutex protection in the API client, proactive refresh in `useAuth`, and `getState()` access for non-React contexts. The 401 retry flow is solid.

5. **Test coverage for state.** All 4 stores tested. 12 of 19 query hook files tested.

## Findings: Issues by Priority

### P1: Query Key Fragility (Maintenance Risk)

**Current:** ~50 `queryKey` string literals scattered across hooks and mutation invalidations. Example: `['dataset', id]` appears in `use-dataset.ts`, `use-collections.ts`, `use-records.ts`, `use-features.ts`.

**Risk:** Typo in one invalidation silently breaks cache coherence. Adding a new mutation that touches datasets requires finding all the scattered keys.

**Fix:** Introduce a query key factory. TanStack Query v5 (current) recommends this pattern:

```typescript
// lib/query-keys.ts
export const queryKeys = {
  datasets: {
    all: ['datasets'] as const,
    detail: (id: string) => ['dataset', id] as const,
    rows: (id: string, limit: number, cursor: number, filters?: Record<string, string>) =>
      ['dataset-rows', id, limit, cursor, filters] as const,
    history: (id: string, skip: number, limit: number) =>
      ['dataset-history', id, skip, limit] as const,
    versions: (id: string, skip: number, limit: number) =>
      ['dataset-versions', id, skip, limit] as const,
  },
  maps: {
    all: ['maps'] as const,
    list: (params: MapBrowseParams) => ['maps', params] as const,
    detail: (id: string) => ['map', id] as const,
    shareToken: (mapId: string) => ['map-share-token', mapId] as const,
    embedTokens: (mapId: string) => ['map-embed-tokens', mapId] as const,
  },
  search: {
    results: (params: Record<string, string>) => ['search', params] as const,
    facets: (params: Record<string, string>) => ['facets', params] as const,
    summary: ['catalog-summary'] as const,
  },
  // ... etc
} as const;
```

Invalidation becomes: `qc.invalidateQueries({ queryKey: queryKeys.datasets.all })` which prefix-matches all dataset queries.

**Impact:** HIGH -- prevents subtle cache bugs, makes invalidation patterns discoverable.
**Effort:** MEDIUM -- mechanical refactor, no logic changes.

### P2: `useBuilderLayers` Size (635 lines)

The largest hook at 635 lines. Contains: local layer state, imperative MapLibre API calls, event handler functions for visibility/reorder/paint/filter/label/style/opacity/layout, ephemeral layer management, add/remove dataset logic.

**Observation:** It is already extracted from `MapBuilderPage`, which is good. But the hook itself mixes two concerns: (1) React state management for layers, and (2) imperative MapLibre map mutations. These could be separated -- the map sync logic could be a dedicated hook or utility that takes map instance + layer state.

**Impact:** MEDIUM -- improves readability and testability. Currently the map-sync parts are hard to test in isolation.
**Effort:** MEDIUM -- requires careful extraction since the concerns are interleaved.

### P3: Duplicated Unsaved Guard Logic

`useBuilderSave` (lines 234-258) manually implements beforeunload + `useBlocker` + Ctrl+S, while `useUnsavedGuard` is a dedicated hook that does the same beforeunload + `useBlocker` pattern. The builder doesn't use `useUnsavedGuard` and instead reimplements it inline.

**Fix:** Have `useBuilderSave` use `useUnsavedGuard(hasUnsavedChanges)` instead of duplicating the pattern.

**Impact:** LOW -- code hygiene only, no behavioral change.
**Effort:** LOW -- 5-minute change.

### P4: `useQuicklook` Bypasses `apiFetch`

`useQuicklook` makes a raw `fetch()` call with manual auth header construction instead of using the existing `apiFetch` client. This means it misses the token refresh mutex, proactive refresh, error translation, and 401 retry logic.

**Fix:** Either use `apiFetch` (would need blob handling support since `apiFetch` currently assumes JSON) or convert to a TanStack Query hook that uses `queryFn` with proper auth.

**Impact:** LOW-MEDIUM -- the current code works because quicklook is read-only and auth failures just show a broken thumbnail. But it's a pattern divergence.
**Effort:** LOW -- small refactor.

### P5: `useAuth` Subscribes to 7 Separate Selectors

```typescript
const token = useAuthStore((s) => s.token);
const user = useAuthStore((s) => s.user);
const expiresAt = useAuthStore((s) => s.expiresAt);
const isAdmin = useAuthStore((s) => s.isAdmin());
const isEditor = useAuthStore((s) => s.isEditor());
const setAuth = useAuthStore((s) => s.setAuth);
const storeLogout = useAuthStore((s) => s.logout);
```

Each creates a separate subscription. This is technically fine for performance (React will batch updates), but the `isAdmin`/`isEditor` selectors call methods on every render, which re-creates references. A `useShallow` pick would be cleaner:

```typescript
const { token, user, expiresAt, setAuth, logout } = useAuthStore(
  useShallow((s) => ({
    token: s.token, user: s.user, expiresAt: s.expiresAt,
    setAuth: s.setAuth, logout: s.logout,
  }))
);
const isAdmin = user?.roles.includes('admin') ?? false;
const isEditor = ['admin', 'editor'].some(r => user?.roles.includes(r));
```

**Impact:** LOW -- minor performance improvement, cleaner code.
**Effort:** LOW.

### P6: Search Store `setFilter` Uses String Key

```typescript
setFilter: (key: string, value: string | string[] | boolean) => set({ [key]: value, offset: 0 }),
```

The `key` parameter is an untyped string, which means callers can pass any string without type checking. The interface should constrain the key to valid filter fields:

```typescript
setFilter: <K extends keyof Omit<SearchState, 'setQuery' | 'setFilter' | ...>>(
  key: K, value: SearchState[K]
) => void;
```

**Impact:** LOW -- type safety improvement, catches bugs at compile time.
**Effort:** LOW.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Query key management | Manual string arrays everywhere | Query key factory pattern | Prevents cache invalidation bugs |
| Unsaved changes guard | Inline beforeunload + useBlocker | `useUnsavedGuard` (already exists) | Avoids duplication |
| Auth token in fetches | Manual `fetch()` with header | `apiFetch` client | Gets refresh/retry/error handling free |

## Common Pitfalls

### Pitfall 1: Query Key Drift
**What goes wrong:** A new mutation invalidates `['datasets']` but a query uses `['dataset', id]` -- the prefix doesn't match and stale data persists.
**How to avoid:** Query key factory with hierarchical keys.
**Warning signs:** Users seeing stale data after mutations.

### Pitfall 2: Over-invalidation
**What goes wrong:** Some mutations invalidate 4-5 query keys. If the keys are broad prefixes, this triggers many unnecessary refetches.
**Current state:** The codebase is reasonable here -- most invalidations are targeted. `useDeleteDataset` invalidates 4 keys which is justified.
**How to avoid:** Prefer targeted key invalidation over broad prefix invalidation.

## Architecture Patterns

### Current Pattern (Keep)
```
stores/          -> 4 zustand stores (client-only state)
hooks/           -> ~37 custom hooks (TanStack Query + behavioral)
api/             -> API client functions (pure fetch wrappers)
components/ui/   -> 2 React contexts (theme, sidebar)
```

This flat structure works well at the current codebase size. Feature folders would add indirection without solving a real problem yet.

### Recommended Priority of Changes

1. **Query key factory** (P1) -- highest ROI, prevents real bugs
2. **useUnsavedGuard dedup** (P3) -- trivial fix, removes duplication
3. **useQuicklook -> apiFetch** (P4) -- removes pattern divergence
4. **Search store setFilter typing** (P6) -- trivial type safety win
5. **useAuth selector cleanup** (P5) -- minor polish
6. **useBuilderLayers split** (P2) -- largest effort, defer unless builder is actively changing

## Sources

### Primary (HIGH confidence)
- Direct code audit of all 4 stores, 37 hooks, 2 context providers, API client
- All files read from `frontend/src/stores/`, `frontend/src/hooks/`, `frontend/src/api/client.ts`
- Test coverage verified from `stores/__tests__/` and `hooks/__tests__/`

### Secondary (MEDIUM confidence)
- Bulletproof React patterns compared from established community documentation
- TanStack Query v5 best practices (query key factory pattern)

## Metadata

**Confidence breakdown:**
- State inventory: HIGH -- every store, hook, and context read in full
- Best practice assessment: HIGH -- based on direct code patterns, not assumptions
- Recommendations: HIGH -- all grounded in specific code locations

**Research date:** 2026-03-28
**Valid until:** 2026-04-28 (stable domain, slow-moving best practices)
