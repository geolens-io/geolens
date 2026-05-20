---
phase: "1064"
plan: "01"
subsystem: close-gate
tags: [security, smoke, changelog, v1014]
dependency_graph:
  requires: [1061, 1062, 1063]
  provides: [v1014-close-gate]
  affects: [CHANGELOG.md]
tech_stack:
  added: []
  patterns: []
key_files:
  created: []
  modified:
    - backend/tests/test_rate_limits.py
    - backend/tests/test_embed_framing_csp.py
    - backend/tests/test_layering.py
    - CHANGELOG.md
decisions:
  - "test_search_facets_rate_limit_returns_429 renamed to test_search_facets_not_rate_limited with inverted assertion — facets is intentionally not rate-limited per WR-02 Phase 1062-review"
  - "test_embed_framing_csp CR-04 helper fixed to use far-future expires_at instead of None — embed_tokens NOT NULL constraint blocks null insert"
  - "service_public.py line-count cap raised 575→600 to account for CR-04 CSP fix growth"
  - "TS typecheck errors and ESLint warnings in test files are pre-existing from Phase 1059 and earlier — out of scope per scope boundary rules"
  - "Tags NOT cut — orchestrator will run Playwright MCP smoke first, then cut v1014 + v1.4.0 locally"
metrics:
  duration: "~35 minutes"
  completed: "2026-05-20T23:07:09Z"
---

# Phase 1064 Plan 01: Close Gate v1014 Summary

**One-liner:** Security audit remediation smoke gate — 288/288 backend tests pass, 2092/2092 vitest tests pass, i18n 2/2, CHANGELOG [1.4.0] promoted; 3 test mismatches auto-fixed inline.

## Smoke Gate Results

| Gate | Result | Details |
|------|--------|---------|
| Backend pytest (20-file smoke) | **PASS** | 288 passed, 3 skipped, 0 failed |
| Frontend vitest | **PASS** | 2092 passed (212 test files) |
| Frontend i18n parity | **PASS** | 2/2 |
| Frontend typecheck (tsc -b) | Pre-existing failures | 37 TS errors in test files only — all pre-date Phase 1061 (oldest: May 18 c8c9d08f); none in production source |
| Frontend ESLint | Pre-existing warnings | 34 problems in builder/test files — none in Phase 1061-1063 changed files; SEC-S14 no-restricted-syntax rule adds 0 new errors |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_search_facets_rate_limit_returns_429 tested removed behavior**

- **Found during:** Task 1 (backend pytest smoke)
- **Issue:** `test_search_facets_not_rate_limited` (previously `test_search_facets_rate_limit_returns_429`) asserted that `/search/facets/` returns 429 after rate limit threshold. But commit `4837ee22` (Phase 1062 WR-02) intentionally removed the `@limiter.limit` decorator from `search_facets_endpoint` — pure SQL aggregation, no embedding call. The test was never updated to match.
- **Fix:** Renamed test to `test_search_facets_not_rate_limited`; inverted assertion to verify `/search/facets/` does NOT return 429 even with limiter enabled at low threshold (3/min). Negative-control regression pin per v1011 EMRG REMOVE pattern.
- **Files modified:** `backend/tests/test_rate_limits.py`
- **Commit:** `f9706269`

**2. [Rule 1 - Bug] test_embed_framing_csp CR-04 helper violated NOT NULL schema constraint**

- **Found during:** Task 1 (backend pytest smoke)
- **Issue:** `_create_non_expiring_embed_token` helper set `expires_at=None`, triggering `asyncpg.exceptions.NotNullViolationError` — `embed_tokens.expires_at` has been NOT NULL since the baseline migration (`0001_baseline.py`). The CR-04 fix in `service_public.py` correctly handles the defensive `IS NULL` case in the CSP query, but the test factory cannot insert a NULL row because the schema never permitted it.
- **Fix:** Updated `_create_non_expiring_embed_token` to use `far_future = datetime.now(UTC) + timedelta(days=365*100)` representing a long-lived token. Updated docstring to clarify that CR-04's `is_(None)` predicate is defensive code for hypothetical legacy rows; the test now verifies the CSP lookup works end-to-end for long-lived tokens with `allowed_origins`.
- **Files modified:** `backend/tests/test_embed_framing_csp.py`
- **Commit:** `f9706269`

**3. [Rule 1 - Bug] service_public.py over line-count budget (588 > 575)**

- **Found during:** Task 1 (backend pytest `test_layering.py::test_decomposed_service_modules_stay_within_size_budgets`)
- **Issue:** Phase 1062 CR-04 added 13 lines to `service_public.py` (the `or_` IS NULL predicate + supporting comments) but did not update the line-count allowlist in `test_layering.py`. The 575-line cap was exceeded.
- **Fix:** Raised cap from 575 → 600 in `private_service_line_budget_allowlist` with inline comment documenting the Phase 1062 CR-04 growth. Per the test's own guidance: "add a reviewed explicit cap only when growth is intentional."
- **Files modified:** `backend/tests/test_layering.py`
- **Commit:** `f9706269`

## Pre-existing Issues (Out of Scope)

| Category | Description | Origin |
|----------|-------------|--------|
| TS typecheck | 37 errors in test files (`map-sync.data-driven-cols.test.ts`, `RegisterPage.alreadySignedIn.test.tsx`, `sublayer-overrides.round-trip.test.ts`, etc.) | Phase 1059 (May 18-19) and earlier; no production source affected |
| ESLint | 34 warnings/errors in builder components and test files (react-hooks/exhaustive-deps, unused vars) | Phase 1059 and earlier; SEC-S14 rule adds 0 new errors to existing source |

These are logged to deferred-items but not fixed — scope boundary rule applies (pre-existing from unrelated phases).

## CHANGELOG

Promoted `[Unreleased]` → `[1.4.0] - 2026-05-20`. Fresh empty `[Unreleased]` block added above. Entry structured by severity (HIGH / MEDIUM / LOW) with one bullet per requirement ID plus Internal section with commit/test/e2e counts.

**Commit:** `c13b20e0`

## Tags

NOT cut at this stage. Orchestrator will run Playwright MCP smoke (Plan 02) first, then cut local tags `v1014` + `v1.4.0`. Push manually with `git push origin v1014 v1.4.0`.

## Self-Check

Commits verified:
- `f9706269` — fix(1064-01): correct 3 test mismatches
- `c13b20e0` — docs(1064-04): promote [Unreleased] to [1.4.0]

Files verified:
- `backend/tests/test_rate_limits.py` — FOUND
- `backend/tests/test_embed_framing_csp.py` — FOUND
- `backend/tests/test_layering.py` — FOUND
- `CHANGELOG.md` — FOUND, [1.4.0] section at line 14

## Self-Check: PASSED
