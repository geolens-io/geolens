---
phase: 222-audit-sink-protocol
plans: 5
requirements: [AUDIT-01, AUDIT-02, AUDIT-03, AUDIT-04, AUDIT-05]
completed_date: "2026-04-30"
tags: [audit, sink-protocol, architecture-guard, extensibility, open-core]
---

# Phase 222: Audit Sink Protocol — Phase Summary

Introduces an extensible `AuditSink` Protocol seam into the geolens core, routing all 64 `log_action()` call sites through a `audit_emit()` facade, and codifying the invariant as a durable CI architecture guard. The geolens-enterprise overlay can now register custom audit sinks (SIEM, export, compliance) without modifying core.

## Requirements Satisfaction

| Requirement | Description | Test | Status |
|-------------|-------------|------|--------|
| AUDIT-01 | AuditSink Protocol + AuditEvent dataclass + DefaultAuditSink + get_audit_sinks() | `test_audit_sink_protocol_shape` | SATISFIED |
| AUDIT-02 | No log_action() callers outside audit module (0 offending lines) | `test_no_log_action_calls_outside_audit_service` | SATISFIED |
| AUDIT-03 | Sink failure does not break business operation (try/except per sink) | `test_raising_sink_does_not_break_business_op` | SATISFIED |
| AUDIT-04 | Multi-sink subscription — FixtureSink + DefaultAuditSink coexist end-to-end | `test_fixture_sink_receives_events_alongside_default` | SATISFIED |
| AUDIT-05 | Preservation — all existing audit/lifecycle tests pass without modification | Full backend suite: 2040 passed | SATISFIED |

## Phase Plans

| Plan | Name | Key Output | Commit(s) |
|------|------|------------|-----------|
| 01 | AuditSink Protocol, AuditEvent, DefaultAuditSink | 4 new files in platform/extensions + audit/events.py | (see 222-01-SUMMARY.md) |
| 02 | audit_emit() facade + AuditEvent re-export + AUDIT-03 test | audit/service.py + test_audit_sink.py (2 tests) | (see 222-02-SUMMARY.md) |
| 03 | 64-site mechanical rewrite (all await log_action → audit_emit) | 18 files rewritten; AUDIT-02 invariant = 0 | c29095ef, b58c38ad |
| 04 | AUDIT-04 multi-sink integration test via HTTP endpoint | test_audit_sink.py (3rd test); end-to-end verified | bbca9230 |
| 05 | Architecture guard + Makefile + close gate (AUDIT-05) | test_layering.py + Makefile; 2040 tests GREEN | a49fcb06, a4dffe4d |

## What the AuditSink Seam Looks Like

**Protocol** (`backend/app/platform/extensions/protocols.py`):
```python
class AuditSink(Protocol):
    async def emit(self, event: AuditEvent) -> None: ...
```

**Event** (`backend/app/modules/audit/events.py`):
```python
@dataclass
class AuditEvent:
    user_id: int | None
    action: str
    resource_type: str
    resource_id: int | None = None
    details: dict | None = None
    ip_address: str | None = None
```

**Facade** (`backend/app/modules/audit/service.py`):
```python
async def audit_emit(session: AsyncSession, event: AuditEvent) -> None:
    for sink in get_audit_sinks():
        try:
            await sink.emit(event)
        except Exception:
            logger.exception("Audit sink %s raised; continuing", type(sink).__name__)
```

**Default sink** (`backend/app/platform/extensions/defaults.py`):
```python
class DefaultAuditSink:
    async def emit(self, event: AuditEvent) -> None:
        from app.modules.audit.service import log_action  # deferred — Pitfall B
        await log_action(session=..., ...)
```

**Call site pattern** (64 files, e.g., `admin/router.py`):
```python
await audit_emit(db, AuditEvent(user_id=..., action="user.create", ...))
```

## Architecture Guard

`backend/tests/test_layering.py::test_no_log_action_calls_outside_audit_service` — scans `backend/app/` for `await log_action(` via git grep, asserts zero matches outside `audit/service.py` and `extensions/defaults.py`. Future regressions blocked at CI time.

```bash
make audit-sink-discipline  # 1.3s local verification
```

## Grade Improvements (per oc-separation-audit-20260430.md)

| Dimension | Pre-Phase-222 | Post-Phase-222 |
|-----------|---------------|----------------|
| Boundary Integrity | A (🟡 audit sink risk) | A+ (zero 🟡 risks) |
| Seam Quality | B (write-side audit sink 🔴) | B+ (🔴 → 🟢) |

## Enterprise Extension Point (AUDIT-FUTURE-01)

The `geolens-enterprise` overlay can now add audit export without core changes:

```python
# In enterprise overlay entry_points:
from app.platform.extensions import _extensions
from app.platform.extensions.protocols import AuditSink

class EnterpriseAuditSink:
    async def emit(self, event: AuditEvent) -> None:
        # Ship to SIEM, compliance log, export queue, etc.
        ...

_extensions.setdefault("audit_sinks", []).append(EnterpriseAuditSink())
```

## Verifier Handoff

**Close gate command:**
```bash
cd backend && uv run pytest -v --tb=short
# Expected: 2040 passed, 19 skipped
```

**Architecture invariant:**
```bash
make audit-sink-discipline
# Expected: 1 passed (test_no_log_action_calls_outside_audit_service)
```

**Manual spot checks:**
1. `grep -rn "await log_action(" backend/app/ --include="*.py" | grep -v "audit/service.py" | grep -v "defaults.py"` → empty output (AUDIT-02)
2. `cd backend && uv run pytest tests/test_audit_sink.py -v` → 3 passed (AUDIT-01, AUDIT-03, AUDIT-04)
3. `cd backend && uv run pytest tests/test_audit.py tests/test_lifecycle.py -v` → all pass (AUDIT-05 preservation)
4. Boot smoke: `cd backend && uv run python -c "from app.api.main import app; from app.modules.audit.service import audit_emit, AuditEvent; print('OK')"` → `OK`
