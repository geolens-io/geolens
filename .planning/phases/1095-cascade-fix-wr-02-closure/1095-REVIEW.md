---
phase: 1095-cascade-fix-wr-02-closure
reviewed: 2026-05-23
depth: standard
files_reviewed: 5
files_reviewed_list:
  - backend/tests/conftest.py
  - backend/tests/test_tiles.py
  - backend/tests/test_embed_tokens.py
  - backend/tests/test_tile_signing.py
  - backend/tests/test_fixture_isolation_v1020.py
findings:
  critical: 0
  warning: 1
  info: 4
  total: 5
status: issues_found
---

# Phase 1095: Code Review Report

**Reviewed:** 2026-05-23
**Depth:** standard
**Files Reviewed:** 5
**Status:** issues_found (1 Warning + 4 Info; zero Critical — phase is ship-ready)

## Summary

Phase 1095 lands two related fixes in a single phase:

1. **PARA-01 (Plan 01):** Wraps the 3 sibling `_init_tile_pool_for_tests` fixtures' raw `asyncpg.create_pool` calls in the existing `_run_with_too_many_clients_retry` envelope. Adds 1 new pin to `test_fixture_isolation_v1020.py`.
2. **PARA-02 (Plan 02):** Documents WR-02's load-bearing `time.sleep` (Shape Y2 rationale block) at `_invoke_sleep_in_sync_context` after empirical Shape Y1 attempt produced 658 RuntimeError cascade. Adds 1 new pin asserting the rationale text persists.

The work is well-executed:
- 3-run `-n auto` measurement gate cleared (distinct = 3/2/3, ALL ≤30 ceiling, ALL pre-existing OOS — ZERO cascade frames)
- Sequential 3057/3 + `-n 4` 3055/5 — 0 NEW failures attributable to v1022
- Pin assertions are well-structured: each test creates fresh state (sentinel_pool, call_count, sleep_calls) with no mock leakage
- Anchor uniqueness verified: `if sleep_fn is asyncio.sleep:` appears at exactly one location in conftest.py
- Import paths consistent with project convention (`from tests.conftest import ...`)
- Both `_invoke_sleep_in_sync_context` call sites (line 743, 880) are reachable from the same code path the WR-02 rationale documents

The deviations (Y1→Y2 fallback per Plan 02 Task 2 explicit fork rule; service restart after broken Y1) followed plan-named contracts. The Y2 rationale (load-bearing `time.sleep` with documented WR-02/PARA-02 cross-references) is the empirically correct landing — Y1 cannot work because the production caller path (`_retry_do_connect` via SQLAlchemy `do_connect` event from inside `greenlet_spawn`) runs inside a live asyncio loop where `asyncio.run()` refuses to nest.

Findings below identify a single warning (asymmetric pin coverage relative to the existing `test_engine_retry_*` family) and four info items (naming clarity, docstring precision, untouched sibling call sites in deselected-by-default perf tests).

## Warnings

### WR-01: New `test_init_tile_pool_*` pin family ships with only 1 pin vs the 4-pin `test_engine_retry_*` precedent

**File:** `backend/tests/test_fixture_isolation_v1020.py:1144`
**Issue:** The existing `test_engine_retry_*` family at lines 905/978/1030/1071 has 4 pins covering: positive retry, raw asyncpg catch, non-transient propagation, budget exhaustion. The new `test_init_tile_pool_*` family ships with only the positive-retry pin. Plan 01 SUMMARY acknowledges this deliberately per audit Section 5.1 + CONTEXT.md `<specifics>` ("positive pin alone is load-bearing"), but the asymmetry leaves two contractual gaps:

1. **No exhaustion pin:** If a future refactor expands `_SETUP_PHASE_RETRY_BACKOFFS` from `(1.0, 2.0, 4.0)` to something that silently swallows on exhaust (e.g., returning `None` instead of re-raising), the `test_init_tile_pool_*` family would not detect it. The `test_engine_retry_exhausts_budget_then_fails_loudly` pin at line 1071 catches drift at the engine-layer, but the fixture-layer wrap uses the same envelope so this is structurally covered — still, the leaner family makes regression-detection contract harder to read at a glance.

2. **No raw-asyncpg-catch pin:** The bug that Plan 1088-03 fought (only catching `OperationalError`, missing the dominant raw-asyncpg-via-greenlet-spawn surface — see conftest.py:392-397 docstring) is currently pinned at line 978 via `test_engine_retry_catches_raw_asyncpg_too_many_connections`. A future contributor narrowing the catch to just `OperationalError` would break the engine-layer pin AND the new fixture-layer wrap simultaneously (both share `_TRANSIENT_CONTENTION_EXCEPTIONS`), so this is mitigated by the existing engine pin. Naming-explicit symmetry would still be more defensible.

**Severity rationale:** Warning, not Critical, because:
- The single positive pin DOES cover the contract that matters most (retry returns the post-2-failures pool)
- The `_SETUP_PHASE_RETRY_BACKOFFS == (1.0, 2.0, 4.0)` drift-guard at the end of the pin (line 1236) catches budget changes
- The shared `_TRANSIENT_CONTENTION_EXCEPTIONS` tuple means engine-layer pins cover catch-narrowing drift transitively

**Fix:** Either accept the deferred scope (per Plan 01 SUMMARY's explicit acknowledgment) and document the gap in a follow-up todo, OR add 2 sibling pins in a Phase 1096 hygiene wave:

```python
def test_init_tile_pool_propagates_non_transient_operational_error():
    """Propagation pin: non-contention OperationalError shapes (DNS / refused /
    auth) must propagate immediately at the fixture-layer envelope, NOT retry."""
    # ... mirror test_engine_retry_propagates_non_transient_operational_error
    # but invoke via _run_with_too_many_clients_retry (lambda: fake_create_pool(...))


def test_init_tile_pool_exhausts_budget_then_fails_loudly():
    """Exhaustion pin: persistent TooManyConnectionsError exhausts the 7s
    budget then re-raises (loud-fail, NOT silent-swallow)."""
    # ... mirror test_engine_retry_exhausts_budget_then_fails_loudly
    # but use the fixture-layer envelope
```

Recommend tracking as a Phase 1096 carry-forward in HYG-01 scope (line is adjacent to the existing pin region).

## Info

### IN-01: Pin name `test_engine_retry_yields_event_loop_during_backoff` is misleading under Shape Y2

**File:** `backend/tests/test_fixture_isolation_v1020.py:1253`
**Issue:** The pin name describes a behavioral assertion ("yields event loop during backoff") but the body (lines 1303-1359) asserts only static text presence in conftest.py — there is no runtime loop-yield check. Plan 02 SUMMARY explicitly retains the name "for traceability symmetry with the original Plan 02 PARA-02 (b) shape," which is documented well in the pin's docstring (lines 1265-1267), but a casual reader scanning `pytest --collect-only` output would expect a runtime behavioral check.

The pin's docstring DOES explain the Y2 alternative, but the name-vs-behavior asymmetry creates a small surprise.

**Fix:** Two options (operator choice):
- (a) Keep the name as-is per the traceability-symmetry rationale; the docstring already explains. No change needed.
- (b) If renaming is acceptable, prefer something like `test_engine_retry_documents_wr02_load_bearing_rationale` to match what the pin actually does. The Plan 02 SUMMARY would need a one-line cross-reference note.

Recommend (a) — the docstring is clear, and renaming would require a SUMMARY/REQUIREMENTS update for a cosmetic gain.

### IN-02: `_run_with_too_many_clients_retry` docstring says "async callable" but accepts any callable returning an awaitable

**File:** `backend/tests/conftest.py:402-405`
**Issue:** The docstring at line 401-405 describes `coro_fn` as "Zero-arg async callable that performs the DB-touching setup work." In practice, both production (lambda returning `Pool` instance via sync `asyncpg.create_pool(...)`) and the new pin (lambda returning coroutine via `fake_create_pool(...)` invocation) are sync callables returning awaitables — not strictly async callables. The `await coro_fn()` line works because the returned object has `__await__` (Pool) or is a coroutine (async def call), but the docstring imprecision could mislead a future contributor.

This is pre-existing behavior — Phase 1095 did not introduce the imprecision, but Plan 01 leaned on it heavily by passing `lambda: asyncpg.create_pool(...)` (where `asyncpg.create_pool` is a regular sync function returning a Pool — not a coroutine).

**Fix:** Tighten the docstring at line 401-405:

```python
Args:
    coro_fn: Zero-arg callable that returns an awaitable. Both async-def
        callables (returning a coroutine) and sync callables returning an
        object with __await__ (e.g., asyncpg.Pool from asyncpg.create_pool)
        are supported. Called fresh on each attempt so the underlying
        asyncpg connection is re-acquired rather than reusing a rejected
        connection.
```

Defer to Phase 1096 or beyond — non-blocking and cosmetic.

### IN-03: Y2 rationale block names one of two `_invoke_sleep_in_sync_context` call sites

**File:** `backend/tests/conftest.py:642-643` (docstring) + `673-674` (inline comment)
**Issue:** The Y2 rationale identifies `_install_dbapi_connect_retry._retry_do_connect` (line 742-745 call site) as "the load-bearing production caller path." The second call site at `_RetryingAsyncEngine.connect()` (line 880) shares the same load-bearing semantics — it's also invoked in sync context from a possibly-running loop — but is not explicitly named in the rationale.

The `_RetryingAsyncEngine.connect()` docstring at line 838-867 acknowledges that in PRODUCTION, the contention surfaces on `__aenter__` rather than on the synchronous `connect()` call, so the retry loop at line 869-884 primarily covers fake/test engines. This means the second call site is rarely hit in real production paths — but it IS the same shape as the first.

The pin at line 1253 asserts `greenlet_spawn` token presence and the WR-02/PARA-02 cross-refs; it does NOT require both call sites to be named. So this is documentation completeness, not a pin defect.

**Fix:** Add a one-sentence reference to the second call site in the rationale block. Suggested addition at end of the docstring bullet (after line 655):

```
The same blocking-sleep contract applies to ``_RetryingAsyncEngine.connect()``
(line 880 call site), which uses ``_invoke_sleep_in_sync_context`` from the
same sync-context constraint — that path is primarily exercised by the
``test_engine_retry_*`` pin family (see ``_RetryingAsyncEngine.connect`` docstring
note about test-fixture vs production paths).
```

Defer — non-blocking.

### IN-04: Two unwrapped `asyncpg.create_pool` call sites remain in `test_perf_regression.py`

**File:** `backend/tests/test_perf_regression.py:136` + `:259`
**Issue:** The audit Section 3.2 named 3 fixture sites (test_tiles.py, test_embed_tokens.py, test_tile_signing.py). Phase 1095 wraps all 3. However, `test_perf_regression.py` contains 2 additional `_perf_tile_pool` / `_perf_polygon_pool` fixtures at lines 136 + 259 that use the same `asyncpg.create_pool(dsn=dsn, min_size=1, max_size=3, command_timeout=10)` shape but are NOT wrapped.

These fixtures are gated behind `@pytest.mark.perf` and `pyproject.toml:82` sets `addopts = "-m 'not perf'"` — so they are deselected by default and do NOT contribute to the `-n auto` cascade window. **Out of scope for Phase 1095 (the cascade source did not include perf tests).**

However, if perf tests are ever included in a CI run (e.g., via a separate `make test-perf` target), the same contention surface would re-emerge. The wrap shape is straightforward to apply (literally the same pattern as Plan 01).

**Fix:** Track as a hygiene followup in HYG-01 (Phase 1096) or beyond:

```python
# backend/tests/test_perf_regression.py:136 (and :259)
# Apply the same Shape A* wrap as Plan 1095-01:
from tests.conftest import _run_with_too_many_clients_retry

pool = await _run_with_too_many_clients_retry(
    lambda: asyncpg.create_pool(
        dsn=dsn, min_size=1, max_size=3, command_timeout=10
    )
)
```

Defer — only matters if perf tests are ever un-deselected in CI.

---

_Reviewed: 2026-05-23_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
