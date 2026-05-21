# Quick Task 260327-kkj: API Endpoint Audit — Summary

**Completed:** 2026-03-27
**Scope:** 23 routers, ~158 endpoints

## Outcome

Produced a comprehensive audit report at `API-AUDIT-REPORT.md` covering all API routers for completeness, correctness, performance, and cleanup opportunities.

## Key Findings

| Severity | Count | Examples |
|----------|-------|---------|
| Critical | 2 | Share token auth gap (C1), embed_tokens role vs permission (C2) |
| High | 8 | `_extent_to_bbox` duplication, STAC missing response_model, trailing slash inconsistency, missing response models, no pagination on API keys, DELETE-with-body on settings |
| Medium | 5 | N+1 queries in collections, STAC N+1 extent queries, extra DB calls in map detail, missing cache invalidation, inline RBAC divergence |
| Low | 6 | Shared admin prefix, double-await, duplicate constants, dead helper, oversized router, stale version |
| Enhancements | 6 | AI rate limiting, bulk delete, export format validation, health schema, anonymous search, saved search pagination |

## Research Validation

- 22 RESEARCH.md findings verified against actual source
- 4 findings invalidated (false positives): jobs cleanup endpoint, double require_permission, httpx per-request client, STAC router
- Line numbers corrected where shifted from research

## What's Working Well

- Audit logging, structured error handling, permission model, OGC compliance, visibility enforcement, cache invalidation, SSRF protection — all strong and consistent across routers.

## Artifacts

- `API-AUDIT-REPORT.md` — Full audit report with fix proposals
- `260327-kkj-RESEARCH.md` — Research findings (with invalidation notes)
- `260327-kkj-CONTEXT.md` — User decisions
- `260327-kkj-PLAN.md` — Execution plan
