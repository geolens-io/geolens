---
phase: 1054-seeder-console-route-import-polish
plan: "02"
subsystem: ui
tags: [react, tanstack-query, zustand, auth, hooks]

# Dependency graph
requires:
  - phase: 1050-rev
    provides: v1010.2 SF-06 consumer-side gating pattern (!!token && isAdmin on useAIStatus)
provides:
  - useAIAvailability gated on !!token && isAdmin — suppresses /api/admin/ai-status/ 401 noise for anonymous + non-admin sessions
affects: [dataset-detail tabs, MapCreateDialog, any future consumer of useAIAvailability]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "useAIAvailability mirrors AIStatusCard/SettingsAITab pattern: !!token && isAdmin gate on the admin probe"

key-files:
  created: []
  modified:
    - frontend/src/hooks/use-ai-availability.ts
    - frontend/src/hooks/__tests__/use-ai-availability.test.tsx

key-decisions:
  - "Gate useAIAvailability on !!token && isAdmin (not just !!token) — mirrors AIStatusCard.tsx:22 and SettingsAITab.tsx:50"
  - "SP-08 beforeEach updated to set adminUser (roles: ['admin']) so caching tests continue to fire the query after gate tightening"
  - "Auth-store rehydration probes (/auth/refresh/, /auth/me/) left intentionally untouched — out of CONSOLE-01 scope per audit recommendation"

patterns-established:
  - "Any hook that calls a /api/admin/* endpoint must gate on !!token && isAdmin, not just !!token"

requirements-completed:
  - CONSOLE-01

# Metrics
duration: 10min
completed: 2026-05-19
---

# Phase 1054 Plan 02: CONSOLE-01 useAIAvailability isAdmin Gate Summary

**Tightened `useAIAvailability` gate from `!!token` to `!!token && isAdmin`, eliminating 401/403 noise on `/api/admin/ai-status/` for anonymous and non-admin sessions across all four dataset-detail consumers.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-05-19T21:35:00Z
- **Completed:** 2026-05-19T21:45:43Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 2

## Accomplishments

- Added `isAdmin` selector from `useAuthStore` in `useAIAvailability`, matching the `AIStatusCard` / `SettingsAITab` pattern exactly
- Eliminated the `/api/admin/ai-status/` ×3 console 401 errors cited in the CONSOLE-01 audit finding
- Updated SP-08 `beforeEach` to set `adminUser` (roles: `['admin']`) so the existing caching tests continue to exercise the enabled-query path after gate tightening
- Added three CONSOLE-01 regression tests covering: anonymous (no token), authed non-admin (viewer), and authed admin (fires)

## What Was Built

`useAIAvailability` previously gated on `enabled: !!token` only. Any user with a token — including editors/viewers — and any anonymous session with a stale localStorage token from a prior admin session would cause TanStack Query to issue `GET /api/admin/ai-status/`. The backend's `admin_required` dependency returns 401/403 for these callers, producing console noise.

The fix adds an `isAdmin` selector (same pattern as `AIStatusCard.tsx:21-22`) and chains `!!token && isAdmin` — identical to the established v1010.2 SF-06 pattern. Non-admin callers now see `isAIAvailable = false` because `aiStatus.data` never loads, which is the correct UX: only admins configure/see AI status.

## Tests Added

Three new tests in `describe('useAIAvailability — CONSOLE-01 gating')`:

1. **anonymous user (no token)**: `useAuthStore.setState({ token: null, user: null })` → `fetchStatus === 'idle'`, `getAIStatus` not called.
2. **authed non-admin (viewer token, no admin role)**: `roles: ['viewer']` → `fetchStatus === 'idle'`, `getAIStatus` not called.
3. **authed admin**: `roles: ['admin']` → `data` resolves, `getAIStatus` called once.

All 6 tests (3 SP-08 + 3 CONSOLE-01) pass. Full suite: 2004/2004.

## Audit-listed 401s

### Closed by this plan

| Error | Count | Route | Fix |
|-------|-------|-------|-----|
| 401 Unauthorized | ×3 | `/api/admin/ai-status/` | `useAIAvailability` now gated on `!!token && isAdmin` |

### Deferred-as-expected (out of CONSOLE-01 scope per audit recommendation)

| Error | Count | Route | Reason |
|-------|-------|-------|--------|
| 401 | ×2 | `/api/auth/refresh/` | Auth-store rehydration probe; fires once on persist hydration when stale `refreshToken` lingers. Closing requires expiry pre-check in `tryRefresh` — audit explicitly flags as "arguably expected" and out of scope. |
| 401 | ×2 | `/api/auth/me/` | Same rehydration flow — fires after refresh attempt. Same rationale. |
| 401/403 | ×3 | `/api/auth/me/permissions/` | Follows /auth/me/ in the rehydration chain. Same rationale. |
| 401 | ×2 | `/api/search/saved/` | Gated by `useAuthStore`'s `token` presence — fires during rehydration window before `logout()` clears the stale token. Same rationale. |

Per CONTEXT.md's audit note: `logout()` at `auth-store.ts:76` already clears all persisted tokens on user-initiated logout. The remaining noise is a one-shot rehydration artifact, not a structural gap.

## Files Created/Modified

- `/Users/ishiland/Code/geolens/frontend/src/hooks/use-ai-availability.ts` — Added `isAdmin` selector + tightened gate to `!!token && isAdmin` + JSDoc explaining rationale and affected consumers
- `/Users/ishiland/Code/geolens/frontend/src/hooks/__tests__/use-ai-availability.test.tsx` — Updated SP-08 `beforeEach` to use `adminUser` fixture; added `describe('CONSOLE-01 gating')` block with 3 new tests

## Task Commits

1. **Task 1: Gate useAIAvailability on isAdmin + add regression test** - `0b0c3564` (feat — TDD RED+GREEN in single commit per plan)

**Plan metadata:** (added after state update)

## Decisions Made

- Gate changed from `!!token` to `!!token && isAdmin` — single-line change, mirrors the two existing correct consumers (`AIStatusCard`, `SettingsAITab`) verbatim.
- SP-08 `beforeEach` updated to set `adminUser` rather than `user: null`. The prior `user: null` worked by accident (the hook fired with any token), but after the gate tightens it would produce 0 calls and break the SP-08 caching assertions. Setting a real admin user in SP-08 is the correct fix and makes the test semantically accurate.
- Auth-store rehydration probes left untouched per audit's explicit out-of-scope rationale.

## Deviations from Plan

None — plan executed exactly as written. The SP-08 `beforeEach` update (adding `adminUser`) was anticipated implicitly by the plan's "Test 1: unchanged — useAIAvailability with `{ enabled: true }` for an admin user" framing, which implies the setup must yield an admin context.

## Issues Encountered

None.

## Requirements Closed

- **CONSOLE-01**: `useAIAvailability` gated on `!!token && isAdmin`; `/api/admin/ai-status/` ×3 console 401s eliminated; regression test pinned.

## Next Phase Readiness

- Four consumers (MapCreateDialog, OverviewTab, MetadataTab, SourceQualityTab) are unchanged — they receive `isAIAvailable = false` for non-admin sessions, which hides AI affordances appropriately.
- Live verification (Phase 1056) can confirm zero `/api/admin/ai-status/` entries in DevTools Network for anonymous dataset-detail browsing.
- Remaining deferred-as-expected auth-store rehydration probes are a separate track if the team decides to pre-check token expiry in `tryRefresh`.

---
*Phase: 1054-seeder-console-route-import-polish*
*Completed: 2026-05-19*
