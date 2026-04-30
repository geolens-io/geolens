---
phase: 222-audit-sink-protocol
plan: "02"
subsystem: backend-audit
tags: [facade, sink-failure, structlog, audit, tdd]
dependency_graph:
  requires:
    - "Plan 01: AuditSink Protocol, AuditEvent, DefaultAuditSink, get_audit_sinks() — all consumed by facade"
  provides:
    - "audit_emit(session, event) async facade in backend/app/modules/audit/service.py"
    - "AuditEvent re-exported from audit/service.py for single-import ergonomics"
    - "AUDIT-03 regression test: test_raising_sink_does_not_break_business_op"
  affects:
    - "backend/app/modules/audit/service.py — 3 new imports, logger, __all__, audit_emit() function"
    - "backend/tests/test_audit_sink.py — AUDIT-03 test appended"
tech_stack:
  added: []
  patterns:
    - "structlog.stdlib.get_logger(__name__) at module level (precedent: extensions/__init__.py:30)"
    - "per-sink try/except inside for-loop body (D-06: each sink isolated, not whole-iteration)"
    - "AuditEvent re-export via __all__ for Plan 03 single-import ergonomics"
    - "get_user_id(session, 'admin') pattern to satisfy audit_logs FK in tests"
key_files:
  created: []
  modified:
    - backend/app/modules/audit/service.py
    - backend/tests/test_audit_sink.py
decisions:
  - "D-04/D-05: log_action() signature and body preserved verbatim — zero modifications"
  - "D-06: per-sink try/except inside the for-loop body — failing sink does not prevent later sinks from running"
  - "D-07: DefaultAuditSink does NOT swallow internally — only the facade does"
  - "D-08: no circuit-breaking — failing sink is retried on next audit_emit() call"
  - "RESEARCH Q2: AuditEvent re-exported from service.py via __all__ so Plan 03 uses one import line"
  - "Rule 1 auto-fix: test used uuid.uuid4() as actor_id causing FK violation; fixed to use get_user_id(session, 'admin') for the real seeded user"
metrics:
  duration: "~4 minutes"
  completed_date: "2026-04-30"
  tasks_completed: 2
  files_created: 0
  files_modified: 2
---

# Phase 222 Plan 02: audit_emit() Facade + Sink-Failure Test Summary

`audit_emit(session, event)` async facade added to `audit/service.py` with per-sink failure isolation (AUDIT-03). A raising sink swallows its exception via `structlog.exception()` and does NOT prevent later sinks from running. The AUDIT-03 regression test passes GREEN.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Write AUDIT-03 RED test (test_raising_sink_does_not_break_business_op) | f771e624 | backend/tests/test_audit_sink.py |
| 2 | Add audit_emit() facade — turns AUDIT-03 test GREEN | f147aa02 | backend/app/modules/audit/service.py, backend/tests/test_audit_sink.py |

## What Was Built

### audit_emit() Facade Contract

`audit_emit(session: AsyncSession, event: AuditEvent) -> None` in `backend/app/modules/audit/service.py`:

- **Iterates** `get_audit_sinks()` (from Plan 01) — returns `[DefaultAuditSink()]` for community, `[DefaultAuditSink(), ...]` for enterprise overlays.
- **Per-sink try/except** (D-06): each `sink.emit(session, event)` is wrapped independently. A failing sink does NOT prevent the next sink from running — the exception is caught at the `try/except` boundary inside the for-loop body.
- **structlog.exception()** logs swallowed failures with structured fields: `sink=type(sink).__name__`, `action`, `resource_type`, `resource_id`. Does NOT include `event.details` (PII risk per T-222-02).
- **Does NOT modify** `log_action()` — signature, docstring, and body preserved verbatim (D-04, D-05).

### AuditEvent Re-Export (RESEARCH Q2)

`AuditEvent` is imported from `app.modules.audit.events` and declared in `__all__`, making `from app.modules.audit.service import audit_emit, AuditEvent` work as a single-line import for the 65 call sites Plan 03 will rewrite.

### AUDIT-03 Regression Test

`test_raising_sink_does_not_break_business_op` in `backend/tests/test_audit_sink.py`:

1. Registers `[DefaultAuditSink(), RaisingSink()]` at `_extensions["audit_sinks"]` with proper save/restore in `try/finally` (Pitfall G).
2. Calls `audit_emit(test_db_session, event)` directly — no HTTP roundtrip; independent of Plan 03's call-site rewrite.
3. Asserts:
   - (b) `audit_emit()` returns normally (no exception propagated)
   - (c) `DefaultAuditSink` wrote its `audit_logs` row (FK uses real admin user ID)
   - (d) `structlog.exception()` emitted a record with "Audit sink raised" in the message

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test FK violation with random UUID as user_id**
- **Found during:** Task 2, first GREEN run
- **Issue:** Plan template used `actor_id = uuid.uuid4()` as `AuditEvent.user_id`. The `audit_logs.user_id` column has a FK to `users.id`. Random UUIDs don't exist in the test DB, causing `IntegrityError: ForeignKeyViolationError`.
- **Fix:** Added `from tests.factories import get_user_id` and replaced `actor_id = uuid.uuid4()` with `actor_id = await get_user_id(test_db_session, "admin")` — the seeded admin user always exists in the test DB. Consistent with how all other audit tests obtain a user ID (e.g., `test_audit.py:31`).
- **Files modified:** `backend/tests/test_audit_sink.py`
- **Commit:** f147aa02

## Verification

- `cd backend && uv run pytest tests/test_audit_sink.py -v` — 2 passed (both AUDIT-01 and AUDIT-03)
- `cd backend && uv run pytest tests/test_audit.py tests/test_lifecycle.py -v` — 18 passed (no regressions)
- `cd backend && uv run python -c "from app.modules.audit.service import audit_emit, AuditEvent, log_action; print('imports OK')"` — OK
- `cd backend && uv run ruff check app/modules/audit/service.py tests/test_audit_sink.py` — All checks passed
- `git diff HEAD~2 HEAD -- backend/app/modules/audit/service.py | grep '^-' | grep -v '^---'` — zero deletions (only additions to service.py)

## Plan 03 is Unblocked

Plan 03 (65-site mechanical rewrite) can now import `audit_emit` and `AuditEvent` from `app.modules.audit.service` in a single line and route all call sites through the facade.

## Known Stubs

None.

## Threat Flags

None — no new network endpoints, auth paths, or schema changes introduced. The `structlog.exception()` call does NOT emit `event.details` (T-222-02 mitigation applied as specified).

## Self-Check: PASSED

- `backend/app/modules/audit/service.py` — FOUND (audit_emit at line 25, log_action unchanged)
- `backend/tests/test_audit_sink.py` — FOUND (2 tests: test_audit_sink_protocol_shape + test_raising_sink_does_not_break_business_op)
- Commit f771e624 — FOUND in git log
- Commit f147aa02 — FOUND in git log
