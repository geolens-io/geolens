---
phase: 223-marketplace-billing-extraction
plan: 01
subsystem: platform-extensions
tags: [protocol, extensions, billing, scaffolding, billing-extension]
dependency_graph:
  requires:
    - 222-05-SUMMARY.md  # AuditSink pattern this plan mirrors verbatim
  provides:
    - BillingExtension Protocol (protocols.py)
    - DefaultBillingExtension (defaults.py)
    - get_billing_extensions() accessor (__init__.py)
    - backend/tests/test_billing_extension.py (Wave-0 BILLING-01 tests)
  affects:
    - backend/app/platform/extensions/  # additive only, no existing symbols changed
tech_stack:
  added: []
  patterns:
    - list-shape Protocol slot (mirrors AuditSink / Phase 222)
    - lazy-default accessor (returns [Default*()] when slot missing, never None)
    - @runtime_checkable Protocol (5th instance in protocols.py)
    - async-only extension method (D-08)
key_files:
  created:
    - backend/tests/test_billing_extension.py
  modified:
    - backend/app/platform/extensions/protocols.py
    - backend/app/platform/extensions/defaults.py
    - backend/app/platform/extensions/__init__.py
decisions:
  - "FastAPI imported at module-top of protocols.py (NOT in TYPE_CHECKING) because @runtime_checkable Protocols need annotation types resolvable at runtime for isinstance() checks — per 223-RESEARCH.md Finding 3, no import cycle exists"
  - "list-shape accessor (get_billing_extensions() -> list[BillingExtension]) mirrors get_audit_sinks() verbatim — D-06 decided list-shape is forward-compatible and maintains one accessor pattern across the codebase"
  - "DefaultBillingExtension is async no-op (async def on_startup(self, app): return) — D-07/D-08, matching DefaultIdentityExtension discipline"
  - "asyncio import removed from test file (unused in Wave-0; Plan 02 will add it when dispatch tests land)"
metrics:
  duration: ~10 minutes
  completed: 2026-04-30
  tasks_completed: 3
  tasks_total: 3
  files_created: 1
  files_modified: 3
---

# Phase 223 Plan 01: BillingExtension Protocol Scaffolding Summary

One-liner: `BillingExtension` 5th `@runtime_checkable` Protocol + `DefaultBillingExtension` no-op + `get_billing_extensions()` list-shape accessor — mirroring Phase 222 AuditSink pattern verbatim.

## What Was Built

### 4 New Symbols

**1. `BillingExtension` Protocol** (`backend/app/platform/extensions/protocols.py`)
- 5th `@runtime_checkable` Protocol in the file alongside `BrandingExtension`, `AuditExtension`, `AuthExtension`, `AuditSink`
- Signature: `async def on_startup(self, app: FastAPI) -> None`
- `from fastapi import FastAPI` added at module-top (safe: FastAPI imports zero `app.*` modules — per 223-RESEARCH.md Finding 3; same precedent as Phase 222's `AsyncSession` import)

**2. `DefaultBillingExtension`** (`backend/app/platform/extensions/defaults.py`)
- 6th default class; community-edition no-op: `async def on_startup(self, app) -> None: return`
- Loosely typed `app` parameter on the default (precedent: `DefaultIdentityExtension`, `DefaultAuditSink`) — the Protocol carries the typed contract; the default doesn't need the import
- `isinstance(DefaultBillingExtension(), BillingExtension)` is `True` (structural subtyping verified)

**3. `get_billing_extensions()` typed accessor** (`backend/app/platform/extensions/__init__.py`)
- Returns `[DefaultBillingExtension()]` when `_extensions["billing_extensions"]` slot is missing (lazy default — D-06)
- Returns defensive `list(exts)` copy when slot is populated (prevents registry mutation mid-iteration)
- Mirrors `get_audit_sinks()` shape verbatim; `DefaultBillingExtension` and `BillingExtension` added to imports in alphabetical order

**4. `backend/tests/test_billing_extension.py`** — Wave-0 BILLING-01 unit smoke tests
- `test_billing_extension_protocol_shape`: Protocol is `@runtime_checkable`; `DefaultBillingExtension` satisfies it structurally; `on_startup` is async (D-06, D-08)
- `test_default_billing_extension_is_noop`: `on_startup` returns `None`, does not raise (D-07)
- `test_get_billing_extensions_default_fallback`: accessor returns `[DefaultBillingExtension()]` when slot missing; never returns `None` (D-06)
- File header documents Plan 02 (dispatch tests), Plan 03 (settings removal), Plan 05 (enterprise overlay) future contributions

## Key Decisions

### FastAPI import at module-top (not in TYPE_CHECKING)
`from fastapi import FastAPI` is at module-top of `protocols.py` because `@runtime_checkable` Protocols need annotation types resolvable at runtime when `isinstance(obj, BillingExtension)` is called in tests. Moving it into `TYPE_CHECKING` would cause an `AttributeError` or `NameError` at runtime. Confirmed zero import cycle via 223-RESEARCH.md Finding 3.

### List-shape accessor (D-06)
`get_billing_extensions() -> list[BillingExtension]` (plural, list-shape) mirrors `get_audit_sinks()` verbatim. Cost: one extra `[]` of syntax. Benefit: forward-compatible (future overlays can register multiple billing extensions), consistent with Phase 222's one-pattern discipline.

### asyncio removed from Wave-0 test file
`import asyncio` was in the plan's template but unused in the three Wave-0 tests (dispatch tests in Plan 02 will need it). Removed per ruff F401 — Plan 02 will re-add it when the dispatch test functions land.

## Test Results

```
tests/test_billing_extension.py::test_billing_extension_protocol_shape PASSED
tests/test_billing_extension.py::test_default_billing_extension_is_noop PASSED
tests/test_billing_extension.py::test_get_billing_extensions_default_fallback PASSED
3 passed, 1 warning in 1.26s
```

Phase 222 regression: `test_audit.py`, `test_lifecycle.py`, `test_audit_sink.py`, `test_layering.py` — 27 passed, 0 failed.

## What Is Unblocked

These symbols are now available for:
- **Plan 02** (lifespan dispatch): imports `get_billing_extensions` from `app.platform.extensions` and `BillingExtension` from `app.platform.extensions.protocols` to build the `asyncio.wait_for` dispatch loop in `api/main.py`
- **Plan 03** (settings removal + marketplace.py deletion): all scaffolding symbols are in place; Plan 03 can safely delete `core/marketplace.py` and remove Settings fields without breaking the extension layer
- **Plan 04** (architecture guard): extends `test_layering.py` — no dependency on Plan 01 symbols, but runs after the scaffolding is committed
- **Plan 05** (enterprise overlay): `MarketplaceBillingExtension` in `geolens-enterprise` imports `DefaultBillingExtension` from `app.platform.extensions.defaults` — this plan makes that import resolvable

## Cross-Repo Note

Plan 05 will amend `geolens-enterprise/geolens_enterprise/__init__.py:register_extensions` to add:
```python
billing_extensions = registry.setdefault("billing_extensions", [DefaultBillingExtension()])
billing_extensions.append(MarketplaceBillingExtension())
```
The `DefaultBillingExtension` import (`from app.platform.extensions.defaults import DefaultBillingExtension`) is now resolvable from this plan's `defaults.py` addition.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed unused `asyncio` import from test file**
- **Found during:** Task 3 ruff check
- **Issue:** The plan's template included `import asyncio` which is unused in Wave-0 tests (needed by Plan 02's dispatch tests)
- **Fix:** Removed `import asyncio` from `test_billing_extension.py`
- **Files modified:** `backend/tests/test_billing_extension.py`
- **Commit:** 865d2302

None other — plan executed with one minor lint fix.

## Threat Flags

None. No new network endpoints, auth paths, file access patterns, or schema changes introduced. The `BillingExtension` Protocol and `_extensions["billing_extensions"]` slot mutation trust boundary is documented in the plan's threat model (T-223-04: Tampering — accepted, documented in `get_billing_extensions()` docstring).

## Self-Check: PASSED

Files created/modified exist and commits verified below.
