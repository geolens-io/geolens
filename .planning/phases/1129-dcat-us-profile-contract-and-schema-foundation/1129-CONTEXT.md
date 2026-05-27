# Phase 1129: DCAT-US Profile Contract and Schema Foundation - Context

**Gathered:** 2026-05-27
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Establish the official DCAT-US 3.0 schema foundation and implementation contract before serializer work.

</domain>

<decisions>
## Implementation Decisions

- Keep DCAT-US 3.0 separate from the existing W3C DCAT 3 serializer.
- Vendor official GSA/dcat-us JSON Schema definitions so validation is deterministic and offline.
- Record the source commit in code and documentation.
- Do not invent contact emails or federal restriction metadata; validation must surface metadata gaps.

</decisions>

<code_context>
## Existing Code Insights

- Current W3C DCAT output lives in `backend/app/standards/dcat/service.py`.
- Current export routes live in `backend/app/modules/catalog/datasets/api/router_export.py`.
- Current catalog metadata fields live in `backend/app/modules/catalog/datasets/domain/models.py`.
- Backend dev dependencies already include JSON Schema tooling; runtime validation endpoints may need the dependency promoted to production dependencies.

</code_context>

<specifics>
## Specific Ideas

- Add a new `backend/app/standards/dcat_us/` package.
- Add schema loader helpers and package-level constants for schema version, source repository, and source commit.
- Add source/mapping documentation near the implementation.

</specifics>

<deferred>
## Deferred Ideas

- DatasetSeries authoring.
- Structured CUI/access/use restriction authoring.
- DCAT-US v1.1 import tooling.

</deferred>
