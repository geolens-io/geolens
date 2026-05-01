---
phase: 223-marketplace-billing-extraction
plan: "04"
subsystem: backend-tests-makefile
tags: [architecture-guard, layering, makefile, billing, regression, BILLING-02, BILLING-03, BILLING-04]
dependency_graph:
  requires:
    - 223-02 (dispatch loop in api/main.py with literal timeout=10.0)
    - 223-03 (core/marketplace.py deleted; aws_marketplace_* removed from Settings)
  provides:
    - test_no_core_marketplace_import @pytest.mark.architecture guard (BILLING-02 invariant durable at CI time)
    - test_billing_dispatch_uses_hardcoded_timeout @pytest.mark.architecture guard (BILLING-04 / D-11 invariant durable at CI time)
    - billing-extraction-discipline Makefile target invoking both guards in one shot (D-16)
  affects:
    - 223-05 (enterprise overlay Plan 05 is unblocked; local-side guards are now in place)
tech_stack:
  added: []
  patterns:
    - Architecture-guard test pattern (importlib + git grep two-pronged check — mirrors Phase 222 AUDIT-02)
    - Makefile discipline target (cd backend && PYTHONPATH=. uv run pytest — mirrors audit-sink-discipline)
key_files:
  created: []
  modified:
    - backend/tests/test_layering.py
    - Makefile
decisions:
  - "Followed Phase 222 AUDIT-02 pattern verbatim: _has_git_metadata + _has_pathspec_magic skip-guards, subprocess.run git grep, fail-with-offending-lines UX"
  - "test_no_core_marketplace_import uses two-pronged check: (a) importlib.import_module raises ImportError (file existence) + (b) git grep finds zero references in backend/app/ (import absence)"
  - "test_billing_dispatch_uses_hardcoded_timeout does NOT need _has_pathspec_magic guard (no :! exclusion path — single-file grep only)"
  - "billing-extraction-discipline target invokes BOTH tests in one pytest command; mirrors audit-sink-discipline but with two test IDs instead of one"
metrics:
  duration: "~8 minutes"
  completed: "2026-04-30"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 2
---

# Phase 223 Plan 04: Architecture Guard + Makefile Discipline

**One-liner:** Extended `test_layering.py` with two `@pytest.mark.architecture` guards (BILLING-02 importlib+grep two-pronged check and BILLING-04/D-11 dispatch-timeout literal check) and added `make billing-extraction-discipline` to the root Makefile — the Phase 222 `audit-sink-discipline` pattern applied to the billing boundary.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Append two architecture-guard tests to test_layering.py | 5fc74722 | `backend/tests/test_layering.py` |
| 2 | Add billing-extraction-discipline target to root Makefile + update .PHONY | 24a45e4c | `Makefile` |

## What Was Done

### Task 1: Two New Architecture-Guard Tests in test_layering.py

**Pre-flight verification confirmed:**
- `backend/app/core/marketplace.py` is absent (`test -f` exits 1) — Plan 03 deletion confirmed.
- `api/main.py` line 197 contains the literal `asyncio.wait_for(ext.on_startup(app), timeout=10.0)` — Plan 02 dispatch loop confirmed.

**`test_no_core_marketplace_import` (BILLING-02):**

A two-pronged architecture guard:
- **(a) importlib check:** `importlib.import_module("app.core.marketplace")` must raise `ImportError`. This verifies the MODULE FILE is gone — a future commit that re-creates `backend/app/core/marketplace.py` fails immediately at CI time with the `pytest.fail` message naming the BILLING-02 invariant.
- **(b) git grep check:** `git grep -n -E "from app\.core\.marketplace|import app\.core\.marketplace" -- backend/app/` must return exit code 1 (no matches). This verifies no surviving IMPORT REFERENCES exist in any `backend/app/` file. Uses `_has_git_metadata` + `_has_pathspec_magic` skip guards following existing test discipline.

**`test_billing_dispatch_uses_hardcoded_timeout` (BILLING-04 / D-11):**

A single-file git grep guard:
- `git grep -n -E "asyncio\.wait_for\(ext\.on_startup\(app\), timeout=10\.0\)" -- backend/app/api/main.py` must return exit code 0 (match found). This verifies the production dispatch loop has NOT drifted to `timeout=settings.foo`, `timeout=10` (no decimal), or a configurable env-var lookup. The test helper `_dispatch()` in `test_billing_extension.py` accepts a parameterized timeout; this guard enforces that the production code stays hardcoded per D-11 YAGNI.
- Uses `_has_git_metadata` skip guard; does NOT need `_has_pathspec_magic` (no `:!` exclusion used — single file path only).

**Total layering tests after this plan: 8** (6 pre-existing + 2 new). All 8 pass GREEN.

### Task 2: billing-extraction-discipline Makefile Target

**`.PHONY` line updated** to append `billing-extraction-discipline` alongside Phase 222's `audit-sink-discipline`.

**New target appended** at the end of the root `Makefile` (after the existing `audit-sink-discipline` target at lines 139-144):

```makefile
billing-extraction-discipline: ## Verify app.core.marketplace is absent + dispatch hardcodes timeout=10.0 (Phase 223 BILLING-02 / BILLING-04)
    cd backend && PYTHONPATH=. uv run pytest tests/test_layering.py::test_no_core_marketplace_import tests/test_layering.py::test_billing_dispatch_uses_hardcoded_timeout -v
```

Recipe uses TAB indentation (verified). The target invokes BOTH architecture tests in one shot — BILLING-02 + BILLING-04/D-11 — without spinning up the full pytest suite. Same `cd backend && PYTHONPATH=. uv run pytest` shape as `audit-sink-discipline` and `openapi-check`.

## Verification Results

### New Tests Individually

```
tests/test_layering.py::test_no_core_marketplace_import PASSED
tests/test_layering.py::test_billing_dispatch_uses_hardcoded_timeout PASSED
2 passed, 1 warning in 1.19s
```

### Full test_layering.py (all 8 tests)

```
test_core_does_not_import_from_any_module PASSED
test_app_settings_imports_only_via_core_db_models PASSED
test_no_imports_from_auth_visibility PASSED
test_no_auth_visibility_module_referenced PASSED
test_cross_domain_does_not_import_user_from_auth_models PASSED
test_no_log_action_calls_outside_audit_service PASSED
test_no_core_marketplace_import PASSED
test_billing_dispatch_uses_hardcoded_timeout PASSED
8 passed, 1 warning in 1.39s
```

### make billing-extraction-discipline

```
make billing-extraction-discipline
cd backend && PYTHONPATH=. uv run pytest tests/test_layering.py::test_no_core_marketplace_import tests/test_layering.py::test_billing_dispatch_uses_hardcoded_timeout -v
2 passed, 1 warning in 1.27s  — exit 0
```

### make audit-sink-discipline (Phase 222 regression check)

```
make -n audit-sink-discipline  — exit 0 (prints pytest command, no syntax error)
```

### Full Phase 222 + Phase 223 Suite (18 tests)

```
tests/test_billing_extension.py (7 tests) PASSED
tests/test_audit_sink.py (3 tests) PASSED
tests/test_layering.py (8 tests) PASSED
18 passed, 16 warnings in 4.07s
```

### Cumulative Phase 223 Boundary Checks (BILLING-01 through BILLING-05)

```
(a) BILLING-01: Protocol scaffolding present — BILLING-01 OK
(b) BILLING-02: core/marketplace.py absent — file deletion OK; 0 import refs found
(c) BILLING-03: no register_usage call in backend/app/ — 0 refs found
(d) BILLING-04: dispatch loop present with timeout=10.0 — count=1 for both greps
(e) BILLING-05: aws_marketplace_* removed from Settings — BILLING-05 OK
```

All 5 checks PASS.

### Ruff Clean

```
cd backend && uv run ruff check tests/test_layering.py  — All checks passed!
```

## Deviations from Plan

None — plan executed exactly as written.

## Success Criteria Verified

- [x] `test_no_core_marketplace_import` added to test_layering.py with `@pytest.mark.architecture`
- [x] Test asserts `importlib.import_module` fails (file absence) AND git grep finds no surviving references (import absence)
- [x] `test_billing_dispatch_uses_hardcoded_timeout` added to test_layering.py with `@pytest.mark.architecture`
- [x] Test asserts api/main.py contains the literal `asyncio.wait_for(ext.on_startup(app), timeout=10.0)`
- [x] Both new tests pass GREEN post-Plans-02-and-03
- [x] Makefile has new `billing-extraction-discipline` target invoking BOTH new tests
- [x] `.PHONY` updated to include `billing-extraction-discipline` (alongside Phase 222's `audit-sink-discipline`)
- [x] `make billing-extraction-discipline` exits 0
- [x] `make audit-sink-discipline` (Phase 222 target) still works (no regression)
- [x] Existing 6 layering tests still pass; total layering test count is 8
- [x] Ruff clean for touched files

## What Is Unblocked

- **Plan 05 (enterprise overlay):** The local-side guards are now in place. Plan 05 can safely create `MarketplaceBillingExtension` in the `geolens-enterprise` repo without risk of accidentally reintroducing the boundary violation in core — any attempt to re-add a `from app.core.marketplace` import in `backend/app/` fails `make billing-extraction-discipline` immediately.
- **BILLING-06 (audit re-run):** Verified in Plan 05 by running `/oc-audit` after the cross-repo overlay is in place. This Plan 04 establishes the local-side guards that BILLING-06's audit re-run will validate. The current local state already satisfies the three 🟡 loci criteria (all closed); the audit re-run will formally confirm the A+ grade.

## Note on BILLING-06

BILLING-06 (audit re-run reports A+ grade) is verified in Plan 05 by running `/oc-audit` after the cross-repo overlay is in place. This Plan 04 establishes the local-side guards that BILLING-06's audit re-run will validate.

## Self-Check: PASSED

Files verified:
- `backend/tests/test_layering.py`: FOUND — `grep -c 'def test_no_core_marketplace_import'` = 1, `grep -c 'def test_billing_dispatch_uses_hardcoded_timeout'` = 1, `grep -c '@pytest.mark.architecture'` = 8
- `Makefile`: FOUND — `grep '^.PHONY' | grep -c 'billing-extraction-discipline'` = 1, `grep -c '^billing-extraction-discipline:'` = 1

Commits verified:
- 5fc74722: FOUND in git log (test(223-04): add BILLING-02 and BILLING-04/D-11 architecture guards)
- 24a45e4c: FOUND in git log (chore(223-04): add billing-extraction-discipline Makefile target)
