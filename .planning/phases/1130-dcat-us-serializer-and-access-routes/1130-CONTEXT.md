# Phase 1130: DCAT-US Serializer and Access Routes - Context

**Gathered:** 2026-05-27
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Emit DCAT-US 3.0 metadata through compatibility-preserving routes.

</domain>

<decisions>
## Implementation Decisions

- Keep existing `/datasets/dcat/` and per-dataset W3C DCAT behavior unchanged.
- Add explicit `/datasets/dcat-us/3.0/` and per-dataset `/datasets/{dataset_id}/dcat-us/3.0/` routes.
- Reuse existing visibility filtering and dataset access helpers.
- Emit mandatory DCAT-US fields only when current metadata supports them; validation will report gaps.

</decisions>

<code_context>
## Existing Code Insights

- `router_export.py` already applies `apply_visibility_filter` to catalog export and `check_dataset_access_or_anonymous` to per-dataset export.
- `test_dcat.py` provides reusable dataset factories and route expectations.

</code_context>

<specifics>
## Specific Ideas

- Add `app.standards.dcat_us.service`.
- Factor shared DCAT relationship loading in the export router.
- Add route tests for new DCAT-US paths and keep W3C DCAT tests passing.

</specifics>

<deferred>
## Deferred Ideas

- Validation report endpoints are Phase 1131.

</deferred>
