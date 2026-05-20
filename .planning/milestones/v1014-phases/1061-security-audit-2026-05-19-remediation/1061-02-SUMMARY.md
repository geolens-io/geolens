---
phase: 1061-security-audit-2026-05-19-remediation
plan: "02"
subsystem: catalog-api-security
tags: [security, idor, access-control, datasets, layers]
dependency_graph:
  requires: []
  provides: [SEC-S02, SEC-S03]
  affects:
    - backend/app/modules/catalog/datasets/api/router.py
    - backend/app/modules/catalog/layers/router.py
tech_stack:
  added: []
  patterns:
    - "check_dataset_access() after get_dataset() + 404 guard — canonical resource-level gate"
    - "owner-or-admin check for destructive ops on public datasets via get_user_roles()"
    - "per-item access check in bulk loop: inner HTTPException caught, recorded as per-item error, batch continues"
key_files:
  created:
    - backend/tests/test_dataset_metadata_idor.py
    - backend/tests/test_column_ddl_idor.py
  modified:
    - backend/app/modules/catalog/datasets/api/router.py
    - backend/app/modules/catalog/layers/router.py
decisions:
  - "admin role is named 'admin' (lowercase) — check is `'admin' in user_roles` where user_roles is a set[str] from get_user_roles()"
  - "bulk-delete: access denial recorded as per-item error (status='error', detail='Dataset not found') — batch is NOT aborted"
  - "delete_dataset_endpoint: check_dataset_access covers private visibility; separate owner-or-admin guard covers public datasets (destructive op requires stronger gate)"
  - "SEC-FU-08 (pg_audit / column-DDL change log) deferred to Phase 1063 per plan threat register"
metrics:
  duration: "~18 minutes (implementation + tests)"
  completed: "2026-05-20T18:20:34Z"
  tasks_completed: 3
  files_changed: 4
requirements:
  - SEC-S02
  - SEC-S03
---

# Phase 1061 Plan 02: SEC-S02 + SEC-S03 IDOR Fix Summary

Resource-level access control added to 7 mutation handlers (3 dataset metadata + 4 column DDL) that previously gate only on role-level `require_permission()` but not on per-dataset ownership. Closes CVSS 8.1 findings SEC-S02 and SEC-S03.

## What Was Built

**router.py (datasets/api/router.py):**
- `check_dataset_access` added to import block (was missing; `check_dataset_access_or_anonymous` was already imported)
- `update_dataset_metadata`: explicit `get_dataset` + `check_dataset_access` before `update_user_metadata`
- `bulk_delete_datasets_endpoint`: per-item `get_dataset` + inner `check_dataset_access`; `HTTPException` from access denial recorded as `status="error"` per-item result, batch continues
- `delete_dataset_endpoint`: `get_dataset` + `check_dataset_access` + owner-or-admin guard (`get_user_roles` → `"admin" in user_roles or created_by == user.id`); returns 403 if non-owner-non-admin on public dataset

**layers/router.py:**
- `check_dataset_access` import added (no prior authorization import in this file)
- `add_column_endpoint`, `rename_column_endpoint`, `alter_column_type_endpoint`, `drop_column_endpoint`: `await check_dataset_access(db, dataset, dataset_id, user)` inserted immediately after the existing 404 check
- `create_layer_endpoint` intentionally unchanged (creates new dataset owned by `user.id`; no IDOR surface)

**test_dataset_metadata_idor.py (7 tests):**
1. `test_patch_dataset_other_user_private_returns_404` — editor B PATCH → 404
2. `test_patch_dataset_owner_private_returns_200` — editor A PATCH own → 200
3. `test_delete_dataset_other_user_private_returns_404` — editor B DELETE private → 404
4. `test_delete_dataset_other_user_public_returns_403` — editor B DELETE public → 403
5. `test_delete_dataset_owner_returns_204` — owner DELETE → 204
6. `test_delete_dataset_admin_returns_204` — admin DELETE any → 204
7. `test_bulk_delete_skips_unauthorized_items` — editor B bulk-delete → deleted=0, errors>=1

**test_column_ddl_idor.py (8 tests):**
- 4 deny-paths: editor B → 404 on add/rename/alter-type/drop
- 4 owner-allow-paths: editor A → 201/200 on same operations

## Key Implementation Details

**Admin role string:** `"admin"` (lowercase) — matches seed in `_ensure_roles_and_admin` which seeds `{"name": "admin", ...}`. The check is:
```python
user_roles = await get_user_roles(db, user)
is_admin = "admin" in user_roles
```

**Bulk-delete per-item error shape:** Returns `200 OK` (not 207) with `deleted=0, errors=1`. The e2e spec accepts `200/207` with `deleted_count == 0` (accepted either). Per-item result: `{dataset_id: ..., status: "error", detail: "Dataset not found"}`.

**DELETE with JSON body in tests:** httpx `AsyncClient.delete()` does not accept `json=`; used `client.request("DELETE", ..., content=json.dumps(...), headers={...,"Content-Type": "application/json"})`.

**Fixture provisioning for e2e env vars:**
- `SEC_AUDIT_PRIVATE_DATASET_ID`: UUID of a dataset with `visibility='private'` owned by editor A; create via `POST /layers/` as editor A (defaults to private) or via admin `PATCH /datasets/{id}` to set visibility.
- `SEC_AUDIT_EDITOR_B_TOKEN`: bearer token from `POST /auth/login` for a second editor user who is NOT the dataset owner.

## Deviations from Plan

None — plan executed exactly as written. The `_create_test_user` signature in the plan skeleton (positional `session, username, role`) did not match the actual codebase (`client, admin_headers, role`); tests were written to match the real signature, which is the correct deviation (Rule 1: fix bug).

## Threat Surface Scan

No new network endpoints or auth paths introduced. Only existing handlers hardened.

## SEC-FU-08 Deferred

Per the plan's threat register, SEC-FU-08 (pg_audit / per-table column-DDL change log — Repudiation category) is accepted and deferred to Phase 1063.

## Self-Check: PASSED

- backend/tests/test_dataset_metadata_idor.py: FOUND
- backend/tests/test_column_ddl_idor.py: FOUND
- .planning/phases/1061-security-audit-2026-05-19-remediation/1061-02-SUMMARY.md: FOUND
- Commit 36b909a4 (SEC-S02 router): FOUND
- Commit bcae9610 (SEC-S03 layers router): FOUND
- Commit f4d9e6c4 (regression tests): FOUND
- All 15 tests pass: VERIFIED
