---
phase: 1081
depth: quick
status: clean
findings:
  critical: 0
  warning: 0
  info: 0
generated: 2026-05-21
files_reviewed:
  - backend/tests/test_phase_279_user_lifecycle.py
  - backend/tests/test_reupload_service.py
  - backend/tests/test_tasks_common_phase_brackets.py
---

# Phase 1081: Code Review Report

**Reviewed:** 2026-05-21
**Depth:** quick
**Files Reviewed:** 3
**Status:** clean

## Summary

Three test files modified across three commits (9bc2294b / 9eccc80b / d660a27d). All four TD items
verified against both the submitted artifacts and the production code they reference. No regressions
introduced; no production code modified by any Phase 1081 commit.

## CODE REVIEW CLEAN

Each focus area from the review brief:

**TD-02 / TD-03 — password fixture correctness**
`"TestPass1234!"` confirmed: 13 chars (≥12), 4 character classes (upper T/P, lower e/s/t/a/s/s,
digits 1/2/3/4, symbol !). `validate_password_complexity` in `password_policy.py` checks
`classes_present < require_classes` where default `require_classes=3`. The fixture satisfies the
policy at maximum margin (4/4). The old `"securepass123"` literal is gone as a live JSON value —
it appears only inside the two explanatory comment blocks (lines 151, 207), which is correct.
Project-wide scan confirms no other test file retains `"password": "securepass123"` as a live JSON
value.

**TD-05 — SSRF mock correctness**
Patch target is `app.modules.catalog.sources.security.validate_url_for_ssrf` (the defining module)
in both tests, confirmed at lines 226 and 363 of `test_reupload_service.py`. The wrong-namespace
target `app.processing.ingest.tasks_reupload.validate_url_for_ssrf` is absent (grep exit 1).
The lazy `from app.modules.catalog.sources.security import (SSRFError, validate_url_for_ssrf,)` in
`tasks_reupload.py` is at line 347, inside the function body — confirming the lazy-import patch
target rule applies. Production code at line 374 does `await validate_url_for_ssrf(source_url)` and
ignores the return value; `AsyncMock()` with no `return_value` is the correct mock shape (returns
`None` on await, matching the gate's success path).

**TD-06 — `client` fixture mechanism**
`conftest.py:369` sets `db_module.async_session = test_session_factory` (a fresh engine per
function). `conftest.py:412` restores `db_module.async_session = original_session` in teardown.
Test signature at line 121 is now `async def test_job_phase_session_none_branch_rolls_back_on_exception(client):`.
The SUMMARY's mechanism explanation ("rebinds the factory to a fresh per-function engine for the
duration of THIS test") matches the conftest source exactly. The `_job_phase_session` helper's lazy
`from app.core.db import async_session` at `tasks_common.py:215` (per plan) resolves to the
test-engine factory while the `client` fixture is in scope. The fix works for the documented reason,
not a side effect of some other initialization.

**No collateral test regression**
The other four sibling tests in `test_tasks_common_phase_brackets.py` are unchanged (confirmed by
reading the full file). `test_phase_session_yields_none_when_job_missing` (line 98) retains its
no-fixture bare-call form — this is safe because that test does not raise inside the block and
therefore never reaches the `await session.rollback()` path that surfaces the cross-loop binding
error.

**No skip marks**
`grep -c "pytest.mark.skip"` returns 0 for all three files.

**Production code untouched**
`git diff HEAD~3..HEAD -- backend/app/` produces no output. The three Phase 1081 commits touch only
`backend/tests/`.

---

_Reviewed: 2026-05-21_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: quick_
