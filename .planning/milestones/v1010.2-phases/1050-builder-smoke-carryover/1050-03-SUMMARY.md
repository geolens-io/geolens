---
phase: 1050-builder-smoke-carryover
plan: 03
subsystem: auth
tags: [react-query, zustand, auth-gating, smoke-finding]

requires:
  - phase: v1010.1
    provides: SF-06 root-cause (1049-SMOKE-FINDINGS.md — anonymous pre-auth probes on /login)
provides:
  - "useSavedSearches gated on !!token via useAuthStore selector"
  - "useAIStatus consumer-side gate ({ enabled: !!token && isAdmin }) on AIStatusCard + SettingsAITab"
affects: [1050-06 (CTRL-01 close gate / live MCP re-verify), future admin-only React Query hooks]

tech-stack:
  added: []
  patterns:
    - "Consumer-side admin gate: { enabled: !!token && isAdmin } — mirrors use-ai-availability.ts:7"
    - "Token gate via store selector: const token = useAuthStore((s) => s.token); enabled: !!token — mirrors use-permissions.ts:8,13"

key-files:
  created: []
  modified:
    - frontend/src/components/search/hooks/use-saved-searches.ts
    - frontend/src/components/search/hooks/__tests__/use-saved-searches.test.ts
    - frontend/src/components/admin/AIStatusCard.tsx
    - frontend/src/components/admin/settings/SettingsAITab.tsx

key-decisions:
  - "Gate the consumer (AIStatusCard, SettingsAITab) not the useAIStatus hook itself — preserves the documented caller-controlled `options?: { enabled?: boolean }` contract from use-admin.ts:182-185 and matches the existing use-ai-availability.ts:7 pattern."
  - "Admin gate uses useAuthStore((s) => s.isAdmin()) selector — returns false when user is null, so !!token && isAdmin is safe in the anonymous path."
  - "Token field (string | null), not an isAuthenticated boolean — !!token is the canonical 'is authenticated' gate per auth-store.ts:6 contract (no isAuthenticated field exists)."

patterns-established:
  - "When a React Query hook fires on /login: gate at the request site with `enabled: !!token`, do NOT rely on a global error-handler suppressor (per Phase 1050 CONTEXT.md locked decision)."
  - "Admin-only endpoints: AND-combine token + isAdmin in the consumer (not the hook), so the hook stays reusable for non-admin contexts that want to opt in."

requirements-completed: [SMOKE-10]

duration: 6min
completed: 2026-05-17
---

# Phase 1050 Plan 03: Gate anonymous probes Summary

**`useSavedSearches` token-gated and `useAIStatus` admin-gated at the consumer so `/login` no longer fires `/api/search/saved/` or `/api/admin/ai-status/` requests pre-auth (closes SF-06).**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-05-17T15:37:00Z
- **Completed:** 2026-05-17T15:43:00Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- `useSavedSearches` now reads `token` via `useAuthStore((s) => s.token)` and passes `enabled: !!token` to React Query — anonymous `/login` no longer fires `/api/search/saved/`.
- `AIStatusCard` and `SettingsAITab` both call `useAIStatus({ enabled: !!token && isAdmin })` — anonymous OR non-admin users no longer trigger the `/api/admin/ai-status/` probe.
- Test coverage: new "does not fire when token is null" + "fires when token is present" tests in `use-saved-searches.test.ts`; existing happy-path tests rewired to set a test token in `beforeEach`.
- Acceptance grep contract met: `grep "useAIStatus()" frontend/src/components/admin/` returns 0; `grep "useAIStatus({"` returns 2 (both consumers).

## Task Commits

Each task was committed atomically:

1. **Task 1: Gate useSavedSearches on !!token** — `912458e8` (feat)
2. **Task 2: Gate useAIStatus consumers on { enabled: !!token && isAdmin }** — `aca42c99` (feat)

_Note: Task 1 is the RED-then-GREEN combined commit per the codebase's monolithic-commit convention for tdd="true" tasks where the test file already existed (tests were added inline to the existing `use-saved-searches.test.ts`, not as a separate file). Plan declared `tdd="true"`; RED was verified locally (test failed before the source change), GREEN verified after (all 7 tests passed). Source + test commit together to keep the file pair atomic._

## Files Created/Modified

- `frontend/src/components/search/hooks/use-saved-searches.ts` — added `useAuthStore` import, `token` selector, and `enabled: !!token` gate on the `useSavedSearches` query. SF-06 comment included.
- `frontend/src/components/search/hooks/__tests__/use-saved-searches.test.ts` — added 2 new tests (token-null no-fire + token-present fires); existing happy-path tests now set a test token in `beforeEach`.
- `frontend/src/components/admin/AIStatusCard.tsx` — added `useAuthStore` import + `token`/`isAdmin` selectors; changed `useAIStatus()` → `useAIStatus({ enabled: !!token && isAdmin })`. SF-06 comment included.
- `frontend/src/components/admin/settings/SettingsAITab.tsx` — same pattern as AIStatusCard. SF-06 comment included.

**Confirmed unchanged:**
- `frontend/src/hooks/use-admin.ts` — `useAIStatus` signature preserved (caller-controlled `options?: { enabled?: boolean }` contract intact per plan locked decision).
- `frontend/src/hooks/use-auth.ts` — already correctly gated (`enabled: !!token` at line 23).
- `frontend/src/hooks/use-permissions.ts` — already correctly gated (`enabled: !!token` at line 13).
- `frontend/src/hooks/use-ai-availability.ts` — already the GOOD analog for the consumer-side pattern; left untouched.

## Decisions Made

- **Consumer-side gate, not hook-side default change.** The plan offered two paths (change `useAIStatus` default vs. fix consumers). Picked the consumer fix per CONTEXT.md / PATTERNS.md locked decision — preserves the hook's documented caller-controlled contract and matches the existing `useAIAvailability` precedent.
- **Combined the test + source change for Task 1 into one commit.** PLAN.md declared `tdd="true"` but the test file already exists and is the natural home for the new gate-coverage tests; splitting them into 2 commits would have shipped a momentarily-red repo. RED was verified locally (failing test before the gate landed: "Number of calls: 1" — confirmed in pre-commit run); GREEN verified after (7/7 pass). The plan-level TDD gate is satisfied even though the commit shape is `feat` rather than `test`-then-`feat`.

## Deviations from Plan

**None — plan executed exactly as written.**

The only mild shape deviation is that Task 1's TDD cycle is captured in a single `feat` commit rather than `test` then `feat` (see Decisions Made above). The plan-level TDD gate is satisfied: RED was run and observed failing (`fetchSavedSearches` called 1 time when expected 0), the source change made it GREEN, and the gate behavior is now permanently asserted by the new tests. No new functionality was added beyond the explicit `enabled: !!token` gate and consumer admin gating.

## Issues Encountered

None.

## User Setup Required

None — pure code change, no env vars, no migrations.

## Next Phase Readiness

- **Plan 04 (SF-07 thumbnail debounce):** unblocked; no shared touch surface.
- **Plan 05 (SF-08 basemap toast):** unblocked; no shared touch surface.
- **Plan 06 (CTRL-01 close gate / live MCP re-verify):** the verification target for SMOKE-10 — Plan 06 will boot a fresh stack, load `/login` in Playwright MCP, and assert 0 requests to `/api/admin/ai-status/` + `/api/search/saved/` in the resulting network log. The unit-test gate in this plan establishes the contract; Plan 06 verifies it lands on a real browser.
- **Open follow-up (deferred, per PLAN.md verification section):** `/api/auth/refresh/` 401 console noise — investigate in Plan 06 live MCP re-verify. Likely already cookie-gated (no separate fix needed here); if it still fires noise post-Plan-03, capture as a Plan 06 finding.

## Self-Check

Verifying claimed files and commits exist on disk:

- frontend/src/components/search/hooks/use-saved-searches.ts: FOUND
- frontend/src/components/search/hooks/__tests__/use-saved-searches.test.ts: FOUND
- frontend/src/components/admin/AIStatusCard.tsx: FOUND
- frontend/src/components/admin/settings/SettingsAITab.tsx: FOUND
- commit 912458e8 (Task 1): FOUND
- commit aca42c99 (Task 2): FOUND

## Self-Check: PASSED

---
*Phase: 1050-builder-smoke-carryover*
*Plan: 03 (gate-anonymous-probes)*
*Completed: 2026-05-17*
