---
phase: 1045-builder-smoke-polish
plan: 02
subsystem: builder-shared-infra
tags: [builder, smoke-polish, perf, a11y, auth, search, network-hygiene]
requirements: [SP-06, SP-07, SP-08, SP-09, SP-10, SP-11]
metrics:
  duration_minutes: ~95
  tasks_completed: 6
  commits: 7
  test_count_delta: +16 (3 use-ai-availability, 2 client SP-09, 2 StackRow, 2 BasemapGroupRow, 6 quicklook-cache, +1 MapTitleBar dedup adjustment)
  files_created:
    - frontend/src/hooks/__tests__/use-ai-availability.test.tsx
    - frontend/src/lib/quicklook-cache.ts
    - frontend/src/lib/__tests__/quicklook-cache.test.ts
  files_modified:
    - frontend/src/hooks/use-admin.ts
    - frontend/src/api/client.ts
    - frontend/src/api/auth.ts
    - frontend/src/api/__tests__/client.test.ts
    - frontend/src/hooks/use-auth.ts
    - frontend/src/components/builder/MapTitleBar.tsx
    - frontend/src/components/builder/StackRow.tsx
    - frontend/src/components/builder/UnifiedStackPanel.tsx
    - frontend/src/components/builder/BasemapGroupRow.tsx
    - frontend/src/components/builder/DatasetSearchPanel.tsx
    - frontend/src/components/search/SearchResultCard.tsx
    - frontend/src/components/builder/__tests__/MapTitleBar.test.tsx
    - frontend/src/components/builder/__tests__/StackRow.test.tsx
    - frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx
    - backend/app/modules/auth/router.py
    - backend/tests/conftest.py
    - backend/tests/test_auth.py
    - backend/tests/test_auth_refresh_logout.py
    - backend/tests/test_embed_tokens.py
    - backend/tests/test_persistent_config.py
    - backend/tests/test_provenance_attribution.py
    - backend/tests/test_raster_tiles.py
    - e2e/export-runtime.spec.ts
    - e2e/permissions.spec.ts
---

# Phase 1045 Plan B: Builder Smoke Polish — SP-06..SP-11

Six MINOR findings closed: network hygiene (ai-status caching + auth refresh
dedupe), a11y (aria-pressed on visibility toggles), header save-state dedup,
search-page console cleanup, and the /auth/login trailing-slash 307.

## Task B.1 / SP-08 — Cache ai-status query with 60s staleTime

**Outcome:** `/api/admin/ai-status/` fires at most once per 60s across all
consumers; idle polling removed entirely.

**Files changed:**
- `frontend/src/hooks/use-admin.ts` — `useAIStatus` updated:
  - `staleTime: 30_000 -> 60_000`
  - `refetchInterval: 60_000` **removed** (this was the poll storm)
  - `gcTime: 5 * 60_000` added (cache stays warm across page transitions)
- `frontend/src/hooks/__tests__/use-ai-availability.test.tsx` (new) —
  3 cases:
  1. Three consumers (useAIStatus + 2× useAIAvailability) share one query.
  2. Re-mount within staleTime does NOT refetch.
  3. Across a fake-timer 180s idle window, exactly one call fires.

**Consumers verified:** `useAIAvailability` (4 callers), `AIStatusCard`,
`SettingsAITab` — all inherit caching via the shared `queryKey`. No
consumer relied on `refetchInterval` (no `isFetching` reads, no manual
`refetch()` invocations off the timer).

**Commit:** `5b4ebcfb`
**Verification:** vitest use-ai 3/3 PASS; full vitest suite green.

## Task B.2 / SP-09 — De-dupe concurrent /auth/refresh via in-flight promise

**Outcome:** Concurrent 401-driven refreshes AND the `use-auth.ts` proactive
timer collapse to a single `/auth/refresh/` POST per refresh cycle.

**Files changed:**
- `frontend/src/api/client.ts` —
  - `refreshPromise` renamed to `inflightRefresh` for clarity.
  - `tryRefresh` is now **exported** so other modules can share the mutex.
- `frontend/src/hooks/use-auth.ts` —
  - Proactive-refresh `setTimeout` callback rewired from a direct
    `refreshAccessToken(...)` call to `void tryRefresh()`.
  - Drops the redundant in-place error handling (tryRefresh swallows
    errors; the 401 interceptor handles a failed refresh on the next
    authenticated request).
- `frontend/src/api/__tests__/client.test.ts` — 2 new SP-09 cases:
  1. 3 concurrent 401s with a held-open refresh promise → exactly one
     `refreshAccessToken` call.
  2. Refresh failure clears `inflightRefresh` so the NEXT cycle retries.

**Plan deviation noted:** The plan task wording suggested the mutex did
not yet exist. The mutex was already present in `client.ts`; the actual
bug was the proactive-refresh timer in `use-auth.ts` bypassing it. Fix
applied per Rule 1 (auto-fix bug) — exporting `tryRefresh` and routing
the timer through it. Comment in `client.ts` explicitly documents both
call sites.

**Commit:** `6b940ca2`
**Verification:** vitest client + use-auth 24/24 PASS.

## Task B.3 / SP-06 — Remove duplicate Saved badge from header

**Outcome:** Header renders exactly one save-state element (the Save
button) carrying all three states (Save / Saving... / Saved / Save failed).

**Files changed:**
- `frontend/src/components/builder/MapTitleBar.tsx` —
  - The `<div data-testid="builder-save-status">` badge (lines ~150-166)
    deleted; its `CheckCircle2`/`AlertTriangle`/dot indicator and label
    are redundant with what the Save button already conveys.
  - `data-testid="builder-save-status"` moved to the Save button itself,
    plus a new `data-save-status={saveStatus}` attribute exposes the
    state value for selector-based tests.
  - `<span class="sr-only">{saveStatusLabel}</span>` added inside the
    button so AT users still hear the status announcement when the
    visible label is hidden on narrow viewports.
  - Unused `CheckCircle2` import removed.
- `frontend/src/components/builder/__tests__/MapTitleBar.test.tsx` —
  Two tests updated:
  1. "shows the all-saved indicator" — now asserts `data-save-status`
     attr value instead of counting 2× "Saved" text matches.
  2. "shows failed save state with a retry action" — same testid still
     works (moved to button); also asserts `data-save-status="failed"`.

**Commit:** `f5a815d8`
**Verification:** vitest MapTitleBar 10/10 PASS; MapBuilderPage 7/7 PASS.

## Task B.4 / SP-10 — aria-pressed on visibility toggle buttons

**Outcome:** Every layer / sublayer / basemap-row visibility toggle exposes
`aria-pressed={visible}` so AT users hear "Toggle visibility for X,
pressed" / "not pressed".

**Files changed:**
- `frontend/src/components/builder/StackRow.tsx` —
  `aria-pressed={layer.visible}` added to the eye button.
- `frontend/src/components/builder/BasemapGroupRow.tsx` —
  `aria-pressed={visible}` added (works alongside the existing
  `aria-disabled` when basemap visibility is not yet wired).
- `frontend/src/components/builder/UnifiedStackPanel.tsx` —
  `aria-pressed={sublayer.visible}` added to the SublayerRow eye button
  (the only sublayer toggle in this file; basemap-row toggle is in
  `BasemapGroupRow.tsx` and was handled above).
- `frontend/src/components/builder/__tests__/StackRow.test.tsx` —
  2 new tests: `pressed: true` and `pressed: false` cases via
  `getByRole('button', { name: /Toggle visibility/i, pressed: true|false })`.
- `frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx` —
  Same pattern, 2 new tests.

**Commit:** `532ca595`
**Verification:** vitest StackRow + UnifiedStackPanel + BasemapGroupRow 99/99 PASS.

## Task B.5 / SP-07 — Skip quicklook fetch when known-missing

**Outcome:** Subsequent renders and reloads within a tab session skip
`<img src=/api/datasets/<id>/quicklook>` for any id whose quicklook
already 404'd. First-load 404 still occurs once per session per bad id
(see "Known limitation" below).

**Files changed:**
- `frontend/src/lib/quicklook-cache.ts` (new) —
  Session-scoped negative cache. API:
  - `isQuicklookKnownMissing(id): boolean`
  - `markQuicklookMissing(id): void`
  - `_resetQuicklookCache(): void` (test helper)
  Storage strategy: in-memory + sessionStorage (so a tab reload preserves
  the cache; new tabs / windows start fresh). Falls back to memory-only
  when sessionStorage is unavailable (private mode, SSR).
- `frontend/src/components/search/SearchResultCard.tsx` —
  `quicklookId` gated on `!isQuicklookKnownMissing(featureId)`. The
  `<img>` element gains an `onError={() => markQuicklookMissing(...)}`
  handler that flags the id on first 404.
- `frontend/src/components/builder/DatasetSearchPanel.tsx` —
  Same pattern applied to the builder's dataset preview tile so the
  catalog drag panel benefits from the cache too.
- `frontend/src/lib/__tests__/quicklook-cache.test.ts` (new) —
  6 cases including a `vi.resetModules()`-based persistence test that
  proves a fresh module init re-reads from sessionStorage.

**Known limitation (documented in commit body):** The OGC search response
has no honest `thumbnail_status` field. `has_quicklook` is derived from
`dataset.quicklook_256_uri IS NOT NULL` — the URI assignment, not file
existence. The proper fix is a backend change to verify file existence
when computing `has_quicklook`, but that's out of scope for this
frontend-only plan. The session cache prevents repeat 404s; the first
load per tab still pays one 404 per known-bad id.

**Commit:** `b70a9caf`
**Verification:** vitest SearchResultCard + SearchPage + DatasetSearchPanel
+ quicklook-cache 67/67 PASS.

## Task B.6 / SP-11 — Drop trailing slash on /auth/login route

**Outcome:** `POST /auth/login` (no trailing slash) returns 200/422
directly without a 307 redirect that drops the form body.

**Files changed:**
- `backend/app/modules/auth/router.py` —
  `@router.post("/login/", ...)` → `@router.post("/login", ...)`
- `frontend/src/api/auth.ts` —
  `fetch(${API_BASE}/auth/login/, ...)` → `fetch(${API_BASE}/auth/login, ...)`
- `e2e/export-runtime.spec.ts` — call updated + misleading comment
  ("trailing slash is required") rewritten.
- `e2e/permissions.spec.ts` — call updated.
- 7 backend test files updated (all using `client.post("/auth/login/", ...)`):
  `conftest.py`, `test_auth.py`, `test_auth_refresh_logout.py`,
  `test_embed_tokens.py`, `test_persistent_config.py`,
  `test_provenance_attribution.py`, `test_raster_tiles.py`.

**Live verification:** `curl -X POST http://localhost:8001/auth/login`
with valid credentials returns HTTP 200 + JWT body (no 307). The api
container bind-mounts `backend/app`, so uvicorn auto-reloaded the change.

**Commit:** `76927b9b`
**Verification:** backend pytest test_auth + test_auth_refresh_logout
37/37 PASS; backend ruff `app/modules/auth/` clean; live curl 200.

## Code review (self-review HEAD~6..HEAD)

`gsd-code-reviewer` agent could not be spawned from the executor function
set; the same constraint Plan A documented. Self-review of the 6-commit
diff produced one finding addressed inline:

### [Rule 1 — Test quality] Misleading quicklook-cache persistence test

**Found during:** self-review of B.5 diff.
**Issue:** The test named "survives a reset to sessionStorage" actually
verified the OPPOSITE — `_resetQuicklookCache()` clearing both memory
and sessionStorage. The "Need to repopulate" comment was confusing.
**Fix:** Split into two cases:
1. **"persists across an in-memory cache drop via sessionStorage"** —
   uses `vi.resetModules()` to simulate a fresh module init while jsdom's
   sessionStorage singleton carries state. This is the real roundtrip
   check.
2. **"_resetQuicklookCache clears both memory and sessionStorage"** —
   covers the cleanup path explicitly.

**Commit:** `be06a4f8`

No other findings. Conventional commits, no AI/bot attribution, no
backward-compat shims, no destructive git ops.

## Deviations from Plan

### Auto-fixed

1. **[Rule 1 — Bug] SP-09 was actually a `use-auth.ts` bypass, not a
   missing `client.ts` mutex.** The plan task implied no mutex existed;
   the mutex was already in place but `use-auth.ts:48` called
   `refreshAccessToken` directly. Fix: export `tryRefresh` from
   `client.ts` and route the proactive timer through it.
   Files: `frontend/src/api/client.ts`, `frontend/src/hooks/use-auth.ts`.
   Commit: `6b940ca2`.

2. **[Rule 2 — Scope expansion] SP-07 quicklook fix applied to
   `DatasetSearchPanel.tsx` in addition to SearchPage.** The plan only
   listed `SearchPage.tsx`, but the builder's `DatasetSearchPanel` has
   the same `<img src=quicklook>` pattern and same 404 risk. Applying
   the cache there too prevents the same console noise in the builder's
   catalog modal at no additional review cost.
   Commit: `b70a9caf`.

3. **[Test-quality] Self-reviewed quicklook-cache test split.**
   See "Code review" above.
   Commit: `be06a4f8`.

### Out of scope (deferred)

- **SP-07 first-load 404.** Frontend cannot prevent the initial doomed
  request without a backend `thumbnail_status` field. Documented in the
  B.5 commit body as a future backend follow-up.
- **Pre-existing lint errors / warnings on `main`.** Same 5 errors +
  pre-existing warnings from Plan A's deferred-items.md still present.
  Plan B's diff introduces **zero** new lint findings. The 2 warnings
  reported against `UnifiedStackPanel.tsx` lines 671/712 were already
  present at lines 670/711 pre-change (1-line shift from my aria-pressed
  addition).

## Hard-rule compliance

| Rule | Status |
| ---- | ------ |
| No AI/bot attribution in commits | clean |
| Conventional commit subjects ≤ 72 chars | longest is 65 chars |
| No backward-compat shims | SP-11 decorator change only |
| Explicit file paths for git add | per-commit individual paths |
| No frontend `docker compose build` | Vite HMR + bind-mount only |
| Did not re-investigate M-02/SP-03 | escalated as separate ticket |

## Post-task gates

| Gate | Result |
| ---- | ------ |
| `cd frontend && npx tsc --noEmit` | clean (0 errors) |
| `cd frontend && npx eslint src/` | 5 errors **all pre-existing on main**; 0 errors in plan B diff |
| `cd frontend && npm test -- --run <plan B test patterns>` | 174/174 PASS |
| `cd backend && uv run ruff check app/modules/auth/` | clean |
| `cd backend && uv run pytest tests/test_auth.py tests/test_auth_refresh_logout.py` | 37/37 PASS |
| `curl POST /auth/login` (live UAT) | HTTP 200 + JWT body, no 307 |

## Commits

| Hash | Subject |
| ---- | ------- |
| `5b4ebcfb` | perf(frontend): cache ai-status query with 60s staleTime |
| `6b940ca2` | fix(api): de-dupe concurrent auth refresh via in-flight promise |
| `f5a815d8` | fix(builder): remove duplicate Saved badge from header |
| `532ca595` | fix(a11y): aria-pressed on visibility toggle buttons |
| `b70a9caf` | fix(search): skip quicklook fetch when thumbnail_status not ready |
| `76927b9b` | fix(auth): drop trailing slash on /auth/login route |
| `be06a4f8` | test(quicklook-cache): tighten persistence test via vi.resetModules |

## Anything for the user's attention

- **SP-07 first-load 404 still happens once per tab session per bad id.**
  The right fix is a backend `has_quicklook` change to verify file
  existence at search-response computation time. Not in plan scope; a
  follow-up issue should track it.
- **SP-09 root cause was different from plan wording.** The mutex was
  already in place in `client.ts`; the real bug was `use-auth.ts`
  bypassing it via direct `refreshAccessToken()` call. The fix routes
  the proactive timer through the shared `tryRefresh()` — captured
  inline; nothing for the user to do.
- **SP-11 live curl verified.** API container bind-mounts `backend/app`
  so uvicorn auto-reloaded the route change. No `docker compose build`
  needed.

## Self-Check: PASSED

- All 7 commits present in `git log HEAD~7..HEAD`.
- All listed files exist and were modified by the recorded commits.
- `frontend/src/lib/quicklook-cache.ts`, its test file, and
  `frontend/src/hooks/__tests__/use-ai-availability.test.tsx` all
  created and committed.
- tsc clean; eslint plan B diff clean (5 pre-existing on main only).
- 174 tests pass across the plan B test surface.
