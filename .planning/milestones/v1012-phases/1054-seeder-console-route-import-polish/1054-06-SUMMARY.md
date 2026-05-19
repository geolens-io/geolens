---
phase: 1054-seeder-console-route-import-polish
plan: "06"
subsystem: api
tags: [fetch, error-handling, typescript, vitest, shared-maps]

requires: []
provides:
  - "ROUTE-04: apiFetch expected404 opt-in for quiet-404 paths"
  - "getSharedMap returns SharedMapResponse | null; 404 resolves to null instead of throwing"
affects:
  - PublicViewerPage
  - useSharedMap
  - any future endpoint that opts into expected404

tech-stack:
  added: []
  patterns:
    - "expected404 opt-in on apiFetch — caller-declared, per-call; converts 404 to null without disabling the 401 refresh chain"

key-files:
  created: []
  modified:
    - frontend/src/api/client.ts
    - frontend/src/api/maps.ts
    - frontend/src/pages/__tests__/PublicViewerPage.test.tsx

key-decisions:
  - "expected404 is strictly opt-in per call-site — no global config, no endpoint pattern matching. Future contributors must explicitly pass the flag."
  - "expected404 fires AFTER authenticatedFetch returns a final response; the 401-refresh-then-retry flow is unaffected."
  - "Only 404 is quieted; 403, 410, 500 etc. still throw ApiError normally. The audit's 410-expired branch is preserved."
  - "Accepted that the browser's native network-tab 404 entry cannot be suppressed from JS — the fix eliminates the application-layer throw, not the browser's own logging."

patterns-established:
  - "expected404 pattern: apiFetch<T | null>(path, { expected404: true }) — caller returns T | null, consumer handles null as not-found without error state"

requirements-completed:
  - ROUTE-04

duration: 8min
completed: 2026-05-19
---

# Phase 1054 Plan 06: ROUTE-04 Quiet-404 for Share Token Lookup Summary

**apiFetch extended with expected404 opt-in; getSharedMap now resolves invalid tokens to null instead of throwing ApiError(404), eliminating application-layer console noise for /m/{invalid-token}**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-05-19T21:47Z
- **Completed:** 2026-05-19T21:55Z
- **Tasks:** 1 (TDD: RED + GREEN commits)
- **Files modified:** 3

## Accomplishments

- Added `expected404?: boolean` opt-in to `apiFetch` — when the response is 404 and the flag is set, returns `null` instead of throwing `ApiError(404)`. Other status codes, and all non-opt-in callers, are unaffected.
- Updated `getSharedMap` to pass `expected404: true` and return `SharedMapResponse | null`. A null return propagates through `useSharedMap` to `PublicViewerPage`'s existing `isError || !data` guard — no UI change.
- Added 3 regression tests: quiet-404 path (null data, no console.error), valid-200 path (viewer renders), loud-410 path (ApiError(410) still surfaces "Link expired" — proves the quiet path is not over-broadened).

## Type Signature Changes

`getSharedMap` return type changed from `Promise<SharedMapResponse>` to `Promise<SharedMapResponse | null>`. TypeScript propagates this cleanly through `useSharedMap` → `PublicViewerPage`'s `data` field, which is already guarded by `isError || !data`. `pnpm typecheck` / `tsc --noEmit` exits 0.

## Browser-Native Network Log Caveat

This fix addresses the **application-layer** error surface. The browser's DevTools network panel will still show a `(failed)` or `404` row for `GET /api/maps/shared/{token}/` — that is produced by the browser before any JavaScript sees the response and cannot be suppressed from application code. The audit's ROUTE-04 recommendation is satisfied by eliminating the `ApiError(404)` throw that previously surfaced in TanStack Query's error reporting.

## Task Commits

TDD cycle — two commits:

1. **RED — regression tests** - `56287858` (test)
2. **GREEN — expected404 implementation** - `ce7f5742` (feat)

## Files Created/Modified

- `frontend/src/api/client.ts` — Added `expected404?: boolean` to `apiFetch` options; destructures it before passing to `authenticatedFetch`; added quiet-return branch for `response.status === 404 && expected404`; JSDoc updated.
- `frontend/src/api/maps.ts` — `getSharedMap` return type widened to `SharedMapResponse | null`; passes `expected404: true`; adds `if (resp === null) return null` guard before layer normalization. JSDoc added.
- `frontend/src/pages/__tests__/PublicViewerPage.test.tsx` — Imported `ApiError`; added `describe('ROUTE-04')` block with 3 tests.

## Decisions Made

- Used destructuring (`const { expected404, ...fetchOptions } = options`) to strip the custom flag before passing options to `authenticatedFetch` — avoids leaking a non-standard property to the browser's `fetch()`.
- The `expected404` branch is placed BEFORE the `!response.ok` block, so it intercepts 404 responses before the error-detail extraction and throw path.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

Test 3 initially used `/link expired/i` but the i18n key `viewer.linkExpired` renders as "This link has expired" in the test environment. Updated the assertion to match the actual rendered text. Minor — caught on first RED run.

## User Setup Required

None — no external service configuration required.

## Requirements Closed

- ROUTE-04: `/m/{invalid-share-token}` quiet 404 path — application-layer error noise eliminated.

## Next Phase Readiness

- ROUTE-04 closed. Phase 1056 live MCP verification can confirm the browser console is clean (application-layer `console.error` is the suppressible surface; browser network tab is accepted as-is).
- No other endpoints use `expected404` — the opt-in is available for future use where 404 is a known-handled outcome.

---
*Phase: 1054-seeder-console-route-import-polish*
*Completed: 2026-05-19*

## Self-Check: PASSED

Files created/modified exist:
- `frontend/src/api/client.ts` — FOUND
- `frontend/src/api/maps.ts` — FOUND
- `frontend/src/pages/__tests__/PublicViewerPage.test.tsx` — FOUND

Commits exist:
- `56287858` — FOUND (test: add ROUTE-04 regression tests)
- `ce7f5742` — FOUND (feat: add expected404 opt-in to apiFetch)
