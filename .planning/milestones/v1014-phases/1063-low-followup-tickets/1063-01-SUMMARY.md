---
phase: 1063-low-followup-tickets
plan: "01"
subsystem: backend-security
tags:
  - sec-fu-01
  - sec-fu-08
  - audit
  - stac
  - tdd
dependency_graph:
  requires:
    - 1061-01  # STAC visibility filter (SEC-S01)
    - 1061-02  # column-DDL write endpoints (SEC-S03) + check_dataset_access pattern
  provides:
    - stac_visibility_force_5xx pytest fixture for 5xx-path regression tests
    - GET /api/audit/datasets/{dataset_id}/column-ddl endpoint
    - query_column_ddl_history service helper
  affects:
    - backend/tests/conftest.py
    - backend/app/modules/audit/
tech_stack:
  added: []
  patterns:
    - monkeypatch.setattr on both module and router namespace bindings (prevents stale import refs)
    - raise_app_exceptions=False on ASGITransport for 5xx regression tests (httpx pattern)
    - window COUNT() over() for single-round-trip pagination (mirrors query_audit_logs)
    - Deferred import of check_dataset_access inside handler (avoids circular import risk)
key_files:
  created:
    - backend/tests/test_stac_visibility_5xx.py
    - backend/tests/test_audit_column_ddl_feed.py
  modified:
    - backend/tests/conftest.py
    - backend/app/modules/audit/service.py
    - backend/app/modules/audit/router.py
    - backend/app/modules/audit/schemas.py
    - backend/app/api/router.py
decisions:
  - "stac_visibility_force_5xx patches both authorization module AND stac.router namespace to handle the from-import binding correctly"
  - "audit_datasets_router uses /audit prefix (not /admin) so non-admin dataset owners can reach the DDL feed"
  - "check_dataset_access raises 404 not 403 for non-owners — tests accept 403 or 404 to match actual implementation"
  - "ASGITransport raise_app_exceptions=False on client_no_raise fixture wraps the standard client transport without duplicating the entire client setup"
metrics:
  duration_minutes: 15
  completed_date: "2026-05-20"
  tasks_completed: 3
  files_modified: 7
---

# Phase 1063 Plan 01: SEC-FU-01 + SEC-FU-08 Summary

SEC-FU-01 STAC 5xx-mutation pytest fixture + no-information-disclosure regression tests; SEC-FU-08 owner-facing column-DDL audit feed endpoint on top of Phase 1061's audit_logs events.

## What Was Built

### SEC-FU-01 (STAC 5xx-mutation fixtures)

- `stac_visibility_force_5xx` fixture in `backend/tests/conftest.py` monkeypatches `apply_visibility_filter` in both `app.modules.catalog.authorization` and `app.standards.stac.router` (patching both namespaces is required because the router binds the name at import time via `from ... import`).
- `client_no_raise` fixture in `backend/tests/test_stac_visibility_5xx.py` wraps the standard `client` fixture's transport with `raise_app_exceptions=False` so 5xx responses are received as HTTP response objects rather than re-raised into the test.
- 3 tests in `test_stac_visibility_5xx.py`:
  1. `test_stac_item_5xx_does_not_leak_private_context` — verifies the GET /stac/items/{id} 5xx body contains neither the dataset UUID nor the record title
  2. `test_stac_search_5xx_does_not_leak_private_context` — same for GET /stac/search?ids=...
  3. `test_stac_item_returns_200_without_5xx_fixture` (control) — confirms the fixture is the only cause of the 5xx path

### SEC-FU-08 (column DDL change log)

- `query_column_ddl_history(session, dataset_id, *, limit, offset)` added to `backend/app/modules/audit/service.py`, filtering `audit_logs` to the 4 column-DDL action strings from Phase 1061 SEC-S03. Returns `(rows, total)` tuple using window COUNT() for single-round-trip pagination. Added to `__all__`.
- `ColumnDdlEntry` + `ColumnDdlFeedResponse` added to `backend/app/modules/audit/schemas.py`.
- `GET /audit/datasets/{dataset_id}/column-ddl` added to `backend/app/modules/audit/router.py` via new `audit_datasets_router` (prefix `/audit`). Handler: 404 check → `check_dataset_access` gate → `query_column_ddl_history` → response.
- `audit_datasets_router` registered in `backend/app/api/router.py`.
- 10 tests in `test_audit_column_ddl_feed.py` (4 service + 6 router): owner 200, non-owner 404, admin 200, anonymous 401, missing dataset 404, pagination.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `stac_visibility_force_5xx` fixture namespace binding**
- **Found during:** Task 1 GREEN
- **Issue:** Monkeypatching only `app.modules.catalog.authorization.apply_visibility_filter` was insufficient; the STAC router had already bound the name via `from ... import apply_visibility_filter`, creating a separate reference. The router's binding was unaffected by a module-level patch.
- **Fix:** Patch both namespaces — `monkeypatch.setattr(_authorization, "apply_visibility_filter", _force_raise)` AND `monkeypatch.setattr(_stac_router, "apply_visibility_filter", _force_raise)`.
- **Files modified:** `backend/tests/conftest.py`
- **Commit:** 8c9ecee9

**2. [Rule 3 - Blocking] ASGITransport re-raises app exceptions by default**
- **Found during:** Task 1 GREEN
- **Issue:** `httpx.AsyncClient` with `ASGITransport` (default `raise_app_exceptions=True`) propagates unhandled server exceptions into the test process as Python exceptions, preventing the test from receiving the HTTP 500 response object.
- **Fix:** Add `client_no_raise` fixture that swaps the transport to `ASGITransport(app=..., raise_app_exceptions=False)` while reusing the existing `client` fixture's DB setup.
- **Files modified:** `backend/tests/test_stac_visibility_5xx.py`
- **Commit:** 8c9ecee9

**3. [Rule 3 - Blocking] `AuditEvent.user_id` required FK + missing commit in `_seed_ddl_event`**
- **Found during:** Task 2/3 GREEN
- **Issue:** (a) `AuditEvent.user_id` is required (not Optional), so passing `None` raises a FK violation. (b) `audit_emit` writes to the session but does not commit; the test's HTTP client uses a different session from the same engine, so uncommitted rows are invisible to the request handler.
- **Fix:** Fall back to `get_user_id(session, "admin")` when no `user_id` supplied; add `await session.commit()` after each `audit_emit` call in `_seed_ddl_event`.
- **Files modified:** `backend/tests/test_audit_column_ddl_feed.py`
- **Commit:** 022fc807

**4. [Rule 1 - API deviation] `require_authenticated_user` dependency does not exist**
- **Found during:** Task 3 implementation
- **Issue:** The plan's interface spec listed `require_authenticated_user` as the auth dependency, but the codebase only has `get_current_active_user` (which enforces the same authenticated+active contract).
- **Fix:** Used `get_current_active_user` instead. Same semantics, correct function name.
- **Files modified:** `backend/app/modules/audit/router.py`
- **Commit:** 022fc807

**5. [Rule 1 - API deviation] `check_dataset_access` raises 404 not 403 for non-owners**
- **Found during:** Task 3 implementation review
- **Issue:** The plan spec says non-owners get 403, but `check_dataset_access` actually raises 404 (by design — avoids confirming dataset existence to unauthorized callers). The test was written to accept 403 or 404.
- **Fix:** No production code change needed; test assertion accepts `resp.status_code in (403, 404)`.
- **Files modified:** `backend/tests/test_audit_column_ddl_feed.py`
- **Commit:** 022fc807

## Verification Results

```
pytest tests/test_stac_visibility_5xx.py tests/test_audit_column_ddl_feed.py -x -v
=== 13 passed, 21 warnings in 14.62s ===
```

Plan verification checks:
- `stac_visibility_force_5xx` defined once in conftest.py (1 `def` line + 2 docstring refs)
- 4 column-DDL action strings present in `service.py` (`_COLUMN_DDL_ACTIONS` tuple)
- `check_dataset_access` present in `audit/router.py` (both import and call)

## Known Stubs

None — all features are fully wired.

## Threat Flags

No new network endpoints or auth paths introduced beyond the planned `GET /audit/datasets/{id}/column-ddl` endpoint (already in the plan's threat model as T-1063-01-03).

## Self-Check: PASSED

- `backend/tests/conftest.py` contains `stac_visibility_force_5xx` fixture: FOUND
- `backend/tests/test_stac_visibility_5xx.py` exists with 3 tests: FOUND
- `backend/app/modules/audit/service.py` exports `query_column_ddl_history`: FOUND
- `backend/app/modules/audit/router.py` contains `get_column_ddl_feed` and `check_dataset_access`: FOUND
- `backend/app/modules/audit/schemas.py` contains `ColumnDdlEntry`, `ColumnDdlFeedResponse`: FOUND
- `backend/tests/test_audit_column_ddl_feed.py` exists with 10 tests: FOUND
- All commits exist in git log: 7f850222, 8c9ecee9, bc16fde9, e8bd7642, 022fc807 FOUND
