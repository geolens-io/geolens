---
phase: quick-260322-gzi
plan: 01
subsystem: api
tags: [arcgis, auth, ogc, gdal, i18n]

requires:
  - phase: none
    provides: existing service probing infrastructure

provides:
  - ArcGIS auth sends token via query param only (no Bearer header)
  - ArcGIS JSON error detection (498/499 token errors)
  - Dynamic objectIdField extraction from service metadata
  - object_id_field threaded through schemas, preview, ingest pipeline

affects: [service-import, arcgis-ingestion]

tech-stack:
  added: []
  patterns: [per-service auth handling instead of blanket client headers]

key-files:
  created:
    - backend/tests/test_arcgis_auth.py
  modified:
    - backend/app/services/router.py
    - backend/app/services/arcgis.py
    - backend/app/services/schemas.py
    - backend/app/services/preview.py
    - backend/app/services/probe.py
    - backend/app/services/wfs.py
    - backend/app/ingest/tasks.py
    - backend/app/datasets/router.py
    - frontend/src/i18n/locales/en/import.json
    - frontend/src/i18n/locales/es/import.json
    - frontend/src/i18n/locales/fr/import.json
    - frontend/src/i18n/locales/de/import.json

key-decisions:
  - "Remove blanket Bearer header from httpx client; each probe handles auth its own way"
  - "WFS auth moved to per-request headers via probe_wfs instead of client defaults"
  - "ArcGIS token errors (498/499) raise HTTPStatusError to surface as auth errors to users"

patterns-established:
  - "Service-type-aware auth: ArcGIS uses query param, WFS uses per-request Bearer header"

requirements-completed: [AGOL-REVIEW]

duration: 3min
completed: 2026-03-22
---

# Quick Task 260322-gzi: ArcGIS Auth Fix Summary

**Fix ArcGIS auth header bug, add JSON error detection, dynamic objectIdField, and corrected UX help text across 4 locales**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-22T16:32:57Z
- **Completed:** 2026-03-22T16:36:00Z
- **Tasks:** 2
- **Files modified:** 13

## Accomplishments
- Removed incorrect `Authorization: Bearer` header from ArcGIS probe requests (was breaking auth)
- Added ArcGIS JSON error detection for code 498 (invalid token) and 499 (token required)
- Dynamic objectIdField extraction from layer/service metadata instead of hardcoded OBJECTID
- Threaded object_id_field through all call sites: schemas, router, datasets, ingest tasks, probe
- Updated token help text in all 4 locales with generateToken path and expiry warning
- 7 new tests covering all auth fixes

## Task Commits

1. **Task 1: Fix ArcGIS auth header bug and add JSON error detection** - `30e985e3` (fix)
2. **Task 2: Fix UX help text for ArcGIS token guidance** - `e57e796c` (fix)

## Files Created/Modified
- `backend/app/services/router.py` - Removed blanket Bearer header, thread object_id_field, store in job metadata
- `backend/app/services/arcgis.py` - ArcGIS JSON error detection, objectIdField extraction per layer
- `backend/app/services/schemas.py` - Added object_id_field to LayerInfo and ServicePreviewRequest
- `backend/app/services/preview.py` - Added order_field parameter to build_gdal_source
- `backend/app/services/probe.py` - Thread object_id_field in _build_arcgis_response
- `backend/app/services/wfs.py` - WFS auth via per-request headers instead of client defaults
- `backend/app/ingest/tasks.py` - Read object_id_field from job metadata, pass to build_gdal_source
- `backend/app/datasets/router.py` - Thread object_id_field to build_gdal_source
- `backend/tests/test_arcgis_auth.py` - 7 tests for auth, error detection, OID extraction
- `frontend/src/i18n/locales/en/import.json` - Updated tokenPlaceholder and tokenHelpText
- `frontend/src/i18n/locales/es/import.json` - Spanish translation of updated help text
- `frontend/src/i18n/locales/fr/import.json` - French translation of updated help text
- `frontend/src/i18n/locales/de/import.json` - German translation of updated help text

## Decisions Made
- Remove blanket Bearer header from httpx client; each probe handles auth its own way
- WFS auth moved to per-request headers via probe_wfs instead of client defaults
- ArcGIS token errors (498/499) raise HTTPStatusError to surface as auth errors to users

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added WFS per-request auth headers**
- **Found during:** Task 1
- **Issue:** After removing Bearer header from httpx client defaults, WFS probes lost auth capability
- **Fix:** Added per-request `Authorization: Bearer` header in `probe_wfs()` when token provided
- **Files modified:** backend/app/services/wfs.py
- **Committed in:** 30e985e3

**2. [Rule 2 - Missing Critical] Thread object_id_field through probe.py**
- **Found during:** Task 1
- **Issue:** `_build_arcgis_response` in probe.py constructs LayerInfo but didn't pass object_id_field
- **Fix:** Added `object_id_field=layer.get("object_id_field")` to LayerInfo construction
- **Files modified:** backend/app/services/probe.py
- **Committed in:** 30e985e3

---

**Total deviations:** 2 auto-fixed (2 missing critical)
**Impact on plan:** Both fixes necessary for correctness. No scope creep.

## Issues Encountered
None

## Known Stubs
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- ArcGIS authenticated layer ingestion now correctly handles auth
- Frontend users guided to both API Keys and generateToken paths

---
*Quick Task: 260322-gzi*
*Completed: 2026-03-22*
