# Quick Task 260327-kkj: API Endpoint Review - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Task Boundary

Review all API endpoints for completeness, correctness and optimizations. Identify gaps, issues, concerns, suggested enhancements, and cleanup opportunities across all 22 routers.

</domain>

<decisions>
## Implementation Decisions

### Review Scope
- All 22 API routers: datasets, maps, records, auth, OGC, tiles, search, AI, collections, features, layers, ingest, jobs, services, settings, admin, audit, config_ops, embed_tokens, export, stac, auth/oauth

### Output Format
- Single structured audit report with findings grouped by severity
- Actionable issues, optimizations, and gaps in one document

### Review Depth
- Identify issues AND propose specific code changes or patterns to resolve them
- Not implementing fixes — cataloging with proposals

### Priority Focus (all selected)
- Correctness & security: auth gaps, input validation, error handling, data integrity
- Completeness & gaps: missing CRUD operations, inconsistent patterns, undocumented endpoints
- Performance & optimization: N+1 queries, missing pagination, unnecessary DB calls, caching opportunities
- Cleanup & simplification: dead code, redundant logic, inconsistent naming, over-engineering

</decisions>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>
