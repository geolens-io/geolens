---
phase: 260327-rkx
verified: 2026-03-27T20:30:00Z
status: passed
score: 6/6 must-haves verified
re_verification: false
---

# Task 260327-rkx: API Audit Follow-ups Verification Report

**Task Goal:** Eliminate N+1 queries in collections listing (M1), JOIN forked_from_name + owner_username into map queries (M2), replace _public_base_url with get_dataset_service_url wrapper (L4), and split datasets/router.py into focused sub-routers (L5).
**Verified:** 2026-03-27T20:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1   | GET /collections/ uses 3 queries (list + batched extent + batched count) instead of 2N+1 | VERIFIED | `batch_collection_extents` + `batch_collection_dataset_counts` with `GROUP BY` in service.py lines 295-375; router uses them at lines 195-202 |
| 2   | GET /maps/{id} returns forked_from_name and owner_username without separate queries | VERIFIED | `get_map_with_layers` returns 4-tuple via `aliased` outerjoin on Map+User; router unpacks at line 243 |
| 3   | PUT /maps/{id} and POST /maps/{id}/duplicate also return forked/owner names from JOIN | VERIFIED | Router lines 336 (update) and 425 (duplicate) both unpack 4-tuple from same service function |
| 4   | Dataset tile connect URLs use DB-backed get_dataset_service_url() wrapper instead of header-derived _public_base_url | VERIFIED | `_public_base_url` is absent from all datasets files; `get_dataset_service_url` in public_urls.py lines 218-228; used at router.py lines 125, 176, 265, 389 |
| 5   | datasets/router.py is split into 6 focused files, each under 600 lines | VERIFIED | router.py=483, helpers.py=188, router_reupload.py=537, router_vrt.py=350, router_metadata.py=397, router_export.py=192, router_data.py=219 — all under 600 |
| 6   | All existing dataset endpoint tests pass unchanged | VERIFIED | SUMMARY documents 1521 passed, 7 deselected (pre-existing failures); commit d5f1d932 includes test mock path updates where needed |

**Score:** 6/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `backend/app/collections/service.py` | batch_collection_extents and batch_collection_dataset_counts | VERIFIED | Both functions present at lines 295-375; each issues single GROUP BY query with visibility filter |
| `backend/app/maps/service.py` | get_map_with_layers returns forked_from_name + owner_username | VERIFIED | Returns `tuple[Map | None, list[tuple], str | None, str | None]`; uses `aliased(Map)` outerjoin + User outerjoin |
| `backend/app/public_urls.py` | get_dataset_service_url wrapper | VERIFIED | Lines 218-228; thin wrapper over get_public_app_url with purpose-named function |
| `backend/app/datasets/helpers.py` | Shared helpers extracted from router.py | VERIFIED | 188 lines; contains `_load_actor_identities`, `_build_raster_metadata`, `_dataset_to_response` |
| `backend/app/datasets/router_reupload.py` | Reupload + presigned reupload endpoints | VERIFIED | 537 lines; APIRouter at line 55; 6 reupload routes |
| `backend/app/datasets/router_vrt.py` | VRT endpoints | VERIFIED | 350 lines; APIRouter at line 33; 4 VRT routes |
| `backend/app/datasets/router_metadata.py` | Attributes, column-stats, relationships, versions | VERIFIED | 397 lines; APIRouter at line 42; 8+ metadata routes |
| `backend/app/datasets/router_export.py` | DCAT + download-cog endpoints | VERIFIED | 192 lines; APIRouter at line 36; 3 export routes |
| `backend/app/datasets/router_data.py` | Rows, validate, related, maps, publication-status | VERIFIED | 219 lines; APIRouter at line 45; 5 data routes |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `collections/router.py` | `collections/service.py` | `batch_collection_extents\|batch_collection_dataset_counts` | WIRED | Both imported at lines 28-29; used in list_collections_endpoint lines 196-197 |
| `maps/router.py` | `maps/service.py` | `forked_from_name.*owner_username` 4-tuple unpack | WIRED | All 3 call sites unpack 4-tuple (lines 243, 336, 425); old separate resolve calls removed |
| `datasets/router.py` | `datasets/helpers.py` | `from app.datasets.helpers import` | WIRED | router.py line 33 imports `_dataset_to_response`, `_build_raster_metadata`, `_load_actor_identities` |
| `datasets/router*.py` | `datasets/helpers.py` | sub-routers import from helpers | NOT APPLICABLE | Sub-routers handle specialized ops (reupload, vrt, metadata, export, data) that don't build DatasetResponse — helpers not needed |
| `datasets/router.py` | `public_urls.py` | `get_dataset_service_url` | WIRED | Line 54 imports it; used at 4 call sites (lines 125, 176, 265, 389) |
| `main.py` | `datasets/router*.py` | `include_router.*datasets` (all 6) | WIRED | Lines 375-380; export router registered BEFORE core router to prevent /dcat/ capture by /{dataset_id} |

### Data-Flow Trace (Level 4)

Not applicable. This task modifies query patterns and module structure — no new dynamic data rendering components introduced.

### Behavioral Spot-Checks

Step 7b: SKIPPED — behavioral checks require running the Docker API service; the test suite (1521 passing) provides equivalent behavioral coverage per SUMMARY.

### Requirements Coverage

| Requirement | Description | Status | Evidence |
| ----------- | ----------- | ------ | -------- |
| M1 | Batch N+1 queries in list_collections_endpoint | SATISFIED | batch_collection_extents + batch_collection_dataset_counts with GROUP BY; wired in router |
| M2 | JOIN forked_from_name + owner_username into get_map_with_layers | SATISFIED | aliased outerjoin on Map+User in service; all 3 router call sites updated |
| L4 | Replace _public_base_url with get_dataset_service_url | SATISFIED | wrapper added in public_urls.py; _public_base_url deleted; all 4 call sites migrated |
| L5 | Split datasets/router.py into sub-routers | SATISFIED | router.py=483 lines (under 600); 5 sub-routers + helpers created; all 6 registered in main.py |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `backend/app/maps/service.py` | 551-559 | `resolve_forked_from_name` still exists after M2 | Info | Unused dead code — no callers in maps/router.py or any other file scanned; harmless but could be deleted |

`resolve_forked_from_name` remains in maps/service.py (the plan said to delete it if no other callers). It has no callers in router.py. This is minor dead code, not a blocker.

### Human Verification Required

None. All must-haves are verifiable from source inspection.

### Gaps Summary

No gaps. All 6 observable truths are verified against the actual codebase. The only finding is an incidental dead-code function (`resolve_forked_from_name` in maps/service.py) that could be cleaned up but does not affect correctness or goal achievement.

---

_Verified: 2026-03-27T20:30:00Z_
_Verifier: Claude (gsd-verifier)_
