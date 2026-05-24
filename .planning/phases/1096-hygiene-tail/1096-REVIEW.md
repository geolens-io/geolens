---
phase: 1096-hygiene-tail
status: clean
depth: standard
reviewed: 2026-05-24
findings_total: 0
---

# Phase 1096 Code Review

**Status:** clean — no issues found at standard depth; phase is ship-ready.

## Files Reviewed

- `backend/tests/conftest.py` — WR-03 narrow catch at L842, WR-04 dispose override at L922-993, `_install_dbapi_connect_retry` signature change at L753, `InvalidRequestError` import at L15, `_sync_engine`/`_do_connect_handler` storage at L835-836/L871-872
- `backend/tests/test_fixture_isolation_v1020.py` — 3 new pins at L1391 (WR-01 event-handler), L1557 (carry-forward catches-raw-asyncpg), L1666 (carry-forward propagates-non-transient)

## Findings

### Critical
None.

### Warning
None.

### Info
None requiring action.

The 2 inline `pass` blocks (conftest.py:865 and conftest.py:974) were flagged by the verifier as INFO with inline rationale. Rationale is sufficient:

- **conftest.py:865** — `handler = None` after WR-03 narrow catch. Cleanly delegates the no-listener state to the dispose() None-guard at L953-956.
- **conftest.py:974** — `pass` in dispose remove try/except. Defense-in-depth: catches race-window failures (sibling dispose already removed, test-double mutation between install and remove). Latent risk WR-04 closes is listener-stacking on re-install, NOT remove failure. Immediate reset to None at L978 ensures idempotency.

## Adversarial Verification

All adversarial concerns checked clean:
1. **WR-04 dispose race conditions** — idempotent via `handler = None` reset inside if-block; broad except absorbs racing duplicate-remove.
2. **State combinations of `_sync_engine` × `_do_connect_handler`** — exhaustively enumerated; impossible-state ruled out by install guarantee.
3. **WR-01 pin exercises event-handler path (not wrapper-method)** — verified via real `create_engine("sqlite:///:memory:")` + direct `dispatch.do_connect` iteration at L1500.
4. **WR-03 narrow tuple expansion to 3 classes** — justified by SQLAlchemy 2.x documented failure shapes; future genuine regressions still loud-fail.
5. **Listener removal idempotency** — verified via reset-inside-if-block ordering.
6. **Mock leakage in new pins** — verified clean; finally blocks restore state.
7. **Imports verified at collection time** — `InvalidRequestError` from `sqlalchemy.exc`, all pin imports resolve.
8. **Plan-deviation documentation** — Rule 1 (WR-03 expansion) + Rule 3 (`engine.dialect.dispatch.do_connect` vs `engine.dispatch.do_connect`) deviations documented inline with 6+ line comment blocks (test_fixture_isolation_v1020.py:1492-1498 + 1534-1536).

## Quality Observations (non-actionable)

1. Assertion ordering in WR-01 pin: `(b) result is sentinel` before `(a) call_count == 3` — fastidious but not a defect.
2. `_sync_engine` not reset to None on dispose (only `_do_connect_handler`) — intentional asymmetry; None-guard short-circuits on either.
3. WR-04 dispose() retry loop uses `await self._sleep_fn(...)` directly (async) vs connect() uses `_invoke_sleep_in_sync_context` (sync) — intentional asymmetry per AsyncEngine 2.x semantics.
4. 2 carry-forward pins are 100+ lines each — well-structured with 4-numbered assertions mirroring existing pins.

## Verdict

**Ship-ready.** All findings the brief asked to scrutinize have inline rationale that survives adversarial scrutiny. Recommend proceeding to Phase 1097.
