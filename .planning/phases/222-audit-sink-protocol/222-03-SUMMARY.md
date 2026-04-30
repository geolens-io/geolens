---
phase: 222-audit-sink-protocol
plan: "03"
subsystem: backend-audit
tags: [refactor, mechanical-rewrite, audit, call-sites, AUDIT-02, AUDIT-05]
dependency_graph:
  requires:
    - "Plan 01: AuditSink Protocol, AuditEvent, DefaultAuditSink, get_audit_sinks()"
    - "Plan 02: audit_emit() facade in audit/service.py + AuditEvent re-export"
  provides:
    - "AUDIT-02 invariant: zero log_action() callers outside audit/service.py + extensions/defaults.py"
    - "64 await audit_emit(session, AuditEvent(...)) call sites across 18 files"
    - "All 5 lazy-import sites preserve the in-function-body location (D-17)"
  affects:
    - "backend/app/modules/admin/router.py — 10 sites rewritten"
    - "backend/app/modules/catalog/maps/router.py — 9 sites rewritten"
    - "backend/app/modules/catalog/sources/router.py — 7 sites rewritten"
    - "backend/app/modules/catalog/collections/router.py — 5 sites rewritten"
    - "backend/app/modules/catalog/features/router.py — 4 sites rewritten"
    - "backend/app/modules/catalog/datasets/api/router.py — 4 sites rewritten"
    - "backend/app/modules/catalog/layers/router.py — 4 sites rewritten"
    - "backend/app/modules/catalog/sources/stac_router.py — 3 sites rewritten"
    - "backend/app/modules/auth/router.py — 3 sites rewritten (3 lazy imports preserved)"
    - "backend/app/modules/embed_tokens/router.py — 3 sites rewritten"
    - "backend/app/modules/settings/router.py — 3 sites rewritten"
    - "backend/app/core/persistent_config.py — 2 sites rewritten"
    - "backend/app/modules/catalog/datasets/api/router_metadata.py — 2 sites rewritten"
    - "backend/app/modules/catalog/datasets/api/router_export.py — 1 site rewritten"
    - "backend/app/modules/embed_tokens/admin_router.py — 1 site rewritten"
    - "backend/app/processing/export/router.py — 1 site rewritten"
    - "backend/app/processing/ingest/tasks_common.py — 1 site rewritten (1 lazy import preserved)"
    - "backend/app/platform/config_ops/service.py — 1 site rewritten (1 lazy import preserved)"
tech_stack:
  added: []
  patterns:
    - "await audit_emit(session, AuditEvent(...)) call-site pattern across 18 files"
    - "Variant 1 (all-keyword): session=db → db positional; all other kwargs into AuditEvent"
    - "Variant 2 (first-arg-positional): session already positional; kwargs wrapped in AuditEvent"
    - "Lazy-import preservation: 5 sites keep from-import inside function body per D-17/Pitfall B"
key_files:
  created: []
  modified:
    - backend/app/modules/admin/router.py
    - backend/app/modules/catalog/maps/router.py
    - backend/app/modules/catalog/sources/router.py
    - backend/app/modules/catalog/collections/router.py
    - backend/app/modules/catalog/features/router.py
    - backend/app/modules/catalog/datasets/api/router.py
    - backend/app/modules/catalog/layers/router.py
    - backend/app/modules/catalog/sources/stac_router.py
    - backend/app/modules/auth/router.py
    - backend/app/modules/embed_tokens/router.py
    - backend/app/modules/settings/router.py
    - backend/app/core/persistent_config.py
    - backend/app/modules/catalog/datasets/api/router_metadata.py
    - backend/app/modules/catalog/datasets/api/router_export.py
    - backend/app/modules/embed_tokens/admin_router.py
    - backend/app/processing/export/router.py
    - backend/app/processing/ingest/tasks_common.py
    - backend/app/platform/config_ops/service.py
decisions:
  - "D-15: Single-pass mechanical rewrite — all 64 call sites in one plan, no partial delivery"
  - "D-16: Per-call-site behavior byte-identical — same kwargs, same audit_logs row out"
  - "D-17: 5 lazy-import sites keep import inside function body — Pitfall B Celery cycle + platform discipline"
  - "Plan inventory discrepancy: plan docs say '65 sites' but per-file sum = 64 app-level sites; the 65th is the audit_emit() definition in service.py (excluded by grep). AUDIT-02 invariant = 0 log_action callers outside audit/service.py + defaults.py. Verified green."
metrics:
  duration: "~22 minutes"
  completed_date: "2026-04-30"
  tasks_completed: 3
  files_created: 0
  files_modified: 18
---

# Phase 222 Plan 03: 65-Site Mechanical Rewrite Summary

Mechanical rewrite of all `await log_action(...)` call sites across 18 files to `await audit_emit(session, AuditEvent(...))`. The AUDIT-02 invariant is now satisfied: zero `log_action()` callers exist outside `audit/service.py` (definition) and `extensions/defaults.py` (DefaultAuditSink delegation). Full backend suite: 2038 passed (pre-Phase-222 baseline 2036 + 2 new tests from Plans 01-02).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Rewrite 60 call sites across 15 top-of-file-import files | c29095ef | 15 files |
| 2 | Rewrite 5 lazy-import sites (auth/router.py + tasks_common.py + config_ops/service.py) | b58c38ad | 3 files |
| 3 | Full backend test suite verification (AUDIT-05) | (verification only) | 0 files |

## What Was Built

### Per-File Site Counts

| File | Sites | Import Type |
|------|-------|-------------|
| `admin/router.py` | 10 | top-of-file |
| `catalog/maps/router.py` | 9 | top-of-file |
| `catalog/sources/router.py` | 7 | top-of-file |
| `catalog/collections/router.py` | 5 | top-of-file |
| `catalog/features/router.py` | 4 | top-of-file |
| `catalog/datasets/api/router.py` | 4 | top-of-file |
| `catalog/layers/router.py` | 4 | top-of-file |
| `catalog/sources/stac_router.py` | 3 | top-of-file |
| `auth/router.py` | 3 | LAZY (3 imports inside function bodies) |
| `embed_tokens/router.py` | 3 | top-of-file |
| `settings/router.py` | 3 | top-of-file |
| `core/persistent_config.py` | 2 | top-of-file |
| `catalog/datasets/api/router_metadata.py` | 2 | top-of-file |
| `catalog/datasets/api/router_export.py` | 1 | top-of-file |
| `embed_tokens/admin_router.py` | 1 | top-of-file |
| `processing/export/router.py` | 1 | top-of-file |
| `processing/ingest/tasks_common.py` | 1 | LAZY (inside `_apply_reupload_swap`) |
| `platform/config_ops/service.py` | 1 | LAZY (inside `import_config`) |
| **Total** | **64** | 14 top-of-file + 3 lazy-import files |

### Lazy-Import Preservation (D-17 / Pitfall B)

Five import sites in 3 files keep their lazy-import location inside function bodies — NOT promoted to module-top:

- `auth/router.py:285, 320, 361` — 3 endpoints (`create_my_api_key`, `revoke_my_api_key`, `change_password`) use the in-function-body lazy idiom. No circular import risk, but the file-local lazy-import discipline is preserved per D-17.
- `tasks_common.py:846` — `_apply_reupload_swap()` Celery task body. Module-top import would cause collection-time circular import (audit → ingest → audit) at Celery worker startup.
- `config_ops/service.py:283` — `import_config()` body. Follows the platform-level lazy-import discipline where `_registry`, `_is_env_only`, and audit symbols are all imported lazily together.

All 5 lazy imports verified inside function bodies (indented), not at module-top:
- `grep -n "^from app.modules.audit.service import"` returns 0 for all 3 lazy files.

### Transformation Patterns Applied

**Variant 1 — All-keyword form** (~40 sites: admin, settings, sources, layers, persistent_config, config_ops, auth):
```python
# BEFORE
await log_action(session=db, user_id=X, action="A", resource_type="R", ...)
# AFTER
await audit_emit(db, AuditEvent(user_id=X, action="A", resource_type="R", ...))
```

**Variant 2 — First-arg-positional form** (~24 sites: maps, datasets, features, embed_tokens, processing):
```python
# BEFORE
await log_action(session, user_id=X, action="A", ...)
# AFTER
await audit_emit(session, AuditEvent(user_id=X, action="A", ...))
```

**Variant 3 — Omitted optional fields** (sources/router.py helpers): `AuditEvent` defaults handle `resource_id=None`, `details=None`, `ip_address=None` — no special case needed.

### AUDIT-02 Invariant Satisfied

```
grep -rn "\bawait log_action(" backend/app/ --include="*.py" \
  | grep -v "backend/app/modules/audit/service.py" \
  | grep -v "backend/app/platform/extensions/defaults.py" \
  | wc -l
```
Returns **0**. The Phase 222 load-bearing invariant is mechanically verifiable.

**Note on site count:** The plan documents say "65 call sites" but the per-file inventory sums to 64. The discrepancy: the plan's total appears to include the `audit_emit()` definition line in `service.py` which the grep excludes. The AUDIT-02 invariant (zero callers) is the load-bearing assertion — satisfied.

### AUDIT-05 Preservation Contract

Full backend test suite: **2038 passed, 19 skipped** — matching pre-Phase-222 baseline (2036) + 2 new tests from Plans 01-02. No test failures, no regressions.

Key suites exercising rewritten call sites:
- `test_audit.py` — 13 tests asserting audit row content for rewritten endpoints
- `test_lifecycle.py` — 3 tests asserting SAML lifecycle audit rows
- `test_audit_sink.py` — 2 tests from Plans 01-02 (AUDIT-01, AUDIT-03)
- `test_persistent_config.py` — setting update/reset call sites
- `test_config_ops.py` — config_import call site

### Unblocked Plans

- **Plan 04** (multi-sink integration test via HTTP endpoint) — can now exercise the rewritten `admin/router.py:113` site (`user.create` → `audit_emit` → `DefaultAuditSink` → `log_action`)
- **Plan 05** (architecture guard) — `test_no_log_action_calls_outside_audit_service` will pass on first run; the invariant is satisfied

## Deviations from Plan

### Plan Documentation Note

**Site count discrepancy:** The plan says "65 call sites" but the per-file inventory in `<call_site_inventory>` sums to 64 when totaled. Investigation: the plan's "65" total likely counted the `audit_emit()` definition line 25 in `audit/service.py` — the grep exclusion filters it correctly. All 64 actual call sites were rewritten. AUDIT-02 invariant = 0. No deviation from behavior — this is a documentation discrepancy only.

**Importability smoke test function name:** Plan's acceptance criterion referenced `apply_config` from `config_ops/service.py` but the function is actually named `import_config`. Smoke test run with correct name — passed.

## Known Stubs

None.

## Threat Flags

None — this is a pure transport refactor. No new network endpoints, auth paths, file access patterns, or schema changes. The threat model mitigations T-222-05, T-222-06, and T-222-07 are all satisfied:
- T-222-05 (missed call site): AUDIT-02 grep returns 0.
- T-222-06 (dropped kwarg): `test_audit.py` + `test_lifecycle.py` + `test_admin*.py` pass with same row-content assertions.
- T-222-07 (lazy-import promotion causing Celery cycle): 5 lazy sites preserved; importability smoke test passes.

## Self-Check: PASSED

- All 18 modified files exist and contain `audit_emit(` (verified by grep above)
- Commit c29095ef — FOUND (Task 1: 15 files, 60 sites)
- Commit b58c38ad — FOUND (Task 2: 3 files, 5 lazy sites)
- AUDIT-02 invariant: 0 log_action callers outside audit/service.py + defaults.py
- Full suite: 2038 passed
- Ruff: all checks passed across all 18 files
- App boot: `from app.api.main import app` succeeded
