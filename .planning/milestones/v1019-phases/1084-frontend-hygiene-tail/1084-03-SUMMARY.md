---
phase: 1084-frontend-hygiene-tail
plan: "03"
subsystem: frontend
tags:
  - frontend
  - api-client
  - console-noise
  - bugfix
dependency_graph:
  requires: []
  provides:
    - clean single-prefix quicklook URLs (/api/datasets/<id>/quicklook)
  affects:
    - frontend/src/components/maps/hooks/use-quicklook.ts
tech_stack:
  added: []
  patterns:
    - "apiFetchBlob single-prefix contract: pass /resource/... not /api/resource/..."
key_files:
  created: []
  modified:
    - frontend/src/components/maps/hooks/use-quicklook.ts
    - frontend/src/components/maps/hooks/__tests__/use-quicklook.test.ts
decisions:
  - "Fix at source (hook), not at nginx or API_BASE — TD-12 explicit scope guardrail"
  - "TDD order: update test assertion first (red), then fix production code (green)"
metrics:
  duration: "~8 minutes"
  completed: "2026-05-22"
  tasks_completed: 1
  tasks_total: 2
  files_changed: 2
---

# Phase 1084 Plan 03: useQuicklook /api/api/ Double-Prefix Elimination Summary

One-liner: Drop leading `/api` literal from `use-quicklook.ts:58` so `apiFetchBlob` produces clean single-prefix `/api/datasets/<id>/quicklook?size=N` URLs.

## What Was Built

TD-12 close. `useQuicklook` was the sole outlier in the codebase — it passed a path starting with `/api/datasets/...` to `apiFetchBlob`, which itself prepends `API_BASE = '/api'` via `safeFetch(\`${API_BASE}${path}\`)`. The two `/api` prefixes concatenated to `/api/api/datasets/...`. Every other `apiFetch`/`apiFetchBlob` caller in the codebase (e.g., `src/api/maps.ts`, `src/api/datasets.ts`) passes paths WITHOUT the `/api` prefix.

## File Delta

### Production fix (`use-quicklook.ts:58`)

Before:
```
const blob = await apiFetchBlob(`/api/datasets/${datasetId}/quicklook?size=${size}`);
```

After:
```
const blob = await apiFetchBlob(`/datasets/${datasetId}/quicklook?size=${size}`);
```

### Test contract update (`use-quicklook.test.ts:188-190`, Test 8)

Before:
```js
expect(mockApiFetchBlob).toHaveBeenCalledWith(
  `/api/datasets/${id}/quicklook?size=256`,
);
```

After:
```js
expect(mockApiFetchBlob).toHaveBeenCalledWith(
  `/datasets/${id}/quicklook?size=256`,
);
```

## TDD Execution

**RED state:** Updated test assertion first. Ran `npx vitest run use-quicklook.test.ts`. Test 8 failed as expected — hook still produced `/api/datasets/...` while test expected `/datasets/...`. Tests 1-7 passed.

**GREEN state:** Applied production fix to line 58. Re-ran vitest. All 8 tests pass.

**Vitest result (final):**
```
Test Files  1 passed (1)
     Tests  8 passed (8)
  Duration  873ms
```

**Sibling tests (no collateral break):**
```
Test Files  3 passed (3)      [use-quicklook + use-map-thumbnail + MapCard]
     Tests  23 passed (23)
```

## Scope Guardrail Checks

| Check | Result |
|---|---|
| `grep -c '/api/datasets/' use-quicklook.ts` | 0 |
| `grep -c "apiFetchBlob(\`/datasets/" use-quicklook.ts` | 1 |
| `/api/datasets/` still in test | 0 |
| `/datasets/` in updated test assertion | 1 |
| Out-of-scope files touched (client.ts, constants.ts, use-map-thumbnail.ts, MapCard.test.tsx, use-map-thumbnail.test.ts) | 0 |
| nginx/backend/docker-compose modified | 0 |
| Commit contains ONLY the 2 in-scope files | PASS (2 files, 2 insertions, 2 deletions) |

## TypeScript

Pre-existing 36 errors in 14 test files (TD-09 baseline, not introduced by this plan). No errors exist in `use-quicklook.ts` or `use-quicklook.test.ts`. TD-09 is closed by Plan 1084-01.

## Task 2: Playwright MCP Verification Steps

Task 2 is a `checkpoint:human-verify` — to be executed by the orchestrator in a separate pass after all Wave 1 plans complete.

### Assertions the verifier must make

**Pre-condition:** Stack is up at `http://localhost:8080`. If not:
```
docker compose up -d --build api worker frontend
```

**Setup:** Open browser DevTools Network panel. Clear all requests.

**Assertion A — SearchPage quicklook requests (primary):**
1. Navigate to `http://localhost:8080/`
2. Scroll dataset card list to trigger at least 5 `useQuicklook` fetches
3. Wait 5 seconds for requests to settle
4. Assert in network log:
   - ZERO requests contain `/api/api/` in URL
   - Quicklook requests appear as `GET /api/datasets/<uuid>/quicklook?size=256` (single-prefix)
   - At least one such request returned status 200 (Bearer JWT still attached, correct route reached)

**Assertion B — Map Builder DatasetSearchPanel:**
1. Navigate to `http://localhost:8080/maps` and open an existing map
2. Open the dataset search drawer, scroll dataset list
3. Assert ZERO requests contain `/api/api/` in URL
4. Assert dataset quicklook thumbnails render (`<img src="blob:...">` elements visible)

**Assertion C — Map thumbnail regression check (useMapThumbnail not broken):**
1. From the `/maps` list page, observe map card thumbnails
2. Assert `GET /api/maps/<id>/thumbnail/` appears in network log (NOT `/api/api/maps/...`)
3. Assert map thumbnail `<img>` elements have `src="blob:..."` (renders correctly)

**Expected pass phrase:** `0 /api/api/ URLs in network log over <N> quicklook requests, <M> 200 OK responses observed, map thumbnails still render correctly`

**Failure protocol:** If any `/api/api/` URL appears, report the offending request path so the executor can check for a second bug site outside `use-quicklook.ts`.

## Deviations from Plan

None — plan executed exactly as written. TDD order followed strictly (red before green). Scope guardrails all green. `App.tsx` was visible in `git diff --name-only` (modified by parallel Plan 1084-02) but was NOT staged in this commit.

## Commits

| Task | Commit | Files |
|---|---|---|
| Task 1: TDD fix (red+green) | 27da412c | use-quicklook.ts, use-quicklook.test.ts |

## Self-Check: PASSED

- [x] `use-quicklook.ts` modified — confirmed at commit 27da412c
- [x] `use-quicklook.test.ts` modified — confirmed at commit 27da412c
- [x] `git log --oneline` shows 27da412c `fix(1084-03): remove /api double-prefix from useQuicklook apiFetchBlob call`
- [x] All 8 vitest tests pass
- [x] Zero out-of-scope files staged
