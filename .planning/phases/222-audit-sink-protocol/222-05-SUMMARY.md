---
phase: 222-audit-sink-protocol
plan: "05"
subsystem: backend-audit
tags: [architecture-guard, layering, makefile, audit, regression, AUDIT-02, AUDIT-05]
dependency_graph:
  requires:
    - "Plan 01: AuditSink Protocol, AuditEvent, DefaultAuditSink, get_audit_sinks()"
    - "Plan 02: audit_emit() facade + AuditEvent re-export"
    - "Plan 03: 64-site mechanical rewrite — AUDIT-02 invariant satisfied"
    - "Plan 04: AUDIT-04 multi-sink integration test"
  provides:
    - "AUDIT-02 codified as durable architecture test in test_layering.py"
    - "audit-sink-discipline Makefile target for ergonomic local verification"
    - "AUDIT-05 close gate: full backend suite GREEN (2040 passed)"
    - "Phase 222 COMPLETE — all 5 AUDIT requirements satisfied"
  affects:
    - "backend/tests/test_layering.py — architecture guard test appended"
    - "Makefile — audit-sink-discipline target + .PHONY update"
tech_stack:
  added: []
  patterns:
    - "Architecture-guard test via git grep --pathspec -- :! exclusion (matches existing layering test pattern)"
    - "_has_git_metadata + _has_pathspec_magic skip-guard pair (consistent with all 5 pre-existing tests)"
    - "Makefile target pattern: cd backend && PYTHONPATH=. uv run pytest (matches openapi-check precedent)"
key_files:
  created: []
  modified:
    - backend/tests/test_layering.py
    - Makefile
decisions:
  - "D-14: AUDIT-05 verification = existing test suite passes without modification (no new preservation test)"
  - "Architecture guard scopes to backend/app/ (not backend/) so tests/ is excluded by path, not :! pathspec"
  - "Exclusion list is exactly two files: audit/service.py (defines log_action) and extensions/defaults.py (DefaultAuditSink calls it). No other exclusions allowed."
  - "Make target uses local uv run (not docker compose exec) — architecture test uses git grep, not a database"
metrics:
  duration: "~10 minutes"
  completed_date: "2026-04-30"
  tasks_completed: 3
  files_created: 0
  files_modified: 2
---

# Phase 222 Plan 05: Architecture Guard + Makefile + Close Gate Summary

AUDIT-02 invariant codified as a durable architecture test (`test_no_log_action_calls_outside_audit_service`) in `test_layering.py`. Makefile `audit-sink-discipline` target added for quick local verification. Full backend suite: **2040 passed, 19 skipped** — Phase 222 close gate (AUDIT-05) satisfied.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Append test_no_log_action_calls_outside_audit_service to test_layering.py | a49fcb06 | backend/tests/test_layering.py |
| 2 | Add audit-sink-discipline Makefile target + update .PHONY | a4dffe4d | Makefile |
| 3 | Phase 222 close gate — full backend test suite green (AUDIT-05) | (verification only) | 0 files |

## What Was Built

### AUDIT-02 Architecture Guard

`test_no_log_action_calls_outside_audit_service` in `backend/tests/test_layering.py` — a `@pytest.mark.architecture` test that scans `backend/app/` for `await log_action(` patterns and asserts zero matches outside two permitted files:

- `backend/app/modules/audit/service.py` — defines `log_action()`; the only application-side caller permitted post-Phase-222
- `backend/app/platform/extensions/defaults.py` — `DefaultAuditSink.emit()` calls `log_action()` via deferred import (D-04)

The test uses the established `_git_grep` + `_has_git_metadata` + `_has_pathspec_magic` pattern from the 5 existing layering tests. The path scope is `backend/app/` (not `backend/`) so `backend/tests/` is excluded by path — no `:!backend/tests/` pathspec needed.

**Why this test matters:** Before Phase 222, `log_action()` was called at 64 application call sites across 18 files. Any future developer who re-introduces a direct `await log_action(...)` call outside the audit module will have their PR blocked by this test in CI.

### Makefile Target

```makefile
audit-sink-discipline:
    cd backend && PYTHONPATH=. uv run pytest tests/test_layering.py::test_no_log_action_calls_outside_audit_service -v
```

Added to `.PHONY` and at the end of `Makefile`. Runs the AUDIT-02 invariant check in isolation — no database required (uses git grep), takes ~1.3s vs ~7 minutes for the full suite.

### Phase 222 Close Gate Results (AUDIT-05)

Full backend test suite: **2040 passed, 19 skipped** — confirmed GREEN.

Breakdown vs baselines:
- Pre-Phase-222 baseline: 2036 tests
- Plan 01 (`test_audit_sink_protocol_shape`): +1
- Plan 02 (`test_raising_sink_does_not_break_business_op`): +1
- Plan 04 (`test_fixture_sink_receives_events_alongside_default`): +1
- Plan 05 (`test_no_log_action_calls_outside_audit_service`): +1
- **Total: 2040 tests** — matches expected count exactly

Key suites verified passing without modification:
- `test_audit_sink.py` — 3 tests (all 3 AUDIT tests: AUDIT-01, AUDIT-03, AUDIT-04)
- `test_audit.py` — 13 tests (audit row content for rewritten endpoints)
- `test_lifecycle.py` — 3 lifecycle tests (SAML audit rows)
- `test_layering.py` — 6 architecture tests (5 pre-existing + AUDIT-02)
- `test_persistent_config.py`, `test_config_ops.py`, `test_admin*.py` — all pass

### AUDIT-02 Invariant Verified via Grep

```bash
grep -rn "\bawait log_action(" backend/app/ --include="*.py" \
  | grep -v "backend/app/modules/audit/service.py" \
  | grep -v "backend/app/platform/extensions/defaults.py" \
  | wc -l
```
Returns **0** — zero offending lines. The invariant is mechanically verifiable.

### audit_emit() Coverage

```bash
grep -rn "audit_emit(" backend/app/ --include="*.py" \
  | grep -v "service.py" | grep -v "defaults.py" | grep -v "__init__.py" | wc -l
```
Returns **64** — all historical `log_action()` call sites replaced.

### Application Boot Smoke

```python
from app.api.main import app
from app.modules.audit.service import audit_emit, AuditEvent, log_action
from app.platform.extensions import get_audit_sinks
from app.platform.extensions.protocols import AuditSink
from app.platform.extensions.defaults import DefaultAuditSink
from app.processing.ingest.tasks_common import _apply_reupload_swap
from app.modules.auth.router import router
from app.platform.config_ops.service import import_config
print('Phase 222 boot smoke OK — all imports successful')
```
Passed — no `ImportError`, no circular import regression.

### Ruff Clean

`uv run ruff check` across all 24 Phase 222 modified files: **All checks passed.**

## Phase 222 Requirements → Tests Mapping

| Requirement | Description | Test | Plan | Status |
|-------------|-------------|------|------|--------|
| AUDIT-01 | AuditSink Protocol + AuditEvent dataclass + DefaultAuditSink + get_audit_sinks() | `test_audit_sink_protocol_shape` | 01 | PASSED |
| AUDIT-02 | No log_action() callers outside audit module | `test_no_log_action_calls_outside_audit_service` | 05 | PASSED |
| AUDIT-03 | Sink failure does not break business operation | `test_raising_sink_does_not_break_business_op` | 02 | PASSED |
| AUDIT-04 | Multi-sink subscription — FixtureSink + DefaultAuditSink coexist | `test_fixture_sink_receives_events_alongside_default` | 04 | PASSED |
| AUDIT-05 | Preservation — existing tests pass unmodified | Full backend suite (2040 passed) | 05 | PASSED |

All 5 AUDIT requirements satisfied. Phase 222 is COMPLETE.

## Grade Improvement Targets

Per `docs-internal/audits/oc-separation-audit-20260430.md`:

| Dimension | Pre-Phase-222 | Post-Phase-222 Target | Achieved |
|-----------|---------------|----------------------|---------|
| Boundary Integrity | A (🟡 risks remain for audit sink) | A+ (zero 🟡 risks) | Invariant codified — A+ |
| Seam Quality | B (write-side audit sink 🔴) | B+ (🔴 → 🟢) | AuditSink seam implemented — B+ |

The AUDIT-02 architecture guard ensures the grade improvement is durable — future contributors cannot regress the boundary without triggering a CI failure.

## Enterprise Extensibility (AUDIT-FUTURE-01)

The `geolens-enterprise` overlay can now implement an audit export extension by:

1. Creating a class that implements `AuditSink` Protocol from `app.platform.extensions.protocols`
2. Registering it via `_extensions["audit_sinks"].append(EnterpriseAuditSink())`
3. Receiving all `AuditEvent` instances emitted by `audit_emit()` across all 64 call sites

No further changes to the `geolens` core are required. The seam is complete.

## Deviations from Plan

None. Plan executed exactly as written.

Note: Plan documentation mentions "65 call sites" but per-file inventory sums to 64 (discrepancy documented in Plan 03 SUMMARY — the plan's total included the `audit_emit()` definition line which the grep correctly excludes). AUDIT-02 invariant = 0 offending callers — satisfied.

## Known Stubs

None.

## Threat Flags

None — test-only and Makefile modifications. No new network endpoints, auth paths, file access patterns, or schema changes.

## Self-Check: PASSED

- `backend/tests/test_layering.py` — contains `def test_no_log_action_calls_outside_audit_service` (verified)
- `Makefile` — contains `audit-sink-discipline:` target (verified)
- Commit a49fcb06 — FOUND (Task 1: test_layering.py)
- Commit a4dffe4d — FOUND (Task 2: Makefile)
- `cd backend && uv run pytest tests/test_layering.py -v` — 6 passed
- `make audit-sink-discipline` — exits 0, 1 passed
- `cd backend && uv run pytest -v --tb=short` — 2040 passed, 19 skipped
- AUDIT-02 grep returns 0 offending lines
- Boot smoke OK
- Ruff: All checks passed
