# Phase 222: audit-sink-protocol - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-30
**Phase:** 222-audit-sink-protocol
**Mode:** `--auto --chain` (Claude picked recommended defaults; chained to plan+execute)
**Areas discussed:** Sink emit signature & event shape, Sync vs async emit, log_action() fate (AUDIT-02), Sink-failure semantics (AUDIT-03), Multi-sink subscription mechanism, Test extensibility verification (AUDIT-04), get_audit_sinks() accessor location

---

## Sink emit signature & event shape

| Option | Description | Selected |
|--------|-------------|----------|
| Frozen `AuditEvent` dataclass | `emit(session, event)` — typed event, append-safe, no positional churn for overlays | ✓ |
| Match `log_action()` 1:1 keyword args | `emit(session, *, user_id, action, ...)` — minimal new surface area | |
| Pydantic event model | Validation + serialization + nested-field support | |

**Auto-selected:** Frozen `AuditEvent` dataclass (recommended default).
**Notes:** Hot path, no validation needed; protocol surface is minimal `(session, event)`; future fields appended without touching every sink. Pydantic rejected for hot-path cost. Mirrors today's `log_action()` parameter surface 1:1 — pure transport refactor (REQUIREMENTS.md "no new audit event types").

---

## Sync vs async emit

| Option | Description | Selected |
|--------|-------------|----------|
| Async-only | `async def emit(...)` — matches existing `log_action()` async shape | ✓ |
| Sync with async wrapper | `def emit(...)` plus `async def emit_async(...)` | |
| Sync-only | `def emit(...)` — caller bridges via `asyncio.run` if needed | |

**Auto-selected:** Async-only.
**Notes:** All 65 existing call sites are already in async functions (FastAPI routers, async service methods, Celery tasks under `asyncio.run`). Async leaves the door open for non-blocking I/O in enterprise sinks (HTTP POST to SIEM, S3 PutObject) without blocking the request thread. Resolves STATE.md design-decision item.

---

## log_action() fate (AUDIT-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Option (a): becomes `DefaultAuditSink.emit()`'s body | Symbol preserved as private/internal helper; `DefaultAuditSink` delegates | ✓ |
| Option (b): removed entirely | Row-construction logic inlined in `DefaultAuditSink`; symbol deleted | |

**Auto-selected:** Option (a) — becomes default sink body.
**Notes:** Smallest possible diff to row-construction logic. Single source of truth for `AuditLog` row creation. Option (b) would require either duplicating field list or doing a no-semantic-benefit symbol rename. AUDIT-02 explicitly accepts either; (a) wins on minimal-risk grounds.

---

## Sink-failure semantics (AUDIT-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Per-sink try/except inside facade | `audit_emit()` loops sinks, wraps each in try/except + `structlog.exception()` | ✓ |
| Try/except inside each sink's own `emit()` | Defaults swallow internally; Protocol contract requires no-raise | |
| Raise-and-rollback (no swallow) | Sinks must succeed; sink failure rolls back the surrounding business operation | |

**Auto-selected:** Per-sink try/except inside facade.
**Notes:** Default sink does NOT swallow internally — preserves today's behavior where DB constraint violations surface during outer `session.flush()`. The facade is the single sink-failure-isolation point. Call sites stay clean — no try/except boilerplate at any of the 65 sites. AUDIT-03 literal text: "swallowed and logged via `structlog.exception()` but do not propagate."

---

## Multi-sink subscription mechanism (AUDIT-04)

| Option | Description | Selected |
|--------|-------------|----------|
| List-based: `_extensions["audit_sinks"]: list[AuditSink]` | Default registered first (lazily by accessor), overlays append | ✓ |
| Single-slot replacement: `_extensions["audit_sink"]: AuditSink` | Last-write-wins, overlay must wrap default if both desired | |
| Pub/sub event bus | Sinks subscribe to events via decorator pattern | |

**Auto-selected:** List-based registry.
**Notes:** A deployment can want default DB-write AND streaming-export simultaneously — sinks coexist, don't compete. Matches AUDIT-04 contract literally ("subscribe additional sinks"). Pub/sub event bus is over-engineered for v13.3 (rejected per YAGNI).

---

## Test extensibility verification (AUDIT-04)

| Option | Description | Selected |
|--------|-------------|----------|
| Fixture-based direct registry append | `_extensions["audit_sinks"].append(FixtureSink())` — pattern mirrors Phase 220 lifecycle test | ✓ |
| Entry-points round-trip | Install a synthetic test package via entry_points, exercise full discovery path | |
| Mock-based | `unittest.mock` patches `get_audit_sinks()` to return `[FixtureSink()]` | |

**Auto-selected:** Fixture-based direct registry append.
**Notes:** Mirrors Phase 220 D-04 / `test_lifecycle.py` pattern. Entry-points round-trip already covered by SAML overlay tests. Mock-based loses end-to-end coverage of the registry-accessor contract. Test asserts BOTH `DefaultAuditSink` (writes audit_logs row) AND `FixtureSink` (records event in list) received the same event end-to-end.

---

## get_audit_sinks() accessor location

| Option | Description | Selected |
|--------|-------------|----------|
| `backend/app/platform/extensions/__init__.py` | Mirrors existing `get_audit_extension()`, `get_branding_extension()`, `get_identity_extension()`, `get_auth_extension()` typed accessors verbatim | ✓ |
| `backend/app/modules/audit/service.py` | Co-locate accessor with the facade that uses it | |
| New `backend/app/platform/extensions/sinks.py` module | Group all multi-instance accessors in their own module | |

**Auto-selected:** `extensions/__init__.py` (mirrors existing pattern).
**Notes:** Zero new mental load for downstream readers. The four existing typed accessors all live here; `get_audit_sinks()` is a near-clone with a list return type and a list default. New module would create scaffolding for one accessor — YAGNI.

---

## Claude's Discretion

Items where the planner has flexibility within the selected decisions:

- `AuditEvent` location — `backend/app/modules/audit/events.py` (new file) vs co-located in `service.py`
- Facade function name — `audit_emit` (recommended) vs `emit_audit` vs `audit_service.emit`
- `AsyncSession` import handling in `protocols.py` — concrete type vs `object` + runtime cast (whichever avoids cycles)
- Test file location — `backend/tests/test_audit_sink.py` (new) vs extending `backend/tests/test_audit.py`
- Eager vs lazy default-sink registration — D-09/D-11 recommend lazy in accessor; planner can choose eager init in `app/api/main.py` startup
- Lazy-import preservation in `processing/ingest/tasks_common.py` (4 sites already lazy)
- Per-sink logging field structure on swallowed failure — recommended: `sink_name`, `action`, `resource_type`, `resource_id`
- Plan partition — single plan with sub-tasks (recommended) vs multiple plans
- `make audit-sink-discipline` linter target — optional addition

## Deferred Ideas

Captured in CONTEXT.md `<deferred>` section:

- Audit-export overlay implementation (AUDIT-FUTURE-01)
- Compliance reporting (AUDIT-FUTURE-02)
- AuditSink advanced semantics (back-pressure, batching, ordering, durable queues)
- Sync emit support
- `log_action()` symbol removal (option b from AUDIT-02)
- Circuit-breaking / sink-quarantine on N consecutive failures
- New audit event types or fields
- Audit-log retention/rotation policy changes
- Unified registry-shape abstraction (single-vs-list slot polymorphism)
- `make audit-sink-discipline` linter target
