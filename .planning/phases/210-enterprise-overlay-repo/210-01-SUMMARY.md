---
phase: 210-enterprise-overlay-repo
plan: 01
subsystem: infra
tags: [enterprise, entry-points, alembic, docker-compose, overlay, extensions]

requires:
  - phase: 209-enterprise-saml-sso
    provides: SAML router and enterprise extension infrastructure
provides:
  - geolens-enterprise package scaffold with entry_points registration
  - Core extension loader with router extraction support
  - Alembic multi-directory migration discovery via entry_points
  - Dynamic router registration in main.py lifespan
  - Docker compose enterprise overlay file
  - Entrypoint enterprise package install hook
affects: [210-02-enterprise-overlay-repo]

tech-stack:
  added: [geolens-enterprise package, setuptools entry_points]
  patterns: [enterprise overlay pattern, dynamic router registration, multi-directory alembic migrations]

key-files:
  created:
    - ../geolens-enterprise/pyproject.toml
    - ../geolens-enterprise/geolens_enterprise/__init__.py
    - ../geolens-enterprise/geolens_enterprise/auth/saml/__init__.py
    - ../geolens-enterprise/geolens_enterprise/audit/__init__.py
    - ../geolens-enterprise/geolens_enterprise/branding/__init__.py
    - ../geolens-enterprise/geolens_enterprise/migrations/versions/e001_enterprise_initial.py
    - ../geolens-enterprise/tests/test_registration.py
    - docker-compose.enterprise.yml
  modified:
    - backend/app/extensions/__init__.py
    - backend/alembic/env.py
    - backend/app/main.py
    - backend/scripts/api-entrypoint.sh

key-decisions:
  - "Enterprise package uses setuptools entry_points for both extension and migration discovery"
  - "Dynamic router registration replaces hardcoded SAML import in main.py"
  - "Enterprise install hook runs before migrations in entrypoint to ensure entry_points are discoverable"

patterns-established:
  - "Enterprise overlay: sibling repo mounted via docker-compose override, installed via uv pip install -e"
  - "Extension routers: extensions register routers via _routers key in registry dict, extracted by core loader"
  - "Migration discovery: geolens.migrations entry_point group returns paths to version directories"

requirements-completed: [REPO-01, REPO-02, REPO-03]

duration: 3min
completed: 2026-03-26
---

# Phase 210 Plan 01: Enterprise Overlay Repo Scaffold Summary

**Enterprise package scaffold with entry_points registration, multi-directory Alembic migration discovery, and dynamic router registration replacing hardcoded SAML import**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-26T20:30:47Z
- **Completed:** 2026-03-26T20:34:30Z
- **Tasks:** 2
- **Files modified:** 12 created, 4 modified

## Accomplishments
- Created geolens-enterprise package with pyproject.toml entry_points for both extensions and migrations
- Stub extension classes for auth/saml, audit, and branding with protocol-compliant interfaces
- Initial enterprise Alembic migration (e001) with branch_labels=['enterprise'] branching from core head
- Core extension loader now extracts and exposes routers registered by enterprise extensions
- Alembic env.py discovers enterprise migration directories via geolens.migrations entry_points
- main.py dynamically registers enterprise routers in lifespan instead of hardcoded SAML import
- Entrypoint installs enterprise package when GEOLENS_ENTERPRISE_PATH volume is mounted
- Docker compose enterprise overlay file mounts sibling repo into api/worker/migrate services

## Task Commits

Each task was committed atomically:

1. **Task 1: Enterprise package scaffold and core extension loader** - `d9a0b37` (enterprise repo) + `d74457df` (core repo)
2. **Task 2: Core infrastructure -- Alembic, main.py, entrypoint, compose overlay** - `31b1885c` (feat)

## Files Created/Modified
- `../geolens-enterprise/pyproject.toml` - Package definition with geolens.extensions and geolens.migrations entry_points
- `../geolens-enterprise/geolens_enterprise/__init__.py` - register_extensions() and get_migration_paths() callables
- `../geolens-enterprise/geolens_enterprise/auth/saml/__init__.py` - EnterpriseSamlExtension stub
- `../geolens-enterprise/geolens_enterprise/audit/__init__.py` - EnterpriseAuditExtension stub
- `../geolens-enterprise/geolens_enterprise/branding/__init__.py` - EnterpriseBrandingExtension stub
- `../geolens-enterprise/geolens_enterprise/migrations/versions/e001_enterprise_initial.py` - Branch label migration
- `../geolens-enterprise/tests/test_registration.py` - 5 tests for registration and migration
- `docker-compose.enterprise.yml` - Enterprise compose overlay
- `backend/app/extensions/__init__.py` - Added _routers list and get_extension_routers()
- `backend/alembic/env.py` - Added _discover_migration_paths() with entry_points discovery
- `backend/app/main.py` - Removed hardcoded saml_router, added dynamic router registration
- `backend/scripts/api-entrypoint.sh` - Added enterprise package install hook

## Decisions Made
- Enterprise package uses setuptools entry_points for both extension and migration discovery (consistent with existing core loader pattern)
- Dynamic router registration replaces hardcoded SAML import in main.py (enterprise routers added in lifespan after extensions load)
- Enterprise install hook runs before migrations in entrypoint to ensure entry_points are discoverable during Alembic upgrade
- Enterprise migration e001 depends on core 0010_add_saml_provider_columns as down_revision

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Enterprise package scaffold is complete and tested (5 passing tests)
- Core infrastructure supports overlay pattern end-to-end
- Plan 02 can now move SAML, audit export, and branding code into the enterprise package

## Self-Check: PASSED

All 9 key files verified present. All 3 commits verified (d74457df, 31b1885c in core; d9a0b37 in enterprise repo).

---
*Phase: 210-enterprise-overlay-repo*
*Completed: 2026-03-26*
