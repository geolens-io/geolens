---
phase: 1061-security-audit-2026-05-19-remediation
plan: "03"
subsystem: catalog-api-security
tags: [security, pgvector, idor, access-control, datasets, embeddings]
dependency_graph:
  requires: []
  provides: [SEC-S05]
  affects:
    - backend/app/modules/catalog/datasets/api/router_data.py
    - backend/app/modules/catalog/datasets/domain/service_relationships.py
tech_stack:
  added: []
  patterns:
    - "check_dataset_access_or_anonymous return value reused as user_roles — eliminates redundant get_user_roles call"
    - "API router gates seed visibility before service layer reads embedding — defense-in-depth caller contract documented at service site"
key_files:
  created:
    - backend/tests/test_related_datasets_idor.py
  modified:
    - backend/app/modules/catalog/datasets/api/router_data.py
    - backend/app/modules/catalog/datasets/domain/service_relationships.py
key_decisions:
  - "Fix applied at API router boundary (not service layer) — check_dataset_access_or_anonymous return value reused as user_roles eliminating redundant get_user_roles"
  - "Defense-in-depth comment added to _load_self_record_and_embedding docstring — future callers must replicate the gate at their call site"
  - "SEC-FU follow-up: narrow _load_self_record_and_embedding to consume the seed via the visibility-filtered query directly, eliminating reliance on caller-side gating (Phase 1063 candidate)"
patterns-established:
  - "Reuse check_dataset_access_or_anonymous return value as user_roles — avoids a second DB roundtrip for role resolution"

requirements-completed:
  - SEC-S05

duration: "~4 minutes"
completed: "2026-05-20"
---

# Phase 1061 Plan 03: SEC-S05 pgvector /related/ Seed Visibility Fix Summary

**Single-line gate addition to `list_related_datasets` blocks anonymous cosine-similarity oracle on private dataset embeddings via `check_dataset_access_or_anonymous` before `_load_self_record_and_embedding` is reached.**

## Performance

- **Duration:** ~4 minutes
- **Started:** 2026-05-20T18:23:07Z
- **Completed:** 2026-05-20T18:25:48Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Closed SEC-S05 (HIGH, CVSS 7.5): anonymous probe of private dataset UUID via `/datasets/{id}/related/` now returns 404 instead of triggering `_load_self_record_and_embedding` for embedding read
- `check_dataset_access_or_anonymous` return value reused as `user_roles` — no redundant `get_user_roles` call, both 404 paths (nonexistent UUID + private-deny) flow through the same code depth for timing uniformity
- Defense-in-depth caller contract documented in `_load_self_record_and_embedding` docstring — prevents regression if a new caller is added
- 5 regression tests covering all visibility paths (anonymous private/nonexistent/public, owner private, non-owner private) — all pass

## Task Commits

1. **Task 1: Apply check_dataset_access_or_anonymous before get_related_datasets** - `02c3f35d` (fix)
2. **Task 2: Defense-in-depth comment in service_relationships._load_self_record_and_embedding** - `589e3769` (docs)
3. **Task 3: pytest regression coverage for SEC-S05** - `07bef8ff` (test)

## Files Created/Modified

- `backend/app/modules/catalog/datasets/api/router_data.py` — `list_related_datasets` handler: added `get_dataset` + 404 check + `check_dataset_access_or_anonymous` before `get_related_datasets`; user_roles sourced from return value (not from separate `get_user_roles` call). +12 lines, -1 line.
- `backend/app/modules/catalog/datasets/domain/service_relationships.py` — `_load_self_record_and_embedding` docstring extended with SEC-S05 caller-contract note. +9 lines, -1 line.
- `backend/tests/test_related_datasets_idor.py` — 5 pytest tests (created, 157 lines).

## check_dataset_access_or_anonymous Return Value Reuse

The original handler called `get_user_roles(db, user) if user is not None else set()` then passed the result to `get_related_datasets`. The fixed handler calls `check_dataset_access_or_anonymous(db, dataset, dataset_id, user)` which per its docstring "Returns the resolved user_roles set (empty for anonymous)". This return value is passed directly to `get_related_datasets` — same downstream contract, one fewer DB roundtrip.

## Deviations from Plan

None — plan executed exactly as written.

The plan's verification grep (`grep -nA 3 "list_related_datasets" ... | grep -c check_dataset_access_or_anonymous`) returns 0 because the function body spans more than 3 lines after the handler definition. Using `-A 20` returns 1. The fix is present at line 74.

## Threat Surface Scan

No new network endpoints or auth paths introduced. Existing endpoint hardened.

## SEC-FU Follow-up (Phase 1063 Candidate)

Narrow `_load_self_record_and_embedding` to consume the seed via a visibility-filtered query directly, eliminating reliance on caller-side gating. This would convert the defense-in-depth docstring into a hard guarantee at the service layer.

## Self-Check: PASSED

- backend/app/modules/catalog/datasets/api/router_data.py: FOUND (check_dataset_access_or_anonymous at line 74)
- backend/app/modules/catalog/datasets/domain/service_relationships.py: FOUND (Phase 1061 SEC-S05 comment at line 49)
- backend/tests/test_related_datasets_idor.py: FOUND (5 tests)
- .planning/phases/1061-security-audit-2026-05-19-remediation/1061-03-SUMMARY.md: FOUND
- Commit 02c3f35d (router fix): FOUND
- Commit 589e3769 (defense-in-depth comment): FOUND
- Commit 07bef8ff (regression tests): FOUND
- All 5 tests pass: VERIFIED (5 passed in 5.66s, 52 related tests pass, 0 regressions)
