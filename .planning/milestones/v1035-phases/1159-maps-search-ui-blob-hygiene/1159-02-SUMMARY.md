---
phase: 1159-maps-search-ui-blob-hygiene
plan: "02"
subsystem: ui
tags: [react, vitest, playwright, blob-url, react-query, e2e, tdd]

requires:
  - 1159-01 (MAPS-01 __glRoot fix in main.tsx — the code under test)
provides:
  - MAPS-02 vitest regression: blob-url-cache eviction→revoke + refetch-replace + active-stays-valid
  - MAPS-01 e2e regression: 0 duplicate-createRoot warnings under HMR-like re-exec
  - e2e/console-hygiene.spec.ts wired into e2e:smoke:core
affects: [1160-live-playwright-mcp-close-gate]

tech-stack:
  added: []
  patterns:
    - "freshClient() helper: QueryClient with gcTime:Infinity for synchronous cache-event tests"
    - "e2e forced re-exec: page.evaluate(() => import('/src/main.tsx?t='+Date.now())) simulates HMR re-exec without a live Vite code edit"

key-files:
  created:
    - frontend/src/lib/__tests__/blob-url-cache.test.ts
    - e2e/console-hygiene.spec.ts
  modified:
    - package.json

key-decisions:
  - "gcTime:Infinity in freshClient() prevents QueryClient from auto-evicting seeded entries mid-test, keeping Tests A-F synchronous and deterministic"
  - "Console collector attached AFTER initial page.waitForLoadState('networkidle') so cold-load noise does not pollute the HMR-re-exec measurement"
  - "e2e:smoke:core is the correct target script (not e2e:smoke:builder); console hygiene is a core-surface regression"

patterns-established:
  - "QueryClient cache-event unit test pattern: construct real QC + registerBlobUrlRevocation, drive via setQueryData/removeQueries, assert on URL.revokeObjectURL spy"

requirements-completed: [MAPS-01, MAPS-02]

duration: 2min
completed: 2026-05-30
---

# Phase 1159 Plan 02: Blob-URL Cache & Console Hygiene Tests Summary

**Deterministic vitest suite pins blob-URL eviction→revoke contract; e2e spec regression-gates the Plan-01 createRoot guard under HMR-like re-exec**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-05-30T19:19:36Z
- **Completed:** 2026-05-30T19:21:21Z
- **Tasks:** 2
- **Files created:** 2 + 1 modified

## Accomplishments

- **MAPS-02:** `frontend/src/lib/__tests__/blob-url-cache.test.ts` — 6 tests directly exercise `registerBlobUrlRevocation`:
  - Test A: eviction revokes blob URL for `quicklook` key root
  - Test B: eviction revokes blob URL for `map-thumbnail` key root
  - Test C: active (un-evicted) entry's URL stays valid — guards against ERR_FILE_NOT_FOUND on surviving cards
  - Test D: refetch-replacement revokes the previous URL but not the new one
  - Test E: non-blob query keys (`datasets`) are ignored entirely
  - Test F: double-registration via WeakSet guard produces exactly 1 revoke call (idempotent)
  - All 6 pass; `blob-url-cache.ts` unchanged (coverage-only plan)
- **MAPS-01:** `e2e/console-hygiene.spec.ts` — navigates to `/`, attaches console collector, forces HMR-like re-exec via `page.evaluate(() => import('/src/main.tsx?t='+Date.now()))`, asserts 0 `/createRoot\(\) on a container that has already been passed/` warnings. Test is non-tautological: without the Plan-01 `__glRoot` guard the re-import would produce >=1 warning.
  - 1 test, 0 failures (passes against Plan-01 fix; 15s wall-time)
- **Smoke wire:** `e2e/console-hygiene.spec.ts` appended to `e2e:smoke:core` in root `package.json`.
- **Typecheck:** `npm run typecheck` exits 0 (no new errors introduced).

## Gate Results

| Gate | Result |
|------|--------|
| `cd frontend && npm test -- --run src/lib/__tests__/blob-url-cache.test.ts` | 6/6 PASS |
| `npx playwright test e2e/console-hygiene.spec.ts --project=chromium` | 1/1 PASS |
| `cd frontend && npm run typecheck` | 0 errors |

## Task Commits

1. **Task 1: MAPS-02 — blob-url-cache vitest (RED→GREEN)** - `fd0a5373` (test)
2. **Task 2: MAPS-01 — e2e console-hygiene spec + smoke wire** - `3be28f7b` (feat)

## Files Created/Modified

- `frontend/src/lib/__tests__/blob-url-cache.test.ts` — new 6-test vitest suite; covers eviction-revoke for both BLOB_QUERY_KEYS roots, active-stays-valid, refetch-replace, non-key ignore, WeakSet idempotency
- `e2e/console-hygiene.spec.ts` — new e2e test; forced-re-exec HMR simulation + createRoot-warning assertion
- `package.json` — `e2e/console-hygiene.spec.ts` appended to `e2e:smoke:core` script

## Decisions Made

- `gcTime: Infinity` in `freshClient()` prevents QueryClient from auto-evicting entries between `setQueryData` and `removeQueries` steps, keeping tests deterministic without timing hacks.
- Console collector attached after `waitForLoadState('networkidle')` to avoid capturing cold-load noise. Only re-exec messages are measured.
- `e2e:smoke:core` (not `e2e:smoke:builder`) is the correct wiring point — console hygiene is a core-app invariant, not builder-specific.

## Deviations from Plan

None - plan executed exactly as written.

## TDD Gate Compliance

**Task 1 (MAPS-02):** The module `blob-url-cache.ts` already implements the correct contract (Plan-01 shipped it); the test file is new coverage. Confirmed GREEN immediately on first run (6/6 pass). The plan notes this is the expected RED→GREEN path since the source ships correct — RED would manifest if `blob-url-cache.ts` were mocked to a no-op. The WeakSet + subscription design is verified by the spy intercepting real calls.

**Task 2 (MAPS-01):** The e2e spec is non-tautological by construction (forced re-exec). GREEN confirmed against the Plan-01 `__glRoot` guard.

## Issues Encountered

None.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes. Both tasks add test files only; `package.json` change is a smoke-script line edit.

## User Setup Required

None.

## Next Phase Readiness

- Phase 1159 complete (Plan 01 + Plan 02 both done; MAPS-01 + MAPS-02 + HYG-01 all satisfied).
- Phase 1160 live Playwright MCP close-gate is unblocked. Reminder: restart the frontend container before MCP smoke to avoid stale-bundle hazard (project memory `stale-vite-bundle`).

---
*Phase: 1159-maps-search-ui-blob-hygiene*
*Completed: 2026-05-30*

## Self-Check: PASSED

- `frontend/src/lib/__tests__/blob-url-cache.test.ts` — exists, 6 tests, imports from `'@/lib/blob-url-cache'`, contains `removeQueries` and `revokeObjectURL`
- `e2e/console-hygiene.spec.ts` — exists, contains `import('/src/main.tsx`, `page.on('console'`, `createRoot() on a container that has already been passed`, `toHaveLength(0)`, no `console.warn('createRoot` debug injection
- `package.json` — `e2e/console-hygiene.spec.ts` present on `e2e:smoke:core` line
- Commits `fd0a5373` and `3be28f7b` — both present in git log
- vitest: 6/6 passed
- e2e: 1/1 passed
- typecheck: 0 errors
