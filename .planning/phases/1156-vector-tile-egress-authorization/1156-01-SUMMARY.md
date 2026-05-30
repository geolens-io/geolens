---
phase: 1156-vector-tile-egress-authorization
plan: "01"
subsystem: auth
tags: [security, vector-tiles, authorization, hmac, fastapi]

# Dependency graph
requires: []
provides:
  - Status-aware vector-tile authorization across all five entry points in tiles/router.py
  - _DatasetMeta carries record_status and created_by for inline status gating
  - Both token endpoints (get_tile_token, get_tile_tokens_batch) route through check_dataset_access_or_anonymous
  - _authorize_vector_tile_request denies anon + non-owner non-admin on public+unpublished datasets
  - cluster_tile_endpoint and tile_endpoint inherit the denial via the shared helper
affects:
  - 1156-02 (regression tests rely on this authorization behavior)
  - 1157 (export access uses same check_dataset_access_or_anonymous pattern)
  - 1160 (live MCP close-gate verifies this fix)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Vector-tile auth now mirrors raster _resolve_raster_access: public+unpublished -> 404 for anon and non-owner non-admin"
    - "Token endpoints use check_dataset_access_or_anonymous one-call form instead of visibility-only gate"

key-files:
  created: []
  modified:
    - backend/app/processing/tiles/router.py

key-decisions:
  - "Used Option A (thread user param into _authorize_vector_tile_request) to keep diff minimal and consistent with raster analog"
  - "check_dataset_access_or_anonymous replaces visibility-only gate in both token endpoints — single call covers all three branches (anon non-published -> 404; anon public+published -> allowed; authenticated -> full RBAC)"
  - "Batch endpoint (get_tile_tokens_batch) uses try/except pattern to preserve per-key error accumulation contract — no bare raise"
  - "Status guard in _authorize_vector_tile_request mirrors raster lines 465-479 exactly: 404 for anon, 404 for non-owner non-admin authenticated, pass for owner/admin/published"

patterns-established:
  - "All vector-tile entry points now enforce: anonymous access requires visibility=='public' AND record_status=='published'"

requirements-completed: [SEC-01]

# Metrics
duration: 8min
completed: 2026-05-30
---

# Phase 1156 Plan 01: Vector-Tile Egress Authorization Summary

**Closed the anonymous MVT data leak (SEC-01): all five vector-tile entry points now enforce `visibility=='public' AND record_status=='published'` for anonymous callers, mirroring the raster path in `_resolve_raster_access`.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-05-30T17:00:17Z
- **Completed:** 2026-05-30T17:03:10Z
- **Tasks:** 3
- **Files modified:** 1

## Accomplishments

- Added `record_status: str` and `created_by: uuid.UUID` to `_DatasetMeta` NamedTuple and populated both from the eager-loaded `dataset.record` in `_resolve_dataset_meta`
- Replaced visibility-only gates in `get_tile_token` and `get_tile_tokens_batch` with `check_dataset_access_or_anonymous`, eliminating HMAC minting for anon callers on public+unpublished datasets
- Added `user: Identity | None` param to `_authorize_vector_tile_request` and inserted the raster-mirrored status guard in the `else` (public) branch: anon -> 404, non-owner non-admin -> 404, owner/admin/published -> pass; threaded `user=user` through both `.pbf` call sites (`cluster_tile_endpoint`, `tile_endpoint`)

## Task Commits

1. **Task 1: Carry record_status and created_by through _DatasetMeta** - `bfaba566` (feat)
2. **Task 2: Make both token endpoints status-aware via check_dataset_access_or_anonymous** - `87df7122` (feat)
3. **Task 3: Add status guard to _authorize_vector_tile_request and thread user through both .pbf call sites** - `a9c0a8e8` (fix)

## Files Created/Modified

- `backend/app/processing/tiles/router.py` - All five vector-tile entry points now enforce status-aware authorization

## Decisions Made

- **Option A for `_authorize_vector_tile_request`**: Adding `user` as a keyword-only param keeps the diff confined to one function and is consistent with the raster path. Option B (call `check_dataset_access_or_anonymous`) would require carrying the full ORM object through `_DatasetMeta` or an extra DB fetch.
- **Batch endpoint error capture preserved**: The `try/except HTTPException` wrapper around `check_dataset_access_or_anonymous` in `get_tile_tokens_batch` maintains the `tokens[key] = {"error": exc.detail}; continue` contract. Anonymous callers on public+unpublished datasets get `{"error": "Dataset not found"}` per key, consistent with 404 behavior.
- **No new imports**: `Identity`, `get_optional_user`, `get_processing_port`, `status`, and `HTTPException` were all already imported in `tiles/router.py`.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. The `uv run python` form was needed (no bare `python` in PATH on this system), but that is a local toolchain detail, not a code issue.

## User Setup Required

None - no external service configuration required.

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes introduced. The fix closes the T-1156-01 and T-1156-02 surfaces identified in the plan's threat register. No new threat surface detected.

## Next Phase Readiness

- Phase 1156 Plan 02 (regression tests) can now run the authoritative behavioral gate: anonymous caller on public+unpublished vector dataset should receive 404 at token endpoint; public+published should still succeed.
- `backend/app/processing/tiles/router.py` imports cleanly; all three signature checks pass.
- No migrations, no new dependencies, no frontend changes needed.

---
*Phase: 1156-vector-tile-egress-authorization*
*Completed: 2026-05-30*
