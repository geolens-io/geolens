---
phase: 1099
reviewed: 2026-05-24T16:03:16Z
depth: standard
files_reviewed: 1
files_reviewed_list:
  - backend/tests/test_oauth.py
findings:
  critical: 0
  warning: 0
  info: 4
  total: 4
status: issues_found
---

# Phase 1099: Code Review Report

**Reviewed:** 2026-05-24T16:03:16Z
**Depth:** standard
**Files Reviewed:** 1
**Status:** issues_found (4 INFO, 0 BLOCKER, 0 WARNING)

## Summary

Phase 1099 modified ONLY `backend/tests/test_oauth.py` — D-02 (test-isolation-only) boundary respected. The diff adds two new fixtures (`client_session`, `_ensure_public_app_url`) and updates 3 OAuth test signatures (lines 921, 975, 1016 post-fix) to declare both fixtures. The diff is small (+132/-19, net +113 LOC), well-commented, and the production OAuth code path (`backend/app/modules/auth/oauth/router.py`, `service.py`, `dependencies.py`, `backend/app/core/public_urls.py`, `backend/app/core/dependencies.py`) is unchanged. No diagnostic instrumentation (`print`, `breakpoint`, `pdb`, `DIAG`) leaked into the committed test file — T2 debug code was cleaned per CONTEXT.md `<specifics>`. Imports are clean — `select` (line 6) is still used at line 548.

The two new fixtures are not autouse, so they apply only to the 3 tests that explicitly declare them. Other tests in the file (`test_oauth_login_not_found` at line 963, and ~33 sibling tests) are unaffected.

**No BLOCKER or WARNING findings.** The 4 INFO findings are non-blocking quality observations to feed into the v1024+ test-isolation ledger per CONTEXT.md `<deferred>` guidance.

## Findings

### Info

#### IN-01: `_ensure_public_app_url` save-and-restore is less hermetic than the established `test_public_urls.py` precedent

**File:** `backend/tests/test_oauth.py:119-122`
**Issue:** The fixture saves `_PUBLIC_URL_CACHE` pre-yield and restores it post-yield:
```python
saved = public_urls._PUBLIC_URL_CACHE
public_urls._PUBLIC_URL_CACHE = None
yield
public_urls._PUBLIC_URL_CACHE = saved
```
The established pattern in `backend/tests/test_public_urls.py:9-19` (audit cluster 6 / 20260425) uses a strict reset — `_PUBLIC_URL_CACHE = None` BOTH before AND after yield — with the inline comment "Reset both before and after to keep tests hermetic." The Phase 1099 fixture is functionally equivalent ONLY when `saved` is None or a stale tuple that the next caller would re-query anyway (TTL is 60s; `_load_public_url_overrides` re-queries on stale TTL). If `saved` was a populated tuple from a sibling-test leaker, the restore perpetuates the leak — net-neutral relative to pre-fixture state, but does not improve test hygiene.

**Fix:** For full hermeticity matching the established precedent, replace lines 119-122 with:
```python
public_urls._PUBLIC_URL_CACHE = None
yield
public_urls._PUBLIC_URL_CACHE = None
```
Deferring to v1024+ test-isolation ledger is acceptable per CONTEXT.md D-07a (no leaker hunt; defensive shape addresses symptom permanently). The current shape is functionally correct — this is a style/consistency observation only.

#### IN-02: T2 diagnosis missed the `_PUBLIC_URL_CACHE` order-dependence root cause; surfaced only at T4 iter-2

**File:** `backend/tests/test_oauth.py:78-122` (the `_ensure_public_app_url` fixture and its rationale comment)
**Issue:** Per SUMMARY.md "T2 Diagnosis" section, the D-03a snapshot-gap hypothesis was "STRUCTURALLY-CONFIRMED via file-read analysis" but the actual root cause (order-dependent `_PUBLIC_URL_CACHE` priming + `for_external_use=True` strict-config) emerged only during T4 verify gate (iter-1 commit `f57f1a76` produced `AttributeError: 'AsyncClient' object has no attribute 'app'` AND would not have closed the URL-cache flake even if the import had worked).

Because iter-1 never actually exercised the `client_session` snapshot-fix logic (it crashed before resolution), the snapshot-gap hypothesis remains **empirically unvalidated**. The `_ensure_public_app_url` fixture (iter-2) is sufficient to close the flake. Whether `client_session` is also load-bearing — or just defensive belt-and-suspenders — is unknown.

Per CONTEXT.md D-07a (no leaker hunt) and `<phase_context>` ("Worth noting as Info for v1024+ ledger but not blocking"): this is an INFO finding for the v1024+ test-isolation audit, not a blocking concern.

**Fix:** Optionally, in v1024+, verify whether `client_session` is necessary by reverting the 3 test signatures to `test_db_session` and re-running `-n 4` ×3 with `_ensure_public_app_url` still applied. If the tests stay green, `client_session` was non-load-bearing and can be removed (smaller diff, less brittle test). If they flake, the snapshot-gap hypothesis is confirmed and `client_session` documentation should be reinforced.

#### IN-03: Fixture reaches into private module-level state (`_PUBLIC_URL_CACHE`)

**File:** `backend/tests/test_oauth.py:111, 119-122`
**Issue:** `_ensure_public_app_url` imports `app.core.public_urls as public_urls` (line 111) and directly mutates the leading-underscore module global `_PUBLIC_URL_CACHE` (lines 119-122). This is a brittle coupling between test and implementation: if the cache implementation changes (e.g., LRU dict, per-key TTL eviction, removal of the cache entirely), this fixture silently breaks or no-ops without compile-time signal.

The comment at lines 116-118 explains the rationale ("the cache may have been populated by an earlier test in this process with whatever happened to be in settings at that moment"), and the precedent in `test_public_urls.py:17-19` already exists. So this is a justified violation of the abstraction boundary.

**Fix:** No immediate action required — the violation is documented and has precedent. For v1024+, consider exposing a public `public_urls.clear_cache()` helper that tests can call without reaching into private state. The same helper could replace the manual mutation in `test_public_urls.py` for consistency.

#### IN-04: No explicit unit test for the `client_session` fixture contract

**File:** `backend/tests/test_oauth.py:51-75` (the `client_session` fixture)
**Issue:** Per CONTEXT.md `<decisions>` "Claude's Discretion" — "Whether to add 1-2 explicit regression tests for the fixture-isolation contract (D-04a defensive pattern) or rely on the existing 3 OAuth tests as the regression pin" — Phase 1099 chose NOT to add. The 3 OAuth tests serve as implicit regression pins. If a future refactor renames `app.dependency_overrides[get_db]` or changes the lifecycle of `override_get_db`, the failure mode would surface as either an `AttributeError` (matching iter-1's surface) or as the OAuth tests flaking again — there is no direct positive-form assertion that the fixture's "shares client's connection factory" contract holds.

**Fix:** Deferred per planner's "Claude's Discretion" decision and CONTEXT.md `<deferred>` guidance. For v1024+, consider a one-paragraph fixture-isolation contract test:
```python
async def test_client_session_shares_override_get_db_factory(client, client_session):
    """Phase 1099 regression pin: client_session must yield a session
    produced by the same factory client uses via dependency_overrides[get_db]."""
    from app.core.dependencies import get_db
    from app.api.main import app
    assert get_db in app.dependency_overrides
    # client_session.bind is the engine the override factory uses
    assert client_session.bind is not None
```
This pins the contract directly. Current 3-OAuth-test regression coverage is sufficient for Phase 1099's smallest-milestone charter.

---

_Reviewed: 2026-05-24T16:03:16Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

## REVIEW COMPLETE WITH FINDINGS
