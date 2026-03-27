---
phase: 210-enterprise-overlay-repo
plan: 02
subsystem: auth, audit, infra
tags: [saml, enterprise, overlay, open-core, fastapi]

# Dependency graph
requires:
  - phase: 210-01
    provides: Enterprise package scaffold, extension loader, router registration
provides:
  - SAML SSO router/config/replay in geolens-enterprise
  - Audit log CSV/JSON streaming export in geolens-enterprise
  - Branding PUT endpoint in geolens-enterprise
  - Core cleaned of enterprise implementations
affects: [enterprise-features, saml, audit-export, branding]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Enterprise overlay: enterprise code imports from core using app.* paths, core never imports from geolens_enterprise"
    - "Enterprise routers registered dynamically via extension loader in main.py lifespan"
    - "pysaml2 dependency lives only in enterprise package, not core"

key-files:
  created:
    - "../geolens-enterprise/geolens_enterprise/auth/saml/router.py"
    - "../geolens-enterprise/geolens_enterprise/auth/saml/config.py"
    - "../geolens-enterprise/geolens_enterprise/auth/saml/replay.py"
    - "../geolens-enterprise/geolens_enterprise/audit/export.py"
    - "../geolens-enterprise/geolens_enterprise/branding/router.py"
  modified:
    - "backend/app/audit/router.py"
    - "backend/app/settings/router.py"
    - "backend/pyproject.toml"
    - "backend/tests/test_saml.py"

key-decisions:
  - "SAML metadata parser stays in core (used by OAuth service CRUD), only router/config/replay move to enterprise"
  - "Enterprise audit export gets its own router with /admin prefix, same URL paths as before"
  - "defusedxml stays in core deps (needed by metadata.py), pysaml2 moves to enterprise-only"

patterns-established:
  - "Enterprise feature extraction: copy code to enterprise, update internal imports to geolens_enterprise.*, keep app.* imports for core deps"
  - "Core cleanup: remove enterprise-gated endpoints and their require_enterprise imports after extraction"

requirements-completed: [REPO-04]

# Metrics
duration: 5min
completed: 2026-03-26
---

# Phase 210 Plan 02: Enterprise Feature Extraction Summary

**Extracted SAML SSO, audit export, and branding write from core to geolens-enterprise package, proving end-to-end open-core overlay pattern**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-27T00:38:29Z
- **Completed:** 2026-03-27T00:43:32Z
- **Tasks:** 2
- **Files modified:** 13

## Accomplishments
- All three enterprise features (SAML, audit export, branding PUT) live in geolens-enterprise package
- Core is clean of enterprise implementations with no import errors
- SAML metadata parser stays in core for OAuth service CRUD
- Core tests pass (8/8 SAML metadata + schema tests)
- pysaml2 dependency removed from core, enterprise-only

## Task Commits

Each task was committed atomically:

1. **Task 1: Extract enterprise features to geolens-enterprise package** - `169e61e` (feat) [enterprise repo]
2. **Task 2: Remove extracted enterprise code from core** - `b7be6558` (feat) [core repo]

## Files Created/Modified
- `../geolens-enterprise/geolens_enterprise/auth/saml/router.py` - SAML login and ACS endpoints
- `../geolens-enterprise/geolens_enterprise/auth/saml/config.py` - pysaml2 client builder
- `../geolens-enterprise/geolens_enterprise/auth/saml/replay.py` - Assertion replay cache
- `../geolens-enterprise/geolens_enterprise/audit/export.py` - Streaming CSV/JSON audit export
- `../geolens-enterprise/geolens_enterprise/branding/router.py` - PUT /settings/branding/ endpoint
- `../geolens-enterprise/.gitignore` - Python artifacts exclusion
- `../geolens-enterprise/tests/test_registration.py` - Added router count test
- `backend/app/audit/router.py` - Stripped to list-only (export removed)
- `backend/app/settings/router.py` - Stripped branding PUT and require_enterprise import
- `backend/app/auth/saml/router.py` - Deleted (moved to enterprise)
- `backend/app/auth/saml/config.py` - Deleted (moved to enterprise)
- `backend/app/auth/saml/replay.py` - Deleted (moved to enterprise)
- `backend/pyproject.toml` - Removed pysaml2 dependency
- `backend/tests/test_saml.py` - Removed replay cache tests (moved to enterprise)

## Decisions Made
- SAML metadata parser stays in core because OAuth service CRUD (create_provider, update_provider) imports it
- defusedxml stays in core deps since metadata.py uses it
- Replay cache tests removed from core (replay.py no longer in core), metadata/schema tests stay
- Enterprise audit export router uses same /admin prefix for consistent URL paths

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- test_admin_stats has pre-existing DNS/socket error unrelated to changes (out of scope)

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Enterprise overlay pattern fully proven end-to-end
- Core starts cleanly without enterprise package
- Enterprise package provides all three features via extension loader

## Self-Check: PASSED

All created files verified present. All deleted files verified absent. All commits verified in git log.

---
*Phase: 210-enterprise-overlay-repo*
*Completed: 2026-03-26*
