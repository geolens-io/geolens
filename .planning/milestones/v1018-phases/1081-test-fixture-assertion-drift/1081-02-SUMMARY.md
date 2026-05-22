---
phase: 1081-test-fixture-assertion-drift
plan: "02"
subsystem: testing
tags: [pytest, ssrf-revalidation, IA-P0-03, reupload-service-worker, test-fixture-drift, asyncmock, lazy-import-patch]

requires:
  - phase: 1075-conftest-test-db-lifecycle-refactor-baseline-fixes
    provides: "Plan 1075-03 closed the same SSRF patch shape in test_ingest.py — canonical precedent for lazy-import patch target rule"
  - phase: 1066-ia-p0-03-ssrf-revalidation
    provides: "Added validate_url_for_ssrf worker-side gate in tasks_reupload.py:373-378 that caused both tests to drift"

provides:
  - "TestServiceReuploadWorker worker-contract pins (identity preservation + version increment, 401-retry guidance) restored under v1016 IA-P0-03 gate"
  - "Lazy-import patch target rule applied a third time — defining-module patch is now canonical across test_ingest.py (1075-03) and test_reupload_service.py (1081-02)"

affects:
  - "future reupload_service worker tests — should mirror same AsyncMock pattern if fixture URLs are not routable from sandbox"

tech-stack:
  added: []
  patterns:
    - "Lazy-import patch target rule (third application): when production code uses `from module import symbol` inside a function body, the patch target MUST be the defining module (`app.modules.catalog.sources.security.validate_url_for_ssrf`), NOT the caller's namespace. The caller's namespace doesn't hold the symbol until the function runs."

key-files:
  created: []
  modified:
    - backend/tests/test_reupload_service.py

key-decisions:
  - "Patched `app.modules.catalog.sources.security.validate_url_for_ssrf` (defining module), not `app.processing.ingest.tasks_reupload.validate_url_for_ssrf` — the lazy from-import inside the worker body makes the worker-namespace patch a silent no-op"
  - "AsyncMock with no return_value (returns None) — production gate raises on deny, returns None on allow; mock's return shape is irrelevant since tasks_reupload.py:374 does `await validate_url_for_ssrf(source_url)` and ignores the return"
  - "One atomic commit for both tests — REQUIREMENTS.md TD-05 explicit 'both companion tests share one root cause → one commit'"
  - "Zero skip decorators — root-cause fix per Phase 1075-05 protocol"

patterns-established:
  - "Lazy-import patch target rule (third application, v1018 sweep): `app.modules.catalog.sources.security.validate_url_for_ssrf` is the correct patch target whenever the production code under test uses a lazy `from app.modules.catalog.sources.security import validate_url_for_ssrf` inside a function body. Applies to test_ingest.py (Plan 1075-03), test_reupload_service.py (Plan 1081-02)."

requirements-completed: [TD-05]

duration: 8min
completed: 2026-05-21
---

# Phase 1081 Plan 02: TD-05 SSRF Re-Validation Drift in Reupload Service Worker Tests

**AsyncMock patch on `app.modules.catalog.sources.security.validate_url_for_ssrf` added to both `TestServiceReuploadWorker` tests, restoring worker-contract coverage under the v1016 IA-P0-03 defense-in-depth gate.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-05-21T00:00:00Z
- **Completed:** 2026-05-21T00:08:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Both `TestServiceReuploadWorker` tests now pass under the IA-P0-03 gate that was added after the tests were written
- Lazy-import patch target rule applied for the third time across the v1017→v1018 sweep (prior applications: Plan 1075-03 in `test_ingest.py`)
- Zero skip decorators added; zero production code touched

## Lines Added

**Edit 1 — `test_reupload_service_preserves_identity_and_increments_version`**

Inserted as the FIRST entry in the `with (...)` block (before the existing `build_gdal_source` patch), at what was line 211:

```python
            # Phase 1066 IA-P0-03 (commit f8c91297) added a defense-in-depth
            # SSRF re-validation of ``source_url`` at the top of the
            # ``reupload_service`` worker body (tasks_reupload.py:373-378)
            # via a LAZY from-import inside the function body:
            #     from app.modules.catalog.sources.security import validate_url_for_ssrf
            # The lazy import re-binds the symbol on every call, so the
            # patch target MUST be the function's defining module (NOT
            # the worker's namespace). The fixture URL
            # ``services.example.com`` fails DNS resolution in the test
            # sandbox, which is unrelated to this test's contract
            # (identity preservation + version increment), so we no-op
            # the gate via AsyncMock. Same fix shape as Plan 1075-03
            # closed in test_ingest.py:1369-1372.
            patch(
                "app.modules.catalog.sources.security.validate_url_for_ssrf",
                new=AsyncMock(),
            ),
```

**Edit 2 — `test_reupload_service_without_token_returns_retry_guidance_on_auth_failure`**

Inserted as the FIRST entry in the `with (...)` block (before the existing `build_gdal_source` patch), at what was line 339:

```python
            # Phase 1066 IA-P0-03: same SSRF defense-in-depth as the first
            # worker test. Fixture URL ``protected.example.com`` fails DNS
            # in the sandbox; mock the gate so the test exercises its actual
            # contract (401-retry guidance message from IngestionError).
            # Plan 1075-03 / test_ingest.py:1369 is the canonical pattern.
            patch(
                "app.modules.catalog.sources.security.validate_url_for_ssrf",
                new=AsyncMock(),
            ),
```

## Task Commits

1. **Task 1: Add validate_url_for_ssrf AsyncMock patch to both TestServiceReuploadWorker tests** — `9eccc80b` (test)

**Plan metadata:** (docs commit to follow)

## Files Created/Modified

- `backend/tests/test_reupload_service.py` — Added SSRF AsyncMock patch as first entry in both `TestServiceReuploadWorker` test `with (...)` blocks; 26 insertions, 0 deletions

## Decisions Made

- Patched `app.modules.catalog.sources.security.validate_url_for_ssrf` (defining module), not `app.processing.ingest.tasks_reupload.validate_url_for_ssrf` — the production code at `tasks_reupload.py:347-350` uses a lazy `from app.modules.catalog.sources.security import (..., validate_url_for_ssrf)` inside the function body. This means the symbol is not present in the worker module's namespace at import time and re-binds on every call from the defining module. Patching the worker namespace would be a silent no-op — the test would still fail with `RuntimeError("source_url failed safety check at worker fetch time...")`. The Plan 1075-03 SUMMARY codified this as the "Lazy-import patch target rule" and it applies verbatim here.
- `AsyncMock()` with no `return_value` used (returns `None`). The production gate does `await validate_url_for_ssrf(source_url)` and ignores the return — `None` is the correct mock return shape (matches Plan 1075-03 / 1075-02 AsyncMock-no-return-value precedent).
- Single atomic commit for both tests per REQUIREMENTS.md TD-05 explicit "one commit" notation — both tests share the same root cause (IA-P0-03 gate added after the tests landed).

## pytest Exit Codes

| Invocation | Exit code |
|---|---|
| `pytest tests/test_reupload_service.py::TestServiceReuploadWorker::test_reupload_service_preserves_identity_and_increments_version -x` | 0 (1 passed) |
| `pytest tests/test_reupload_service.py::TestServiceReuploadWorker::test_reupload_service_without_token_returns_retry_guidance_on_auth_failure -x` | 0 (1 passed) |
| `pytest tests/test_reupload_service.py::TestServiceReuploadWorker -x` | 0 (2 passed) |
| `pytest tests/test_reupload_service.py -x` | 0 (3 passed) |

## Production Code Unchanged

`git diff --stat backend/app/` — empty. The `validate_url_for_ssrf` gate at `tasks_reupload.py:373-378` is byte-identical before and after this plan. The `with patch(...)` only neutralizes the gate inside each test's lexical scope. Production deployments hit `validate_url_for_ssrf(source_url)` with a real network resolution path.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None. `AsyncMock` and `patch` were already imported at `test_reupload_service.py:14` (`from unittest.mock import ANY, AsyncMock, MagicMock, patch`). No new imports were needed.

## Known Stubs

None.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes. Production SSRF gate at `tasks_reupload.py:373-378` is unchanged.

## Next Phase Readiness

TD-05 closed. Plans 1081-01 (TD-02/TD-03) and 1081-03 (TD-06) are independent wave-1 plans; this plan does not block or depend on either.

---
*Phase: 1081-test-fixture-assertion-drift*
*Completed: 2026-05-21*
