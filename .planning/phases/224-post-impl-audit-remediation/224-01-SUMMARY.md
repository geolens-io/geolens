---
phase: 224-post-impl-audit-remediation
plan: 01
subsystem: backend
tags: [performance, sql, async, auth]
completed: 2026-04-12

dependency_graph:
  requires: []
  provides:
    - selectinload-based eager loading via _eager_load_record_relations helper
    - non-blocking LocalStorageProvider (asyncio.to_thread)
    - throttled API key last_used_at writes (60s threshold)
    - parallel presigned URL generation (asyncio.gather)
    - paginated get_maps_for_dataset (skip/limit)
    - canonical get_user_roles usage across 6 call sites
  affects:
    - backend/app/search/service.py
    - backend/app/stac/router.py
    - backend/app/storage/local.py
    - backend/app/auth/dependencies.py
    - backend/app/ingest/router.py
    - backend/app/datasets/router_reupload.py
    - backend/app/maps/service.py
    - backend/app/datasets/router_data.py
    - backend/app/jobs/router.py
    - backend/app/ingest/service.py
    - backend/app/datasets/router_export.py

tech_stack:
  patterns:
    - selectinload for one-to-many SQLAlchemy eager loading (replaces joinedload)
    - asyncio.to_thread for blocking filesystem I/O in async context
    - asyncio.gather for parallel coroutine execution
    - 60s deduplication window for high-frequency DB writes

key_files:
  modified:
    - backend/app/search/service.py
    - backend/app/stac/router.py
    - backend/app/storage/local.py
    - backend/app/auth/dependencies.py
    - backend/app/ingest/router.py
    - backend/app/datasets/router_reupload.py
    - backend/app/maps/service.py
    - backend/app/datasets/router_data.py
    - backend/app/jobs/router.py
    - backend/app/ingest/service.py
    - backend/app/datasets/router_export.py

decisions:
  - "P0-1: _eager_load_record_relations helper centralizes selectinload options at all 3 query sites (search base_join, RRF re-fetch, STAC raster query)"
  - "P1-1: get_to_file wrapped in to_thread alongside all other LocalStorageProvider async methods"
  - "P1-2: 60s threshold on last_used_at writes uses datetime.now(timezone.utc) instead of func.now() for comparison — avoids extra DB round-trip"
  - "P1-4: router_data.py was the actual router file (not maps/router_data.py as the plan stated) — auto-corrected"
  - "P1-5: auth/dependencies.py had circular import risk avoided by importing get_user_roles at module level (not inside function)"

metrics:
  duration: ~25 minutes
  completed_date: 2026-04-12
  tasks_completed: 6
  tasks_total: 6
  files_modified: 11
---

# Phase 224 Plan 01: Backend Performance Audit Remediation Summary

**One-liner:** Eliminated Cartesian joinedload explosion, async event-loop blocking, per-request DB writes, sequential I/O, unbounded queries, and duplicated role SQL across 11 backend files.

## Tasks Completed

| Task | Commit | Description |
|------|--------|-------------|
| 1: P0-1 selectinload | 16f58696 | _eager_load_record_relations helper replaces joinedload at 3 Cartesian sites |
| 2: P1-1 asyncio.to_thread | 094897d1 | All 7 LocalStorageProvider async methods delegate sync I/O to thread pool |
| 3: P1-2 last_used_at throttle | a329f65a | API key writes only occur when timestamp is None or >60s stale |
| 4: P1-3 asyncio.gather | 702429eb | Presigned URL generation parallelized in both ingest and reupload routers |
| 5: P1-4 pagination | b99cc908 | get_maps_for_dataset accepts skip/limit (default 0/50, max 200) |
| 6: P1-5 role SQL dedup | a7886be1 | 6 inline role SQL sites replaced with get_user_roles canonical helper |

## Changes by File

**backend/app/search/service.py**
- Added `_eager_load_record_relations(stmt)` helper using `selectinload`
- Replaced `base_join` joinedload chain (FTS path, line ~685)
- Replaced `fetch_stmt` joinedload chain (RRF re-fetch path, line ~889)
- Removed unused `joinedload` import

**backend/app/stac/router.py**
- Imported `_eager_load_record_relations` from `search.service`
- Replaced `_base_published_raster_query` joinedload chain
- Removed unused `joinedload` import

**backend/app/storage/local.py**
- Added `import asyncio`
- `put`: reads BinaryIO bytes before thread handoff, wraps write in `to_thread`
- `get`: delegates `path.read_bytes` to `to_thread`
- `get_to_file`: wraps `shutil.copy2` + `mkdir` in `to_thread`
- `delete`: delegates `path.unlink(missing_ok=True)` to `to_thread`
- `exists`: delegates `path.exists` to `to_thread`
- `list`: wraps entire rglob/glob traversal in `to_thread`
- `health_check`: delegates `base_dir.exists` to `to_thread`

**backend/app/auth/dependencies.py**
- Added `datetime`, `timedelta`, `timezone` imports
- Added `get_user_roles` import from `app.auth.visibility`
- `_resolve_api_key`: replaced unconditional `func.now()` write with 60s conditional
- Removed unused `func` and `Role`, `UserRole` imports
- `require_role._role_checker`: replaced inline SQL with `get_user_roles`
- `require_permission._permission_checker`: replaced inline SQL with `get_user_roles`

**backend/app/ingest/router.py**
- Replaced sequential `for part_num` loop with `asyncio.gather(*[...])`

**backend/app/datasets/router_reupload.py**
- Replaced sequential `for part_num` loop with `asyncio.gather(*[...])`

**backend/app/maps/service.py**
- Added `skip: int = 0` and `limit: int = 50` to `get_maps_for_dataset`
- Applied `.offset(skip).limit(limit)` to the query

**backend/app/datasets/router_data.py**
- Added `skip: int = Query(0, ge=0)` and `limit: int = Query(50, ge=1, le=200)` to `dataset_maps`
- Passes skip/limit through to `get_maps_for_dataset`

**backend/app/jobs/router.py**
- Replaced 2 inline role SQL blocks with `get_user_roles(db, user)`
- Removed `Role`, `UserRole` imports

**backend/app/ingest/service.py**
- Replaced inline role SQL block with `get_user_roles(db, user)`
- Removed `Role`, `UserRole` imports

**backend/app/datasets/router_export.py**
- Replaced inline role SQL block at COG export with `get_user_roles(db, user)`
- Removed `Role`, `UserRole` imports

## Deviations from Plan

### Auto-corrected Issues

**1. [Rule 1 - Bug] router_data.py path correction**
- **Found during:** Task 5
- **Issue:** Plan listed `backend/app/maps/router_data.py` as the route handler file but this file does not exist. The actual file is `backend/app/datasets/router_data.py`.
- **Fix:** Read and modified the correct file.
- **Files modified:** `backend/app/datasets/router_data.py`

**2. [Rule 2 - Missing cleanup] Remove unused func import in auth/dependencies.py**
- **Found during:** Task 3 verification (ruff F401)
- **Issue:** Replacing `func.now()` with `datetime.now(timezone.utc)` left `sqlalchemy.func` imported but unused.
- **Fix:** Removed the unused import.
- **Commit:** a329f65a

## Verification

```
ruff check backend/ → All checks passed
```

Tests require a live PostgreSQL/PostGIS database connection (not available in this environment). Ruff and Python syntax checks passed for all modified files. The test suite reported `socket.gaierror` on database tests — this is a pre-existing infrastructure constraint, not introduced by these changes.

## Known Stubs

None — all changes are behavioral fixes with no placeholder values.

## Threat Flags

None — changes reduce attack surface (fewer DB writes under API key load, no new network endpoints).

## Self-Check

### Files exist:
- backend/app/search/service.py: FOUND
- backend/app/stac/router.py: FOUND
- backend/app/storage/local.py: FOUND
- backend/app/auth/dependencies.py: FOUND
- backend/app/ingest/router.py: FOUND
- backend/app/datasets/router_reupload.py: FOUND
- backend/app/maps/service.py: FOUND
- backend/app/datasets/router_data.py: FOUND
- backend/app/jobs/router.py: FOUND
- backend/app/ingest/service.py: FOUND
- backend/app/datasets/router_export.py: FOUND

### Commits exist:
- 16f58696: selectinload Task 1
- 094897d1: asyncio.to_thread Task 2
- a329f65a: last_used_at throttle Task 3
- 702429eb: asyncio.gather Task 4
- b99cc908: pagination Task 5
- a7886be1: get_user_roles dedup Task 6

## Self-Check: PASSED
