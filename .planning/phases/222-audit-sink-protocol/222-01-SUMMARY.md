---
phase: 222-audit-sink-protocol
plan: "01"
subsystem: backend-extensions
tags: [protocol, extensions, audit, dataclass, open-core]
dependency_graph:
  requires: []
  provides:
    - "AuditSink Protocol in backend/app/platform/extensions/protocols.py"
    - "AuditEvent frozen dataclass in backend/app/modules/audit/events.py"
    - "DefaultAuditSink in backend/app/platform/extensions/defaults.py"
    - "get_audit_sinks() accessor in backend/app/platform/extensions/__init__.py"
  affects:
    - "backend/app/platform/extensions/ — all 4 extension modules touched"
    - "backend/app/modules/audit/ — new events.py added"
tech_stack:
  added: []
  patterns:
    - "@runtime_checkable Protocol with AsyncSession module-import (precedent: core/identity.py:29)"
    - "TYPE_CHECKING forward-ref for AuditEvent to avoid platform->modules layering inversion"
    - "Deferred import inside emit() body (Phase 214 discipline)"
    - "list[AuditSink] accessor with lazy-default + defensive copy (departure from single-instance pattern)"
key_files:
  created:
    - backend/app/modules/audit/events.py
    - backend/tests/test_audit_sink.py
  modified:
    - backend/app/platform/extensions/protocols.py
    - backend/app/platform/extensions/defaults.py
    - backend/app/platform/extensions/__init__.py
decisions:
  - "D-01: AuditSink is @runtime_checkable Protocol with async emit(session, event) — AsyncSession imported at module level (not TYPE_CHECKING) for isinstance() to work at runtime"
  - "D-02: AuditEvent is frozen @dataclass with 6 fields mirroring log_action() 1:1"
  - "D-09: audit_sinks slot is a list (plural), not repurposing _extensions['audit'] (read-side)"
  - "D-10/D-11: get_audit_sinks() returns [DefaultAuditSink()] lazily when slot missing, list() defensive copy when populated"
  - "AuditEvent uses TYPE_CHECKING forward-ref in protocols.py to avoid platform.extensions -> modules.audit layering inversion"
metrics:
  duration: "~5 minutes"
  completed_date: "2026-04-30"
  tasks_completed: 3
  files_created: 2
  files_modified: 3
---

# Phase 222 Plan 01: AuditSink Protocol Scaffolding Summary

AuditSink Protocol scaffolding — 4 new symbols (AuditSink, AuditEvent, DefaultAuditSink, get_audit_sinks) added as the write-side extension contract alongside the existing 3 read-side Protocols.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | AuditEvent frozen dataclass + Wave-0 test (RED) | 5f8d81a2 | backend/app/modules/audit/events.py, backend/tests/test_audit_sink.py |
| 2 | AuditSink Protocol + DefaultAuditSink | 5db28606 | backend/app/platform/extensions/protocols.py, backend/app/platform/extensions/defaults.py |
| 3 | get_audit_sinks() accessor; Wave-0 test GREEN | 3cc10cfe | backend/app/platform/extensions/__init__.py |

## What Was Built

### 4 New Symbols

**`AuditSink`** (`backend/app/platform/extensions/protocols.py`) — 4th `@runtime_checkable` Protocol alongside `BrandingExtension`, `AuditExtension`, `AuthExtension`. Write-side contract. Signature: `async def emit(self, session: AsyncSession, event: "AuditEvent") -> None`. `AsyncSession` imported at module level (not inside `TYPE_CHECKING`) so `isinstance(obj, AuditSink)` works at runtime — precedent from `core/identity.py:29`.

**`AuditEvent`** (`backend/app/modules/audit/events.py`, new file) — `@dataclass(frozen=True)` with 6 fields mirroring `log_action()` parameter surface 1:1: `user_id`, `action`, `resource_type`, `resource_id`, `details`, `ip_address`. Three fields have defaults (`None`) matching `log_action()`'s signature exactly so the call-site rewrite (Plan 03) is a 1:1 wrap.

**`DefaultAuditSink`** (`backend/app/platform/extensions/defaults.py`) — Community-edition default sink. `async def emit(self, session, event) -> None` uses deferred import (`from app.modules.audit.service import log_action`) per Phase 214 discipline so the platform-layer module does not pull modules-layer imports at load time. Does NOT swallow exceptions (D-07) — facade swallows.

**`get_audit_sinks()`** (`backend/app/platform/extensions/__init__.py`) — `-> list[AuditSink]` typed accessor, the one departure from the four existing single-instance accessors. Returns `[DefaultAuditSink()]` when `_extensions["audit_sinks"]` slot is missing (lazy default, D-11). Returns `list(sinks)` defensive copy when slot is populated so iterating sinks cannot mutate the registry mid-loop.

### TYPE_CHECKING Forward-Ref Decision

`AuditEvent` is imported inside `if TYPE_CHECKING:` in `protocols.py`. If it were a real import, `platform.extensions.protocols` would import from `modules.audit.events`, inverting the layering boundary that Phase 212/214 closed. The string forward-ref `"AuditEvent"` in the emit signature resolves at type-check time only; at runtime, `isinstance(obj, AuditSink)` checks structural compatibility without needing the `AuditEvent` type.

### Deferred Import in DefaultAuditSink.emit()

`from app.modules.audit.service import log_action` lives inside the `emit()` method body, not at module level. This follows Phase 214 deferred-import discipline: `app/platform/extensions/defaults.py` is platform-layer; pulling a modules-layer import at load time would create an edge that could cause circular-import issues during application startup.

### list-typed Accessor (D-09 Departure)

The four existing accessors return a single object (`get_branding_extension() -> BrandingExtension`, etc.). `get_audit_sinks()` returns `list[AuditSink]` because community deployments want one sink (DB row) AND enterprise deployments can add N additional sinks (S3, SIEM, syslog) simultaneously — they coexist, they don't compete for a slot.

Enterprise overlays append via `setdefault + append`:
```python
sinks = registry.setdefault("audit_sinks", [DefaultAuditSink()])
sinks.append(MyEnterpriseSink())
```

Overwriting the slot (`registry["audit_sinks"] = [MySink()]`) makes `DefaultAuditSink` disappear and breaks AUDIT-05. Documented in `get_audit_sinks()` docstring. Cannot be enforced in the contract (overlay code is out-of-repo).

### Wave-0 Test

`test_audit_sink_protocol_shape` in `backend/tests/test_audit_sink.py`:
- Confirms `AuditSink` is `@runtime_checkable`
- Confirms `isinstance(DefaultAuditSink(), AuditSink)` is `True`
- Confirms `AuditEvent` has exactly the 6 expected fields

Test runs GREEN. File is the home for Plan 02 (raising-sink AUDIT-03 test) and Plan 04 (fixture-sink AUDIT-04 test).

## Plan 02 and Plan 03 are Unblocked

- **Plan 02** (facade `audit_emit()` in `backend/app/modules/audit/service.py`) imports `AuditSink`, `DefaultAuditSink`, `get_audit_sinks()`, and `AuditEvent` — all now exist.
- **Plan 03** (65-site mechanical rewrite: `log_action(...)` → `audit_emit(session, AuditEvent(...))`) depends on both the facade (Plan 02) and `AuditEvent` (this plan).

## Verification

- `cd backend && uv run pytest tests/test_audit_sink.py -v` — 1 passed
- `cd backend && uv run pytest tests/test_audit.py tests/test_lifecycle.py -v` — 18 passed
- `cd backend && uv run ruff check ...` — all checks passed
- No import cycles: `from app.platform.extensions import get_audit_sinks; from app.modules.audit.events import AuditEvent; print('imports OK')` — OK
- `_extensions["audit"]` (read-side `AuditExtension`) untouched — confirmed
- `AuditExtension.get_export_formats()` untouched — confirmed (D-18)
- `log_action()` signature untouched — confirmed (D-05)

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- `backend/app/modules/audit/events.py` — FOUND
- `backend/tests/test_audit_sink.py` — FOUND
- `backend/app/platform/extensions/protocols.py` — FOUND (4 @runtime_checkable Protocols)
- `backend/app/platform/extensions/defaults.py` — FOUND (DefaultAuditSink class)
- `backend/app/platform/extensions/__init__.py` — FOUND (get_audit_sinks accessor)
- Commits 5f8d81a2, 5db28606, 3cc10cfe — all exist in git log
