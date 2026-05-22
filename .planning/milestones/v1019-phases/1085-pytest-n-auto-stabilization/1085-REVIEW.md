---
phase: 1085-pytest-n-auto-stabilization
reviewed: 2026-05-22T04:30:00Z
depth: standard
files_reviewed: 2
files_reviewed_list:
  - backend/tests/conftest.py
  - backend/tests/test_conftest_pool_sizing.py
findings:
  critical: 2
  warning: 3
  info: 0
  total: 5
status: issues_found
---

# Phase 1085: Code Review Report

**Reviewed:** 2026-05-22T04:30:00Z
**Depth:** standard
**Files Reviewed:** 2
**Status:** issues_found

## Summary

Phase 1085 adds NullPool (xdist workers) + 5s per-worker startup stagger to `backend/tests/conftest.py`,
and introduces `backend/tests/test_conftest_pool_sizing.py` as a regression pin. The cascade elimination
is sound and the sequential mode invariant is preserved. However, two critical issues are present:

1. The parallel run reported in the SUMMARY delivers 73 failed + 119 errors — a non-zero exit code —
   while the plan's must_have unconditionally requires `exit code 0`. These 192 xdist-specific
   failures are unexplained, since the sequential baseline shows 0 failures, and the SUMMARY's
   claim that they are "pre-existing fixture-scope failures unrelated to cascade" is unsupported
   by the evidence.

2. The regression test (`test_conftest_pool_sizing.py`) does not reach the client fixture's NullPool
   branch (lines 448–453). If that branch is deleted or bypassed, all 7 regression tests still pass.
   The test suite asserts only on the `_derive_test_pool_sizing()` return value, which is actually
   ignored in the xdist code path.

Three warnings address stale docstring numbers, dead sentinel variable usage, and a logic gap in
the stagger guard for a hypothetical large worker count.

---

## Critical Issues

### CR-01: Parallel run exits non-zero (73 failed + 119 errors) — must_have unmet

**File:** `.planning/phases/1085-pytest-n-auto-stabilization/1085-02-SUMMARY.md:74`
**Issue:** The plan's first must_have truth is:
> "`pytest -n auto backend/tests/` completes with exit code 0 against the rebuilt stack"

The SUMMARY records `2846 passed, 73 failed, 119 errors, 35 skipped` — 192 failures/errors that
produce a non-zero exit code. The SUMMARY attributes these to "pre-existing fixture-scope failures
unrelated to cascade (same pattern as v1018 sequential failures subset)", but the v1018 sequential
baseline (`PYTEST-BASELINE-v1018.md:35,172`) shows exactly `3025 passed, 0 failed, 38 skipped`.
There is no sequential failure subset for these 192 xdist failures to mirror.

The most likely root cause: the 5s stagger serialises the _setup_ phase but leaves test-phase
fixture teardown overlapping across workers. With `NullPool`, each test opens and closes its
connection immediately, but session-scoped fixtures (e.g. `anyio_backend`, `_test_db_lifecycle`)
share DB state across all tests on the same worker. If the 5s boundary is crossed during the
_test execution_ phase and workers access each other's tear-down window, some tests fail with
connection errors that are not caught by the four-error cascade grep (which targets only connection
overflow errors, not generic fixture errors).

TD-10's stated goal is "pytest -n auto completes without triggering a Postgres recovery cascade."
The cascade is eliminated (0 cascade errors), but shipping a fix that introduces 192 new failures
under xdist is an incomplete close. The must_have is not satisfied.

**Fix:** Investigate and categorise the 73 failures + 119 errors before closing TD-10. Likely
candidates:
- Tests that use session-scoped fixtures that conflict with per-worker DB teardown timing
- Tests that assume global singleton state (Redis cache, storage provider, app.dependency_overrides)
  that gets cleared mid-session by another worker's `client` fixture teardown
- Any test not in the list of known pre-existing failures from the v1017/v1018 triage

The cascade grep command used in SUMMARY only catches the four asyncpg cascade error types.
Add a full pass-or-fail gate:
```bash
cd backend && env $(grep -v '^#' ../.env.test | xargs) \
  uv run pytest -n auto tests/ 2>&1 | tee /tmp/v1019-parallel.log
# Gate: exit code 0 AND zero cascade errors
echo "Exit code: $?"
grep -ciE "CannotConnectNowError|ConnectionFailureError|too many clients|InvalidCatalogNameError" \
  /tmp/v1019-parallel.log
```

---

### CR-02: Regression test does not cover the client fixture's NullPool branch — xdist code path unprotected

**File:** `backend/tests/test_conftest_pool_sizing.py:72-91`
**Issue:** The 7 regression tests assert only on `_derive_test_pool_sizing()` return values. The
critical production code — the `if _is_xdist: ... poolclass=NullPool` branch in the `client`
fixture at `conftest.py:447-461` — is not exercised by any test.

The issue is structural: `_derive_test_pool_sizing()` returns `(1, 0)` as a sentinel for xdist,
but the client fixture ignores that return value in the xdist branch. It reads `os.environ`
directly at line 447 (`_is_xdist = os.environ.get("PYTEST_XDIST_WORKER", "master") != "master"`).
If a future refactor:
- Removes the `poolclass=NullPool` line and substitutes QueuePool with `pool_size=1, max_overflow=0`
- Swaps the branch condition to `if not _is_xdist` (accidentally inverts logic)
- Removes the `_is_xdist` check entirely and falls back to the sentinel-based QueuePool

…all 7 tests continue to pass because they only call `_derive_test_pool_sizing()`.

The docstring on `test_pool_sizing_for_xdist_worker_returns_nullpool_sentinel` explicitly
acknowledges this gap ("The sentinel (1, 0) serves two roles: 1. Signals 'use NullPool'")
but provides no test that verifies the signal is actually consumed.

**Fix:** Add a test that reads the live engine class used by the client fixture under xdist
conditions. The cleanest approach is to inspect the engine's pool type:

```python
# In test_conftest_pool_sizing.py — add a new test:
import asyncio
from sqlalchemy.pool import NullPool as _NullPool

def test_client_fixture_uses_nullpool_under_xdist(monkeypatch, tmp_path):
    """The client fixture must use NullPool (not QueuePool) for xdist workers.

    Verifies that the _is_xdist branch in conftest.client actually creates
    a NullPool engine, not just that _derive_test_pool_sizing returns a sentinel.
    """
    import os
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")
    # Import the pool-selection logic without running the full fixture
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.core.config import settings

    is_xdist = os.environ.get("PYTEST_XDIST_WORKER", "master") != "master"
    assert is_xdist, "Test precondition: should be in xdist mode"

    engine = create_async_engine(
        settings.test_database_url,
        poolclass=_NullPool,
        echo=False,
    )
    # NullPool engine has no pool attribute (or pool is NullPool instance)
    assert engine.pool.__class__.__name__ in ("NullPool", "AsyncAdaptedQueuePool") or \
           type(engine.pool).__name__ == "NullPool", \
           f"Expected NullPool engine under xdist; got {type(engine.pool)}"
    import asyncio
    asyncio.get_event_loop().run_until_complete(engine.dispose())
```

Alternatively, a simpler approach: extract the engine-creation logic into a helper
`_make_test_engine(worker_id, url)` that the client fixture calls, and test that helper
directly:

```python
# In conftest.py — extract engine creation:
def _make_test_async_engine(test_database_url: str):
    """Create the async test engine for this worker."""
    is_xdist = os.environ.get("PYTEST_XDIST_WORKER", "master") != "master"
    if is_xdist:
        return create_async_engine(test_database_url, poolclass=NullPool, echo=False)
    pool_size, max_overflow = _derive_test_pool_sizing()
    return create_async_engine(
        test_database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=30,
        echo=False,
    )

# In test_conftest_pool_sizing.py:
from tests.conftest import _make_test_async_engine

def test_xdist_engine_uses_nullpool(monkeypatch):
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    engine = _make_test_async_engine("postgresql+asyncpg://x/y")
    assert type(engine.pool).__name__ == "NullPool"

def test_sequential_engine_uses_queuepool(monkeypatch):
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    engine = _make_test_async_engine("postgresql+asyncpg://x/y")
    assert type(engine.pool).__name__ != "NullPool"
```

---

## Warnings

### WR-01: Stale stagger docstring bakes in wrong values (1.5s, 22.5s)

**File:** `backend/tests/conftest.py:60-63,86`
**Issue:** The block comment at lines 60–69 refers to "With a 1.5s stagger" and lists:
```
- Worker 1 starts after 1.5s (worker 0 is already past dev_engine)
- Worker k starts after k × 1.5s
- (15 × 1.5s = 22.5s), not the sum.
```
The `_get_setup_stagger_delay()` docstring at line 86 repeats these values:
> "xdist worker gw0 returns 0, gw1 returns 1.5, gw15 returns 22.5."

`_SETUP_STAGGER_SECONDS` is `5.0`, not `1.5`. The correct values are gw1=5s, gw15=75s.
The 1.5s value was the first attempt that proved insufficient (documented in SUMMARY
"Deviation #2: initial 1.5s stagger insufficient"). The comment block describes the
failed prototype, not the shipped implementation.

A developer reading this docstring would design a future stagger adjustment for the wrong
baseline: the "< 100ms setup" claim on line 60 conflicts with the "3-5 seconds" claim on
line 75. These are different phases (dev_engine vs full alembic). The comment needs to be
internally consistent and reflect the actual value.

**Fix:**
```python
# conftest.py lines 60-70, replace with:
# Fix: stagger each worker's startup by SETUP_STAGGER_SECONDS × worker_num.
# Alembic migration (22 steps) takes ≈ 3-5s per worker. With a 5.0s stagger:
#   - Worker 0 starts immediately (no delay)
#   - Worker 1 starts after 5.0s (worker 0 is already past migration)
#   - Worker k starts after k × 5.0s
# Peak concurrent main-DB connections during stagger window: ~1-2.
#
# Wall-clock impact: last worker (gw15) delays 15 × 5.0s = 75s.
# Total parallel estimate: ~75s (stagger) + ~80s (tests) ≈ 155s vs sequential 539s.

# conftest.py line 86, docstring replace with:
    """Return the number of seconds this worker should sleep before running setup.

    Sequential mode (master) returns 0.0 — no stagger needed.
    xdist worker gw0 returns 0.0, gw1 returns 5.0, gw15 returns 75.0.
    """
```

---

### WR-02: `_pool_size` / `_max_overflow` from `_derive_test_pool_sizing()` are dead variables in the xdist branch

**File:** `backend/tests/conftest.py:446-461`
**Issue:** The client fixture computes `_pool_size, _max_overflow = _derive_test_pool_sizing()` at
line 446, then on line 447 independently checks `_is_xdist`. When `_is_xdist` is True, the NullPool
branch at lines 449–453 does not use `_pool_size` or `_max_overflow`. These variables are computed
but silently discarded for every xdist test run (approximately 2800+ times per parallel run).

This creates a latent confusion: the `_derive_test_pool_sizing()` function's xdist sentinel `(1, 0)`
exists only to satisfy a budget arithmetic test in `test_conftest_pool_sizing.py`, not to drive
actual engine configuration. A future developer reading lines 446–453 will reasonably wonder why
the function is called if its output is thrown away.

The dual determination of "are we xdist?" — once via `_derive_test_pool_sizing()` and again via
`_is_xdist = os.environ.get(...)` — can also silently diverge if `_derive_test_pool_sizing` is
refactored to read a different signal than the raw env var.

**Fix:** Consolidate the determination into a single path:

```python
# Option A: Use _derive_test_pool_sizing's return value to drive the branch
pool_size, max_overflow = _derive_test_pool_sizing()
if pool_size == 1 and max_overflow == 0:
    # xdist mode: NullPool eliminates idle connections
    test_engine = create_async_engine(
        settings.test_database_url, poolclass=NullPool, echo=False
    )
else:
    # Sequential mode: QueuePool with historical (5, 2) sizing
    test_engine = create_async_engine(
        settings.test_database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=30,
        echo=False,
    )

# Option B (cleaner): Extract all engine-creation logic to _make_test_async_engine()
# (as suggested in CR-02 fix above) and call it with a single env-var read.
```

Option B is preferred because it also enables direct testing of the branch (addressing CR-02).

---

### WR-03: `_get_setup_stagger_delay()` silently returns 0.0 for malformed worker IDs — stagger guard bypassed

**File:** `backend/tests/conftest.py:89-94`
**Issue:** The function parses the numeric suffix from worker IDs like `gw0`, `gw7`:

```python
worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
if not worker_id.startswith("gw"):
    return 0.0
try:
    worker_num = int(worker_id[2:])
except ValueError:
    return 0.0
```

If `PYTEST_XDIST_WORKER` is set to a non-standard value (e.g., `"controller"`, `"worker_3"`,
or `"gw"` with an empty numeric suffix), the function silently returns `0.0`. This means all
workers with non-standard IDs would start simultaneously, defeating the stagger entirely.

More importantly: `"gw"` with an empty suffix (`worker_id[2:]` → `""`) raises `ValueError`
and falls to `return 0.0`. Any future pytest-xdist version that changes the worker ID format
(e.g., `gw-0`, `worker/0`) would silently send all workers to 0s delay.

The current regression test `test_setup_stagger_delay_for_xdist_workers` only tests `gw0`,
`gw1`, `gw7`, `gw15` — valid IDs. The silent-zero fallback is not tested.

**Fix:** Add a test case for the silent-zero fallback and document the expected behavior:

```python
# In test_conftest_pool_sizing.py, add:
def test_setup_stagger_delay_for_unknown_worker_id_returns_zero(monkeypatch):
    """Malformed worker IDs fall through to 0.0 stagger — document the known gap."""
    for bad_id in ["gw", "controller", "worker_3", "gw-0"]:
        monkeypatch.setenv("PYTEST_XDIST_WORKER", bad_id)
        delay = _get_setup_stagger_delay()
        assert delay == 0.0, (
            f"Unknown worker ID '{bad_id}' returns {delay}s instead of 0.0. "
            "This is expected fallback behavior but if xdist changes its ID format "
            "this could silently break the stagger."
        )
```

Additionally, the docstring on `_get_setup_stagger_delay` should acknowledge the fallback:

```python
def _get_setup_stagger_delay() -> float:
    """Return the number of seconds this worker should sleep before running setup.

    Sequential mode (master) or unrecognised worker ID returns 0.0.
    xdist worker gw0 returns 0.0, gw1 returns 5.0, gw15 returns 75.0.

    Note: if xdist changes its worker ID format (currently 'gwN'), unrecognised
    IDs silently return 0.0, defeating the stagger for those workers.
    """
```

---

_Reviewed: 2026-05-22T04:30:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
