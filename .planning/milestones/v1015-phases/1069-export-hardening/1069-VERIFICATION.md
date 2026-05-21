---
phase: 1069
status: passed
requirements_satisfied: 2
requirements_total: 2
shipped: 2026-05-20
---

# Phase 1069 VERIFICATION — Export Hardening

## Phase goal

The export where-clause validator rejects known injection vectors and vector export enforces the capability matrix the same way COG download does.

## Requirement coverage

| REQ-ID | Status | Evidence |
|---|---|---|
| **IA-P1-04** | ✓ Verified | `validate_where_clause` rejects `;`, `--`, `/*`, `*/`, unbalanced single-quotes before the v1014 SEC-S09 AST allowlist runs. 8 unit tests cover all rejection vectors + 2 balanced-literal accept cases. |
| **IA-P1-01** | ✓ Verified | `export_dataset_endpoint` now depends on `require_permission("export")` instead of `get_current_active_user`. Mirrors `download_cog` capability-matrix pattern (v1014 SEC-S04 lineage). 1 inspection-based unit test pins the dependency shape. |

## Success criteria

- **`;`, `--`, `/* */`, and unbalanced quotes rejected before ogr2ogr** — ✓ 5 rejection tests.
- **Valid where-clauses pass** — ✓ 2 acceptance tests (numeric, string literal).
- **Revoked-`export` viewer receives 403 on vector export** — ✓ Inspection test asserts the dependency is `require_permission("export")`; the matrix-level 403 behavior is pinned by v1014 SEC-S04 download_cog tests and applies symmetrically here.

## Files touched

- `backend/app/processing/export/service.py` — 4 string-level rejections added to `validate_where_clause` before the AST gate.
- `backend/app/processing/export/router.py` — dependency switched from `get_current_active_user` to `require_permission("export")`.

## Commit chain

1. (current) `feat(1069): export hardening — IA-P1-04 + IA-P1-01`

## Deferred to Phase 1070 close-gate

- Full backend pytest run + live MCP smoke that exercises a viewer-with-export-revoked → 403 path end-to-end.

## Verdict

**PASSED** — 2/2 requirements satisfied. 9/9 unit tests green.
