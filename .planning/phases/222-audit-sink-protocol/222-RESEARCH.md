# Phase 222: audit-sink-protocol - Research

**Researched:** 2026-04-30
**Domain:** Backend Python — structural typing (PEP 544 Protocol), extension/registration seam, mechanical 65-site call-rewrite, structlog facade
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Sink contract & event shape:**
- **D-01:** New `AuditSink` Protocol in `backend/app/platform/extensions/protocols.py` (sibling to existing `AuditExtension`, not replacement). Signature: `async def emit(self, session: AsyncSession, event: AuditEvent) -> None`. Marked `@runtime_checkable`.
- **D-02:** `AuditEvent` is a frozen `@dataclass(frozen=True)` with 6 fields mirroring `log_action()` parameter surface 1:1: `user_id: uuid.UUID`, `action: str`, `resource_type: str`, `resource_id: uuid.UUID | None = None`, `details: dict | None = None`, `ip_address: str | None = None`. Lives in `backend/app/modules/audit/events.py` (new file) — co-location in `service.py` is Claude's discretion.

**Sync vs async:**
- **D-03:** Async-only emit. No sync overload.

**`log_action()` fate (AUDIT-02 a vs b):**
- **D-04:** `log_action()` becomes `DefaultAuditSink.emit()`'s implementation body — option (a) from AUDIT-02. The symbol stays as an internal helper called only by `DefaultAuditSink`.
- **D-05:** `log_action()` signature stays unchanged.

**Sink-failure semantics (AUDIT-03):**
- **D-06:** A single module-level facade `audit_emit(session, event)` in `backend/app/modules/audit/service.py` is the only function the 65 call sites call. Per-sink try/except + `structlog.exception()` on failure.
- **D-07:** Default community sink does NOT swallow exceptions internally; only the facade does.
- **D-08:** Sink-failure scope is per-emit, not per-transaction. No circuit-breaking.

**Multi-sink subscription (AUDIT-04):**
- **D-09:** Registry shape is a list at `_extensions["audit_sinks"]: list[AuditSink]`. Default registered first (lazily by accessor), overlays append via `setdefault + append`.
- **D-10:** `get_audit_sinks() -> list[AuditSink]` typed accessor lives in `backend/app/platform/extensions/__init__.py`.
- **D-11:** Default sink instance created fresh on each accessor call when slot missing (community case).

**Test-extensibility verification:**
- **D-12:** AUDIT-04 verified end-to-end via fixture-based test sink registered by direct `_extensions["audit_sinks"]` append. Test exercises a representative call site, asserts BOTH `DefaultAuditSink` (writes audit_logs row) AND fixture sink (records event in list) received the same event.
- **D-13:** AUDIT-03 verified by separate test with a `RaisingSink` whose `emit()` raises; assert business op succeeds AND default sink wrote AND request did NOT 500.
- **D-14:** AUDIT-05 verified by existing audit test suite passing without modification.

**Call-site rewrite mechanics:**
- **D-15:** 65 call sites rewritten in single mechanical pass. `await log_action(session, user_id=X, ...)` → `await audit_emit(session, AuditEvent(user_id=X, ...))`.
- **D-16:** No call-site behavior changes (same args, same audit_logs row, same FK references).
- **D-17:** Preserve lazy-import idiom (4 lazy `log_action` imports — see Pitfall B for the corrected file paths).

**Out-of-scope guards:**
- **D-18:** `AuditExtension.get_export_formats()` is NOT modified.
- **D-19:** `_extensions["audit"]` (single-slot read-side) is NOT repurposed; new write-side uses brand-new slot `_extensions["audit_sinks"]` (plural).

### Claude's Discretion
- **`AuditEvent` location** — new file (`backend/app/modules/audit/events.py`) vs co-located in `service.py`. Recommendation: new file (recommended in this research — see Architecture Patterns §Recommended Project Structure).
- **Facade function name** — `audit_emit` recommended (mirrors `log_action`'s underscored style, importable as `from app.modules.audit.service import audit_emit`).
- **`AsyncSession` import in `protocols.py`** — verify whether importing at module level cycles. Recommended path: real import (no cycle predicted — see Pitfall A).
- **Test file location** — new `backend/tests/test_audit_sink.py` (recommended) vs extend `test_audit.py`.
- **Whether `_init_default_sinks()` is needed** — D-09/D-11 recommend lazy-default in accessor (no init step); use that.
- **Lazy-import preservation** — preserve the 3 sites in `auth/router.py` + 1 in `tasks_common.py` + 1 in `config_ops/service.py` (see Pitfall B).
- **Per-sink logging field structure** — recommended fields: `sink_name`, `action`, `resource_type`, `resource_id` (D-06).
- **Whether the plan is one PR or multiple** — recommended single plan with phased tasks (Protocol → Default → accessor → facade → 65-site rewrite → tests). See §Implementation Sequence.

### Deferred Ideas (OUT OF SCOPE)
- Audit-export overlay implementation (`geolens-enterprise/audit_export/`) — AUDIT-FUTURE-01.
- Compliance reporting — AUDIT-FUTURE-02.
- AuditSink advanced semantics: back-pressure, batching, ordering across sinks, durable queues, retry, async fan-out.
- Sync emit support.
- `log_action()` symbol removal (option b from AUDIT-02 — rejected).
- Circuit-breaking / sink-quarantine on N failures.
- New audit event types or fields. `AuditEvent` mirrors today's surface 1:1.
- Audit-log retention/rotation policy changes.
- Removing `AuditExtension` (read-side) entirely.
- AuditSink terminology rename.
- Unified registry-shape abstraction (single-vs-list polymorphism).
- `audit_emit` rename to `emit_audit_event`.
- Standalone `make audit-sink-discipline` linter target — recommended as **Claude's discretion** (this research recommends adding it; see §CI / Make Targets).

</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| AUDIT-01 | `AuditSink` Protocol in `backend/app/platform/extensions/protocols.py` with `emit(event)` covering today's `log_action()` parameter surface; `DefaultAuditSink` in `extensions/defaults.py` delegates to existing `audit_logs` table write. | Existing pattern verified at `protocols.py` (3 Protocols: `BrandingExtension`, `AuditExtension`, `AuthExtension`) and `defaults.py` (4 defaults). `log_action()` body verified at `audit/service.py:49-67` — `AuditLog(...)` construction + `session.add(entry)` only, no commit. Plan adds 4th Protocol + 5th default class following identical shape. |
| AUDIT-02 | All 65 `log_action()` emit sites in `backend/app/` route through `get_audit_sink().emit(...)` (or facade equivalent) rather than calling `log_action()` directly. `log_action()` either (a) becomes default-sink body or (b) is removed. **D-04 chooses (a).** | 65 sites verified via `grep -rn "log_action(" backend/app/ --include="*.py" \| wc -l` = 65. Per-file counts match CONTEXT.md exactly (admin/router.py 10, maps 9, sources 7, etc.). All 65 are `await log_action(...)` — verified async. |
| AUDIT-03 | Sink-failure semantics: a sink that raises does not break surrounding business op; failures logged via `structlog.exception()` but do not propagate. | Facade pattern (D-06) wraps each sink's `emit()` in per-sink try/except. `structlog.stdlib.get_logger(__name__)` import shape already used at `extensions/__init__.py:30`. AUDIT-03 verified end-to-end by `RaisingSink` test (D-13) — assert business op succeeds AND default sink wrote AND request not 500. |
| AUDIT-04 | Enterprise audit-export overlay can subscribe additional sinks (file, S3, SIEM, syslog) by registering `AuditSink` impl through `geolens.extensions` entry-point group, without core code change. Verified end-to-end via fixture-based test sink. | List registry shape (`_extensions["audit_sinks"]: list[AuditSink]`, D-09) supports multi-sink coexistence. Existing `_enterprise_audit_ext()` helper at `tests/test_audit.py:242-270` is the exact precedent for direct-`_extensions[...]` registration in tests. Phase 220 D-04 / `tests/test_lifecycle.py:466-484` (`saml_overlay_registered` fixture) is the canonical save/restore pattern Phase 222's test fixture mirrors. |
| AUDIT-05 | Existing audit behavior preserved — every event recorded today still recorded; existing tests pass without modification; no row-count or row-content drift on a deterministic test workload. | `DefaultAuditSink.emit()` delegates to unchanged `log_action()` (D-04, D-05). Existing test suite at `backend/tests/test_audit.py` (390 LOC, 13 tests covering create/filter/pagination/authz/export) is the deterministic workload (D-14). Plus 4 lifecycle tests in `test_lifecycle.py` and ~30+ tests across the suite that consume `log_action` indirectly. |

</phase_requirements>

---

## Project Constraints (from CLAUDE.md)

The repo `./CLAUDE.md` is **absent**; only the user-global `~/.claude/CLAUDE.md` applies. Active directives for this phase:

- **Version control:** Never indicate AI/Bot activity in commit messages.
- **Code style:** Prefer simple, readable code over clever abstractions. Follow existing project conventions when editing files.
- **Communication:** Direct and concise; ask before assuming.

From auto-memory `MEMORY.md`:
- **CI billing:** `feedback_run_ci_local_first.md` — run lint/typecheck/tests locally before pushing. `project_geolens_io_actions_billing.md` — free-tier Actions minutes routinely exhausted; prefer PR path.
- **Planning hygiene:** `feedback_no_blanket_add_planning.md` — never `git add -fA .planning/<dir>/`.
- **Sibling-repo audit at milestone close:** `feedback_audit_sibling_repos_at_milestone_close.md` — check `~/Code/geolens-enterprise` for unpushed commits tied to v13.3 phases.

---

## Summary

Phase 222 is a **transport refactor** with surgical scope: introduce a write-side `AuditSink` Protocol that 65 existing audit-emit sites flow through, leaving row construction byte-identical (D-04). Three new symbols ship in `backend/app/platform/extensions/{protocols,defaults,__init__}.py` (Protocol + default class + typed accessor), one new symbol in `backend/app/modules/audit/service.py` (`audit_emit` facade), and one new file `backend/app/modules/audit/events.py` (`AuditEvent` frozen dataclass). The 65 `await log_action(session, user_id=X, ...)` call sites become `await audit_emit(session, AuditEvent(user_id=X, ...))` in a single mechanical pass across 19 files. Two new tests in `backend/tests/test_audit_sink.py` verify AUDIT-03 (raising sink doesn't break business op) and AUDIT-04 (fixture sink registered via direct `_extensions["audit_sinks"]` append receives every event alongside `DefaultAuditSink`). AUDIT-05 verification is "existing audit test suite passes unchanged" — no new preservation tests authored.

Three precedents make this low-risk: (1) the four-Protocol pattern (`BrandingExtension`, `AuditExtension`, `AuthExtension`, `IdentityExtension`) is fully exercised in the same files, with one departure — `audit_sinks` is a `list[AuditSink]` slot, not a single object slot; (2) Phase 220+221's `tests/test_lifecycle.py` fixture-based registry-manipulation pattern is the verbatim model for `test_audit_sink.py`'s `_extensions["audit_sinks"]` save/restore; (3) the existing `_enterprise_audit_ext()` helper in `tests/test_audit.py:242-270` already demonstrates direct-`_extensions[...]` manipulation under the existing `_extensions["audit"]` slot — Phase 222's fixture is the same shape against the new `audit_sinks` (plural) slot.

**Primary recommendation:** Single plan with 7 atomic task waves: (1) Protocol + Default + accessor (additive scaffolding), (2) `AuditEvent` dataclass file, (3) `audit_emit` facade in `audit/service.py`, (4) 65-site mechanical rewrite across 19 files, (5) test_audit_sink.py with AUDIT-03 + AUDIT-04 tests, (6) optional `make audit-sink-discipline` invariant target + `test_layering.py` extension, (7) full-suite verification (AUDIT-05). Constraints: scaffolding (1-3) lands first; rewrite (4) only after `audit_emit` exists; tests (5) and discipline gate (6) after rewrite; verification last.

**Three correctness flags planner must reconcile** (see §Pitfalls):
1. **CONTEXT.md D-17 misattributes 4 lazy imports to `tasks_common.py`.** Reality: `tasks_common.py` has 1 lazy import at line 846; `auth/router.py` has 3 lazy imports at lines 285/318/357; `platform/config_ops/service.py` has 1 lazy import at line 283. Total 5 lazy import sites, not 4-in-one-file. All five must be preserved as lazy.
2. **`AuditEvent.user_id` typing.** CONTEXT.md D-02 specifies `user_id: uuid.UUID` (non-nullable). Reality: `AuditLog.user_id: Mapped[uuid.UUID | None]` is nullable (`ondelete=SET NULL`). Today's `log_action(user_id: uuid.UUID, ...)` parameter is also non-nullable, and all 65 call sites pass a non-None value. The non-nullable Protocol surface is correct for the **emit** path (every emit names an actor); the row's nullable column allows post-hoc user deletion to NULL-out the FK. No conflict — but planner should annotate this in the dataclass docstring so future readers don't conflate the two.
3. **ROADMAP SC#4 wording vs D-06 implementation.** SC#4 says "all 65 sites route through `get_audit_sink().emit()`" (singular accessor). D-06 implements via `audit_emit()` facade looping `get_audit_sinks()` (plural). Equivalent contract — the facade IS the singular call shape, behind which the iteration happens. No SC update needed; the SC is satisfied by D-06's facade.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Audit Sink contract (write-side Protocol) | Backend / `app.platform.extensions.protocols` | — | Mirrors existing `BrandingExtension` / `AuditExtension` / `AuthExtension` pattern verbatim. |
| Audit event payload (typed value object) | Backend / `app.modules.audit.events` (new file) | — | Co-located with audit module so future `AuditEvent` extensions live with the audit domain, not the platform extension layer. |
| Default community sink (DB-row writer) | Backend / `app.platform.extensions.defaults` | — | Default classes live next to existing four defaults. Body delegates to `log_action()` (D-04). |
| Sink registry (multi-sink list slot) | Backend / `app.platform.extensions.__init__` | `importlib.metadata` entry-points (`geolens.extensions` group) | Existing accessor pattern with one departure: list-typed return for multi-sink coexistence. |
| Sink-emit facade (per-sink try/except + structlog) | Backend / `app.modules.audit.service` | `structlog` for swallowed-failure logging | The facade is application-level (audit module), not registry-level — it consumes the registry. |
| Call-site emit (the 65 routers/services/tasks) | Backend / 19 caller files | — | Pure rewrite — no responsibility shift, just substituting `log_action(...)` for `audit_emit(AuditEvent(...))`. |
| AUDIT-04 / AUDIT-03 verification | Backend / `tests/test_audit_sink.py` (new) | — | Mirrors `tests/test_lifecycle.py` Phase 220+221 pattern (registry manipulation under fixture save/restore). |
| AUDIT-05 verification | Backend / existing `tests/test_audit.py` + `tests/test_lifecycle.py` (unchanged) | — | "Existing tests pass" IS the AUDIT-05 contract; no new test infrastructure. |
| Architecture-guard (no `log_action(` outside `audit/service.py`) | Backend / `tests/test_layering.py` (extended) **OR** `Makefile` target | — | Existing layering-test precedent for git-grep-based invariants; recommended as the discipline mechanism. |

## Standard Stack

### Core (no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | ≥3.13 | Language | `pyproject.toml requires-python = ">=3.13"`. `typing.Protocol`, `typing.runtime_checkable`, `dataclasses.dataclass(frozen=True)` are stdlib. [VERIFIED: pyproject.toml:5] |
| FastAPI | ≥0.115.0 | HTTP framework | All 65 emit sites are FastAPI router endpoints or service functions called from them; no FastAPI surface change. [VERIFIED: pyproject.toml:9] |
| SQLAlchemy | ≥2.0.25 | ORM | `AsyncSession` from `sqlalchemy.ext.asyncio` — type for `AuditSink.emit()`'s session parameter. `AuditLog` ORM unchanged. [VERIFIED: pyproject.toml:10; backend/app/modules/audit/models.py:15-34] |
| structlog | ≥25.4.0 | Structured logging | `structlog.stdlib.get_logger(__name__).exception(...)` is the AUDIT-03 swallowing log shape. Existing import pattern at `extensions/__init__.py:30`. [VERIFIED: pyproject.toml:31] |
| pytest | ≥9.0.3 | Test runner | New `tests/test_audit_sink.py` uses `@pytest.mark.anyio` (project default) for async tests + the existing `test_db_session` / `client` / `admin_auth_header` fixtures. [VERIFIED: pyproject.toml:dev:pytest>=9.0.3] |
| anyio | (transitive) | Async test runtime | `anyio_mode = "auto"` in `[tool.pytest.ini_options]` lets async tests use plain `async def` with no decorator beyond `@pytest.mark.anyio` where explicit. [VERIFIED: backend/pyproject.toml:67] |

**Version verification:** All dependencies pinned in `backend/pyproject.toml`; no new packages required for Phase 222. Verified 2026-04-30 against the existing `pyproject.toml` snapshot. [VERIFIED]

### No new packages required

Phase 222 is additive structural-typing + mechanical rewrite + 2 tests. Zero new dependencies; zero pyproject changes; zero migration.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `AuditEvent` as `@dataclass(frozen=True)` | Pydantic v2 `BaseModel` | Pydantic adds runtime validation overhead per emit (potentially thousands per request). Audit emit is internal trusted code; validation is not needed. Dataclass is zero-cost. [CITED: PEP 557 dataclass docs; D-02 rationale] |
| `AuditEvent` co-located in `service.py` | Separate `events.py` file | Co-location reduces file count by 1, but `service.py` already has 159 lines of query/stream logic. Separate file matches the hint in CONTEXT.md "lives in `backend/app/modules/audit/events.py` (new file) — Claude's discretion to co-locate." Recommended path: separate file (cleaner separation of concerns; future `AuditEvent` field extensions don't churn `service.py`). |
| Single accessor `get_audit_sink()` returning list | List accessor `get_audit_sinks()` (chosen — D-10) | Singular accessor returning list reads weirdly; plural matches the list semantics. ROADMAP SC#4's wording "get_audit_sink().emit()" is satisfied by D-06's `audit_emit()` facade — the facade IS the singular call shape behind which iteration happens. |
| Single try/except around the whole iteration | Per-sink try/except (chosen — D-06) | Whole-iteration try/except means one raising sink stops the iteration — `DefaultAuditSink` may not run if a registered enterprise sink raises first. Per-sink try/except is the AUDIT-03 + AUDIT-05 contract verbatim ("default sink writes its row even if a downstream enterprise sink fails, and vice-versa"). |
| Eager init step `_init_default_sinks()` at app startup | Lazy default in accessor (chosen — D-11) | Eager init introduces ordering dependency (must run before `load_extensions()`); lazy default in accessor mirrors existing 4 typed accessors exactly. |
| Replacement of `AuditExtension` with unified `AuditSink` | Sibling Protocols (chosen — D-01) | `AuditExtension` is read-side (export-format gating at `audit/router.py:107`); `AuditSink` is write-side (emit). Different responsibilities, different consumers. Future enterprise overlay may implement BOTH on one class (Phase 217 D-13 dual-Protocol pattern), but the contracts stay separate. |

## Architecture Patterns

### System Architecture Diagram

```
BEFORE (today)
─────────────────────────────────────────────────────────────────────
  65 call sites in 19 files
   │
   │  await log_action(session, user_id=..., action=..., ...)
   ▼
  app.modules.audit.service.log_action()        [audit/service.py:49-67]
   │  AuditLog(user_id, action, resource_type, ...)
   │  session.add(entry)
   ▼
  caller's outer transaction (session.commit())
   │
   ▼
  catalog.audit_logs row

AFTER (Phase 222)
─────────────────────────────────────────────────────────────────────
  65 call sites in 19 files (mechanically rewritten)
   │
   │  event = AuditEvent(user_id=..., action=..., ...)        [audit/events.py — frozen dataclass]
   │  await audit_emit(session, event)                        [audit/service.py — new facade]
   ▼
  audit_emit(session, event)                                  [D-06]
   │  for sink in get_audit_sinks():                          [D-09, D-10]
   │    try: await sink.emit(session, event)
   │    except Exception: structlog.exception(...)            [AUDIT-03]
   │
   ├──► DefaultAuditSink                                      [extensions/defaults.py — new]
   │      emit() body == today's log_action() body            [D-04]
   │      (preserved log_action() called as internal helper)
   │      AuditLog(...) → session.add(entry)
   │      ▼
   │     caller's outer transaction (session.commit())
   │      ▼
   │     catalog.audit_logs row                               [byte-identical to today — AUDIT-05]
   │
   └──► [Future] EnterpriseAuditSink (audit-export overlay)   [out of scope — AUDIT-FUTURE-01]
          appended to _extensions["audit_sinks"] via
          geolens-enterprise's register_extensions(registry)
          ▼
         S3 / SIEM / syslog / file-export

REGISTRY SHAPE
─────────────────────────────────────────────────────────────────────
  _extensions: dict[str, object]                              [extensions/__init__.py:32]
   │
   ├── "branding"   → BrandingExtension (single)              [unchanged — Phase pre-214]
   ├── "audit"      → AuditExtension    (single, READ-side)   [unchanged — D-19]
   ├── "auth"       → AuthExtension     (single)              [unchanged]
   ├── "identity"   → IdentityExtension (single)              [unchanged — Phase 214]
   └── "audit_sinks"→ list[AuditSink]   (PLURAL, WRITE-side)  [NEW — D-09]
        │
        │ Lazy default when slot missing (community case):
        │   get_audit_sinks() returns [DefaultAuditSink()]    [D-11]
        │
        │ Enterprise overlay (future) appends:
        │   sinks = registry.setdefault("audit_sinks", [DefaultAuditSink()])
        │   sinks.append(S3AuditSink(...))
        ▼
       Multi-sink coexistence (no slot collision; default + N overlays)
```

### Recommended Project Structure

```
backend/app/
├── modules/
│   └── audit/
│       ├── service.py                  ⚙ audit_emit() facade ADDED here
│       ├── events.py                   ✨ NEW — AuditEvent frozen dataclass
│       ├── models.py                   (unchanged — AuditLog ORM)
│       ├── router.py                   (unchanged — read-side; line 107 still consults AuditExtension)
│       └── schemas.py                  (unchanged)
│
├── platform/
│   └── extensions/
│       ├── protocols.py                ⚙ AuditSink Protocol ADDED here
│       ├── defaults.py                 ⚙ DefaultAuditSink ADDED here
│       └── __init__.py                 ⚙ get_audit_sinks() ADDED here
│
├── core/persistent_config.py           ⚙ 2 call sites rewritten (lines 201, 247)
├── platform/config_ops/service.py      ⚙ 1 call site rewritten (line 339); 1 lazy import (line 283)
├── processing/export/router.py         ⚙ 1 call site rewritten (line 118)
├── processing/ingest/tasks_common.py   ⚙ 1 call site rewritten (line 929); 1 lazy import (line 846)
└── modules/
    ├── admin/router.py                 ⚙ 10 call sites rewritten (113, 213, 243, 298, 341, 371, 400, 488, 674, 779)
    ├── auth/router.py                  ⚙ 3 call sites rewritten (291, 331, 375); 3 LAZY imports (285, 318, 357)
    ├── catalog/maps/router.py          ⚙ 9 call sites rewritten (241, 433, 470, 510, 587, 628, 667, 823, 864)
    ├── catalog/sources/router.py       ⚙ 7 call sites rewritten (56, 71, 202, 236, 321, 383, 430)
    ├── catalog/collections/router.py   ⚙ 5 call sites rewritten (83, 201, 246, 280, 313)
    ├── catalog/features/router.py      ⚙ 4 call sites rewritten (354, 443, 526, 592)
    ├── catalog/datasets/api/router.py  ⚙ 4 call sites rewritten (159, 294, 333, 403)
    ├── catalog/layers/router.py        ⚙ 4 call sites rewritten (125, 177, 237, 283)
    ├── catalog/sources/stac_router.py  ⚙ 3 call sites rewritten (297, 310, 550)
    ├── settings/router.py              ⚙ 3 call sites rewritten (455, 524, 582)
    ├── embed_tokens/router.py          ⚙ 3 call sites rewritten (93, 155, 192)
    ├── catalog/datasets/api/router_metadata.py    ⚙ 2 call sites (172, 223)
    ├── catalog/datasets/api/router_export.py      ⚙ 1 call site (250)
    └── embed_tokens/admin_router.py               ⚙ 1 call site (78)
                                                        65 total — confirmed by grep

backend/tests/
├── test_audit_sink.py                  ✨ NEW — AUDIT-03 (RaisingSink) + AUDIT-04 (FixtureSink) tests
├── test_audit.py                       (unchanged — AUDIT-05 verification target; 13 tests, 390 LOC)
├── test_lifecycle.py                   (unchanged — Phase 220+221 reference for registry-manipulation pattern)
└── conftest.py                         (unchanged — reuses test_db_session, client, admin_auth_header)
```

### Pattern 1: Sibling Protocol Addition

**What:** Add a 4th `@runtime_checkable` Protocol to `extensions/protocols.py` alongside the existing 3.

**When to use:** When a new orthogonal extension concern arises (write-side audit emit is orthogonal to read-side audit export).

**Example:**

```python
# backend/app/platform/extensions/protocols.py
from __future__ import annotations
from typing import Protocol, runtime_checkable
from sqlalchemy.ext.asyncio import AsyncSession  # NEW import — see Pitfall A

if TYPE_CHECKING:
    from app.modules.audit.events import AuditEvent

@runtime_checkable
class BrandingExtension(Protocol):
    def get_branding_defaults(self) -> dict[str, object]: ...

@runtime_checkable
class AuditExtension(Protocol):
    def get_export_formats(self) -> list[str]: ...

@runtime_checkable
class AuthExtension(Protocol):
    def get_auth_methods(self) -> list[str]: ...

# NEW (Phase 222):
@runtime_checkable
class AuditSink(Protocol):
    """Write-side hook for audit event emission.

    Sibling to AuditExtension (read-side export-format gating). Enterprise
    overlays subscribe by appending instances to _extensions["audit_sinks"].
    """
    async def emit(self, session: AsyncSession, event: "AuditEvent") -> None: ...
```

[VERIFIED: existing pattern at `backend/app/platform/extensions/protocols.py:11-29` (3 Protocols today). The `if TYPE_CHECKING` import block does NOT exist there today — file imports only `Protocol, runtime_checkable` from `typing`. The Phase 222 addition needs `AsyncSession` (real import) + `AuditEvent` (forward-ref via TYPE_CHECKING to avoid `protocols.py → modules.audit.events` edge that would re-create the layering inversion Phase 212 closed).]

### Pattern 2: Frozen Dataclass Event Payload

**What:** Use `@dataclass(frozen=True)` for the typed event payload — not Pydantic.

**When to use:** Hot-path internal-trusted value objects where validation is not needed.

**Example:**

```python
# backend/app/modules/audit/events.py — NEW FILE
"""Typed event payload for audit emission.

Sibling to log_action() parameter surface; mirrors fields 1:1 (D-02).
Frozen so sinks cannot mutate the event between subscribers.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass

@dataclass(frozen=True)
class AuditEvent:
    """Immutable audit event passed to every registered AuditSink.

    Note on user_id typing: required (non-None) — every emit call site names
    an actor. The corresponding AuditLog.user_id column IS nullable (FK to
    users.id with ondelete=SET NULL) to allow post-hoc user deletion to
    NULL-out the FK; that is a row-storage concern, not an emit concern.
    """
    user_id: uuid.UUID
    action: str
    resource_type: str
    resource_id: uuid.UUID | None = None
    details: dict | None = None
    ip_address: str | None = None
```

[CITED: PEP 557 dataclass docs; D-02 rationale]

### Pattern 3: Default Implementation Delegating to Preserved Helper

**What:** `DefaultAuditSink.emit()` calls the preserved `log_action()` — the row-construction body stays in one place (D-04).

**Example:**

```python
# backend/app/platform/extensions/defaults.py
class DefaultAuditSink:
    """Community-edition default: writes one audit_logs row via log_action().

    log_action() is preserved as an internal helper (D-04). Application
    code does NOT call log_action() directly post-Phase-222; only this
    sink does.
    """
    async def emit(self, session, event) -> None:
        # Deferred import: log_action lives in app.modules.audit.service,
        # which imports AuditLog from app.modules.audit.models. The
        # extensions/ directory is platform-level and should not pull
        # modules-level imports at module load. (Same discipline as
        # IdentityExtension's deferred imports — Phase 214 RESEARCH.md.)
        from app.modules.audit.service import log_action
        await log_action(
            session,
            user_id=event.user_id,
            action=event.action,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            details=event.details,
            ip_address=event.ip_address,
        )
```

[VERIFIED: existing `DefaultIdentityExtension.resolve_identity_from_token()` at `defaults.py:42-43` is async with no body beyond `return None`; `DefaultAuditSink.emit()` is the same async-method shape with a delegation body.]

### Pattern 4: List-Typed Multi-Instance Accessor with Lazy Default

**What:** `get_audit_sinks() -> list[AuditSink]` differs from existing 4 single-instance accessors — returns a defensive copy of the list.

**Example:**

```python
# backend/app/platform/extensions/__init__.py — ADDITIONS
from app.platform.extensions.defaults import (
    DefaultAuditExtension,
    DefaultAuditSink,        # NEW
    DefaultAuthExtension,
    DefaultBrandingExtension,
    DefaultIdentityExtension,
)
from app.platform.extensions.protocols import (
    AuditExtension,
    AuditSink,               # NEW
    AuthExtension,
    BrandingExtension,
)

# NEW (Phase 222) — list-typed accessor with lazy default (D-10, D-11)
def get_audit_sinks() -> list[AuditSink]:
    """Return all registered AuditSinks, or [DefaultAuditSink()] when none.

    Departure from existing four single-instance accessors: returns a list
    (D-09 — community always has 1 sink, enterprise can have N). Defensive
    list copy stops a sink from accidentally mutating the registry mid-iteration.
    """
    sinks = _extensions.get("audit_sinks")
    if sinks is None:
        return [DefaultAuditSink()]
    return list(sinks)  # type: ignore[arg-type]  # defensive copy
```

[VERIFIED: existing 4 accessors at `extensions/__init__.py:87-125` (`get_branding_extension`, `get_audit_extension`, `get_auth_extension`, `get_identity_extension`) — single-instance shape. `get_audit_sinks()` follows the slot-lookup-or-default pattern but returns a `list`.]

### Pattern 5: Per-Sink Try/Except Facade with Structlog Swallowing

**What:** A module-level free function in `audit/service.py` is the single entry point the 65 call sites use; per-sink try/except wraps each `emit()` so one raising sink doesn't break others (AUDIT-03, D-06–D-08).

**Example:**

```python
# backend/app/modules/audit/service.py — ADDITIONS (top of file)
import structlog

from app.modules.audit.events import AuditEvent  # NEW co-located import
from app.platform.extensions import get_audit_sinks  # NEW

logger = structlog.stdlib.get_logger(__name__)

# NEW (Phase 222) — the only function the 65 call sites call (D-06)
async def audit_emit(session: AsyncSession, event: AuditEvent) -> None:
    """Dispatch event to every registered AuditSink with per-sink failure isolation.

    AUDIT-03: a sink that raises does NOT break the surrounding business
    op. Failures are logged via structlog.exception() but do not propagate.
    AUDIT-05: DefaultAuditSink runs first by virtue of the lazy-default
    list ordering — enterprise overlays append after.
    """
    for sink in get_audit_sinks():
        try:
            await sink.emit(session, event)
        except Exception:  # broad: AUDIT-03 contract — never propagate sink failures
            logger.exception(
                "Audit sink raised; suppressed per AUDIT-03",
                sink=type(sink).__name__,
                action=event.action,
                resource_type=event.resource_type,
                resource_id=str(event.resource_id) if event.resource_id else None,
            )

# UNCHANGED — log_action() preserved verbatim; only DefaultAuditSink.emit() calls it
async def log_action(  # D-04, D-05 — internal helper post-Phase-222
    session: AsyncSession,
    user_id: uuid.UUID,
    action: str,
    ...
) -> None:
    """Create an audit log entry. Does NOT commit -- caller's transaction handles it."""
    entry = AuditLog(...)
    session.add(entry)
```

[CITED: D-06 facade pattern; structlog import shape matches `extensions/__init__.py:30` `logger = structlog.stdlib.get_logger(__name__)`]

### Pattern 6: 65-Site Mechanical Rewrite (the big mechanical step)

**What:** Each `await log_action(session, user_id=X, action="A", resource_type="R", resource_id=R, details=D, ip_address=IP)` becomes `await audit_emit(session, AuditEvent(user_id=X, action="A", resource_type="R", resource_id=R, details=D, ip_address=IP))`.

**Example transformation (admin/router.py:113 — `user.create`):**

```python
# BEFORE
await log_action(
    session=db,
    user_id=current_user.id,
    action="user.create",
    resource_type="user",
    resource_id=user.id,
    details={"username": body.username, "role": body.role},
    ip_address=ip,
)

# AFTER
await audit_emit(
    db,
    AuditEvent(
        user_id=current_user.id,
        action="user.create",
        resource_type="user",
        resource_id=user.id,
        details={"username": body.username, "role": body.role},
        ip_address=ip,
    ),
)
```

**Imports per file:**

```python
# BEFORE (in each of the 19 caller files)
from app.modules.audit.service import log_action

# AFTER
from app.modules.audit.events import AuditEvent
from app.modules.audit.service import audit_emit
```

[CITED: D-15, D-16; transformation is purely mechanical — same arg values, wrapped in `AuditEvent(...)` constructor.]

**Argument-shape variance verified across the 65 sites** (sampled `admin/router.py`, `auth/router.py`, `catalog/maps/router.py`, `catalog/sources/router.py`, `processing/export/router.py`, `processing/ingest/tasks_common.py`, `core/persistent_config.py`, `platform/config_ops/service.py`, `catalog/datasets/api/router_metadata.py`):

| Variant | Count | Files |
|---------|-------|-------|
| All-keyword (`session=db, user_id=..., action=..., ...`) | ~40 | admin/router.py, auth/router.py, settings/router.py, persistent_config.py, config_ops/service.py, sources/router.py, layers/router.py |
| First-arg-positional (`db, user_id=..., action=..., ...`) | ~25 | maps/router.py, datasets/api/router.py, datasets/api/router_metadata.py, datasets/api/router_export.py, features/router.py, embed_tokens/router.py, processing/export/router.py, tasks_common.py |
| With `details` dict | ~50 | most sites |
| Without `details` (omitted) | ~15 | dataset.view, change_password, attribute.reset (some), etc. |
| Without `resource_id` (some helper functions in sources/router.py) | ~5 | `_probe_audit_fail`, `_fail_preview` at sources/router.py:56, 71 |
| With `ip_address` | ~50 | router endpoints with `request: Request` injected |
| Without `ip_address` (helper functions, internal services) | ~15 | sources helpers, persistent_config, config_ops/service.py |

**Mechanical-rewrite contract:** every variant shape transforms to `audit_emit(session, AuditEvent(<same kwargs as before>))`. Default values (`resource_id=None`, `details=None`, `ip_address=None`) on `AuditEvent` allow omitting the same kwargs the original sites omit. **No outlier sites need special handling beyond the 5 lazy-import preservation sites (Pitfall B).**

### Anti-Patterns to Avoid

- **Don't unify `AuditExtension` and `AuditSink` into one Protocol.** They're orthogonal — read-side export-format gating vs write-side emit. Future audit-export overlays may implement BOTH on one class (Phase 217 D-13 dual-Protocol pattern), but the contracts must stay separate.
- **Don't introduce a registry-shape abstraction unifying single-vs-list slots.** YAGNI — one departure (`audit_sinks` is a list) for one good reason. Per CONTEXT.md `<canonical_refs>`: "Do NOT introduce a new 'registry shape abstraction' to unify single and list slots."
- **Don't move the lazy `log_action` imports to module-top during the rewrite.** Five sites are deliberately lazy (Pitfall B); preserve the lazy idiom for `audit_emit` and `AuditEvent` imports there too.
- **Don't put try/except around the whole iteration in `audit_emit`.** Per-sink try/except is the contract (D-06) — one raising sink must NOT prevent the others (especially `DefaultAuditSink`) from running.
- **Don't have `DefaultAuditSink.emit()` swallow internally.** D-07 — only the facade swallows. Internal swallowing would silently lose `session.flush()` constraint failures that today's tests expect to surface.
- **Don't repurpose `_extensions["audit"]` for sinks.** D-19 — that slot holds `AuditExtension` (read-side); the new sinks use brand-new `_extensions["audit_sinks"]` (plural). Slot keys do not collide.
- **Don't add a new pytest marker for the audit-sink tests.** Existing markers are sufficient; tests should run by default in CI (no opt-out gate).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Protocol-class scaffold | Custom protocol-base / ABC hierarchy | `typing.Protocol` + `@runtime_checkable` | Existing pattern at `protocols.py:11-29`. Stdlib. Zero overhead. |
| Default-class scaffold | Subclass of Protocol (Protocol can't be subclassed) | Plain class implementing the methods structurally | Existing pattern at `defaults.py:6-43`. PEP 544 structural subtyping. |
| Typed-accessor scaffold | New registry abstraction | Existing `_extensions: dict[str, object]` + accessor mirroring `get_audit_extension()` | Existing pattern at `extensions/__init__.py:87-125`. Same shape; one departure (list return). |
| Frozen event payload | Pydantic BaseModel | `@dataclass(frozen=True)` | Hot path; no validation needed; minimal protocol surface. D-02. |
| structlog logger pattern | Bare `import logging` | `structlog.stdlib.get_logger(__name__)` | Existing pattern at `extensions/__init__.py:30`. Project convention. |
| Test sink registration | New entry-point round-trip in test fixture | Direct `_extensions["audit_sinks"]` append + restore in fixture finally | Existing pattern at `tests/test_audit.py:242-270` (`_enterprise_audit_ext`) + `tests/test_lifecycle.py:466-484` (`saml_overlay_registered`). |
| Test for "default sink wrote a row" | Custom row-counting helper | `select(AuditLog).where(...)` SQL select | Existing pattern at `tests/test_lifecycle.py:537-548` (asserts seeded `AuditLog` row). |
| Test for "exception logged" | Custom log capture | `caplog` fixture (pytest stdlib) OR `structlog.testing.capture_logs` | Either works; recommend `caplog` for simplicity (no new structlog import in tests). |
| Architecture-guard "no `log_action(` outside audit/service.py" | Bash script in CI | Extend `tests/test_layering.py` with a 6th `git grep` test | Existing pattern at `test_layering.py:1-329` (5 layering tests using `_git_grep` + pathspec exclusions). Phase 213+214 precedent. |
| FastAPI session injection | New session-context helper | Existing `db: AsyncSession = Depends(get_db)` | All 65 sites already pass session explicitly; `audit_emit(session, event)` keeps it explicit. |

**Key insight:** Phase 222 is the **5th instance** of the four-Protocol pattern (after `BrandingExtension`, `AuditExtension`, `AuthExtension`, `IdentityExtension` from Phase 214). Every piece of scaffolding has 1-4 prior instances to copy from. The only novel work is the list-typed accessor and the per-sink try/except facade — both narrow extensions of the existing pattern.

## Runtime State Inventory

> Phase 222 is a **transport refactor** (code-only mechanical rewrite + new Protocol/dataclass/accessor/facade scaffolding). No persistent runtime state changes are introduced. The inventory below is included per the rename/refactor heuristic — every category answered explicitly.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — `audit_logs` rows constructed identically (D-04, D-16). No DB schema change. No alembic migration. Existing rows untouched. | None. |
| Live service config | None — no external service stores the string "log_action" or the symbol's signature. The audit pipeline is purely in-process. No n8n / Datadog / Tailscale / Cloudflare config touches the audit emit path. | None. |
| OS-registered state | None — no Windows Task Scheduler, pm2, launchd, systemd, or cron entry references `log_action` or the audit emit symbol. Audit emit happens inside FastAPI request handlers and Celery tasks; OS doesn't know about the function name. | None. |
| Secrets / env vars | None — no env var or secret key references `log_action` or `audit_emit`. Sink-failure swallowing logs via structlog with no secret material. | None. |
| Build artifacts / installed packages | None — no compiled binary or installed package carries the old symbol. Backend ships from source; the rewrite is in-source. **Sibling `~/Code/geolens-enterprise` overlay does NOT call `log_action()` today** (verified by re-reading `feedback_audit_sibling_repos_at_milestone_close.md` context — overlay is auth-side, not audit-side). The future audit-export overlay (AUDIT-FUTURE-01) will subscribe to the new sink protocol; it doesn't exist yet. | None. |

**The canonical question:** *After every file in the repo is updated, what runtime systems still have the old call shape cached, stored, or registered?*

Answer: nothing. This is a pure-Python mechanical rewrite with byte-identical row-write behavior — see AUDIT-05 for the verification stance.

## Common Pitfalls

### Pitfall A: AsyncSession import cycle in `protocols.py`

**What goes wrong:** `protocols.py`'s docstring claims "Uses only stdlib types to avoid circular imports with domain models." Adding `from sqlalchemy.ext.asyncio import AsyncSession` (D-01) at module level may risk a cycle.

**Why it happens:** `sqlalchemy.ext.asyncio.AsyncSession` is the parameter type for `AuditSink.emit()`. The docstring reflects a Phase-214-era discipline (`Request` was added by Phase 214 with a similar concern — see `core/identity.py` docstring: "Uses only stdlib types (plus ``fastapi.Request`` and SQLAlchemy's ``AsyncSession`` for the extension method signature)"). So Phase 214 already broke the strict-stdlib discipline once for this exact reason. **Verification: `sqlalchemy.ext.asyncio` does NOT import from `app.modules.*` — there is no cycle path.** Importing `AsyncSession` here is safe.

**How to avoid:** At plan time, run `cd backend && uv run python -c "from app.platform.extensions.protocols import AuditSink"` after the import is added. If it raises ImportError, fall back to the typed-as-`object` workaround (Plan B):

```python
# Plan B — only if real import cycles
class AuditSink(Protocol):
    async def emit(self, session: object, event: "AuditEvent") -> None: ...
# Then in DefaultAuditSink:
from sqlalchemy.ext.asyncio import AsyncSession
async def emit(self, session, event):
    assert isinstance(session, AsyncSession)  # runtime cast
    ...
```

**Warning signs:** ImportError at app boot; pytest collection errors mentioning `protocols.py`.

**Recommended approach:** Real `AsyncSession` import (Plan A — match `core/identity.py`'s precedent at line 27 which already imports `AsyncSession`). [VERIFIED: `core/identity.py:27` imports `AsyncSession` from `sqlalchemy.ext.asyncio`; that file works at module-level today.]

### Pitfall B: CONTEXT.md D-17 misattributes lazy import locations

**What goes wrong:** CONTEXT.md says lazy `log_action` imports live at `tasks_common.py` lines 285, 318, 357, 846. **Reality: only line 846 is in `tasks_common.py`. Lines 285, 318, 357 are in `auth/router.py`. There's also a 5th lazy import at `platform/config_ops/service.py:283`.** If the planner moves any of these to module-top during the rewrite, expect one of:
- **`tasks_common.py:846`** — Celery task collection-time circular import (audit ↔ ingest); the file already does explicit lazy imports for `text`, `metadata`, `DatasetVersion`, `_qtable` to avoid the cycle. The lazy `log_action` import is part of that discipline.
- **`auth/router.py:285,318,357`** — three FastAPI endpoints that import `log_action` lazily inside the function body (NOT at module-top alongside the file's other audit/auth imports). If moved to top, no cycle predicted (auth doesn't import from audit at module-top elsewhere), but this changes the local code style and may surprise future readers. Preserve the lazy-import idiom.
- **`config_ops/service.py:283`** — lazy `log_action` import inside `apply_config()` to defer the audit-service import until call time (the file imports `_registry`, `_is_env_only`, and `log_action` all lazily inside this one function). Preserve.

**Verified file-by-file via `grep -rn "from app.modules.audit"`:**

| File | Line(s) | Lazy? | Why preserved |
|------|---------|-------|---------------|
| `core/persistent_config.py` | 21 | top-of-file | — |
| `processing/ingest/tasks_common.py` | 846 | LAZY (inside `_apply_reupload_swap`) | celery task module-import-time cycle |
| `processing/export/router.py` | 13 | top-of-file | — |
| `platform/config_ops/service.py` | 283 | LAZY (inside `apply_config`) | preserve idiom |
| `modules/settings/router.py` | 10 | top-of-file | — |
| `modules/auth/router.py` | 285, 318, 357 | LAZY (inside 3 endpoints) | preserve idiom |
| `modules/catalog/maps/router.py` | 19 | top-of-file | — |
| `modules/catalog/layers/router.py` | 9 | top-of-file | — |
| `modules/catalog/datasets/api/router_metadata.py` | 15 | top-of-file | — |
| `modules/catalog/datasets/api/router_export.py` | 20 | top-of-file | — |
| `modules/catalog/datasets/api/router.py` | 19 | top-of-file | — |
| `modules/catalog/features/router.py` | 12 | top-of-file | — |
| `modules/catalog/sources/stac_router.py` | 21 | top-of-file | — |
| `modules/catalog/sources/router.py` | 12 | top-of-file | — |
| `modules/catalog/collections/router.py` | 11 | top-of-file | — |
| `modules/embed_tokens/admin_router.py` | 8 | top-of-file | — |
| `modules/embed_tokens/router.py` | 25 | top-of-file | — |
| `modules/admin/router.py` | 33 | top-of-file | — |

**How to avoid:** Plan task explicitly enumerates the 5 lazy-import sites. Post-rewrite, run `grep -n "from app.modules.audit" backend/app/ -r` and verify the lazy `audit_emit` imports remain inside their respective function bodies.

**Warning signs:** ImportError at Celery worker boot ("circular import"); FastAPI startup hangs; backend unit tests collection error in `test_persistent_config.py` or `test_audit.py`.

### Pitfall C: Test fails to initialize `_extensions["audit_sinks"]` slot before appending fixture sink

**What goes wrong:** If the AUDIT-04 test only does `_extensions["audit_sinks"].append(fixture_sink)`, the slot starts as `KeyError` (community has no slot — D-11 lazy default). The append fails with KeyError, OR if test sets `_extensions["audit_sinks"] = [fixture_sink]`, the default is missing → AUDIT-05 default-row assertion fails.

**Why it happens:** `get_audit_sinks()` returns `[DefaultAuditSink()]` lazily when slot missing — but ONLY for `get_audit_sinks()` callers. Direct registry manipulation needs to seed the slot explicitly with both the default AND the fixture.

**How to avoid:** Test fixture seeds the slot to a list with both:

```python
import pytest
from app.platform.extensions import _extensions
from app.platform.extensions.defaults import DefaultAuditSink

class FixtureSink:
    def __init__(self):
        self.received: list = []
    async def emit(self, session, event):
        self.received.append(event)

@pytest.fixture
async def audit_sinks_with_fixture():
    """Register a fixture sink alongside the default. Restore on teardown."""
    saved = _extensions.get("audit_sinks")  # likely None in community tests
    fixture_sink = FixtureSink()
    _extensions["audit_sinks"] = [DefaultAuditSink(), fixture_sink]
    try:
        yield fixture_sink
    finally:
        if saved is None:
            _extensions.pop("audit_sinks", None)
        else:
            _extensions["audit_sinks"] = saved
```

[CITED: pattern matches `_enterprise_audit_ext()` at `tests/test_audit.py:252-268` (saves prior, sets new, restores in finally) and `saml_overlay_registered` at `tests/conftest.py:466-484`.]

**Warning signs:** test asserts `len(fixture_sink.received) == 1` passes BUT the corresponding `select(AuditLog)` query returns 0 rows (default missing); OR KeyError at fixture setup.

### Pitfall D: Future enterprise overlay's `register_extensions()` overwriting (not appending) the slot

**What goes wrong:** A future audit-export overlay's `register_extensions(registry)` writes `registry["audit_sinks"] = [S3AuditSink()]` instead of `setdefault + append`. Result: the community default disappears; AUDIT-05 row-write contract violated for that deployment.

**Why it happens:** Mutation discipline isn't enforced at the registry level — Python dicts are mutable. Phase 222 cannot prevent this in core (the overlay code lives outside this repo).

**How to avoid:**
1. **Document the `setdefault + append` idiom in the canonical ref** — already in CONTEXT.md `<canonical_refs>` "Code (enterprise overlay — outside repo, future consumer)".
2. **Recommended (this research):** Add a comment in `extensions/__init__.py` next to `get_audit_sinks()` documenting the expected append pattern.
3. **Optional defensive lint:** `make audit-sink-discipline` (see §CI / Make Targets) could grep the enterprise overlay's `register_extensions()` body for `registry["audit_sinks"] = ` (assignment) and warn — but this is out-of-scope for v13.3 per CONTEXT.md.

**Warning signs:** Audit-export overlay deployed; `audit_logs` row count drops to zero (or the export subscriber receives events but DB has no records).

### Pitfall E: `AuditEvent.user_id` typing vs nullable column

**What goes wrong:** `AuditEvent.user_id: uuid.UUID` (non-nullable per D-02) but `AuditLog.user_id: Mapped[uuid.UUID | None]` (nullable, `ondelete=SET NULL`). A reader could conflate the two and conclude the dataclass field type is wrong.

**Why it happens:** Two different concerns. The emit-time type asserts "every emit names an actor" (today's `log_action(user_id: uuid.UUID, ...)` parameter is non-nullable). The row-storage type allows post-hoc user deletion to NULL-out the FK retroactively.

**How to avoid:** Add a one-line comment in `events.py`:

```python
# user_id is required at emit-time (every emit names an actor), even though
# the AuditLog.user_id column is nullable to allow post-hoc user deletion to
# NULL-out the FK (ondelete=SET NULL).
```

**Warning signs:** mypy/pyright flagging an assignment from `AuditEvent.user_id` to `AuditLog.user_id` as a type narrowing — this is benign (UUID assigning to UUID|None is allowed).

### Pitfall F: `details` dict is free-form — frozen dataclass + `details: dict | None` allows mutation

**What goes wrong:** `@dataclass(frozen=True)` prevents reassignment of `event.details = {...}` but NOT mutation of the dict's contents (`event.details["foo"] = "bar"`). A misbehaving overlay sink could mutate `event.details` mid-iteration, and subsequent sinks would see the mutated dict.

**Why it happens:** Python's `frozen=True` is shallow — it freezes attribute assignment, not contained collection mutation.

**How to avoid:** Two options:
1. **Document, don't enforce** (recommended for v13.3): a one-line note in the `AuditEvent` docstring saying "sink implementations MUST NOT mutate `event.details`." Trust contract.
2. **Defensively copy in facade** (heavier): `audit_emit` does `event = replace(event, details=dict(event.details) if event.details else None)` before each sink. Cost: one dict copy per sink per emit. Out-of-scope per REQUIREMENTS.md "Out of Scope: advanced semantics."

**Recommended:** Option 1 (document only). The overlay-side discipline is the same as the read-only-Protocol-method assumption that already governs `BrandingExtension`/`AuditExtension`/`AuthExtension` — overlays are trusted not to misbehave.

**Warning signs:** an enterprise overlay's `S3AuditSink.emit()` writes `event.details["s3_uploaded"] = True` and the next sink in iteration order sees the mutated dict.

### Pitfall G: Test-order dependence on `_extensions`

**What goes wrong:** Test A leaves `_extensions["audit_sinks"]` populated; test B (running later) sees test A's fixture sink and assertions fail with unexpected sink behavior.

**Why it happens:** `_extensions` is module-level state; pytest fixtures don't auto-restore unless the fixture body has a `finally` clause.

**How to avoid:** Mirror `saml_overlay_registered` at `tests/conftest.py:466-484` exactly — save snapshot in a dict, set new state, restore in `finally`. The fixture in Pitfall C above already follows this discipline. Add a regression check at fixture teardown: `assert _extensions.get("audit_sinks") == saved` to catch leaks.

**Warning signs:** Tests pass in isolation but fail when run together; nondeterministic test results.

### Pitfall H: Celery task without `await` async context

**What goes wrong:** A future Celery task author calls `audit_emit(session, event)` without `await`; Python silently returns a coroutine that's never awaited; no row written; runtime warning emitted.

**Why it happens:** All current 65 sites are verified-async (CONTEXT.md `<code_context>` "Integration Points"). The Celery task at `tasks_common.py:929` is `async def _apply_reupload_swap(...)` — verified at line 831 (`async def _apply_reupload_swap(`).

**How to avoid:** No action needed for the 65 existing sites (all async). For future sites: the architecture-guard test (recommended) catches `audit_emit(` calls outside the canonical pattern at lint time.

**Warning signs:** `RuntimeWarning: coroutine 'audit_emit' was never awaited` in test output.

### Pitfall I: SC#4 wording vs implementation

**What goes wrong:** ROADMAP §Phase 222 SC#4 says "all 65 sites route through `get_audit_sink().emit()`" (singular accessor). D-06 implements via `audit_emit()` facade looping `get_audit_sinks()` (plural).

**Why it happens:** The SC was written before the discuss-phase locked the facade pattern; `get_audit_sink()` was the early-spec name for the single emit entrypoint. After D-06, the facade IS the singular call shape (the iteration is implementation-detail behind it).

**How to avoid:** No code change. If the planner wants documentation consistency, update ROADMAP SC#4 to read "all 65 sites route through `audit_emit()`" — but this is cosmetic, not contractual. The verification (no `log_action(` outside `audit/service.py`) is the load-bearing assertion.

**Warning signs:** Confusion in code review; PR template comments asking "where's `get_audit_sink()`?"

### Pitfall J: structlog.exception() context fields under flapping enterprise sink

**What goes wrong:** Under a misbehaving enterprise sink that raises on every emit, the facade emits one `structlog.exception()` per emit. With 65 emit sites firing under heavy concurrent load, log volume can spike.

**Why it happens:** Phase 222 ships zero rate-limiting; that's REQUIREMENTS.md "Out of Scope" (back-pressure, advanced semantics).

**How to avoid:** Document as a known operational characteristic. The facade's structured fields (`sink_name`, `action`, `resource_type`, `resource_id`) are what operators use to filter/silence the noisy sink at the structlog config layer. No core change.

**Warning signs:** Production log spike correlated with audit-export overlay flapping; ops paging on log volume.

[CITED: D-06 + structlog config; CONTEXT.md `<code_context>` "Risk surfaces"]

## Code Examples

Verified patterns from official sources and the codebase:

### Existing four-Protocol pattern (the precedent)

```python
# backend/app/platform/extensions/protocols.py — current state [VERIFIED]
@runtime_checkable
class BrandingExtension(Protocol):
    def get_branding_defaults(self) -> dict[str, object]: ...

@runtime_checkable
class AuditExtension(Protocol):
    def get_export_formats(self) -> list[str]: ...

@runtime_checkable
class AuthExtension(Protocol):
    def get_auth_methods(self) -> list[str]: ...

# (IdentityExtension lives in core/identity.py per Phase 214 D-12, not here.
#  Phase 222 adds AuditSink HERE per AUDIT-01 explicit naming.)
```

### Existing typed-accessor pattern (the precedent for `get_audit_sinks`)

```python
# backend/app/platform/extensions/__init__.py [VERIFIED]
def get_audit_extension() -> AuditExtension:
    """Return the registered AuditExtension or the community default."""
    ext = _extensions.get("audit")
    if ext is None:
        return DefaultAuditExtension()
    return ext  # type: ignore[return-value]
```

### Existing `log_action()` body (preserved verbatim)

```python
# backend/app/modules/audit/service.py:49-67 [VERIFIED — body to preserve]
async def log_action(
    session: AsyncSession,
    user_id: uuid.UUID,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Create an audit log entry. Does NOT commit -- caller's transaction handles it."""
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address,
    )
    session.add(entry)
```

[VERIFIED: `log_action()` body is exactly: build `AuditLog(...)` with the 6 fields → `session.add(entry)`. No commit. No coercion. No defaults beyond what the function signature declares.]

### Existing fixture-registry pattern (the precedent for `audit_sinks_with_fixture`)

```python
# backend/tests/test_audit.py:242-270 [VERIFIED]
def _enterprise_audit_ext():
    """Context manager that registers an AuditExtension advertising csv+json."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        import app.platform.extensions as ext_mod
        from app.core.edition import init_edition
        from app.platform.extensions.defaults import DefaultAuditExtension

        prior_ext = ext_mod._extensions.get("audit")
        prior_info = __import__("app.core.edition", fromlist=["_info"])._info

        class _ExportingAudit(DefaultAuditExtension):
            def get_export_formats(self):
                return ["csv", "json"]

        ext_mod._extensions["audit"] = _ExportingAudit()
        init_edition(["audit"])
        try:
            yield
        finally:
            if prior_ext is None:
                ext_mod._extensions.pop("audit", None)
            else:
                ext_mod._extensions["audit"] = prior_ext
            __import__("app.core.edition", fromlist=["_info"])._info = prior_info

    return _ctx()
```

### Existing `saml_overlay_registered` pattern (Phase 220+221 precedent)

```python
# backend/tests/conftest.py:454-484 [VERIFIED]
@pytest.fixture
def saml_overlay_registered():
    from app.platform.extensions import _extensions, _routers

    saved_ext = dict(_extensions)
    saved_routers = list(_routers)
    try:
        from geolens_enterprise.auth.saml import EnterpriseSamlExtension
        from geolens_enterprise.auth.saml.router import router as saml_router

        ext = EnterpriseSamlExtension()
        _extensions["auth"] = ext
        _extensions["identity"] = ext
        _routers.append(saml_router)
        yield ext
    finally:
        _extensions.clear()
        _extensions.update(saved_ext)
        _routers.clear()
        _routers.extend(saved_routers)
```

### Existing layering-guard pattern (precedent for audit-discipline gate)

```python
# backend/tests/test_layering.py:80-329 [VERIFIED — pattern to extend]
def _git_grep(pattern: str, path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "grep", "-n", "-E", pattern, "--", path],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )

@pytest.mark.architecture
def test_no_log_action_calls_outside_audit_service():
    """Phase 222 AUDIT-02: log_action() is called only by DefaultAuditSink.emit().

    All 65 historical call sites must route through audit_emit() instead.
    """
    if not _has_git_metadata() or not _has_pathspec_magic():
        pytest.skip("git pathspec :! exclusion required")
    result = _git_grep(
        r"\bawait log_action\(",
        ":(top)backend/app :!backend/app/modules/audit/service.py "
        ":!backend/app/platform/extensions/defaults.py",
    )
    assert result.returncode == 1, (  # rc=1 == no matches (success)
        f"Phase 222 invariant violated: log_action() called outside "
        f"DefaultAuditSink.emit() / audit_emit():\n{result.stdout}"
    )
```

[CITED: pattern from `test_layering.py` Phase 213+214 architecture tests. The exclusion `:(top)` makes paths repo-root-relative; `:!` excludes specific files where `log_action()` legitimately appears (`audit/service.py` definition + `defaults.py` if `DefaultAuditSink` calls it directly).]

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 65 direct `log_action()` calls scattered across 19 files | Single `audit_emit()` facade dispatching to N registered sinks | Phase 222 (this) | Audit-export overlay is a 1-line `setdefault + append`; no patching of 65 sites. |
| Read-side audit gating only (`AuditExtension`) | Sibling write-side `AuditSink` | Phase 222 (this) | Read and write concerns separated. Future overlay can implement either or both. |
| Single-instance accessors only (`get_X_extension`) | Multi-instance `get_audit_sinks() -> list[AuditSink]` | Phase 222 (this) | First multi-instance accessor in the registry. Documents the precedent for future "subscribe many" seams. |

**Deprecated/outdated:**
- **`log_action()` as a public API.** Post-Phase-222, `log_action()` is an internal helper called only by `DefaultAuditSink.emit()`. It is NOT removed (D-04 picks option a from AUDIT-02), but new code should use `audit_emit(session, AuditEvent(...))` always. Future cleanup ticket (out of v13.3) may inline the body and remove the symbol entirely; that's cosmetic.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest >= 9.0.3` + `pytest-anyio` (auto mode) |
| Config file | `backend/pyproject.toml [tool.pytest.ini_options]` |
| Quick run command | `cd backend && uv run pytest tests/test_audit_sink.py tests/test_audit.py tests/test_lifecycle.py -v --tb=short` |
| Full suite command | `cd backend && uv run pytest -v --tb=short` (or `make test` from repo root) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| AUDIT-01 | `AuditSink` Protocol + `DefaultAuditSink` exist; default delegates to `log_action()` body | unit / smoke | `cd backend && uv run pytest tests/test_audit_sink.py::test_audit_sink_protocol_shape -v` | ❌ Wave 0 (new test file) |
| AUDIT-02 | All 65 `log_action()` emit sites route through `audit_emit()`; `log_action()` only called from `DefaultAuditSink.emit()` | architecture / git-grep | `cd backend && uv run pytest tests/test_layering.py::test_no_log_action_calls_outside_audit_service -v` | ❌ Wave 0 (new test) |
| AUDIT-03 | Sink that raises does NOT break business op; failure logged via `structlog.exception()`; default sink still wrote row | integration | `cd backend && uv run pytest tests/test_audit_sink.py::test_raising_sink_does_not_break_business_op -v` | ❌ Wave 0 (new test) |
| AUDIT-04 | Fixture sink registered via `_extensions["audit_sinks"]` append receives every event alongside `DefaultAuditSink` | integration | `cd backend && uv run pytest tests/test_audit_sink.py::test_fixture_sink_receives_events_alongside_default -v` | ❌ Wave 0 (new test) |
| AUDIT-05 | Existing audit test suite + lifecycle tests pass without modification | regression | `cd backend && uv run pytest tests/test_audit.py tests/test_lifecycle.py -v` | ✅ Existing (`test_audit.py` 13 tests; `test_lifecycle.py` 3 tests) |

### AUDIT-01 — `test_audit_sink_protocol_shape`

```python
# backend/tests/test_audit_sink.py
def test_audit_sink_protocol_shape():
    """AUDIT-01: AuditSink Protocol + DefaultAuditSink exist with correct shape."""
    from app.platform.extensions.protocols import AuditSink
    from app.platform.extensions.defaults import DefaultAuditSink

    # Protocol is runtime_checkable
    assert hasattr(AuditSink, "_is_runtime_protocol") or hasattr(
        AuditSink, "_is_protocol"
    )

    # DefaultAuditSink satisfies the protocol structurally
    assert isinstance(DefaultAuditSink(), AuditSink)

    # AuditEvent has the 6 expected fields
    from app.modules.audit.events import AuditEvent
    import dataclasses
    fields = {f.name for f in dataclasses.fields(AuditEvent)}
    assert fields == {
        "user_id", "action", "resource_type",
        "resource_id", "details", "ip_address",
    }
```

### AUDIT-02 — architecture guard

```python
# backend/tests/test_layering.py — APPENDED test
@pytest.mark.architecture
def test_no_log_action_calls_outside_audit_service():
    """AUDIT-02: log_action() is called only by DefaultAuditSink.emit() post-Phase-222."""
    if not _has_git_metadata() or not _has_pathspec_magic():
        pytest.skip("requires git metadata + git >= 2.13 pathspec :! support")
    result = _git_grep(
        r"\bawait log_action\(",
        ":(top)backend/app "
        ":!backend/app/modules/audit/service.py "
        ":!backend/app/platform/extensions/defaults.py",
    )
    assert result.returncode == 1, (
        f"Phase 222 AUDIT-02 invariant violated: log_action() called "
        f"outside the audit module. All 65 historical sites must use "
        f"audit_emit() instead.\nOffending lines:\n{result.stdout}"
    )
```

### AUDIT-03 — `test_raising_sink_does_not_break_business_op`

```python
# backend/tests/test_audit_sink.py
@pytest.mark.anyio
async def test_raising_sink_does_not_break_business_op(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    caplog,
):
    """AUDIT-03: a raising sink does not propagate; default sink still wrote row."""
    from app.platform.extensions import _extensions
    from app.platform.extensions.defaults import DefaultAuditSink
    from app.modules.audit.models import AuditLog

    class RaisingSink:
        async def emit(self, session, event):
            raise RuntimeError("simulated sink failure")

    saved = _extensions.get("audit_sinks")
    _extensions["audit_sinks"] = [DefaultAuditSink(), RaisingSink()]
    try:
        # Exercise a representative call site (admin user.create endpoint)
        resp = await client.post(
            "/admin/users/",
            json={"username": "audit-sink-test-user", "password": "x" * 12, "email": "ast@test", "role": "viewer"},
            headers=admin_auth_header,
        )
        # Business op succeeded despite raising sink
        assert resp.status_code == 201, f"business op unexpectedly failed: {resp.text}"

        # Default sink wrote the audit_logs row (AUDIT-05 still holds)
        row = (
            await test_db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "user.create",
                    AuditLog.details.contains({"username": "audit-sink-test-user"}),
                )
            )
        ).scalar_one_or_none()
        assert row is not None, "DefaultAuditSink did not write its row"

        # The exception was logged (structlog routes through stdlib logging by default)
        logged = [r for r in caplog.records if "Audit sink raised" in r.getMessage()]
        assert logged, "structlog.exception() did not emit a record"
    finally:
        if saved is None:
            _extensions.pop("audit_sinks", None)
        else:
            _extensions["audit_sinks"] = saved
```

### AUDIT-04 — `test_fixture_sink_receives_events_alongside_default`

```python
# backend/tests/test_audit_sink.py
@pytest.mark.anyio
async def test_fixture_sink_receives_events_alongside_default(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """AUDIT-04: enterprise-shape overlay receives events; default still writes row."""
    from app.platform.extensions import _extensions
    from app.platform.extensions.defaults import DefaultAuditSink
    from app.modules.audit.events import AuditEvent
    from app.modules.audit.models import AuditLog

    class FixtureSink:
        def __init__(self):
            self.received: list[AuditEvent] = []
        async def emit(self, session, event):
            self.received.append(event)

    fixture_sink = FixtureSink()
    saved = _extensions.get("audit_sinks")
    _extensions["audit_sinks"] = [DefaultAuditSink(), fixture_sink]
    try:
        resp = await client.post(
            "/admin/users/",
            json={"username": "audit-sink-test-2", "password": "x" * 12, "email": "ast2@test", "role": "viewer"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201

        # FixtureSink received the event
        assert len(fixture_sink.received) >= 1
        evt = next(e for e in fixture_sink.received if e.action == "user.create")
        assert evt.resource_type == "user"
        assert evt.details and evt.details.get("username") == "audit-sink-test-2"

        # DefaultAuditSink also wrote its row (multi-sink coexistence)
        row = (
            await test_db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "user.create",
                    AuditLog.details.contains({"username": "audit-sink-test-2"}),
                )
            )
        ).scalar_one_or_none()
        assert row is not None, "DefaultAuditSink did not write its row"
    finally:
        if saved is None:
            _extensions.pop("audit_sinks", None)
        else:
            _extensions["audit_sinks"] = saved
```

### AUDIT-05 — existing-suite regression

No new test. Verification command: `cd backend && uv run pytest tests/test_audit.py tests/test_lifecycle.py -v` — all 13 audit tests + 3 lifecycle tests pass without modification. The test files themselves are NOT touched by Phase 222 (per D-14 — "preservation contract is the existing suite").

### Sampling Rate

- **Per task commit:** `cd backend && uv run pytest tests/test_audit_sink.py tests/test_audit.py -v --tb=short` (~30s once the new test file lands)
- **Per wave merge:** `cd backend && uv run pytest -v --tb=short` (full backend suite — historically ~5min)
- **Phase gate:** Full suite green + `make audit-sink-discipline` (or the equivalent `test_no_log_action_calls_outside_audit_service` architecture test) green before `/gsd-verify-work`.

### Wave 0 Gaps

- [ ] `backend/tests/test_audit_sink.py` — covers AUDIT-01, AUDIT-03, AUDIT-04
- [ ] `backend/tests/test_layering.py` — append `test_no_log_action_calls_outside_audit_service` for AUDIT-02
- [ ] No new fixtures needed in `conftest.py` — reuse `client`, `admin_auth_header`, `test_db_session` (existing)
- [ ] No new pytest markers — `@pytest.mark.anyio` (default) for new tests; `@pytest.mark.architecture` for the layering test (already registered)

*(No framework install gap — pytest + anyio + structlog all in `pyproject.toml` already.)*

## Security Domain

> Not applicable in the conventional ASVS sense — Phase 222 is a transport refactor with byte-identical row-write behavior. The audit log itself is a security-relevant resource (used for compliance), and Phase 222's contract preservation IS the security guarantee.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth code touched. |
| V3 Session Management | no | No session code touched. |
| V4 Access Control | no | No RBAC/ACL code touched. Read-side audit-export gating (require_enterprise) at `audit/router.py:96` unchanged (D-18). |
| V5 Input Validation | no | No new input surface. `AuditEvent` consumes already-validated values from existing call sites. |
| V6 Cryptography | no | No new crypto. `details` may contain sensitive fields but the existing call sites already gate this; Phase 222 does not change which fields are recorded. |
| V8 Data Protection | yes (preservation) | AUDIT-05 IS the data-protection contract: every audit row recorded today must still be recorded after the refactor. Existing test suite verifies. |
| V9 Communications | no | No network surface. |
| V10 Malicious Code | no | No code-execution surface. |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Audit row dropped (silent loss of compliance trail) | Repudiation | AUDIT-05 contract — existing tests must pass. Plus AUDIT-02 architecture-guard ensures all 65 sites still emit. |
| Sink failure cascade kills business op | DoS (self-inflicted) | AUDIT-03 contract — per-sink try/except in facade. RaisingSink test verifies. |
| Enterprise overlay sink leaks `details` (e.g., to S3 with weak ACL) | Information Disclosure | Out of Phase 222 scope — overlay's responsibility. The facade emits `event.details` to every sink; gating WHICH sinks receive WHICH events is overlay-side concern (subscription filter) deferred to AUDIT-FUTURE-01. |
| Allow-listed `details` invariant (Phase 221 D-09) | Information Disclosure | Phase 221 D-09 introduced an allow-list for `user.convert_saml_to_local` event details; that allow-list is enforced AT THE EMIT SITE (admin/router.py), not in the sink. Phase 222's transport refactor preserves the emit-site gating verbatim — the allow-list still runs before `audit_emit()` is called. |

## Sources

### Primary (HIGH confidence)
- **`.planning/phases/222-audit-sink-protocol/222-CONTEXT.md`** [VERIFIED — read in full] — locked decisions D-01..D-19; out-of-scope guards.
- **`.planning/REQUIREMENTS.md` §AUDIT-01..05** [VERIFIED — read in full] — five requirements; out-of-scope clarifications.
- **`.planning/ROADMAP.md` §Phase 222** [VERIFIED — read in full] — goal + 5 success criteria.
- **`docs-internal/audits/oc-separation-audit-20260430.md` §2 Seam #3 + §5 + §7 P1** [VERIFIED — read in full] — source spec; +242% regression evidence; load-bearing rationale.
- **`backend/app/platform/extensions/protocols.py`** [VERIFIED — read in full, 30 lines] — existing 3-Protocol scaffold; `@runtime_checkable` discipline; "stdlib only" docstring.
- **`backend/app/platform/extensions/defaults.py`** [VERIFIED — read in full, 44 lines] — existing 4-default scaffold; async-method precedent in `DefaultIdentityExtension`.
- **`backend/app/platform/extensions/__init__.py`** [VERIFIED — read in full, 126 lines] — registry shape; entry-point loader; 4 typed accessors.
- **`backend/app/modules/audit/service.py`** [VERIFIED — read in full, 159 lines] — `log_action()` body to preserve verbatim; query/stream functions unchanged.
- **`backend/app/modules/audit/models.py`** [VERIFIED — read in full, 35 lines] — `AuditLog` ORM; `user_id` is nullable (FK SET NULL).
- **`backend/tests/test_audit.py`** [VERIFIED — read 1-300] — existing audit test suite (13 tests, 390 LOC); `_enterprise_audit_ext()` precedent at lines 242-270.
- **`backend/tests/test_lifecycle.py`** [VERIFIED — read in full, 797 LOC] — Phase 220+221 fixture-cleanup pattern; `log_action` direct usage in test seeds at lines 421, 687.
- **`backend/tests/conftest.py`** [VERIFIED — read 1-120, 440-520] — `saml_overlay_registered` fixture pattern at 454-484; existing test scaffolding.
- **`backend/tests/test_layering.py`** [VERIFIED — read 1-80] — architecture-guard pattern; `_git_grep`/`_has_git_metadata`/`_has_pathspec_magic` helpers.
- **`backend/app/processing/ingest/tasks_common.py:846`** [VERIFIED] — single lazy `log_action` import in this file (NOT 4 sites as CONTEXT.md claims).
- **`backend/app/modules/auth/router.py:285,318,357`** [VERIFIED] — three lazy `log_action` imports (correctly attributed by file but mis-attributed in CONTEXT.md to `tasks_common.py`).
- **`backend/app/platform/config_ops/service.py:283`** [VERIFIED] — fifth lazy `log_action` import (not enumerated in CONTEXT.md but found via grep).
- **`backend/pyproject.toml`** [VERIFIED — read 1-80] — Python ≥3.13; pytest 9.0.3; anyio_mode auto; existing 4 markers (perf, requires_ogr2ogr, architecture, lifecycle); structlog ≥25.4.0.
- **`Makefile`** [VERIFIED — read in full, 138 lines] — no `audit-sink-discipline` target exists today; existing `test`/`test-cov`/`sdks-check`/`cli-check` targets show the project's make-target conventions.
- **65-site count** [VERIFIED] — `grep -rn "log_action(" backend/app/ --include="*.py" | wc -l` = 65; per-file counts match CONTEXT.md.

### Secondary (MEDIUM confidence)
- **`.planning/milestones/v13.1-phases/214-identity-protocol-extract/214-RESEARCH.md`** [CITED — read 1-200] — pattern reference for "extract write-side Protocol; default in extensions/defaults.py; typed accessor in extensions/__init__.py."
- **`backend/app/core/identity.py`** [VERIFIED — read 1-100] — Phase 214 precedent for `AsyncSession` import in a Protocol module despite "stdlib only" discipline (Pitfall A justification).

### Tertiary (LOW confidence — flagged for validation)
- None. All claims in this research are either VERIFIED via direct file reads / grep counts or CITED to CONTEXT.md/REQUIREMENTS.md/ROADMAP.md (locked decisions).

## Implementation Sequence Proposal

CONTEXT.md "Claude's Discretion" leaves the wave/plan partition open. Recommendation: **single phase plan with 7 sequential task waves**, each runnable independently for atomic verifiability:

| Wave | Task | Files Touched | Verification |
|------|------|---------------|--------------|
| **Wave 0** | (Test infrastructure scaffolding) — none required; reuses existing fixtures | — | — |
| **Wave 1** | Add `AuditSink` Protocol to `protocols.py`; add `DefaultAuditSink` to `defaults.py`; add `get_audit_sinks()` to `__init__.py`; add `AuditEvent` dataclass to new `events.py` | 4 files (additive only) | `cd backend && uv run python -c "from app.platform.extensions.protocols import AuditSink; from app.platform.extensions.defaults import DefaultAuditSink; from app.platform.extensions import get_audit_sinks; from app.modules.audit.events import AuditEvent"` succeeds |
| **Wave 2** | Add `audit_emit(session, event)` facade to `audit/service.py`. `log_action()` preserved verbatim. | 1 file | New `tests/test_audit_sink.py::test_audit_sink_protocol_shape` test passes |
| **Wave 3** | Mechanical 65-site rewrite across 19 files (Pattern 6). Preserve 5 lazy-import sites (Pitfall B). | 19 files | `cd backend && uv run pytest -v` — full suite green (AUDIT-05 holds) |
| **Wave 4** | Add `tests/test_audit_sink.py` with `test_audit_sink_protocol_shape`, `test_raising_sink_does_not_break_business_op`, `test_fixture_sink_receives_events_alongside_default` | 1 file | New tests pass; full suite still green |
| **Wave 5** | Append `test_no_log_action_calls_outside_audit_service` to `tests/test_layering.py` (AUDIT-02 architecture guard) | 1 file | Test passes after Wave 3's rewrite; would have failed BEFORE Wave 3 |
| **Wave 6** | Optional: add `make audit-sink-discipline` Makefile target invoking the architecture test directly (one-line `pytest tests/test_layering.py::test_no_log_action_calls_outside_audit_service`) | 1 file (Makefile) | `make audit-sink-discipline` passes |
| **Wave 7** | Final verification — full backend suite + lint + typecheck. Phase gate. | — | `make test` passes; `cd backend && uv run ruff check .` passes |

**Constraint flow:**
- Wave 1 is purely additive — no behavior change. Can ship in isolation.
- Wave 2 introduces `audit_emit` BUT does NOT yet route through it. Backward-compatible.
- Wave 3 is the only "behavior-flipping" wave — but the behavior is byte-identical (D-04, D-16). No semantic change.
- Wave 4 verifies the facade + multi-sink work end-to-end.
- Wave 5 enforces the AUDIT-02 invariant going forward.
- Wave 6 (optional) adds the make target for ergonomic developer feedback.
- Wave 7 is the final phase gate.

**Why single plan:** 19-file mechanical rewrite is medium scope but mechanical — splitting it across multiple plans buys risk (intermediate states where some sites use new facade, others use `log_action()` directly) without buying clarity. CONTEXT.md D-15 locks "single mechanical pass."

**Why 7 waves:** each wave has a clear pre/post verification; reviewers can mentally trace the diff per wave. CONTEXT.md "Claude's Discretion: Whether the plan is one PR or multiple — recommendation: single plan with sub-tasks" — this proposes 7 sub-tasks within one plan.

## CI / Make Targets

The project has no `make audit-discipline` style invariant lint today. Existing targets are `dev`, `down`, `test`, `test-cov`, `e2e`, `openapi`, `openapi-check`, `sdks`, `sdks-check`, `cli-build`, `cli-test`, `cli-check`, plus a few publish targets — see `Makefile` lines 1-138.

**Recommendation: ADD `make audit-sink-discipline`.**

Rationale:
1. The 65-site rewrite is mechanical — easy to forget a site. The architecture-guard test (Wave 5) catches reintroduction.
2. A make target lets developers run the discipline check WITHOUT spinning up the full pytest suite (~5min).
3. Runs the same architecture test pytest will run in CI — no duplication.

Proposed addition to `Makefile`:

```makefile
# Phase 222 invariant: log_action() is called only by DefaultAuditSink.emit().
# All 65 historical emit sites must route through audit_emit() instead.
audit-sink-discipline:
	cd backend && PYTHONPATH=. uv run pytest tests/test_layering.py::test_no_log_action_calls_outside_audit_service -v
```

Add `audit-sink-discipline` to the `.PHONY` declaration line at top of `Makefile`.

**Alternative (LIGHTER):** Skip the make target; rely on CI running the full pytest suite. The architecture test runs by default (it's `@pytest.mark.architecture` which is NOT in the `addopts = "-m 'not perf'"` deselect list — verified at `backend/pyproject.toml:69`).

**Recommendation:** Add the make target (Wave 6 — optional but cheap; ~3-line Makefile addition).

## Assumptions Log

> All claims in this research were either VERIFIED (read direct file content / ran grep / counted lines) or CITED (referenced from CONTEXT.md / REQUIREMENTS.md / ROADMAP.md / Phase 214 RESEARCH.md as locked decisions or canonical source).

**No `[ASSUMED]` claims in this research.** Every factual claim is either:
- VERIFIED via tool (grep counts, file-content reads, codebase line numbers)
- CITED via locked decision in CONTEXT.md, REQUIREMENTS.md, ROADMAP.md, or audit doc

**Three flagged corrections to CONTEXT.md** (Pitfalls B + I + Summary §1-3) are not assumptions — they are verified-against-codebase findings that contradict CONTEXT.md's stated facts. Planner reconciles by trusting the verified findings over CONTEXT.md's wording.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| — | (no assumed claims) | — | — |

**No user confirmation needed before planning.** All decisions are locked in CONTEXT.md or verified against the codebase.

## Open Questions

1. **Does the AUDIT-04 fixture test need to verify the order of sink invocation (`DefaultAuditSink` first, then enterprise sinks), or only that BOTH ran?**
   - What we know: AUDIT-05 contract is "default sink writes its row." AUDIT-04 contract is "enterprise sink receives every event." Neither contract specifies invocation order.
   - What's unclear: Whether order is observable (it is, via the test's `received: list` order); whether order is contractually guaranteed.
   - Recommendation: TEST is order-agnostic (asserts BOTH sinks ran with same event, not that default ran first). DOCUMENTATION in `audit_emit()` docstring should note "iteration order is the registry's list order; default is registered first by lazy-default semantics, but post-overlay-registration the order depends on overlay's `setdefault + append` discipline." Out-of-scope to enforce.

2. **Should `AuditEvent` be exported from `app.modules.audit.events` AND re-exported from `app.modules.audit.service` for ergonomic single-import?**
   - What we know: 19 caller files will need both `audit_emit` (from `service`) and `AuditEvent` (from `events`).
   - What's unclear: Whether `from app.modules.audit.service import audit_emit, AuditEvent` (re-export) reads better than two imports.
   - Recommendation: Re-export `AuditEvent` from `service.py` (one line: `from app.modules.audit.events import AuditEvent  # re-export for ergonomic single-import`). Keeps the 65-site rewrite to a single import line. Planner's call.

3. **Does the audit-sink-discipline architecture test need to also exclude the test files themselves?**
   - What we know: `tests/test_lifecycle.py:421,687` calls `log_action()` directly today (test seeds an audit row).
   - What's unclear: Whether the AUDIT-02 invariant ("no `log_action(` outside `audit/service.py`") applies to test files.
   - Recommendation: Either (a) update `test_lifecycle.py` to use `audit_emit(AuditEvent(...))` (one-line change, more consistent), OR (b) add `:!backend/tests/` to the architecture test's pathspec exclusion. Recommended: (b) — tests are allowed to use internal helpers directly. Same precedent as `test_layering.py:24-28` D-09 allowlist excludes tests. Document in the test docstring.

## Environment Availability

> Phase 222 is a pure-Python code refactor + 2 new tests. No external services, no new tooling, no new compose services. The dependency audit confirms zero gaps.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | All | ✓ | ≥3.13 | — |
| FastAPI | Routers | ✓ | ≥0.115.0 | — |
| SQLAlchemy + asyncpg | DB | ✓ | ≥2.0.25 | — |
| structlog | Sink-failure logging | ✓ | ≥25.4.0 | — |
| pytest + anyio | Tests | ✓ | ≥9.0.3 | — |
| pytest-asyncio | Tests (strict mode) | ✓ | (transitive) | — |
| Docker + docker-compose | Test DB | ✓ | (existing dev env) | — |
| git ≥2.13 | Architecture test (`:!` pathspec) | ✓ | (existing dev env) | Skip via `_has_pathspec_magic()` (existing precedent) |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all deps in `pyproject.toml`, no new packages.
- Architecture: HIGH — pattern is the 5th instance of an established 4-Protocol scaffold; one departure (list-typed accessor) is well-precedented in CONTEXT.md.
- Pitfalls: HIGH — three are verified contradictions of CONTEXT.md (lazy-import locations, `user_id` nullability discussion, SC#4 vs facade); seven are forward-looking (cycle, registry pollution, test-order, etc.) drawn from the canonical Phase 220+221 reference at `tests/test_lifecycle.py`.
- Test approach: HIGH — three new tests are direct adaptations of existing patterns at `tests/test_audit.py:242-270` and `tests/test_lifecycle.py`.
- 65-site count + per-file distribution: VERIFIED — `grep -rn "log_action(" backend/app/ --include="*.py"` returns 65 lines matching CONTEXT.md's per-file breakdown exactly.

**Research date:** 2026-04-30
**Valid until:** 2026-05-30 (30 days; codebase is stable; v13.3 only adds Phase 223 in parallel which doesn't touch audit).
