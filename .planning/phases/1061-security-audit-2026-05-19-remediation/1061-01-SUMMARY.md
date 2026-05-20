---
phase: 1061-security-audit-2026-05-19-remediation
plan: "01"
subsystem: backend/stac
tags: [security, stac, visibility, sec-s01]
dependency_graph:
  requires: []
  provides: [SEC-S01]
  affects: [backend/app/standards/stac/router.py]
tech_stack:
  added: []
  patterns:
    - apply_visibility_filter on STAC item-returning endpoints (matches OGC peer)
    - _resolve_roles helper for anonymous/authenticated role resolution
key_files:
  created:
    - backend/tests/test_stac_visibility.py
  modified:
    - backend/app/standards/stac/router.py
decisions:
  - "Apply apply_visibility_filter to _base_published_raster_query — matches OGC Features peer pattern exactly"
  - "_published_raster_filters retained for aggregate queries (get_collections/get_collection) — bounded by CollectionDataset membership, no item bodies leak"
  - "Collection-level aggregate carve-out (T-1061-02) deferred to SEC-FU follow-up per audit scope"
metrics:
  duration: "~25 minutes"
  completed_date: "2026-05-20"
  tasks_completed: 4
  files_changed: 2
---

# Phase 1061 Plan 01: STAC Visibility Filter (SEC-S01) Summary

Closes SEC-S01 (HIGH, CVSS 7.5) — STAC visibility bypass. Anonymous users could retrieve private/restricted published raster records via `/api/stac/items/{id}` and `/api/stac/search`. Port of the OGC Features visibility pattern to the STAC router.

## What Was Built

- **`_base_published_raster_query(user, user_roles)`** — refactored from no-arg to accept identity context; applies `apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)` mirroring the OGC peer.
- **`_resolve_roles(db, user)`** — helper that returns `set()` for anonymous callers, `get_user_roles(db, user)` for authenticated callers.
- **5 item-returning STAC endpoints** updated: `get_collection_items`, `get_collection_item`, `get_item`, `search_get`, `search_post` — all accept `user: Identity | None = Depends(get_optional_user)` and resolve roles before querying.
- **`_execute_search`** — extended with `user` / `user_roles` positional params forwarded from `search_get` / `search_post`.
- **`_published_raster_filters()`** — retained unchanged for aggregate queries; marked with `# Phase 1061 SEC-S01` inline comment.
- **`backend/tests/test_stac_visibility.py`** — 6 new pytest cases mirroring `test_ogc_public_access.py`.

## Files Changed

| File | LOC Delta |
|------|-----------|
| `backend/app/standards/stac/router.py` | +56 / -14 |
| `backend/tests/test_stac_visibility.py` | +241 (new) |

## Deviations from Plan

None — plan executed exactly as written.

## Test Status

### Backend pytest

| Suite | Result |
|-------|--------|
| `test_stac_api.py` (29 tests) | PASS |
| `test_stac_integration.py` (included above) | PASS |
| `test_stac_visibility.py` (6 new tests) | PASS |
| **Total** | **35 passed** |

All 6 new visibility test cases:
1. `test_stac_item_no_auth_private_returns_404` — PASS
2. `test_stac_item_no_auth_public_returns_200` — PASS
3. `test_stac_search_no_auth_excludes_private` — PASS
4. `test_stac_collection_items_no_auth_excludes_private` — PASS
5. `test_stac_item_owner_can_read_private` — PASS
6. `test_stac_item_non_owner_cannot_read_private` — PASS

### e2e SEC-S01 Specs

Both S01 specs **SKIPPED** — `SEC_AUDIT_PRIVATE_RECORD_ID` not set in local environment.

Skip message: `Set SEC_AUDIT_PRIVATE_RECORD_ID to a private published raster`.

Backend pytest coverage in Task 3 is the load-bearing automated gate. The e2e specs pin the same surface against a live API and serve as the close-gate (Phase 1064) verification.

## SEC_AUDIT_PRIVATE_RECORD_ID Fixture Provisioning Recipe

To run the 2 S01 e2e specs against a live stack:

```bash
# 1. Stack up
make dev

# 2. Get admin token
ADMIN_TOKEN=$(curl -sS -X POST "http://localhost:8000/api/auth/login" \
  -d "username=admin&password=admin" | jq -r '.access_token')

# 3. Upload any sample .tif via the API or UI, then patch it to private+published:
#    (replace DATASET_ID with the dataset id from the upload response)
RECORD_ID=$(curl -sS -X PATCH "http://localhost:8000/api/datasets/<DATASET_ID>/" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"visibility":"private","record_status":"published"}' | jq -r '.record_id')

# 4. The /stac/items/{item_id} path uses Dataset.id — get it:
DATASET_ID=$(curl -sS "http://localhost:8000/api/datasets/<DATASET_ID>/" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq -r '.id')

# 5. Run the S01 specs (use Dataset.id as the env var value)
SEC_AUDIT_PRIVATE_RECORD_ID=$DATASET_ID \
  npx playwright test e2e/sec-audit.spec.ts --project=chromium --grep "S01"
```

**Note:** The env var `SEC_AUDIT_PRIVATE_RECORD_ID` is used as the STAC item id, which corresponds to `Dataset.id` (not `Record.record_id`). The STAC `/items/{item_id}` endpoint uses `Dataset.id` as the path parameter.

## Bounded Carve-Out Note — get_collections / get_collection Aggregates

The `get_collections` and `get_collection` aggregate endpoints continue to use `_published_raster_filters()` for extent/keyword/EPSG aggregation. Per T-1061-02 in the threat register and the audit's explicit scope for S01:

- These aggregates return only counts/bboxes/keyword lists scoped by `CollectionDataset` membership — no item bodies leak.
- The visibility leakage on these aggregates is bounded: an observer may infer that some records exist in a collection, but cannot read any item document (geometry, assets, properties).
- Narrowing these aggregates to the full visibility predicate is deferred to a SEC-FU follow-up (T-1061-02 accept disposition).

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | `1c10a9e0` | Refactor _base_published_raster_query to accept user/roles |
| Task 2 | `2eb2f9bc` | Thread user/user_roles through all STAC item endpoints |
| Task 3 | `a69184ec` | Backend pytest visibility regression coverage for STAC |

## Self-Check: PASSED

- `backend/app/standards/stac/router.py` — FOUND
- `backend/tests/test_stac_visibility.py` — FOUND
- `1061-01-SUMMARY.md` — FOUND
- Commit `1c10a9e0` — FOUND
- Commit `2eb2f9bc` — FOUND
- Commit `a69184ec` — FOUND
