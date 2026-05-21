# Phase 1069: Export Hardening - Context

**Gathered:** 2026-05-20
**Status:** Ready for planning
**Mode:** Auto-generated (autonomous mode)

<domain>
## Phase Boundary

Two export-API hardenings:
1. **IA-P1-04** — `validate_where_clause` rejects statement terminators (`;`), comments (`--`, `/* */`), and unbalanced single-quotes via fast-path string-level checks, BEFORE the v1014 SEC-S09 AST allowlist runs.
2. **IA-P1-01** — `export_dataset_endpoint` gates on `require_permission("export")` instead of bare `get_current_active_user`. Closes the asymmetry with `router_export.download_cog` (:236-245) which already consults the capability matrix.

</domain>

<decisions>
## Implementation Decisions

- String-level rejection runs FIRST (cheaper). AST allowlist second.
- Quote-balance counts after collapsing the SQL `''` escape sequence.
- The IA-P1-01 dep is `require_permission("export")` — single capability, matches what `download_cog` already uses.

</decisions>

<code_context>
## Existing Code Insights

- `backend/app/processing/export/service.py:50` — `validate_where_clause` (modified).
- `backend/app/processing/export/where_validator.py:77` — `validate_where_ast` (v1014 SEC-S09 AST allowlist, called from `validate_where_clause`).
- `backend/app/processing/export/router.py:32` — `export_dataset_endpoint` (modified).
- `backend/app/modules/auth/dependencies.py:270` — `require_permission(...)` factory.
- `backend/app/core/permissions.py:7` — `EXPORT = "export"` constant.
- `backend/app/modules/catalog/datasets/api/router_export.py:241` — existing capability-matrix check on `download_cog`. Reference pattern.

</code_context>

<specifics>
## Specific Ideas

- The string-level checks could be a separate function for reuse, but inline is fine here — they're three trivial guards in one place.
- The test for IA-P1-01 uses `inspect.signature(...)` to assert the dependency shape. This is brittle to a refactor that renames `_permission_checker`, but accepts the trade-off because a live-FastAPI test would require a full DB + auth stack.

</specifics>

<deferred>
## Deferred Ideas

- Extend the test for IA-P1-01 to a live HTTP request that asserts 403 when "viewer" loses "export". Deferred to Phase 1070 close-gate live MCP smoke.
- Move the IA-P1-04 string-level checks into `validate_where_ast` so callers don't need to remember to invoke both. Refactor scope.

</deferred>
