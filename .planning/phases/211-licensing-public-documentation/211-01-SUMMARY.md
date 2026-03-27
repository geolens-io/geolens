---
phase: 211-licensing-public-documentation
plan: 01
subsystem: infra
tags: [license, apache-2.0, env, docker, devex]

# Dependency graph
requires: []
provides:
  - Apache 2.0 LICENSE at repo root
  - Zero-config .env.example for local development
affects: [211-02]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "[CHANGE IN PRODUCTION] marker pattern for .env.example values"

key-files:
  created: []
  modified:
    - LICENSE
    - .env.example

key-decisions:
  - "Apache 2.0 full text only, no NOTICE file or per-file headers (per D-06)"
  - "Local dev defaults populated in .env.example with [CHANGE IN PRODUCTION] markers"

patterns-established:
  - "[CHANGE IN PRODUCTION] marker: env vars that work locally but must be changed for production"

requirements-completed: [DOCS-01, DOCS-03]

# Metrics
duration: 2min
completed: 2026-03-27
---

# Phase 211 Plan 01: Licensing & Environment Defaults Summary

**Apache 2.0 license replacing BUSL-1.1, plus zero-config .env.example with local-dev defaults for copy-and-go startup**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-27T10:51:02Z
- **Completed:** 2026-03-27T10:53:15Z
- **Tasks:** 2
- **Files modified:** 4 (LICENSE, .env.example, docs/EULA.md deleted, LICENSE-FAQ.md deleted)

## Accomplishments
- Replaced BUSL-1.1 license with standard Apache License 2.0 with correct copyright line
- Deleted enterprise EULA and BUSL FAQ artifacts that no longer apply
- Populated .env.example with working local defaults (POSTGRES_PASSWORD, JWT_SECRET_KEY, GEOLENS_ADMIN_PASSWORD) so `cp .env.example .env && docker compose up` works without edits

## Task Commits

Each task was committed atomically:

1. **Task 1: Replace LICENSE with Apache 2.0 and delete BUSL artifacts** - `73a2418d` (feat)
2. **Task 2: Populate .env.example with working local defaults** - `a190ebe1` (feat)

## Files Created/Modified
- `LICENSE` - Replaced BUSL-1.1 with Apache License 2.0 full text, copyright "2026 Carto Concepts, LLC"
- `.env.example` - Populated three required values with local defaults, updated header comment, replaced [REQUIRED] with [CHANGE IN PRODUCTION]
- `docs/EULA.md` - Deleted (enterprise EULA replaced by Apache 2.0)
- `LICENSE-FAQ.md` - Deleted (BUSL-specific FAQ no longer applicable)

## Decisions Made
- Apache 2.0 full text only with no NOTICE file or per-file headers (per discussion decision D-06)
- Local dev defaults: geolens/dev-only-change-me-in-production/admin for the three previously-blank required values
- [CHANGE IN PRODUCTION] marker replaces [REQUIRED] to communicate that values work as-is but need changing for production

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- LICENSE is clean Apache 2.0, ready for Plan 02 (README/CONTRIBUTING/quickstart docs) to reference
- .env.example zero-config enables the quickstart "under 10 minutes" requirement

## Self-Check: PASSED

All files exist. All commits verified.

---
*Phase: 211-licensing-public-documentation*
*Completed: 2026-03-27*
