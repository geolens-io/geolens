# Phase 225: processing-port-protocol-cycle-inversion - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-01
**Phase:** 225-processing-port-protocol-cycle-inversion
**Areas discussed:** Protocol surface granularity, Default impl & accessor location, Wire-in pattern, Architecture-guard scope, Test seam, Catalog→processing direction
**Mode:** `--auto --chain` — Claude auto-selected the recommended option for every gray area; chain auto-advances to plan-phase after CONTEXT.md is committed.

---

## Protocol surface granularity

| Option | Description | Selected |
|--------|-------------|----------|
| Single comprehensive `ProcessingPort` | One Protocol exposing every catalog accessor processing/* needs (read+write). Mirrors Phase 214 IdentityProtocol. | ✓ |
| Multiple narrow Protocols | `DatasetReadPort`, `MapWritePort`, `SearchPort`, `AuthzPort` — split by call type. Each processing file takes 2–4 dependencies. | |
| Module-by-module Ports | One Port per processing sub-package (`AIPort`, `IngestPort`, `TilesPort`, `ExportPort`). | |

**User's choice:** Single comprehensive (auto-selected — recommended).
**Notes:** ROADMAP §225 binds the goal to "ProcessingPort Protocol" (singular); audit P0 #2 says "mirror Phase 214 IdentityProtocol pattern." Phase 214 D-01 chose comprehensive over narrow for the same reason — narrower forces half-converted callers and split test seams. Comprehensive lets every site receive ONE port. The audit's separate `CatalogReadPort` (P2 #4 for non-processing read-only consumers) is a different, later phase.

---

## Default impl & accessor location

| Option | Description | Selected |
|--------|-------------|----------|
| Mirror Phase 214 (Identity) | Protocol in `core/processing_port.py`, default in `platform/extensions/defaults.py` (`DefaultProcessingPort`), accessor in `platform/extensions/__init__.py` (`get_processing_port()`). Single-slot. | ✓ |
| Mirror Phase 222 (AuditSink) | Protocol in `platform/extensions/protocols.py`, list-shape accessor `get_processing_ports()` returning `[DefaultProcessingPort()]`. | |
| In-catalog default | Default impl lives in `app.modules.catalog.processing_port` — catalog owns the implementation. | |

**User's choice:** Mirror Phase 214 (auto-selected — recommended).
**Notes:** ProcessingPort is a consumer-facing type (callers annotate against it from cross-domain code). Consumer-facing types belong in `core/` per Phase 214 IDENT-01 — `core/` is the lowest layer and the architecture-guard already enforces `core/ → modules/` is forbidden, which is exactly the discipline Phase 225 needs. Single-slot accessor matches the consumer-pull semantics (only one Port impl per deployment; overlays REPLACE). List-shape (Phase 222 AuditSink) is for fan-out hooks (audit_emit dispatches to N sinks) — not the Port pattern.

---

## Wire-in pattern

| Option | Description | Selected |
|--------|-------------|----------|
| FastAPI Depends + worker singleton | Routes use `port: ProcessingPort = Depends(get_processing_port)`; workers call `get_processing_port()` directly. Service-layer functions take `port` as explicit parameter (testability). | ✓ |
| Module-level singleton everywhere | All callers reach for `get_processing_port()` directly; no FastAPI Depends. | |
| Inject via app.state | Port stored on `app.state.processing_port` at startup; routes read from `request.app.state`. | |

**User's choice:** FastAPI Depends + worker singleton + service-layer parameter (auto-selected — recommended).
**Notes:** FastAPI Depends composes cleanly with existing `Depends(get_db)`, `Depends(get_optional_user)` patterns at the route layer. Worker tasks (Procrastinate) don't go through FastAPI dep injection — they call the accessor directly at the top of the task body, mirroring the existing deferred-import discipline (Phase 213 D-04). Service-layer functions taking `port` as an explicit parameter is required to satisfy ROADMAP SC#5's "fake ProcessingPort" test seam.

---

## Architecture-guard scope

| Option | Description | Selected |
|--------|-------------|----------|
| Strict zero-hit (no allowlist for processing/*) | `^(from|import) app.modules.catalog` returns zero hits under `backend/app/processing/`. Pathspec excludes only `backend/tests/`. Mirrors Phase 222 AUDIT-02 + Phase 224 DECOUPLE-04. | ✓ |
| Allowlist function-scope deferred imports | Module-level imports forbidden; deferred imports inside function bodies allowed (legacy). | |
| Allowlist specific files | Like Phase 214's User allowlist — designate side-effect imports OK. | |

**User's choice:** Strict zero-hit (auto-selected — recommended).
**Notes:** Codebase scan confirms there are NO legitimate side-effect catalog imports in processing/* today (catalog ORM classes are transitively pulled in via `app.api.main` — no equivalent of Phase 214's `tasks_raster.py:142` `User` registration). ROADMAP §225 SC#2 binds the strict grep. Function-scope deferred imports also migrate (D-19) — keep deferral, swap path. The pathspec excludes `backend/tests/` because test fixtures construct catalog ORM objects directly (structurally satisfies Protocols at the call site).

---

## Test seam

| Option | Description | Selected |
|--------|-------------|----------|
| Focused `FakeProcessingPort` unit test | One test in `tests/test_processing_port.py` constructs a fake port with canned data, passes it to an AI service function, asserts output. | ✓ |
| Full mock-port integration suite | Mock the entire Port across all processing/* modules, run a broad regression suite. | |
| Runtime `isinstance(Dataset(), DatasetProtocol)` conformance test | Verify ORM classes structurally satisfy Protocols at runtime. | |

**User's choice:** Focused `FakeProcessingPort` unit test (auto-selected — recommended).
**Notes:** ROADMAP §225 SC#5 binds the focused test ("focused unit test that swaps in a fake `ProcessingPort`"). The 2036/2036 backend baseline is the broader correctness gate. Phase 214 D-21 deferred runtime conformance tests for marginal value; Phase 225 inherits. Single high-signal test demonstrating the seam works.

---

## Catalog → processing direction

| Option | Description | Selected |
|--------|-------------|----------|
| Leave untouched (one-way inversion only) | Catalog → processing imports (51 lines) stay; only processing → catalog inverts. | ✓ |
| Bidirectional inversion | Also invert catalog → processing via separate Protocol (e.g., `IngestExtension`). | |

**User's choice:** Leave untouched (auto-selected — recommended).
**Notes:** ROADMAP §225 SC#2's grep is direction-specific (`processing → catalog` only). Catalog drives processing top-down — that's the natural direction. The audit P0 #2 also explicitly flags only the processing → catalog direction. If a future phase wants stricter bidirectional decoupling, that's a separate phase (no scope creep into Phase 225).

---

## Claude's Discretion

The following implementation choices were left explicitly for the planner/executor (per CONTEXT.md `### Claude's Discretion` section):

- Commit decomposition (likely 4 atomic commits — additive scaffold → top-level migration → function-scope migration → architecture-guard test).
- Module docstring wording in `core/processing_port.py`.
- Whether to refactor any catalog helper functions during the migration (default NO — only trivial dead-import cleanup).
- Method naming convention (default: mirror existing catalog function names exactly).
- `SearchFilters` / `SearchResult` / `MapSpec` / `DatasetCreatePayload` / `ColumnStats` types stay in catalog with TYPE_CHECKING forward-references.
- AI service signature changes — `port: ProcessingPort` parameter added; planner picks keyword-only vs positional.

## Deferred Ideas

(Captured in CONTEXT.md `<deferred>` — full list there.)

- `CatalogReadPort` for non-processing read-only consumers (audit P2 #4 — separate phase).
- `PermissionExtension` Protocol for authorization helpers (Phase 999.8 backlog).
- `AIProviderExtension` Protocol (Phase 226 — sequences after 225).
- `WorkflowExtension`, `Connector` ORM, `geolens-schemas` extraction, `geolens.yaml` manifest — all separate phases.
- Inverting the catalog → processing direction — explicitly out of scope.
- Pyright/mypy CI gate — Phase 214 D-25 deferred; Phase 225 inherits.
- Cosmetic doc/compose drifts from audit-26-b — fold into Phase 229 or a quick task.
