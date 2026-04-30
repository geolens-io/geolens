---
phase: 222
slug: audit-sink-protocol
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-30
---

# Phase 222 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `222-RESEARCH.md` §Validation Architecture (lines 934-1131).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | `pytest >= 9.0.3` + `pytest-anyio` (auto mode) |
| **Config file** | `backend/pyproject.toml [tool.pytest.ini_options]` |
| **Quick run command** | `cd backend && uv run pytest tests/test_audit_sink.py tests/test_audit.py tests/test_lifecycle.py -v --tb=short` |
| **Full suite command** | `cd backend && uv run pytest -v --tb=short` |
| **Estimated runtime** | ~30s quick / ~5 min full |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && uv run pytest tests/test_audit_sink.py tests/test_audit.py -v --tb=short`
- **After every plan wave:** Run `cd backend && uv run pytest -v --tb=short` (full backend suite)
- **Before `/gsd-verify-work`:** Full suite must be green AND `pytest tests/test_layering.py::test_no_log_action_calls_outside_audit_service` green
- **Max feedback latency:** ~30 seconds (quick) / ~300 seconds (full)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 222-01-01 | 01 | 1 | AUDIT-01 | T-222-01 | `AuditSink` Protocol + `AuditEvent` dataclass + `DefaultAuditSink` exist with correct shape | unit | `cd backend && uv run pytest tests/test_audit_sink.py::test_audit_sink_protocol_shape -v` | ❌ W0 | ⬜ pending |
| 222-02-01 | 02 | 2 | AUDIT-01 | — | `get_audit_sinks()` typed accessor returns `[DefaultAuditSink()]` when slot missing | unit | `cd backend && uv run pytest tests/test_audit_sink.py::test_get_audit_sinks_default -v` | ❌ W0 | ⬜ pending |
| 222-02-02 | 02 | 2 | AUDIT-03 | T-222-02 | `audit_emit()` facade swallows per-sink failures via `structlog.exception()`, never propagates | integration | `cd backend && uv run pytest tests/test_audit_sink.py::test_raising_sink_does_not_break_business_op -v` | ❌ W0 | ⬜ pending |
| 222-03-01 | 03 | 3 | AUDIT-02 | — | All 65 historical `log_action(` call sites rewritten to `audit_emit()`; `log_action()` called only from `DefaultAuditSink.emit()` | architecture / git-grep | `cd backend && uv run pytest tests/test_layering.py::test_no_log_action_calls_outside_audit_service -v` | ❌ W0 | ⬜ pending |
| 222-04-01 | 04 | 4 | AUDIT-04 | — | Fixture sink receives every event alongside `DefaultAuditSink` (multi-sink coexistence) | integration | `cd backend && uv run pytest tests/test_audit_sink.py::test_fixture_sink_receives_events_alongside_default -v` | ❌ W0 | ⬜ pending |
| 222-05-01 | 05 | 5 | AUDIT-05 | — | Existing audit/lifecycle test suite passes without modification | regression | `cd backend && uv run pytest tests/test_audit.py tests/test_lifecycle.py -v` | ✅ Existing | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_audit_sink.py` — new file covering AUDIT-01, AUDIT-03, AUDIT-04 (4 test functions)
- [ ] `backend/tests/test_layering.py` — append `test_no_log_action_calls_outside_audit_service` for AUDIT-02 (architecture guard via `_git_grep` with `:!` pathspec exclusions)
- [ ] No new fixtures in `conftest.py` — reuse `client`, `admin_auth_header`, `test_db_session`
- [ ] No new pytest markers — `@pytest.mark.anyio` for async tests; `@pytest.mark.architecture` for the layering test (already registered)

*No framework install gap — pytest, anyio, structlog all in `backend/pyproject.toml` already.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Future enterprise audit-export overlay can register sinks via `setdefault + append` pattern without core changes | AUDIT-04 (forward-compatibility) | Enterprise overlay ships in separate `geolens-enterprise` repo; verifying real entry-point round-trip requires installing the overlay package. CI already installs it (Phase 220 D-06) but a literal new audit-export overlay won't exist until AUDIT-FUTURE-01 ships. The fixture-based test (`test_fixture_sink_receives_events_alongside_default`) covers the contract end-to-end. | When the future audit-export overlay is built, append a smoke test in the enterprise repo that imports the overlay's sink class, asserts it implements `AuditSink`, and runs against a representative endpoint. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (`test_audit_sink.py`, `test_layering.py` append)
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s (quick) / 300s (full)
- [ ] `nyquist_compliant: true` set in frontmatter (set by planner once test stubs land)

**Approval:** pending
