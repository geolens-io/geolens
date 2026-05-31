---
phase: 1157-backend-export-access-route-hygiene
plan: 01
subsystem: api
tags: [fastapi, export, authorization, ogc, anonymous-access, route-hygiene]

# Dependency graph
requires:
  - phase: 1156-vector-tile-egress-authorization
    provides: "Phase 1156 established check_dataset_access_or_anonymous direct-import pattern (not via port)"
provides:
  - "Anonymous-aware vector export gate (get_optional_user + anon/auth branch)"
  - "OGC items trailing-slash dual-shape alias (/collections/{id}/items/)"
affects: [1157-02-EXP-02-regression-test, 1158-builder-layer-visibility]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "EXP-01 anon branch: check_dataset_access_or_anonymous + public-visibility defense-in-depth guard (mirrors download_cog)"
    - "API-01 dual-shape stacked decorator: outermost has trailing-slash + include_in_schema=False; inner is canonical no-slash (mirrors auth/router.py)"

key-files:
  created: []
  modified:
    - backend/app/processing/export/router.py
    - backend/app/standards/ogc/router.py

key-decisions:
  - "EXP-01: use get_optional_user (not require_permission) to allow anonymous access; capability check relocated to authenticated branch only"
  - "EXP-01: audit_emit null-safe (user_id=user.id if user is not None else None) matching download_cog KNOWN-01 pattern"
  - "API-01: stacked @ogc_features_router.get decorators (not @router.get) per ogc_features_router instance at :37"
  - "Authorization helpers imported directly from app.modules.catalog.authorization — NOT via port (Phase 1156 GOTCHA preserved)"

patterns-established:
  - "Phase 1157 EXP-01 anon export: two-branch visibility check pattern now covers both raster COG and vector export endpoints"

requirements-completed: [EXP-01, API-01]

# Metrics
duration: 10min
completed: 2026-05-30
---

# Phase 1157 Plan 01: Backend Export Access + Route Hygiene Summary

**Anonymous vector export gate + OGC items trailing-slash alias: `get_optional_user` branch pattern mirrors COG download, stacked decorator mirrors ROUTE-01 auth precedent**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-05-30T18:00:00Z
- **Completed:** 2026-05-30T18:10:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- EXP-01: `export_dataset_endpoint` now accepts anonymous callers via `get_optional_user`; anon path calls `check_dataset_access_or_anonymous` + public-visibility defense-in-depth guard; authenticated path retains full RBAC visibility check + per-role `export` capability check via `get_effective_permissions`
- EXP-01: `audit_emit` null-safe (`user_id=user.id if user is not None else None`) — anonymous exports no longer 500 at the audit step
- API-01: `GET /collections/{dataset_id}/items/` registered as a hidden trailing-slash alias via stacked `@ogc_features_router.get` decorators; no-slash canonical form unchanged in OpenAPI schema

## Task Commits

1. **Task 1: EXP-01 — anonymous-aware vector export gate** - `f24b74b9` (feat)
2. **Task 2: API-01 — trailing-slash dual-shape alias on get_collection_items** - `3ff2e0a6` (feat)

**Plan metadata:** (docs commit — see final commit)

## Files Created/Modified

- `backend/app/processing/export/router.py` - Replace `require_permission("export")` with `get_optional_user`; add anon/auth two-branch check; null-safe audit emit
- `backend/app/standards/ogc/router.py` - Add trailing-slash alias decorator above canonical `get_collection_items` decorator

## Decisions Made

- Authorization helpers (`check_dataset_access`, `check_dataset_access_or_anonymous`, `get_user_roles`) imported directly from `app.modules.catalog.authorization` — not via `get_processing_port()`. The port does not expose `check_dataset_access_or_anonymous`; calling `port.check_dataset_access_or_anonymous()` silently AttributeErrors at runtime (Phase 1156 GOTCHA). `get_dataset` via port is legitimate and unchanged.
- Stacked decorators use `@ogc_features_router.get` (the router instance defined at `:37`), not `@router.get` — there is no bare `router` in `ogc/router.py`.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes beyond those in the plan's threat model. EXP-01 widens anonymous access only to public+published datasets (same contract as OGC/tiles). API-01 adds a URL alias pointing at the unchanged `get_collection_items` handler with its own `get_optional_user` auth — no new access surface.

## Next Phase Readiness

- EXP-01 fix is in place. Plan 02 (EXP-02) can now write regression tests that exercise both the allow path (public+published → 200) and deny paths (private/unpublished → 401/403/404).
- API-01 alias active; OGC items resolves at both `/collections/{id}/items` and `/collections/{id}/items/`.

## Self-Check

- `backend/app/processing/export/router.py` — exists and verified (EXP-01 structure OK via python -c check)
- `backend/app/standards/ogc/router.py` — exists and verified (API-01 dual-shape OK via python -c check)
- `f24b74b9` — EXP-01 commit confirmed
- `3ff2e0a6` — API-01 commit confirmed
- `import app.api.main` — succeeds (verified)

## Self-Check: PASSED

---
*Phase: 1157-backend-export-access-route-hygiene*
*Completed: 2026-05-30*
