---
phase: 1088-fixture-isolation-fixes-regression-pins
reviewed: 2026-05-22T18:07:32Z
depth: standard
files_reviewed: 2
files_reviewed_list:
  - backend/tests/conftest.py
  - backend/tests/test_fixture_isolation_v1020.py
findings:
  critical: 0
  warning: 4
  info: 5
  total: 9
status: issues_found
---

# Phase 1088: Code Review Report

**Reviewed:** 2026-05-22T18:07:32Z
**Depth:** standard
**Files Reviewed:** 2
**Status:** issues_found

## Summary

Phase 1088 adds three retry-with-backoff helpers (`_create_test_db_with_retry`, `_run_with_too_many_clients_retry`, `_acquire_test_session_with_retry`) plus a `_TRANSIENT_CONTENTION_EXCEPTIONS` catch tuple to `backend/tests/conftest.py`, wired into the per-worker DB lifecycle, the `client` fixture's first async-session acquisition (`_ensure_roles_and_admin`), and the per-request `override_get_db` and `test_db_session` fixtures. 11 regression pins land at `backend/tests/test_fixture_isolation_v1020.py`. The implementation is methodical and well-documented inline — the iter-1 → iter-2 → iter-3 measurement-driven evolution is preserved verbatim in helper docstrings, and the catch tuple correctly spans both SQLAlchemy-wrapped and raw asyncpg shapes (the iter-1 42%-coverage bug fixed by widening).

**No critical (blocker) defects found.** The retry helpers preserve loud-fail-on-exhaust semantics, correctly distinguish contention from non-contention OperationalError shapes, and pre-quote SQL identifiers at the helper boundary so the helper itself cannot introduce injection surface. Sequential baseline preservation (3047/0/38) is verified per the SUMMARY chain.

The 4 warnings + 5 info items below cover: (1) async-context-manager protocol drift in `_acquire_test_session_with_retry` (the explicit `raise` after `__aexit__` ignores `__aexit__`'s suppression return), (2) calling `cm.__aexit__()` when `cm.__aenter__()` itself raised (defensively swallowed but undefined-behavior per Python protocol), (3) a coverage gap for the `__aexit__`-raising path in the in-test retry helper, (4) the catch-tuple "too many clients already" substring guard being narrower than the documented "transient contention" semantic, and several minor hygiene items (unused `patch` import, late `import sys`, slightly misleading docstring about autouse-fixture independence, fragile `tests.conftest` import path).

## Warnings

### WR-01: `_acquire_test_session_with_retry` re-raises unconditionally after `__aexit__`, ignoring suppression contract

**File:** `backend/tests/conftest.py:589-597`
**Issue:** The post-yield teardown path explicitly re-raises after calling `cm.__aexit__(*sys.exc_info())`:

```python
try:
    yield session
except BaseException:
    import sys
    await cm.__aexit__(*sys.exc_info())
    raise
else:
    await cm.__aexit__(None, None, None)
return
```

This deviates from the standard async context manager protocol where a truthy return from `__aexit__` suppresses the exception. The `raise` at line 597 fires regardless of `__aexit__`'s return value. For the live `_AsyncSessionContextManager` (which always returns falsy), this is harmless in practice — but the contract drift means any future replacement of the underlying session-CM that wants to suppress an exception (e.g., a SAVEPOINT wrapper used inside the per-test rollback work-in-progress mentioned in the conftest tech-debt note at lines 1098-1113) will silently fail to suppress.

**Fix:**
```python
try:
    yield session
except BaseException:
    import sys
    exc_info = sys.exc_info()
    suppress = await cm.__aexit__(*exc_info)
    if not suppress:
        raise
else:
    await cm.__aexit__(None, None, None)
return
```

This preserves `__aexit__`'s contractual suppression semantics; today's behavior is preserved because `AsyncSession.__aexit__` returns None.

---

### WR-02: `cm.__aexit__()` called when `cm.__aenter__()` itself raised — undefined-behavior per Python protocol

**File:** `backend/tests/conftest.py:553-577`
**Issue:** In the warm-up retry loop:

```python
try:
    session = await cm.__aenter__()           # line 554 — if THIS raises...
    await session.execute(text("SELECT 1"))
except _TRANSIENT_CONTENTION_EXCEPTIONS as e:
    last_exc = e
    try:
        await cm.__aexit__(type(e), e, e.__traceback__)   # ...we still call __aexit__
    except Exception:
        pass
```

If `__aenter__()` raised, the context-manager protocol (PEP 343 / async equivalent) says `__aexit__` should NOT be called. Calling it is undefined behavior — for SQLAlchemy's `_AsyncSessionContextManager`, internal state checks make this safe-enough (the `try/except Exception: pass` swallows any teardown error), but the helper is depending on implementation details outside the contract.

In practice, under the documented NullPool lazy-connection contract (helper docstring lines 493-512), `__aenter__()` does not acquire a connection, so it should not raise the transient contention exceptions. The warm-up `SELECT 1` is the documented contention trigger. So in production this branch is unreachable. But the helper handles it defensively, masking the protocol violation. Worth narrowing the cleanup to skip `__aexit__` when `session is None`.

**Fix:**
```python
except _TRANSIENT_CONTENTION_EXCEPTIONS as e:
    last_exc = e
    # Per PEP 343, only call __aexit__ if __aenter__ succeeded.
    if session is not None:
        try:
            await cm.__aexit__(type(e), e, e.__traceback__)
        except Exception:
            pass
    # ... rest of the except block unchanged
```

---

### WR-03: Regression-pin file does not cover the path where `cm.__aexit__()` itself raises during the warm-up cleanup

**File:** `backend/tests/test_fixture_isolation_v1020.py` (in-test retry tests, lines 546-825)
**Issue:** All 4 in-test regression pins use `_FakeSessionCM` (line 526-543) whose `__aexit__` returns `False` and never raises. The `try/except Exception: pass` at conftest.py:571-577 (which swallows `__aexit__` failures during the warm-up retry path) is therefore unexercised by the regression pins.

This matters because the swallowing is a deliberate behavior — under heavy contention, the `__aexit__` call itself can plausibly raise on the same contention surface (e.g., a final transactional `ROLLBACK` that needs a connection). If a future refactor changes the swallow to propagate (e.g., narrows the catch to `OperationalError` only and lets `asyncpg.PostgresError` escape), the loud-fail contract changes silently.

The 11-pin matrix has symmetric coverage for retry-success / propagate-non-contention / exhaust-budget across all 3 helpers, but no pin for "what if cleanup fails too?"

**Fix:** Add one in-test pin (or extend an existing one) where `_FakeSessionCM.__aexit__` raises a contention exception during the failed-warm-up cleanup path, asserting the helper still retries (the cleanup failure is swallowed, the original warm-up failure drives the retry). Example:

```python
class _FakeSessionCMWithRaisingExit(_FakeSessionCM):
    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None:
            raise asyncpg.exceptions.TooManyConnectionsError(
                "cleanup also failed under contention"
            )
        return False

# Then assert the retry path still engages and the ORIGINAL warm-up exception
# surfaces on exhaust (not the cleanup exception).
```

---

### WR-04: `_run_with_too_many_clients_retry` substring guard depends on a single English error string

**File:** `backend/tests/conftest.py:443`
**Issue:** The substring check `"too many clients already" not in str(e).lower()` is the gating predicate for retry-vs-propagate on `OperationalError` shapes. Postgres's `connection_limit_exceeded` SQLSTATE (53300) typically surfaces as "sorry, too many clients already" in English locales, but if the Postgres server's `lc_messages` is set to a non-C locale (e.g., during reproducible CI runs with localized error catalogs) the message text may differ. The substring check would then propagate the contention error as non-contention, regressing 4.2/4.3 fixes.

This is identical to the `_create_test_db_with_retry` predicate at line 306 — both depend on the English message.

The asyncpg-raw classes in the catch tuple (`TooManyConnectionsError`, `CannotConnectNowError`) are unambiguously type-checked and don't depend on the message. So the locale-sensitivity only affects the SQLAlchemy-wrapped path.

**Fix:** Either (a) prefer SQLSTATE detection via `e.orig.pgcode == "53300"` when available, or (b) document the locale assumption inline so a future maintainer setting up localized CI doesn't silently lose retry coverage:

```python
# CAUTION: this substring is locale-sensitive. Postgres surfaces the contention
# message in English under default `lc_messages = "C"`; non-C locales may translate
# the message and break this predicate. Prefer SQLSTATE-based detection if the
# orig DBAPI exception exposes `pgcode`:
#   pgcode = getattr(getattr(e, "orig", None), "pgcode", None)
#   if pgcode == "53300": ...
if isinstance(e, OperationalError) and "too many clients already" not in str(e).lower():
    raise
```

Either fix is acceptable; the inline comment alone makes the locale-dependency visible.

## Info

### IN-01: Unused `patch` import in regression-pin file

**File:** `backend/tests/test_fixture_isolation_v1020.py:28`
**Issue:** `from unittest.mock import MagicMock, patch` imports `patch`, but `patch` is not used anywhere in the file (all mocking is done with `MagicMock` and the `_FakeSession`/`_FakeSessionCM` helpers).

**Fix:**
```python
from unittest.mock import MagicMock
```

---

### IN-02: Docstring misleading about autouse-fixture independence

**File:** `backend/tests/test_fixture_isolation_v1020.py:6-10`
**Issue:** Module docstring says:

> "The pins do NOT need a live Postgres host: they exercise the extracted helpers [...] directly with mocked engine factories / coroutine callables, so they run cleanly under `pytest tests/test_fixture_isolation_v1020.py` even without the autouse `_test_db_lifecycle` setup completing."

The autouse session-scoped `_test_db_lifecycle` fixture (conftest.py:606) IS triggered for every test in the session. It either succeeds (DB reachable, DB created), retries-then-fails (post-1088-01 loud-fail on exhausted budget — would fail ALL tests in the session including these pins), or `pytest.skip`s (DB unreachable). The pins are pure-unit in terms of their assertions, but they aren't independent of the autouse session fixture's outcome.

This is a documentation-accuracy concern, not a correctness defect — the tests work as designed in all 3 outcomes. But the docstring overstates independence.

**Fix:** Tighten the language to:

> "The pin bodies do NOT touch Postgres: they exercise the extracted helpers directly with mocked engine factories / coroutine callables. They still share the session-scoped `_test_db_lifecycle` autouse fixture with the rest of the suite, so a Postgres-unreachable environment will produce a `pytest.skip` on this file's tests via the fixture's skip semantics (not a hard failure)."

---

### IN-03: `import sys` inside async function body at line 595

**File:** `backend/tests/conftest.py:595`
**Issue:** `import sys` appears inside the `except BaseException:` handler. Late imports are an established idiom for rarely-used dependencies, but `sys` is already a near-zero-cost stdlib import and would normally live at module-level alongside `os`, `time`, etc.

**Fix:** Move to module-level imports (line 2 alongside `import os`):
```python
import os
import sys
import time
```

Then remove the late import at line 595.

---

### IN-04: Test file uses absolute `from tests.conftest import ...` rather than relative

**File:** `backend/tests/test_fixture_isolation_v1020.py:33`
**Issue:** `from tests.conftest import (...)` depends on pytest's rootdir resolving `tests` as a top-level package. The `backend/pyproject.toml` `testpaths = ["tests"]` configuration makes this work in the CI invocation pattern (`cd backend && uv run pytest`), but the import would fail if a developer ran the test from a different working directory or with a different rootdir resolution.

**Fix (optional):** Either keep as-is and ensure `__init__.py` exists at `backend/tests/__init__.py` so `tests` is a real package, OR switch to a relative import:
```python
from .conftest import (
    _IN_TEST_RETRY_BACKOFFS,
    _acquire_test_session_with_retry,
    _create_test_db_with_retry,
    _run_with_too_many_clients_retry,
)
```

Relative imports are more robust to rootdir changes. Low priority — the existing import works in the documented invocation pattern.

---

### IN-05: Critical `return` at line 600 in `_acquire_test_session_with_retry` lacks an explanatory comment

**File:** `backend/tests/conftest.py:600`
**Issue:** The `return` at line 600 is structurally significant — without it, the post-yield code inside the `for attempt in range(attempt_budget)` loop would fall through to the next iteration, calling `session_factory()` again after a successful yield+teardown. A future maintainer cleaning up this function might remove the `return` thinking it's redundant (since the function "ends" naturally after the loop), reintroducing a double-yield bug.

**Fix:** Add an inline comment explaining the structural role of the `return`:

```python
else:
    await cm.__aexit__(None, None, None)
# Exit the retry loop after a successful yield+teardown. Without this `return`,
# control would loop back and call session_factory() again, double-yielding to
# the caller (which @asynccontextmanager would surface as a generator-protocol
# error like "RuntimeError: generator didn't stop after throw()").
return
```

---

## v1019 Invariants Preserved (verified during review)

- `_make_test_async_engine(test_database_url: str)` signature unchanged at conftest.py:54.
- NullPool branch at conftest.py:67-69 unchanged (`poolclass=NullPool` for xdist workers).
- `_SETUP_STAGGER_SECONDS = 5.0` at conftest.py:109 unchanged.
- `_derive_test_pool_sizing` and `_get_setup_stagger_delay` unchanged.
- Imports at lines 1-22 only ADD (`asyncio`, `asynccontextmanager`, `asyncpg.exceptions`, `OperationalError`) — no removals or shadowing.
- The 5s stagger comment block at lines 80-109 is preserved verbatim; the Audit Section 4.1 comment block at conftest.py:629-651 is additive.

## Security Review

- No new hardcoded secrets. (`hash_password(settings.geolens_admin_password.get_secret_value())` is pre-existing.)
- SQL identifier quoting trust boundary preserved: `_create_test_db_with_retry` takes `quoted_db_name` already-quoted (docstring + caller pattern both enforce this); the helper cannot introduce injection surface.
- `_quote_database_identifier` at line 196-197 escapes embedded quotes via doubling — standard SQL identifier quoting.
- All `text(f"...")` calls inside helpers interpolate either the pre-quoted identifier OR fixed SQL literals (`"SELECT 1"`). No user-input interpolation.

## Resource Cleanup Audit

- `_create_test_db_with_retry`: `engine.dispose()` in `finally` block — guaranteed cleanup per attempt. Sequential attempts use fresh engines.
- `_run_with_too_many_clients_retry`: `coro_fn` owns its own resources; helper does not need to dispose.
- `_acquire_test_session_with_retry`: `cm.__aexit__()` called in 3 branches (warm-up failure cleanup at line 572, post-yield exception cleanup at line 596, post-yield success cleanup at line 599). The warm-up-failure path may be undefined-behavior-adjacent when `__aenter__` itself raised (see WR-02), but is defensively wrapped in `try/except Exception: pass`.

## Backoff Schedule Sanity Check

- Setup-phase budget: `(1.0, 2.0, 4.0)` = 7s cumulative. Fires once per worker at `_create_test_db_with_retry` or `_ensure_roles_and_admin`. Bounded below the 75s gw15 stagger window. Documented inline at conftest.py:244-247 + 319-323.
- In-test budget: `(0.5, 1.0)` = 1.5s cumulative. Fires per-request inside test bodies. Documented inline at conftest.py:454-470. The per-request frequency justifies the tighter budget — a 7s budget here would compound across sequential requests.
- Both budgets are documented at the constant definition with explicit rationale tying the choice to measured contention windows.

---

_Reviewed: 2026-05-22T18:07:32Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
