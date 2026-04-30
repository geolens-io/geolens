# Phase 222: audit-sink-protocol - Context

**Gathered:** 2026-04-30
**Status:** Ready for planning
**Mode:** `--auto --chain` (recommended-default decisions; chained to plan+execute)

<domain>
## Phase Boundary

Every audit event emitted from `backend/app/` routes through a single extensible sink Protocol — `AuditSink.emit(session, event)` — instead of calling `log_action()` directly. Community behavior is byte-identical to today: a single registered `DefaultAuditSink` writes one `audit_logs` row per emit, with no row-count or row-content drift on a deterministic test workload. An enterprise audit-export overlay can register additional sinks (file, S3, SIEM, syslog) by appending to the `_extensions["audit_sinks"]` list via the existing `geolens.extensions` entry-point group, without touching any of the 65 emit sites in core. Sink failures are swallowed and logged via `structlog.exception()` so a failed audit emit never rolls back or suppresses the surrounding business operation.

Concretely after this phase:

- A new `AuditSink` Protocol lives in `backend/app/platform/extensions/protocols.py`, alongside the existing `BrandingExtension`, `AuditExtension`, `AuthExtension` Protocols. Signature: `async def emit(self, session: AsyncSession, event: AuditEvent) -> None`. (Existing `AuditExtension.get_export_formats()` is the **read-side** contract for export-format gating at `audit/router.py:107`; `AuditSink` is the new **write-side** contract. They are siblings, not replacements.)
- A new frozen `AuditEvent` dataclass lives in `backend/app/modules/audit/events.py` (or co-located in `audit/service.py` — Claude's discretion at plan time). Fields mirror today's `log_action()` parameter surface 1:1: `user_id: uuid.UUID`, `action: str`, `resource_type: str`, `resource_id: uuid.UUID | None`, `details: dict | None`, `ip_address: str | None`. No new fields, no scope creep — this is a transport refactor, not an event-schema expansion (per REQUIREMENTS.md "Out of Scope: No new audit event types").
- A new `DefaultAuditSink` lives in `backend/app/platform/extensions/defaults.py` alongside `DefaultAuditExtension`/etc. Its `emit()` body is the existing `log_action()` logic verbatim (build `AuditLog`, `session.add(entry)` — no commit). The existing `log_action()` symbol in `backend/app/modules/audit/service.py` is preserved as the in-process call site that `DefaultAuditSink.emit()` delegates to (option **a** from AUDIT-02), but no application code outside `DefaultAuditSink` calls it directly.
- A new typed accessor `get_audit_sinks() -> list[AuditSink]` lives in `backend/app/platform/extensions/__init__.py`, mirroring the existing `get_audit_extension()` / `get_branding_extension()` / `get_identity_extension()` pattern verbatim. It returns `_extensions["audit_sinks"]` if present, else `[DefaultAuditSink()]`. Community deployments always have exactly one sink (the default); enterprise overlays append.
- A new module-level facade `await audit_emit(session, event)` (or `audit_service.emit(...)` — name finalized at plan time) lives in `backend/app/modules/audit/service.py`. It is the single function the 65 (now-refactored) call sites call. It loops `for sink in get_audit_sinks(): try: await sink.emit(session, event); except Exception: structlog.exception(...)` — per-sink try/except with structlog.exception() logging. The default community sink itself does NOT swallow exceptions internally — only the facade does — so existing behavior where DB constraint violations surface during `session.flush()` (NOT during `session.add()`) is unchanged.
- All 65 `await log_action(...)` call sites in 19 files are mechanically rewritten to `await audit_emit(session, AuditEvent(...))` (or equivalent — exact name picked at plan). Every one of them lives in an already-async function (verified during scout); no function signatures change.
- A new fixture-based extension test verifies AUDIT-04 end-to-end: a test sink class implementing `AuditSink` is registered by directly appending to `_extensions["audit_sinks"]` (mirrors Phase 220 D-04 registry-level pattern), a representative call site is exercised, and the test asserts that BOTH `DefaultAuditSink` (writes its `audit_logs` row) AND the fixture sink (records the event in an in-memory list) received the same event. Test lives in `backend/tests/test_audit_sink.py` (new file) or extends `backend/tests/test_audit.py` if a clean slot exists at plan time.
- The existing audit test suite (queries, exports, RBAC, search) passes unchanged — this is a pure transport refactor below the public-surface line.

**In scope:**
- New `AuditSink` Protocol in `backend/app/platform/extensions/protocols.py` (`async def emit(session, event) -> None`).
- New `AuditEvent` frozen dataclass with the 6 fields matching today's `log_action()` parameter surface.
- New `DefaultAuditSink` in `backend/app/platform/extensions/defaults.py` whose `emit()` delegates to the existing `log_action()` (option **a** from AUDIT-02).
- New `get_audit_sinks() -> list[AuditSink]` typed accessor in `backend/app/platform/extensions/__init__.py`, mirroring `get_audit_extension()` shape.
- New `audit_emit(session, event)` facade in `backend/app/modules/audit/service.py` that loops registered sinks with per-sink try/except + `structlog.exception()`.
- Mechanical rewrite of 65 `log_action(...)` call sites across 19 files to `audit_emit(...)` (call signature change: positional/keyword args → single `AuditEvent` instance).
- New fixture-based test in `backend/tests/` registering a second `AuditSink` via direct `_extensions["audit_sinks"]` append, asserting AUDIT-04 end-to-end with both default and fixture sinks receiving the same event.
- Preservation test: existing audit-related tests pass without modification (AUDIT-05).
- Sink-failure regression test: a sink that raises does NOT cause the surrounding async business operation to roll back; the failure is logged via `structlog.exception()` (AUDIT-03).

**Out of scope:**
- Any new audit event types or fields (REQUIREMENTS.md "Out of Scope" — `AuditEvent` mirrors today's surface 1:1).
- Audit-export overlay implementation (`geolens-enterprise/audit_export/` — that's AUDIT-FUTURE-01, builds on this seam).
- AuditSink advanced semantics: back-pressure, batching, ordering across sinks, durable queues, retry, async fan-out (REQUIREMENTS.md "Out of Scope").
- Sync emit support — Protocol is async-only.
- Removing the `log_action()` symbol from `backend/app/modules/audit/service.py` (option **b** from AUDIT-02 was rejected; the symbol stays as `DefaultAuditSink.emit()`'s implementation detail).
- Compliance reporting, retention/rotation policy changes (REQUIREMENTS.md "Out of Scope").
- Tenant scoping, IdP changes (REQUIREMENTS.md "Out of Scope").
- AWS Marketplace / `BillingExtension` work (Phase 223).
- Any change to `AuditExtension.get_export_formats()` or the read-side audit query/export endpoints — they keep working as-is.

</domain>

<decisions>
## Implementation Decisions

### Sink contract & event shape
- **D-01: `AuditSink` is a new Protocol in `backend/app/platform/extensions/protocols.py`, sibling to (NOT replacement for) `AuditExtension`.** Signature: `async def emit(self, session: AsyncSession, event: AuditEvent) -> None`. Marked `@runtime_checkable`, matching the existing `BrandingExtension`/`AuditExtension`/`AuthExtension` pattern. Imports `AsyncSession` from `sqlalchemy.ext.asyncio` and `AuditEvent` (forward-ref or local import) — Claude's discretion at plan time on the exact import shape to avoid circulars (the existing `protocols.py` docstring says "Uses only stdlib types to avoid circular imports with domain models" — planner verifies whether `AsyncSession` import here causes any cycle; if so, fall back to `session: object` typed and runtime-cast inside `DefaultAuditSink`).

  Rationale: AUDIT-01 explicitly names the file. The existing `AuditExtension` is read-side only (`get_export_formats() -> list[str]`); it's consulted at `backend/app/modules/audit/router.py:107` for export-format gating. The write-side concern (event emission) is orthogonal — adding `emit()` to `AuditExtension` would conflate two contracts that overlays will want to implement independently (a SIEM streamer doesn't add export formats; a CSV exporter doesn't subscribe to writes). Two protocols, two slots, two accessors.

- **D-02: `AuditEvent` is a frozen `@dataclass(frozen=True)` with the six fields mirroring today's `log_action()` parameter surface 1:1.** Fields:
  ```python
  @dataclass(frozen=True)
  class AuditEvent:
      user_id: uuid.UUID
      action: str
      resource_type: str
      resource_id: uuid.UUID | None = None
      details: dict | None = None
      ip_address: str | None = None
  ```
  Lives in `backend/app/modules/audit/events.py` (new file) — Claude's discretion at plan time to co-locate in `service.py` if planner prefers minimal new files. Frozen so sinks cannot mutate the event between subscribers; default values match `log_action()`'s signature exactly so the call-site rewrite is a 1:1 wrap.

  Rationale: a typed event keeps the Protocol surface minimal (`emit(session, event)` — two args forever) and lets future fields be added by extending `AuditEvent` without touching every sink signature. Dataclass over Pydantic because (a) it's hot-path: `audit_emit` is called potentially thousands of times/sec under load, dataclass instantiation is cheaper, (b) we don't need validation — call sites are internal/trusted, (c) keeps `protocols.py` light. No `details` validation — it's free-form `dict | None`, same as today.

### Sync vs async
- **D-03: `AuditSink.emit()` is async-only.** No sync overload, no sync facade. All 65 existing `log_action()` call sites are already in async functions (router endpoints, async service methods, Celery tasks running under `asyncio.run`). Async also leaves the door open for an enterprise overlay's `emit()` to do non-blocking I/O (HTTP POST to a SIEM, S3 PutObject) without blocking the request thread.

  Rationale: zero migration cost (async `audit_emit` drops in everywhere), no architectural debt, no sync/async-bridge complexity. Claude's call to make per the STATE.md design-decision list — also confirmed by the audit doc framing it as a forward-compatibility concern.

### log_action() fate (AUDIT-02 a vs b)
- **D-04: `log_action()` becomes `DefaultAuditSink.emit()`'s implementation body — option (a) from AUDIT-02.** The symbol `log_action` in `backend/app/modules/audit/service.py` is **preserved** as a private/internal helper that `DefaultAuditSink.emit()` calls. Application code (the 65 call sites) is rewritten to call `audit_emit(...)` instead. After this phase, `log_action()` has exactly **one caller** in production code: `DefaultAuditSink.emit()`.

  Rationale (vs option b — full removal): option (a) keeps the row-write logic byte-identical to today, satisfying AUDIT-05 ("no row-count or row-content drift") with the smallest possible diff to the row-construction code. It also lets the planner do the call-site rewrite as a single `find/replace` pass without rewriting the row-construction logic in two places. Option (b) would require either (i) inlining the AuditLog construction inside `DefaultAuditSink.emit()` (duplicating the field list and any future field additions in two places if anyone restores `log_action`) or (ii) deleting `log_action` entirely and putting the row-construction inside `DefaultAuditSink` — which is functionally identical to (a) but with one extra symbol-rename commit and no semantic benefit. Option (a) is the smallest-diff path that satisfies AUDIT-02's "either" clause.

- **D-05: The `log_action()` signature stays unchanged.** Same `(session, user_id, action, resource_type, resource_id, details, ip_address)` keyword/positional surface. `DefaultAuditSink.emit()` unpacks the `AuditEvent` and calls `await log_action(session, user_id=event.user_id, action=event.action, ...)`. No new parameters, no rename, no `_log_action` privatization.

  Rationale: any rename or signature change cascades into the 65 call sites Phase 222 is supposed to consolidate. Stability of `log_action()` is the cheapest correctness contract.

### Sink-failure semantics (AUDIT-03)
- **D-06: A single module-level facade `audit_emit(session, event)` in `backend/app/modules/audit/service.py` is the only function the 65 call sites call.** It loops registered sinks and wraps each individual sink's `emit()` in try/except. Pseudocode:
  ```python
  async def audit_emit(session: AsyncSession, event: AuditEvent) -> None:
      for sink in get_audit_sinks():
          try:
              await sink.emit(session, event)
          except Exception:
              logger.exception(
                  "Audit sink raised; suppressing per AUDIT-03",
                  sink=type(sink).__name__,
                  action=event.action,
                  resource_type=event.resource_type,
              )
  ```
  Final function name (`audit_emit` vs `emit_audit` vs `audit_service.emit`) is Claude's discretion at plan time — the contract is a single-function facade, not the spelling.

  Rationale: per-sink try/except inside the facade means (a) the default community sink writes its `audit_logs` row even if a downstream enterprise sink fails, and vice-versa, (b) the call sites stay clean — no try/except boilerplate at any of the 65 sites, (c) the `structlog.exception()` log line gives operators visibility on failed emits without poisoning the business operation. AUDIT-03's literal text says "sink failures are swallowed and logged via `structlog.exception()` but do not propagate" — D-06 is exactly that.

- **D-07: The default community sink does NOT swallow exceptions internally.** Exceptions from `session.add()` (rare — typically only on type errors) or constraint validation will propagate out of `DefaultAuditSink.emit()` and be caught by the facade's try/except. This preserves today's behavior where misshapen audit log entries surface during the surrounding `session.flush()`/`session.commit()` rather than being silently dropped at construction time.

  Rationale: today's tests assert constraint behavior (FK to users, NOT NULL on action) by relying on `session.flush()` raising. If `DefaultAuditSink.emit()` swallowed internally, those tests would silently pass with no row written — semantic regression. Letting the facade swallow at the per-sink boundary preserves the "default sink behaves like today's `log_action()`" contract while making the facade the single sink-failure-isolation point.

- **D-08: Sink-failure scope is per-emit, not per-transaction.** The facade loops all sinks for ONE event; if any sink fails, the others still run. The failed sink does NOT prevent the next `audit_emit()` call (later in the same request) from invoking that same sink again. Phase 222 does NOT introduce circuit-breaking, sink-quarantine, or sink-disable-on-N-failures behavior — that's REQUIREMENTS.md "Out of Scope" advanced-semantics territory.

  Rationale: the simplest implementation that satisfies AUDIT-03. Operators looking for circuit-breaking can build it inside their own sink's `emit()` body; core stays unopinionated.

### Multi-sink subscription mechanism (AUDIT-04)
- **D-09: Registry shape is a list at `_extensions["audit_sinks"]: list[AuditSink]`.** Community deployments boot with this slot containing exactly one sink — `[DefaultAuditSink()]`. Enterprise overlays append additional sinks during their `register_extensions(registry)` call:
  ```python
  # In geolens-enterprise/audit_export/__init__.py (deferred phase, illustrative)
  def register_extensions(registry: dict[str, object]) -> None:
      sinks = registry.setdefault("audit_sinks", [DefaultAuditSink()])
      sinks.append(S3AuditSink(...))
      sinks.append(SyslogAuditSink(...))
  ```
  Initialization timing: the default sink is registered during application startup *before* `load_extensions()` runs (so overlays append rather than displace). Implementation choice for the planner: either (a) a `_init_default_sinks()` step before `load_extensions()` in `app/api/main.py` startup, OR (b) `get_audit_sinks()` returns `[DefaultAuditSink()]` when the slot is missing (lazy default). Recommendation: **option (b) — lazy default in the accessor, mirrors `get_audit_extension()` exactly** and avoids ordering dependencies.

  Rationale: the existing extension registry is single-slot for `branding`, `audit`, `auth`, `identity` (one extension per slot, last-write-wins). Audit sinks are fundamentally different: a deployment can want `DefaultAuditSink` (DB row) AND an `S3AuditSink` (export streaming) simultaneously — they don't compete for a slot, they coexist. List-based subscription matches the AUDIT-04 contract literally ("subscribe additional sinks") and is the mental model audit-export overlays will expect.

- **D-10: `get_audit_sinks() -> list[AuditSink]` typed accessor lives in `backend/app/platform/extensions/__init__.py`.** Implementation:
  ```python
  def get_audit_sinks() -> list[AuditSink]:
      sinks = _extensions.get("audit_sinks")
      if sinks is None:
          return [DefaultAuditSink()]
      return list(sinks)  # defensive copy
  ```
  Pattern matches `get_audit_extension()`/`get_branding_extension()`/`get_auth_extension()`/`get_identity_extension()` — same shape, same default-fallback, same return-by-value-list semantics.

  Rationale: identical pattern means zero new mental load for downstream readers. The defensive `list(...)` copy stops a sink from accidentally mutating the registry mid-iteration.

- **D-11: Default sink instance is created fresh on each accessor call when the slot is missing (i.e., community).** The community case path (`return [DefaultAuditSink()]`) instantiates a new default sink object per call. `DefaultAuditSink` is stateless (`emit()` constructs an `AuditLog` row from the event and adds it to the passed-in session — no instance state), so per-call instantiation has no observable effect; cost is negligible. When enterprise overlays register, the slot is populated once at startup and `get_audit_sinks()` returns the persistent list. Mirrors `get_audit_extension()` exactly.

  Rationale: zero-state sinks make the lifetime question moot; following the exact existing pattern minimizes risk.

### Test extensibility verification (AUDIT-04)
- **D-12: AUDIT-04 is verified end-to-end via a fixture-based test sink, registered by directly appending to `_extensions["audit_sinks"]` (no entry-point round-trip).** Test pattern mirrors Phase 220 D-04 (registry-level simulation in single pytest session). The test:
  1. Setup: import `_extensions` from `app.platform.extensions`. Create a `FixtureSink` class implementing `AuditSink` whose `emit()` appends `event` to an instance-level `received: list[AuditEvent]`. Append the fixture sink to `_extensions["audit_sinks"]` (initialize the slot to `[DefaultAuditSink(), fixture_sink]` to ensure the default is also present — this also implicitly tests the multi-sink loop ordering in the facade).
  2. Exercise: trigger one representative call site that emits an audit event (Claude's discretion at plan time — likely a TestClient call to a known endpoint that emits a single deterministic event, e.g., `POST /admin/users` for a `user.create` event).
  3. Assert: (a) the `audit_logs` table contains exactly one new row matching the expected `action`/`resource_type`/`resource_id` (proves DefaultAuditSink ran), (b) `fixture_sink.received` contains exactly one `AuditEvent` whose fields match (proves enterprise-overlay-shape end-to-end). No alembic, no docker-compose, no entry-point manipulation — pure registry.
  4. Teardown: `_extensions["audit_sinks"]` restored (or the slot deleted if it was originally absent — test bookkeeps the pre-test snapshot).

- **D-13: AUDIT-03 (sink-failure semantics) is verified by a separate test function in the same file: register a `RaisingSink` whose `emit()` raises `RuntimeError`, then exercise the same call site, assert (a) the surrounding business operation succeeds (e.g., the user was created), (b) the `audit_logs` row was written by `DefaultAuditSink` (so the raising sink didn't poison the iteration), (c) the request did NOT 500.** Test additionally asserts the exception was logged (planner picks the assertion mechanism: `caplog`, `structlog.testing.capture_logs`, or simply trusting the structlog config — Claude's discretion).

  Rationale: a separate test makes each requirement's assertion crystal-clear. AUDIT-03 says "is not rolled back" — the test asserts both halves: business op succeeds AND default sink wrote.

- **D-14: AUDIT-05 (preservation) is verified by relying on the existing audit test suite passing without modification.** Phase 222 does NOT add a new "preservation test" beyond running `pytest backend/tests/test_audit*.py` (and any other test that references audit_logs). The literal AUDIT-05 contract is "existing tests pass without modification" — running them green is the verification. Planner will document this in the plan's verification step.

  Rationale: a "deterministic-workload row count" test would be net-new infrastructure for a refactor that's already covered by the existing suite. The existing tests ARE the deterministic workload; they're the expected-row-set assertions; if the refactor preserves behavior, they pass.

### Call-site rewrite mechanics
- **D-15: The 65 call sites are rewritten in a single mechanical pass, not split across plans.** Each rewrite is purely local: `await log_action(session, user_id=X, action="A", ...)` becomes `await audit_emit(session, AuditEvent(user_id=X, action="A", ...))` (or whatever the final facade name resolves to). Same arg values, wrapped in `AuditEvent(...)` constructor. Imports change from `from app.modules.audit.service import log_action` to `from app.modules.audit.service import audit_emit, AuditEvent` (or `audit_emit` + `from app.modules.audit.events import AuditEvent` if D-02 takes the new-file path).

  Rationale: 65 sites x 19 files is mechanical scope; splitting it across plans only buys risk (partial-rewrite intermediate states where some sites use the new facade and others use `log_action()` directly). One plan, one PR-equivalent commit cluster, atomic.

- **D-16: No call-site behavior changes.** Same arguments in, same audit_logs row out, same async-context, same transaction, same FK references. The rewrite is a pure transport change. No new fields populated, no fields dropped, no fields renamed in the call args. If a call site today passes `details={"foo": 1}`, after rewrite it still passes the same dict via `AuditEvent(details={"foo": 1})`.

- **D-17: One ingest-task call site (`backend/app/processing/ingest/tasks_common.py:929`) lives in a Celery task that imports `log_action` lazily inside the function body to avoid module-load circularity.** The rewrite preserves the lazy import pattern: `from app.modules.audit.service import audit_emit, AuditEvent` stays inside the function. Planner verifies the existing `from app.modules.audit.service import log_action` at lines 285, 318, 357 (in the same file) and 846 are all lazy imports — if any are top-of-file imports, they get moved to lazy if the new audit_emit module-level import causes a cycle.

  Rationale: scout caught this inline-import idiom; preserving it avoids surprise import-cycle regressions.

### Out-of-scope guards (locked from REQUIREMENTS.md)
- **D-18: `AuditExtension.get_export_formats()` is NOT modified.** It's the read-side contract used by `audit/router.py:107` for export-format gating. Phase 222 only adds the write-side `AuditSink` Protocol and leaves `AuditExtension` untouched.

- **D-19: `_extensions["audit"]` (the existing single-slot) is NOT repurposed.** It holds the `AuditExtension` (read-side). The new write-side uses a brand-new slot `_extensions["audit_sinks"]` (plural) — no key collision possible.

### Claude's Discretion
- **AuditEvent location** — `backend/app/modules/audit/events.py` (new file) vs co-located in `audit/service.py`. Recommendation: new file when planner finds the existing `service.py` is already large; otherwise co-locate. Either is fine — the import path is what matters for downstream agents.
- **Facade function name** — `audit_emit`, `emit_audit`, `audit_service.emit`. Recommendation: `audit_emit` (mirrors `log_action`'s underscored style; module-level free function matches `log_action`'s shape; importable as `from app.modules.audit.service import audit_emit`). Final name is planner discretion.
- **`AsyncSession` import in `protocols.py`** — verify whether importing `AsyncSession` at the protocols module level introduces circulars (existing `protocols.py` docstring claims "stdlib only"). If so, fall back to `session: object` typed in the Protocol body and runtime-cast inside `DefaultAuditSink`. Either is acceptable; choose the path that keeps the import graph clean.
- **Test file location** — `backend/tests/test_audit_sink.py` (new) vs extending `backend/tests/test_audit.py`. Recommendation: new file when the new test surface is sizable enough to warrant its own module (likely yes — D-12 + D-13 + D-14 verification all live there); keep it close to the existing audit tests for discoverability.
- **Whether `_init_default_sinks()` is needed** — D-09 / D-11 recommend lazy-default in the accessor (no init step). Planner can choose eager init in `app/api/main.py` startup if there's a strong reason; otherwise stick with the accessor-default pattern for consistency.
- **Lazy-import preservation** — verify which of the 4-5 lazy `log_action` imports in `processing/ingest/tasks_common.py` need to remain lazy; planner makes the call after grepping the import graph.
- **Per-sink logging field structure** — when the facade swallows a sink failure, what context fields go into `structlog.exception()`? Recommendation: `sink_name`, `action`, `resource_type`, `resource_id`. Planner finalizes.
- **Whether the plan is one PR or multiple** — recommendation: single plan with sub-tasks (Protocol → Default → accessor → facade → call-site rewrite → tests). 19 files affected by the call-site rewrite is the meatiest commit; everything else is small additive scaffolding. Planner finalizes the wave/plan partition.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Source spec — the audit doc that motivates this work
- `docs-internal/audits/oc-separation-audit-20260430.md` §2 (Seam #3) — the row noting "no write-side `AuditSink.emit()` Protocol; now load-bearing — `log_action` grew 19 → 76 call sites in v13.2; every new sink will multiply." (Note: revision header at line 5 corrects the count to **65** across **19 files** — that's the canonical figure Phase 222 uses; the 76 in earlier revisions is superseded.)
- `docs-internal/audits/oc-separation-audit-20260430.md` §5 (Coupling Health, log_action regression at line 224) — explains the +242% regression and frames the fix: "introduce the `AuditSink.emit()` Protocol so the 65 sites become a single hook."
- `docs-internal/audits/oc-separation-audit-20260430.md` §7 P1 row at line 262 — the explicit P1 prioritization that drove this milestone.

### Requirements / roadmap (the source of truth)
- `.planning/REQUIREMENTS.md` §AUDIT-01..05 — the five requirements this phase closes. AUDIT-02 is the "log_action becomes default sink body OR is removed" decision (D-04 picks option a). AUDIT-03 is the sink-failure semantics contract (D-06–D-08 pick the per-sink try/except + structlog facade). AUDIT-04 is the multi-sink subscription contract (D-09–D-12 pick list-based + fixture-based test). AUDIT-05 is the preservation contract (D-14: existing tests pass).
- `.planning/ROADMAP.md` §Phase 222 — goal statement + 5 success criteria. SC#1 (community-deployment row-count fidelity) maps to D-14; SC#2 (sink failure doesn't roll back business op) maps to D-06+D-13; SC#3 (enterprise overlay registers without core change) maps to D-09+D-12; SC#4 (no call site calls log_action() directly) maps to D-15+D-16; SC#5 (existing tests pass) maps to D-14 directly.
- `.planning/STATE.md` — confirms milestone state (v13.3 planning), Phase 222 first available, design questions enumerated (sync vs async; log_action fate; sink-failure semantics — Phase 222 CONTEXT D-03/D-04/D-06 close all three).
- `.planning/PROJECT.md` — milestone overview at "Current Milestone: v13.3 Boundary A+ Cleanup."

### Project / state — most-load-bearing upstream context
- `.planning/milestones/v13.1-phases/214-identity-protocol-extract/214-CONTEXT.md` — the canonical pattern for "extract a write-side Protocol, default in extensions/defaults.py, typed accessor in extensions/__init__.py, registered via geolens.extensions entry-point group." Phase 222 mirrors this verbatim for `AuditSink`. **Read in full.**
- `.planning/milestones/v13.1-phases/217-auth-saml-enterprise/217-CONTEXT.md` — D-13 (single-class dual-Protocol pattern) shows that an enterprise overlay can implement multiple Protocols on one class. Future audit-export overlay may use this same trick (one class implements both `AuditExtension` for export formats AND `AuditSink` for streaming) — Phase 222 leaves that door open by keeping the two Protocols sibling, not unified.
- `.planning/milestones/v13.2-phases/220-lifecycle-runbooks-and-preservation/220-CONTEXT.md` — D-04 (registry-level test pattern) is the test approach D-12/D-13 mirror. **Read for Pitfall 2/3/5 carry-forward** (module-level state surfaces, register_extensions idempotency, deferred imports for community-only test environments).
- `.planning/milestones/v13.2-phases/221-lifecycle-user-continuity-and-verification/221-CONTEXT.md` — D-05 (single-transaction model) and D-10 (audit_log seed pattern in tests) are reusable; the lifecycle test infrastructure that Phase 220+221 stood up is the natural place Phase 222's tests draw from.

### Code (where the new Protocol lands)
- `backend/app/platform/extensions/protocols.py` — current file: `BrandingExtension`, `AuditExtension`, `AuthExtension`. Phase 222 adds `AuditSink` here as a 4th Protocol (alongside the existing three). Existing pattern: `@runtime_checkable class X(Protocol): def method(...) -> ...:`. AUDIT-01 names this file explicitly.
- `backend/app/platform/extensions/defaults.py` — current file: `DefaultBrandingExtension`, `DefaultAuditExtension`, `DefaultAuthExtension`, `DefaultIdentityExtension`. Phase 222 adds `DefaultAuditSink` here. Pattern: simple class implementing the protocol method.
- `backend/app/platform/extensions/__init__.py` — current file with `_extensions: dict`, `_routers: list`, `_loaded: bool`, `load_extensions()`, typed accessors. Phase 222 adds `get_audit_sinks() -> list[AuditSink]` typed accessor (the only multi-instance accessor; existing four are single-instance). Implementation per D-10: returns `_extensions.get("audit_sinks") or [DefaultAuditSink()]`.

### Code (the facade and event dataclass land here)
- `backend/app/modules/audit/service.py` — current file with `log_action()` at line 49 (the function Phase 222 preserves as `DefaultAuditSink.emit()`'s body — D-04). Phase 222 adds `audit_emit(session, event)` facade in this file (D-06). Existing `log_action()`, `query_audit_logs()`, `stream_audit_logs()`, `_apply_filters()` stay untouched.
- `backend/app/modules/audit/events.py` — **new file** for `AuditEvent` frozen dataclass (D-02). Or co-located in `service.py` — Claude's discretion at plan time.
- `backend/app/modules/audit/models.py` — `AuditLog` ORM model. Phase 222 does NOT modify this. `DefaultAuditSink.emit()` continues to construct `AuditLog(...)` rows the same way `log_action()` does today.

### Code (the 65 call sites — to be rewritten)
- `backend/app/modules/admin/router.py` — 10 call sites (user.create at line 113, user.update at 213, user.deactivate at 243, user.convert_saml_to_local at 298, etc.). Highest-density file — exemplar for the rewrite pattern.
- `backend/app/modules/catalog/maps/router.py` — 9 call sites.
- `backend/app/modules/catalog/sources/router.py` — 7 call sites.
- `backend/app/modules/catalog/collections/router.py` — 5 call sites.
- `backend/app/modules/catalog/features/router.py` — 4 call sites.
- `backend/app/modules/catalog/datasets/api/router.py` — 4 call sites.
- `backend/app/modules/catalog/layers/router.py` — 4 call sites.
- `backend/app/modules/embed_tokens/router.py` — 3 call sites.
- `backend/app/modules/auth/router.py` — 3 call sites.
- `backend/app/modules/settings/router.py` — 3 call sites.
- `backend/app/modules/catalog/sources/stac_router.py` — 3 call sites.
- `backend/app/core/persistent_config.py` — 2 call sites.
- `backend/app/modules/catalog/datasets/api/router_metadata.py` — 2 call sites.
- `backend/app/modules/catalog/datasets/api/router_export.py` — 1 call site.
- `backend/app/modules/embed_tokens/admin_router.py` — 1 call site.
- `backend/app/processing/export/router.py` — 1 call site.
- `backend/app/processing/ingest/tasks_common.py` — 1 call site (with **lazy import** at lines 285, 318, 357, 846 — see D-17). **Verify lazy-import preservation here.**
- `backend/app/modules/audit/service.py` — `log_action()` defines itself; the file does NOT need rewriting.
- `backend/app/platform/config_ops/service.py` — 1 call site.
- **Total: 65 call sites in 19 files.** Phase 222 SC#4: "No call site in `backend/app/` calls `log_action()` directly — all 65 sites route through `get_audit_sink().emit()`." (Note: ROADMAP SC#4 wording assumes `get_audit_sink().emit()` singular — D-06 implements this via `audit_emit()` facade which iterates `get_audit_sinks()` plural. Equivalent contract; planner verifies the wording is updated in code/docs to match the implementation if needed.)

### Code (read-side audit, untouched but referenced)
- `backend/app/modules/audit/router.py:107` — `get_audit_extension().get_export_formats()` consumer. Phase 222 leaves this untouched. Establishes that `AuditExtension` (read-side) and `AuditSink` (write-side) are sibling Protocols — see D-01.

### Code (the test sink lands here)
- `backend/tests/test_audit_sink.py` — **new file** (recommended) for D-12 (multi-sink) + D-13 (sink-failure) + D-14 (preservation reference). OR extends `backend/tests/test_audit.py` if a clean home exists at plan time.
- `backend/tests/conftest.py` — global fixtures (DB session, TestClient, async fixtures). Phase 222 reuses; no new global fixture.
- `backend/tests/test_lifecycle.py` (Phase 220+221) — reference for the registry-level test pattern Phase 222's D-12 mirrors. **Read for fixture cleanup pattern (`_cleanup_lifecycle_rows`-style yield-finally) and module-level state restoration.**
- `backend/pyproject.toml` — `[tool.pytest.ini_options]` markers list (existing `lifecycle`, `perf`, `requires_ogr2ogr`, `architecture`). Phase 222 does NOT add a new marker — the audit-sink tests run by default in CI with no marker.

### Code (enterprise overlay — outside repo, future consumer)
- `~/Code/geolens-enterprise/geolens_enterprise/__init__.py` — `register_extensions(registry)`. Future audit-export overlay (AUDIT-FUTURE-01, deferred) appends sinks here:
  ```python
  sinks = registry.setdefault("audit_sinks", [DefaultAuditSink()])
  sinks.append(S3AuditSink(...))
  ```
  Phase 222 does NOT modify the enterprise overlay; the seam Phase 222 creates is the contract the overlay will use. **Read for `register_extensions` shape and entry-point structure.**

### CLAUDE.md operational notes
- `CLAUDE.md` (project-local + user-global) — `feedback_run_ci_local_first.md` (run lint/typecheck/tests locally before pushing), `project_geolens_io_actions_billing.md` (free-tier Actions minutes routinely exhausted; prefer PR path), `feedback_no_blanket_add_planning.md` (no `git add -fA .planning/<dir>/`), `feedback_audit_sibling_repos_at_milestone_close.md` (check `~/Code/geolens-enterprise` at milestone close — relevant when v13.3 ships).

### Existing reusable extension patterns (don't reinvent)
- The four-Protocol pattern (Protocol → Default → typed accessor → registry slot) is fully exercised by `BrandingExtension`, `AuditExtension`, `AuthExtension`, `IdentityExtension`. Phase 222's `AuditSink` follows this pattern with **one departure**: it's a list at `_extensions["audit_sinks"]` instead of a single object at `_extensions["audit"]`. The accessor signature reflects this: `get_audit_sinks() -> list[AuditSink]` instead of `get_audit_extension() -> AuditExtension`. **Do NOT introduce a new "registry shape abstraction" to unify single and list slots — YAGNI; one departure for one good reason.**

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Protocol scaffolding (`backend/app/platform/extensions/protocols.py`)** — three existing Protocols (`BrandingExtension`, `AuditExtension`, `AuthExtension`) demonstrate the exact pattern Phase 222 follows for `AuditSink`. Plus `IdentityExtension` (in `app/core/identity.py`) shows the async-method pattern.
- **Default-class scaffolding (`backend/app/platform/extensions/defaults.py`)** — four existing defaults (`DefaultBranding/Audit/Auth/IdentityExtension`) demonstrate the body shape. `DefaultIdentityExtension.resolve_identity_from_token()` shows the async-default pattern that `DefaultAuditSink.emit()` mirrors.
- **Typed-accessor scaffolding (`backend/app/platform/extensions/__init__.py`)** — four existing accessors (`get_branding_extension`, `get_audit_extension`, `get_auth_extension`, `get_identity_extension`) demonstrate the slot-lookup-or-default pattern. `get_audit_sinks()` is a near-clone with a list return type and a list default.
- **`log_action()` in `backend/app/modules/audit/service.py:49`** — preserved verbatim as `DefaultAuditSink.emit()`'s implementation body (D-04). The session-add-no-commit semantics are exactly what every call site expects.
- **`AuditLog` ORM (`backend/app/modules/audit/models.py`)** — unchanged; rows are constructed the same way in the new sink.
- **`structlog.stdlib.get_logger(__name__)` pattern in `backend/app/platform/extensions/__init__.py:30`** — the facade's swallowing log line uses this same import shape (D-06).
- **Phase 220 test pattern in `backend/tests/test_lifecycle.py`** — registry clear/restore yield-finally fixture, fixture-based extension registration via direct dict manipulation. Phase 222's `test_audit_sink.py` mirrors.
- **Phase 217 SAML overlay's `register_extensions()` call shape** — populates `_extensions["auth"]`, `_extensions["identity"]`, etc. The future audit-export overlay's append-to-list pattern is a natural extension.

### Established Patterns
- **One Protocol per write-side concern** — branding, audit (read), auth, identity each get their own slot. `AuditSink` follows this convention; do not extend `AuditExtension` with `emit()` (D-01 rationale).
- **Default in `defaults.py`, NOT inline in `__init__.py`** — keeps the registry module focused on lookup logic; default classes are testable in isolation.
- **Accessor returns either registered or default — never `None`** — call sites never null-check. `get_audit_sinks()` follows: returns `[DefaultAuditSink()]` when slot is missing.
- **Lazy import inside hot-path functions** — `processing/ingest/tasks_common.py` imports `log_action` lazily inside Celery task functions (lines 285, 318, 357, 846) to avoid import-cycle risk. Phase 222's call-site rewrite preserves this idiom for the corresponding `audit_emit` import.
- **`structlog` for operational warnings/errors** — used everywhere in `extensions/`, `core/`, etc. The facade's swallowing log line uses `logger.exception(...)` with structured fields (`sink`, `action`, `resource_type`).
- **`runtime_checkable` Protocol** — all three existing Protocols are `@runtime_checkable`; `AuditSink` is too. Lets a future `isinstance(x, AuditSink)` check work for sanity assertions in tests.

### Integration Points
- **The 65 call sites all sit in already-async functions.** Verified by scout: routers (FastAPI async), service methods (async-decorated), Celery tasks (running under `asyncio.run`). No synchronous call site exists. The async `audit_emit` facade drops in everywhere.
- **Every call site passes a session** — either a request-scoped `db: AsyncSession = Depends(get_db)` (routers) or an explicitly-acquired session in service code/tasks. The `audit_emit(session, event)` facade keeps session-passing explicit; no global session lookup.
- **Session lifecycle is unchanged** — `audit_emit` (and `DefaultAuditSink.emit()`) call `session.add(entry)` only; the caller's outer transaction continues to handle `flush`/`commit`. Sink failure (per D-08) does not affect the caller's transaction except for whatever sink-internal state mutations the failing sink already made (which is its own bug, not Phase 222's concern).
- **Audit row contract is the FK to `users.id`** — every `AuditEvent` has a `user_id`, every existing call site passes one. `users.id` is durable per Phase 221 D-06; FK survives any user-attribute changes. No new constraint, no new column.
- **CI test job needs no new amendment** — `geolens-enterprise` overlay is already installed in CI per Phase 220 D-06; Phase 222's tests inherit. The audit-sink tests do NOT require the overlay (they register a fixture sink directly), so they run on fork PRs too.
- **No frontend impact** — Phase 222 is pure backend. `frontend/src/api/...` consumers are unaffected.

### Risk surfaces
- **Import cycle on `AsyncSession` import in `protocols.py`** — the existing `protocols.py` docstring explicitly says "stdlib only to avoid circular imports." Adding `from sqlalchemy.ext.asyncio import AsyncSession` here may or may not cycle (likely not — sqlalchemy doesn't import from app). Planner verifies; fallback per D-01: type the param as `object` and runtime-cast in `DefaultAuditSink`.
- **Lazy-import preservation in `tasks_common.py`** — D-17. If the planner moves the import to module-top accidentally, expect a Celery task collection-time circular import. Verify all four lazy-import sites in that file.
- **65-site mechanical rewrite has rote-error potential** — fat-finger renames, missed sites, args dropped during the wrap into `AuditEvent(...)`. Mitigations: (a) a single `grep -r "log_action(" backend/app/` post-rewrite must return ZERO matches outside `audit/service.py` (the function definition itself + the `DefaultAuditSink.emit()` delegation); (b) the planner adds a `make audit-sink-discipline` (or similar) target that asserts this invariant; (c) existing audit tests (AUDIT-05) catch any semantic drift from missed call-site edits.
- **Sink-failure tests must not pollute the `_extensions` registry across test functions** — pytest fixture must restore `_extensions["audit_sinks"]` to its pre-test state in `finally`. Pattern from Phase 220 D-04 / `test_lifecycle.py` is the reference.
- **The default sink's `_extensions["audit_sinks"]` slot is missing in community by default** (per D-09 / D-11 — lazy default in accessor). Tests that exercise the AUDIT-04 fixture sink path MUST initialize the slot to `[DefaultAuditSink(), fixture_sink]` explicitly so both sinks run. If the test only appends `fixture_sink` to a missing slot, only `fixture_sink` is in the registry post-init and the AUDIT-05 default-row assertion will fail. Planner documents the test-fixture pattern explicitly.
- **`structlog.exception()` in the facade emits a log line per failed sink per emit** — under heavy concurrent load with a flapping enterprise sink, log volume can spike. Phase 222 ships zero rate-limiting; this is acceptable for v13.3 (REQUIREMENTS.md "No back-pressure / rate-limiting" out-of-scope), but document it as a known operational characteristic for future-phase awareness.
- **Future enterprise overlay registration ordering** — Phase 222 says "default registered first, overlays append." If a future overlay's `register_extensions()` accidentally OVERWRITES `_extensions["audit_sinks"]` (e.g., `registry["audit_sinks"] = [MySinks(...)]` instead of `setdefault + append`), the community default disappears and AUDIT-05 fails for that deployment. Phase 222 cannot prevent this in the contract (overlays are out-of-repo); document it in the canonical_refs note and rely on overlay-side review. The `setdefault + append` idiom is the documented pattern.
- **Free-tier Actions billing exhaustion (project memory)** — relevant when Phase 222 ships. Phase 222 should run lint/typecheck/tests locally before pushing per `feedback_ci_local_first.md`; prefer PR path for verification per `project_geolens_io_actions_billing.md`.

</code_context>

<specifics>
## Specific Ideas

- **Two-Protocol coexistence: `AuditExtension` (read) + `AuditSink` (write)** — D-01. Don't unify; future audit-export overlays will likely implement BOTH on a single class (Phase 217 D-13 dual-Protocol pattern), but the Protocol contracts stay separate so the responsibilities are crystal-clear.
- **`log_action()` becomes `DefaultAuditSink.emit()`'s body, not removed** — D-04. Option (a) from AUDIT-02. Smallest diff; preserves audit_logs row construction logic in one place.
- **Async-only emit; no sync overload** — D-03. All 65 sites already async; no sync/async-bridge complexity.
- **Single facade `audit_emit(session, event)` is THE emit path** — D-06. Per-sink try/except + `structlog.exception()`. Default sink does NOT swallow internally.
- **List-based registry: `_extensions["audit_sinks"]: list[AuditSink]`, default registered lazily by the accessor** — D-09 + D-11. Mirrors `get_audit_extension()` shape; community has exactly one sink in the list.
- **Fixture-based test sink registers via direct `_extensions["audit_sinks"]` append, not entry_points** — D-12. Mirrors Phase 220 lifecycle test pattern; entry_points round-trip already covered by SAML overlay tests.
- **65-site rewrite is a single mechanical pass** — D-15. Atomic; no intermediate state where some sites use the new facade and others use `log_action()` directly.
- **Preserve lazy-import idiom in `processing/ingest/tasks_common.py`** — D-17.
- **AUDIT-05 verification is "existing tests pass"** — D-14. No new "deterministic-workload" test infrastructure; existing audit tests ARE the deterministic workload.
- **`AuditEvent` is a frozen dataclass, not Pydantic** — D-02. Hot path; no validation needed; minimal protocol surface.

</specifics>

<deferred>
## Deferred Ideas

- **Audit-export overlay implementation (`geolens-enterprise/audit_export/`)** — AUDIT-FUTURE-01. Builds on the seam Phase 222 delivers. Streams audit events to S3/SIEM/syslog and renders signed CSV/JSON exports. Lives in the enterprise repo, not v13.3.
- **Compliance reporting** — AUDIT-FUTURE-02. Who-accessed-what dashboards, retention policies, SOC2-style report generation. Requires AuditSink + audit-export overlay + report-template engine.
- **AuditSink advanced semantics** — back-pressure, batching, ordering across sinks, durable queues, retry, async fan-out. Out of v13.3 per REQUIREMENTS.md "Out of Scope." If enterprise customers need batching/queuing, that lands inside the audit-export overlay's `emit()` body, not in core's facade.
- **Sync emit support** — out of v13.3. All current call sites are async; revisit only if a sync caller materializes (unlikely given the architecture).
- **`log_action()` symbol removal (option b from AUDIT-02)** — out of v13.3 per D-04 rationale. Option (a) was selected; option (b) becomes a future-cleanup ticket if a hygienic team wants to remove the now-internal helper. Cosmetic, not architectural.
- **Circuit-breaking / sink-quarantine on N consecutive failures** — D-08. Out of v13.3; build inside an overlay if needed.
- **New audit event types or fields** — REQUIREMENTS.md "Out of Scope." `AuditEvent` mirrors today's surface 1:1.
- **Audit-log retention/rotation policy changes** — REQUIREMENTS.md "Out of Scope." Compliance concern; Phase 222 preserves current behavior exactly.
- **Removing `AuditExtension` (read-side) entirely** — out of v13.3. It's the export-format gating contract used by `audit/router.py:107`; nothing about Phase 222 affects its purpose. Sibling, not replacement.
- **Doc/PR rename of "AuditSink" if terminology drifts** — AUDIT-01 names the Protocol `AuditSink`; ROADMAP SC#3 calls it `AuditSink`; STATE.md calls it `AuditSink`. Locked.
- **A unified registry-shape abstraction (single-vs-list slot polymorphism)** — out of v13.3. YAGNI; one departure for one good reason. Rebuild only if a third concern needs the same polymorphism.
- **`audit_emit` rename (e.g., `emit_audit_event`)** — Claude's discretion at plan time; not a deferred enhancement, just a naming microdecision.
- **Standalone `make audit-sink-discipline` linter target** — Recommended in code_context risk surfaces; planner picks whether to add (lightweight grep + assert) or skip and rely on test coverage.

</deferred>

---

*Phase: 222-audit-sink-protocol*
*Context gathered: 2026-04-30*
*Mode: --auto --chain (recommended-default decisions)*
