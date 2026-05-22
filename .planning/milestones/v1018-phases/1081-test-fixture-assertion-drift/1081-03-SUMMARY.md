---
phase: 1081-test-fixture-assertion-drift
plan: "03"
subsystem: testing
tags: [pytest, asyncio-event-loop, sqlalchemy, asyncpg, async_session, fixture-scoping, hygiene]

requires:
  - phase: 1080-production-code-drift-config-hygiene
    provides: broad-except justifications at tasks_common.py:232,238 (WR-02 contract pin)

provides:
  - TD-06 closed: test_job_phase_session_none_branch_rolls_back_on_exception passes in full-suite sequential mode
  - lazy-import + test-DB binding pattern documented in docstring and patterns-established

affects:
  - any future test that bare-calls a helper using from app.core.db import async_session

tech-stack:
  added: []
  patterns:
    - "Lazy-import + test-DB binding rule: request client (or test_db_session) for any test that bare-calls a helper whose body does from app.core.db import async_session"

key-files:
  created: []
  modified:
    - backend/tests/test_tasks_common_phase_brackets.py

key-decisions:
  - "Fix at fixture-scoping level (add client arg) not at production code — lazy import in tasks_common.py:215 is correct by design"
  - "client fixture chosen over a new dedicated rebinding fixture — conftest already does the work, adding client is the smallest possible diff"
  - "anyio_backend NOT promoted to function scope — would churn per-test DB recreation via session-scoped _test_db_lifecycle (30s+ overhead per test)"

patterns-established:
  - "Lazy-import + test-DB binding rule: any test that bare-calls a helper using `from app.core.db import async_session` inside the helper body MUST request the `client` fixture (or any fixture that transitively requests it, e.g., `test_db_session`) — otherwise the lazy import resolves to the production session factory, which may have prior-loop pool state in full-suite runs. The rule mirrors Plan 1075-03's 'Lazy-import patch target rule' but for fixtures instead of mocks."

requirements-completed: [TD-06]

duration: 12min
completed: 2026-05-21
---

# Phase 1081 Plan 03: TD-06 SUMMARY

**`client` fixture arg added to `test_job_phase_session_none_branch_rolls_back_on_exception` — forces conftest monkey-patch to rebind `db_module.async_session` to a fresh per-function engine, eliminating asyncpg cross-loop pool contamination in full-suite mode**

## Performance

- **Duration:** 12 min
- **Started:** 2026-05-21T~22:00Z
- **Completed:** 2026-05-21T~22:12Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- TD-06 closed: `test_job_phase_session_none_branch_rolls_back_on_exception` passes in BOTH isolation AND full-suite sequential mode (test_ingest.py → test_tasks_common_phase_brackets.py)
- WR-02 contract pin (rollback-on-exception in none-branch) preserved intact — no production code touched
- Plan 1080-01's broad-except justifications at `tasks_common.py:232,238` byte-identical post-fix
- 18-line docstring addition explains the root cause and the fix mechanism for future maintainers

## Line Edit (before/after)

**Before (line 121):**
```python
async def test_job_phase_session_none_branch_rolls_back_on_exception():
```

**After:**
```python
async def test_job_phase_session_none_branch_rolls_back_on_exception(client):
```

Plus 18-line docstring paragraph explaining the cross-loop binding root cause (Plan 1081-03 / TD-06 comment block). No other changes to the test body — `missing_id`, `pytest.raises`, `async with _job_phase_session(...)`, `assert job is None`, `raise RuntimeError("none-branch exception")` all byte-identical.

## Task Commits

1. **Task 1: Add client fixture arg** - `d660a27d` (test)

**Plan metadata:** see docs commit below

## Full-suite reproducer

**Command:**
```
cd backend && env $(grep -v '^#' ../.env.test | xargs) uv run pytest tests/test_ingest.py tests/test_tasks_common_phase_brackets.py -x -v
```

**Post-fix result (exit 0):**
```
collected 44 items

tests/test_ingest.py::TestUpload::test_upload_requires_auth PASSED
...
tests/test_ingest.py::TestCommitImportDispatch::test_commit_missing_title_returns_422 PASSED
tests/test_tasks_common_phase_brackets.py::test_phase_session_loads_existing_job PASSED
tests/test_tasks_common_phase_brackets.py::test_phase_session_yields_none_when_job_missing PASSED
tests/test_tasks_common_phase_brackets.py::test_job_phase_session_none_branch_rolls_back_on_exception PASSED
tests/test_tasks_common_phase_brackets.py::test_phase_session_rolls_back_on_exception PASSED
tests/test_tasks_common_phase_brackets.py::test_phase_session_commit_persists_on_normal_exit PASSED

44 passed in 13.38s
```

Pre-fix: `test_job_phase_session_none_branch_rolls_back_on_exception` would fail with `RuntimeError: Task <...> got Future <...> attached to a different loop` at the `await session.rollback()` call inside the broad-except at `tasks_common.py:232`.

## pytest exit codes for all 4 verification runs

| Command | Exit code | Result |
|---------|-----------|--------|
| `pytest tests/test_tasks_common_phase_brackets.py::test_job_phase_session_none_branch_rolls_back_on_exception -x` | 0 | 1 passed in 3.53s |
| `pytest tests/test_ingest.py tests/test_tasks_common_phase_brackets.py -x` | 0 | 44 passed in 13.38s |
| `pytest tests/test_tasks_common_phase_brackets.py -x` | 0 | 5 passed in 3.24s |
| `grep -c "pytest.mark.skip" backend/tests/test_tasks_common_phase_brackets.py` | — | 0 (no skip decorators) |

## Why bare-call form was order-dependent

`_job_phase_session` uses a lazy `from app.core.db import async_session` at line 215 of `tasks_common.py` (inside the function body, not at module import time). This is intentional — it avoids a circular import and means the helper always resolves the symbol at call time, not at definition time.

In **isolation**, `db_module.async_session` is the production singleton — a session factory bound to a fresh asyncpg connection pool, created under the current per-function anyio event loop. Everything works.

In **full-suite sequential mode**, a prior test file (e.g., `test_ingest.py`) exercises the production session factory under a DIFFERENT per-function anyio event loop. Anyio creates a new event loop per test function (default `asyncio_default_test_loop_scope=function`). After that test completes, the asyncpg connection pool remains bound to the now-defunct loop. When the TD-06 test runs and the helper's lazy import resolves to the same production factory, `async_session()` opens a new connection from the pool — and when `session.rollback()` fires inside the broad-except at line 232, asyncpg's internal `Future` is attached to the defunct loop from the prior test. This surfaces as `RuntimeError: Task <...> got Future <...> attached to a different loop`.

The asymmetric failure (only this one test, not the 4 siblings) is explained by:
1. This test raises inside the `async with` block, forcing the `session.rollback()` path in the broad-except at line 232.
2. The 4 siblings all request `test_db_session`, which transitively requests `client`, which monkey-patches `db_module.async_session = test_session_factory` (conftest.py:368-369) — so their calls to the helper resolve to the FRESH per-test engine, not the production pool.
3. `test_phase_session_yields_none_when_job_missing` (line 98) also bare-calls the helper with no fixture, but it does NOT raise inside the block — so the broad-except path never fires, and the defunct-loop pool state never surfaces as a hard error.

The fix: requesting `client` in the TD-06 target pulls the same conftest monkey-patch that the other 4 tests get transitively via `test_db_session`. For the duration of this test, `db_module.async_session` points at `test_session_factory` — a fresh session factory bound to a newly created `test_engine` on the current per-function event loop. The helper's lazy import at line 215 then resolves to this loop-clean factory. When `session.rollback()` fires, it operates on a connection from the fresh pool — no cross-loop Future.

The `client` fixture body (HTTP `AsyncClient`) is never used in this test. We only need the side effect of the monkey-patch and its teardown (conftest.py:411-412 restores the original binding and disposes the test engine).

## Plan 1080-01 broad-except justifications unchanged

```
git diff --stat backend/app/
(empty — no production code modified)
```

`tasks_common.py:232` remains: `except Exception:  # broad: caller-yielded block may raise any exception; we must rollback the session before re-raising to avoid pool leak`

`tasks_common.py:238` remains: `except Exception:  # broad: caller-yielded block may raise any exception; we must rollback the session before re-raising to avoid pool leak`

Both sites byte-identical to their post-Plan-1080-01 state.

## Files Created/Modified
- `backend/tests/test_tasks_common_phase_brackets.py` - `client` arg + 18-line docstring paragraph in TD-06 target

## Decisions Made
- Add `client` as direct fixture arg rather than creating a new dedicated `_async_session_rebinder` fixture — conftest already does the right thing; the dedicated fixture would duplicate machinery for one test
- Do not promote `anyio_backend` to function scope — would churn `_test_db_lifecycle` (session-scoped autouse) and force per-test DB recreation (~30s+ overhead)
- Do not change `_job_phase_session` — production-code change is out of scope; the lazy import is correct by design

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None. The fix worked on the first attempt. Full-suite reproducer gate passed immediately post-edit.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plans 01 + 02 + 03 are all in wave 1 (independent). This plan is complete. The combined cross-plan gate (`pytest tests/test_phase_279_user_lifecycle.py tests/test_reupload_service.py tests/test_tasks_common_phase_brackets.py -x`) can be run after Plans 01 and 02 land.

---
*Phase: 1081-test-fixture-assertion-drift*
*Completed: 2026-05-21*
