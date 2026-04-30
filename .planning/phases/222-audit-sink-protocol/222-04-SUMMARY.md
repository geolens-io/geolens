---
phase: 222-audit-sink-protocol
plan: "04"
subsystem: backend-audit
tags: [test, multi-sink, integration, audit, AUDIT-04]
dependency_graph:
  requires:
    - "Plan 01: AuditSink Protocol, AuditEvent, DefaultAuditSink, get_audit_sinks()"
    - "Plan 02: audit_emit() facade in audit/service.py + AuditEvent re-export"
    - "Plan 03: 64 call-site rewrite — audit_emit() at admin/router.py:113"
  provides:
    - "AUDIT-04 verified: FixtureSink + DefaultAuditSink coexist end-to-end via HTTP endpoint"
    - "Multi-sink subscription contract confirmed through rewritten call path"
    - "test_fixture_sink_receives_events_alongside_default in test_audit_sink.py"
  affects:
    - "backend/tests/test_audit_sink.py — third test appended"
tech_stack:
  added: []
  patterns:
    - "Fixture sink registered via direct _extensions['audit_sinks'] = [DefaultAuditSink(), FixtureSink()] (D-12)"
    - "Snapshot/restore pattern: saved = _extensions.get('audit_sinks') + finally restore (T-222-08 mitigation)"
    - "Pitfall C resolution: both DefaultAuditSink() and FixtureSink() seeded in same slot"
    - "Session visibility: await test_db_session.commit() before querying committed audit row"
key_files:
  created: []
  modified:
    - backend/tests/test_audit_sink.py
decisions:
  - "Used POST /admin/users/ (not direct audit_emit()) to exercise the rewritten admin/router.py:113 call site end-to-end"
  - "Omitted email field — AdminUserCreate schema has it optional; existing working tests also omit it"
  - "Queried audit_logs via test_db_session (same session factory, READ COMMITTED) after commit() — no API query needed"
metrics:
  duration: "~5 minutes"
  completed_date: "2026-04-30"
  tasks_completed: 1
  files_created: 0
  files_modified: 1
---

# Phase 222 Plan 04: AUDIT-04 Multi-Sink Integration Test Summary

Appended `test_fixture_sink_receives_events_alongside_default` to `backend/tests/test_audit_sink.py`, verifying the multi-sink subscription contract end-to-end via HTTP endpoint POST /admin/users/ — both DefaultAuditSink and FixtureSink receive the user.create event through the Plan 03-rewritten `audit_emit` call path.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Append test_fixture_sink_receives_events_alongside_default | bbca9230 | backend/tests/test_audit_sink.py |

## What Was Built

### AUDIT-04 Integration Test

`test_fixture_sink_receives_events_alongside_default` validates the complete multi-sink subscription path:

1. **Arrange**: Snapshot `_extensions["audit_sinks"]`, set to `[DefaultAuditSink(), FixtureSink()]`.
2. **Act**: `POST /admin/users/` with unique username `audit-sink-test-multi-{8hex}` — exercises `admin/router.py:113` (Plan 03's rewritten `audit_emit` call).
3. **Assert FixtureSink** (AUDIT-04): `fixture_sink.received` contains a `user.create` event with matching `resource_type`, `details.username`, `details.role`.
4. **Assert DefaultAuditSink** (AUDIT-05 coexistence proof): `audit_logs` row exists with `action="user.create"` and JSONB containment on username.
5. **Cleanup**: `finally` block restores (or pops) `_extensions["audit_sinks"]` per T-222-08.

### Why HTTP endpoint (not direct audit_emit):

Plan 02's `test_raising_sink_does_not_break_business_op` calls `audit_emit()` directly — it tests facade isolation, not call-site wiring. Plan 04 must exercise the actual HTTP request path so it verifies Plan 03's work: that `admin/router.py:113` routes through `audit_emit()` and thus reaches the FixtureSink. A direct `audit_emit()` call would pass even if Plan 03 had not completed the rewrite.

### Pitfall C resolution:

Both `DefaultAuditSink()` and `FixtureSink()` are seeded in the `audit_sinks` slot. If only `[fixture_sink]` were set, DefaultAuditSink would be absent from the iteration — the audit_logs row assertion would fail even though the fixture sink ran correctly.

### Session visibility:

`test_db_session` opens from the same `db_module.async_session` factory the client uses. The HTTP request commits its own session. Calling `await test_db_session.commit()` before the query starts a new READ COMMITTED transaction that sees the committed row — no API query proxy needed.

### Test Results

```
tests/test_audit_sink.py::test_audit_sink_protocol_shape PASSED
tests/test_audit_sink.py::test_raising_sink_does_not_break_business_op PASSED
tests/test_audit_sink.py::test_fixture_sink_receives_events_alongside_default PASSED
3 passed in 3.75s
```

Ruff: all checks passed.

### Unblocked Plans

- **Plan 05** (architecture guard): `test_no_log_action_calls_outside_audit_service` tests the AUDIT-02 invariant. The invariant is already satisfied by Plan 03 and will pass on first run.

## Deviations from Plan

None. Plan executed exactly as written. The only minor adaptation: `email` field omitted from the POST body (it is optional in `AdminUserCreate` schema and existing tests omit it) — this matches the plan's intent and the test passes at 201.

## Known Stubs

None.

## Threat Flags

None — test-only file modification. No new network endpoints, auth paths, or schema changes.

## Self-Check: PASSED

- `backend/tests/test_audit_sink.py` exists and contains 3 tests
- Commit bbca9230 — FOUND (`git log --oneline -1` confirms)
- `grep -c 'def test_fixture_sink_receives_events_alongside_default' backend/tests/test_audit_sink.py` → 1
- `grep -c 'class FixtureSink' backend/tests/test_audit_sink.py` → 1
- `grep -c 'DefaultAuditSink(), fixture_sink' backend/tests/test_audit_sink.py` → 1
- All 3 tests GREEN: 3 passed in 3.75s
- Ruff: all checks passed
