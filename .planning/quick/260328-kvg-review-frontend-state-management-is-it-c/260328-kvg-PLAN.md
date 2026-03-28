---
phase: 260328-kvg
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/lib/query-keys.ts
  - frontend/src/lib/__tests__/query-keys.test.ts
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
autonomous: true
requirements: [QUICK-TASK]

must_haves:
  truths:
    - "All query keys are defined in a single centralized factory file"
    - "Every hook file uses the factory instead of string literal query keys"
    - "Cache invalidation uses factory keys with prefix matching"
    - "useBuilderSave delegates unsaved-guard logic to useUnsavedGuard hook"
    - "useQuicklook uses apiFetch-compatible auth pattern instead of raw fetch"
    - "Search store setFilter is type-safe against known filter keys"
    - "All existing tests pass after refactor"
  artifacts:
    - path: "frontend/src/lib/query-keys.ts"
      provides: "Centralized query key factory"
      exports: ["queryKeys"]
    - path: "frontend/src/lib/__tests__/query-keys.test.ts"
      provides: "Query key factory tests"
  key_links:
    - from: "frontend/src/hooks/*.ts"
      to: "frontend/src/lib/query-keys.ts"
      via: "import { queryKeys }"
      pattern: "queryKeys\\."
    - from: "frontend/src/hooks/use-builder-save.ts"
      to: "frontend/src/hooks/use-unsaved-guard.ts"
      via: "import { useUnsavedGuard }"
      pattern: "useUnsavedGuard"
---

<objective>
Refactor frontend state management to address the six findings from the research audit, prioritized by impact.

Purpose: Eliminate query key fragility (main maintenance risk), remove code duplication, improve type safety, and bring patterns into closer alignment with TanStack Query and Bulletproof React best practices.

Output: Centralized query key factory, all hooks migrated, duplicated unsaved-guard removed, useQuicklook auth fixed, search store typed, comprehensive SUMMARY with findings report.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/quick/260328-kvg-review-frontend-state-management-is-it-c/260328-kvg-CONTEXT.md
@.planning/quick/260328-kvg-review-frontend-state-management-is-it-c/260328-kvg-RESEARCH.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create query key factory and migrate all hooks</name>
  <files>
    frontend/src/lib/query-keys.ts,
    frontend/src/lib/__tests__/query-keys.test.ts,
    frontend/src/hooks/use-dataset.ts,
    frontend/src/hooks/use-maps.ts,
    frontend/src/hooks/use-collections.ts,
    frontend/src/hooks/use-admin.ts,
    frontend/src/hooks/use-search.ts,
    frontend/src/hooks/use-records.ts,
    frontend/src/hooks/use-features.ts,
    frontend/src/hooks/use-settings.ts,
    frontend/src/hooks/use-embed-tokens.ts,
    frontend/src/hooks/use-ingest.ts,
    frontend/src/hooks/use-saved-searches.ts,
    frontend/src/hooks/use-api-keys.ts,
    frontend/src/hooks/use-tile-token.ts,
    frontend/src/hooks/use-vrt.ts,
    frontend/src/hooks/use-edition.ts,
    frontend/src/hooks/use-permissions.ts,
    frontend/src/hooks/use-auth.ts,
    frontend/src/hooks/use-builder-save.ts
  </files>
  <action>
    This is the P1 fix from research -- highest ROI, prevents real cache invalidation bugs.

    **Step 1: Create `frontend/src/lib/query-keys.ts`**

    Define a hierarchical query key factory using `as const` assertions. Group by domain. Every unique query key string currently scattered across hooks must have a factory entry.

    Domains to include (derived from full grep of existing keys):

    ```
    queryKeys.auth        -> me: ['auth', 'me'], permissions: ['auth', 'permissions']
    queryKeys.datasets    -> all: ['datasets'], detail(id), rows(id, limit, cursor, filters?), history(id, skip, limit), versions(id, skip, limit), attributes(id), validation(id), related(id)
    queryKeys.maps        -> all: ['maps'], list(params), detail(id), shareToken(mapId), datasetMaps(datasetId), columnValues(datasetId, col), columnStats(datasetId, col)
    queryKeys.collections -> all: ['collections'], list(skip, limit), detail(id), datasets(collectionId, skip, limit)
    queryKeys.search      -> results(params), facets(params), summary: ['catalog-summary']
    queryKeys.records     -> contacts(recordId), keywords(recordId), distributions(recordId)
    queryKeys.admin       -> stats, users(skip, limit, status, search), userNames, auditLogs(params), pendingCount, jobs(params), failedJobCount, aiStatus, shareTokens(skip, limit, search, status), embedTokens(params), apiKeys(userId), embeddingStats, infrastructure
    queryKeys.settings    -> basemaps, mapDefaults, tileConfig, enabledWidgets, all, configMode, apiKeyStatus, branding
    queryKeys.embedTokens -> list(mapId)
    queryKeys.ingest      -> jobStatus(jobId), discoverTables, uploadConfig
    queryKeys.savedSearches -> all: ['saved-searches']
    queryKeys.apiKeys     -> mine: ['my-api-keys']
    queryKeys.tileTokens  -> token(datasetId)
    queryKeys.vrt         -> sources(datasetId), status(datasetId), generations(datasetId, params)
    queryKeys.edition     -> edition: ['edition']
    queryKeys.sharedMap   -> detail(token, apiKey)
    ```

    Key design rules:
    - Each domain has an `all` key (the shortest prefix) used for broad invalidation. E.g. `queryKeys.datasets.all` returns `['datasets']` so `invalidateQueries({ queryKey: queryKeys.datasets.all })` prefix-matches all dataset queries.
    - Parameterized keys extend the prefix: `queryKeys.datasets.detail(id)` returns `['datasets', id]`.
    - IMPORTANT: Preserve exact existing key structures. For example, the current codebase uses `['dataset', id]` (singular) for detail and `['datasets']` for list. To avoid breaking any existing cached data during deployment, keep those exact strings. The factory value is the key structure, not a new naming convention.
    - Use `as const` on all returned tuples for type safety.

    **Step 2: Create `frontend/src/lib/__tests__/query-keys.test.ts`**

    Test that:
    - Each factory function returns the expected array structure
    - Parameterized keys include all params
    - `all` keys are proper prefixes of their domain's detail keys (this is what makes invalidation work)

    **Step 3: Migrate all 19 hook files + use-builder-save.ts**

    For each hook file:
    1. Add `import { queryKeys } from '@/lib/query-keys';`
    2. Replace every `queryKey: ['literal', ...]` with the corresponding `queryKeys.domain.method(...)` call
    3. Replace every `invalidateQueries({ queryKey: ['literal', ...] })` with the factory equivalent
    4. Remove no-longer-needed inline key arrays

    Migration must be mechanical -- NO logic changes to any hook. Only key references change.

    CRITICAL: The `use-builder-save.ts` file at line 119 uses `queryClient.getQueryData<MapResponse>(['maps', id])` -- this must also be migrated to use the factory key. And line 40 `queryClient.invalidateQueries({ queryKey: ['maps'] })` must use `queryKeys.maps.all`.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx vitest run --passWithNoTests 2>&1 | tail -20</automated>
  </verify>
  <done>
    - `frontend/src/lib/query-keys.ts` exists and exports `queryKeys` with entries for all ~50 unique query key patterns
    - Zero string literal `queryKey:` arrays remain in any hook file (all use factory)
    - Zero string literal `invalidateQueries({ queryKey: [` patterns remain (all use factory)
    - All existing tests pass
  </done>
</task>

<task type="auto">
  <name>Task 2: Fix duplicated unsaved guard, quicklook auth bypass, search store typing, and auth selectors</name>
  <files>
    frontend/src/hooks/use-builder-save.ts,
    frontend/src/hooks/use-quicklook.ts,
    frontend/src/stores/search-store.ts
  </files>
  <action>
    Address P3, P4, P5, and P6 from research. All are small, independent fixes.

    **P3: Deduplicate unsaved guard in useBuilderSave**

    In `use-builder-save.ts`:
    1. Add `import { useUnsavedGuard } from '@/hooks/use-unsaved-guard';`
    2. Replace the inline `useEffect` for beforeunload (lines ~234-242) AND the `useBlocker` call (line ~245) with a single: `const blocker = useUnsavedGuard(state.hasUnsavedChanges);`
    3. Keep the Ctrl+S keyboard shortcut effect -- that is NOT part of the unsaved guard pattern.
    4. Return `blocker` as before -- the `useUnsavedGuard` hook already returns the blocker.

    **P4: Fix useQuicklook auth bypass**

    In `use-quicklook.ts`, the raw `fetch()` bypasses `apiFetch` (and its token refresh mutex, proactive refresh, 401 retry). Since quicklook needs blob response (not JSON), we cannot directly use `apiFetch`. Instead:

    1. Keep the manual `fetch()` approach (blob responses require it), BUT import the token from the auth store via `useAuthStore.getState()` and also import `apiFetch` internals if available, OR more pragmatically:
    2. Refactor to use TanStack Query with a custom `queryFn` that does the blob fetch but still gets the token from `useAuthStore.getState()`. This replaces the manual `useState`/`useEffect` with `useQuery`:

    ```typescript
    import { useQuery } from '@tanstack/react-query';
    import { useAuthStore } from '@/stores/auth-store';
    import { queryKeys } from '@/lib/query-keys';

    export function useQuicklook(datasetId: string | null) {
      const { data: src = null, isLoading, isError } = useQuery({
        queryKey: queryKeys.datasets.quicklook(datasetId!),
        queryFn: async () => {
          const token = useAuthStore.getState().token;
          const headers: Record<string, string> = {};
          if (token) headers['Authorization'] = `Bearer ${token}`;
          const r = await fetch(`/api/datasets/${datasetId}/quicklook?size=256`, { headers });
          if (!r.ok) throw new Error(String(r.status));
          const blob = await r.blob();
          return URL.createObjectURL(blob);
        },
        enabled: !!datasetId,
        staleTime: 5 * 60 * 1000,
        retry: false,
        meta: { skipGlobalError: true },
      });
      return { src, isLoading, isError };
    }
    ```

    NOTE: This approach means we lose the manual blob URL revocation on unmount. That is acceptable -- blob URLs from `createObjectURL` are small references and are automatically released when the document unloads. For a thumbnail that is a negligible memory impact. If you want to be precise, you can add a `useEffect` cleanup that revokes the previous `src` when it changes. But do NOT add complex ref-based lifecycle -- the whole point is simplification.

    Add `quicklook(datasetId)` to `queryKeys.datasets` in the factory (from Task 1) -- e.g. `quicklook: (id: string) => ['dataset-quicklook', id] as const`.

    **P5: Clean up useAuth selectors** (SKIP -- the research rated this LOW impact and the current code is not wrong, just slightly verbose. The 7 individual selectors are actually fine for performance since React batches updates. Changing to `useShallow` would be a style preference, not a bug fix. Leave as-is to minimize churn.)

    **P6: Type-safe search store setFilter**

    In `search-store.ts`:
    1. Extract a `SearchFilterKey` type from the `SearchState` interface that includes only the data fields (exclude methods and non-filter fields like `offset`, `limit`, `spatialPanelOpen`):

    ```typescript
    type SearchFilterKey = 'q' | 'bbox' | 'keywords' | 'geometry_type' | 'srid'
      | 'source_organization' | 'record_type' | 'collection_id' | 'datetime'
      | 'date_from' | 'date_to' | 'vintage_start' | 'vintage_end' | 'sort_by'
      | 'exclude_synthetic' | 'geometry' | 'spatial_predicate';
    ```

    2. Update `setFilter` signature from `(key: string, value: string | string[] | boolean)` to `(key: SearchFilterKey, value: string | string[] | boolean)`.

    3. Verify callers compile -- all existing callers already pass valid field names, so this should be a pure type-narrowing change with no runtime effect.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx vitest run --passWithNoTests 2>&1 | tail -20</automated>
  </verify>
  <done>
    - `use-builder-save.ts` imports and uses `useUnsavedGuard` -- no inline beforeunload/useBlocker logic remains (except the Ctrl+S handler which is separate)
    - `use-quicklook.ts` uses TanStack Query with `queryKeys` instead of raw `useState`/`useEffect`/`fetch`
    - `search-store.ts` exports `SearchFilterKey` type and `setFilter` accepts only valid filter keys
    - All existing tests pass
    - No behavioral changes -- all refactors are structural/type-safety only
  </done>
</task>

</tasks>

<verification>
After both tasks complete:

1. **No string literal query keys remain in hooks:**
   ```bash
   grep -rn "queryKey: \['" frontend/src/hooks/ | grep -v query-keys | wc -l
   # Should be 0
   ```

2. **Factory is the single source of truth:**
   ```bash
   grep -rn "queryKeys\." frontend/src/hooks/ | wc -l
   # Should be ~120+ (all former string literals now use factory)
   ```

3. **Full test suite passes:**
   ```bash
   cd frontend && npx vitest run --passWithNoTests
   ```

4. **TypeScript compiles clean:**
   ```bash
   cd frontend && npx tsc --noEmit
   ```
</verification>

<success_criteria>
- Query key factory exists at `frontend/src/lib/query-keys.ts` with all ~50 key patterns
- All 19 hook files + `use-builder-save.ts` import and use the factory
- Zero string literal query key arrays in hook files
- `useBuilderSave` uses `useUnsavedGuard` instead of duplicated logic
- `useQuicklook` uses TanStack Query pattern
- `search-store.ts` `setFilter` is type-constrained
- All tests pass, TypeScript compiles
</success_criteria>

<output>
After completion, create `.planning/quick/260328-kvg-review-frontend-state-management-is-it-c/260328-kvg-SUMMARY.md`

The SUMMARY must include the full findings report covering:
1. Architecture assessment (what the codebase does well)
2. Pattern alignment with Bulletproof React
3. All 6 findings from research (P1-P6), their status (fixed vs deferred), and rationale
4. What was changed and why
5. What was NOT changed and why (P2 useBuilderLayers split deferred, P5 auth selectors left as-is)
</output>
