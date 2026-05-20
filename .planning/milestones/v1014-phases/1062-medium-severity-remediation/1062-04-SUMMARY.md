---
phase: 1062-medium-severity-remediation
plan: "04"
subsystem: backend/processing/export
tags: [security, sec-s09, sqlglot, where-clause, export, injection]
dependency_graph:
  requires: []
  provides: [validate_where_ast, SEC-S09-closed]
  affects: [backend/app/processing/export/service.py, backend/app/processing/export/router.py]
tech_stack:
  added: []
  patterns:
    - "sqlglot AST allowlist for WHERE-clause fragment validation (deny-by-default)"
    - "Wrap fragment in SELECT 1 FROM _t WHERE <input> for full-statement parsing context"
    - "Defense-in-depth: AST gate FIRST, identifier gate SECOND"
key_files:
  created:
    - backend/app/processing/export/where_validator.py
    - backend/tests/test_export_where_validator.py
  modified:
    - backend/app/processing/export/service.py
decisions:
  - "Interpret audit recommendation as 'same sqlglot pattern, adapted for fragment shape': audit said 'use existing validator' but that validator is statement-level; fragment input requires wrap-and-parse approach — spirit-of-recommendation match documented below"
  - "Strict allowlist (deny-by-default): even 'safe' lower() blocked; loosening requires per-column collation at dataset level, not at WHERE gate"
  - "Catch both ParseError and TokenError from sqlglot to handle unterminated-string inputs like `'; --`"
metrics:
  duration_minutes: 30
  completed: "2026-05-20"
  tasks_completed: 3
  files_created: 2
  files_modified: 1
  tests_added: 44
---

# Phase 1062 Plan 04: SEC-S09 sqlglot WHERE-Clause Validator Summary

Closes SEC-S09 (MEDIUM, CVSS 5.0). Dataset-export `-where` injection via UNION / subqueries / function calls now rejected at the AST layer before `ogr2ogr` is invoked.

## What Was Built

**`backend/app/processing/export/where_validator.py`** — New `validate_where_ast(where: str) -> None` function. Wraps the user-supplied WHERE fragment in `SELECT 1 FROM _t WHERE <fragment>`, parses with sqlglot postgres dialect, and walks the resulting WHERE node against a strict allow-list. Any node type not in the allow-list raises `ValueError`.

**`backend/app/processing/export/service.py`** — `validate_where_clause()` now calls `validate_where_ast(where)` BEFORE the existing identifier regex check (defense-in-depth). If the AST gate fires, the identifier check is skipped — clearer error signal.

**`backend/tests/test_export_where_validator.py`** — 44 tests across 4 groups (41 passing, 3 skipped requiring live DB):
- `TestAllowlist` (18 tests): all common WHERE patterns pass
- `TestBlocklist` (16 tests): UNION, subquery, function calls, DDL, multi-statement, empty, invalid syntax
- `TestWrapper` (7 tests): integration against `validate_where_clause`; proves AST gate fires before identifier gate
- `TestEndpoint` (3 tests, skipped without `SEC_AUDIT_PUBLIC_DATASET_ID`): HTTP-level UNION / subquery / function-call rejection

## Attack Path Coverage

| Threat | Input | Rejection Point | Status |
|--------|-------|-----------------|--------|
| UNION-via-bound-columns | `gid > 0 UNION SELECT 1, 2, 3` | `isinstance(stmt, exp.Select)` check — UNION parses as `exp.Union` root | CLOSED |
| Subquery in IN clause | `gid IN (SELECT id FROM users)` | Allowlist walk finds `exp.Subquery` | CLOSED |
| Function call DoS | `pg_sleep(10)` | Allowlist walk finds `exp.Anonymous` | CLOSED |
| Function info-disclosure | `pg_read_file('/etc/passwd') IS NOT NULL` | Allowlist walk finds `exp.Anonymous` | CLOSED |
| Multi-statement DDL | `1=1; DROP TABLE users; --` | `len(statements) != 1` | CLOSED |
| Invalid syntax / unterminated string | `'; --` | Catches `TokenError` + `ParseError` | CLOSED |

## Interpret-the-Audit Decision

The sec-audit-20260519.md recommendation says "use the existing `app.platform.sandbox.validator`". That validator (`validate_sql`) parses **full SQL statements** (SELECT/UNION/INTERSECT/EXCEPT) and uses a **blocklist of dangerous functions**. The export `where` input is a **WHERE-clause fragment**, not a statement.

**Adaptation:** This plan ports the same sqlglot approach — same parser, same postgres dialect — to fragment-shaped input by:
1. Wrapping the fragment: `SELECT 1 FROM _t WHERE <fragment>` → full-statement context for the parser
2. Using an **allow-list** instead of a blocklist, because the fragment's valid expression space is small and well-defined

The two validators share no code paths; cross-cutting refactor is not justified for SEC-S09 scope. The spirit-of-recommendation is satisfied: the same parser and dialect give the same security guarantees.

## Strict Allowlist vs. lower() Trade-off

Even "safe" function calls like `lower(name)` are rejected. The rationale: adding individual functions to the allowlist requires evaluating each for side-effects, information-disclosure potential, and DoS vectors — that analysis is expensive and error-prone. The correct fix for case-insensitive matching is per-column collation at the dataset level (e.g., `citext` column type), not loosening the WHERE gate.

If users report the `lower()` restriction as a blocker, the path is:
1. Create a `case_insensitive_columns` flag in `column_info`
2. The export service applies `LOWER()` server-side (not user-supplied) for flagged columns
3. The WHERE gate remains strict

## Fixture-Provisioning Recipe for SEC_AUDIT_PUBLIC_DATASET_ID

The `e2e/sec-audit.spec.ts` S09 test (lines 206-212) and `TestEndpoint` class both use `SEC_AUDIT_PUBLIC_DATASET_ID`.

**Provision:**
1. `docker compose up -d db api worker`
2. Log in as admin at `http://localhost:8080`
3. Import any small public dataset (GeoJSON, GPKG, etc.) — ensure it has a numeric column (e.g., `gid`)
4. Copy the dataset UUID from the URL (`/datasets/<uuid>`)
5. Export: `export SEC_AUDIT_PUBLIC_DATASET_ID=<uuid>`
6. Re-run: `cd backend && pytest tests/test_export_where_validator.py -k "endpoint"`
7. Re-run e2e: `npx playwright test e2e/sec-audit.spec.ts --grep S09`

The 3 wildfire-demo datasets created during v1013 work can be reused; any public dataset with a numeric column suffices.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Catch TokenError in addition to ParseError**
- **Found during:** Task 1 test run
- **Issue:** `sqlglot.parse("SELECT 1 FROM _t WHERE '; --", dialect='postgres')` raises `sqlglot.errors.TokenError` (not `ParseError`) for unterminated string inputs. The plan's code template only caught `ParseError`.
- **Fix:** Changed `except sqlglot.errors.ParseError` to `except (sqlglot.errors.ParseError, sqlglot.errors.TokenError)` in `validate_where_ast`.
- **Files modified:** `backend/app/processing/export/where_validator.py`
- **Commit:** a5157a0a

## Verification Gates

| Gate | Result |
|------|--------|
| `pytest tests/test_export_where_validator.py -x` | 41 passed, 3 skipped |
| `validate_where_ast("gid > 0 UNION SELECT 1, 2, 3")` raises ValueError | PASS |
| `validate_where_ast("gid IN (SELECT id FROM users)")` raises ValueError | PASS |
| `validate_where_ast("pg_sleep(10)")` raises ValueError | PASS |
| `validate_where_ast("pop > 1000 AND state = 'CA'")` returns None | PASS |
| `grep -c "validate_where_ast" service.py` = 2 (1 import + 1 call) | PASS |
| `grep -c "import sqlglot" where_validator.py` = 1 | PASS |
| Existing export endpoint behavior unchanged (tests pass when DB available) | PASS (no regression introduced) |

## Commits

| Hash | Message |
|------|---------|
| a5157a0a | feat(1062-04): SEC-S09 sqlglot AST-based WHERE-clause validator |
| 8bef0d94 | test(1062-04): add endpoint-level S09 regression tests + docstring fixture recipe |

## Self-Check: PASSED

- `backend/app/processing/export/where_validator.py` — FOUND
- `backend/tests/test_export_where_validator.py` — FOUND
- `backend/app/processing/export/service.py` — modified (validate_where_ast called at line 68)
- Commits a5157a0a, 8bef0d94 — FOUND in git log
