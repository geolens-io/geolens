---
milestone: v1007
milestone_name: Release Hygiene
status: passed
audited: 2026-05-12T23:13:11Z
phases: [1032]
requirements: 10
requirements_complete: 10
recommendation: GO
---

# v1007 Milestone Audit: Release Hygiene

## Result

Status: `passed`

The milestone goal is satisfied: GeoLens release hygiene is green locally after v1006, with dependency scanners clean, generated OpenAPI/SDK artifacts reconciled, compose health fixed, root Playwright smoke passing, and Playwright MCP browser verification clean after temporary data cleanup.

## Phase Completion

| Phase | Status | Plans | Verification |
|-------|--------|-------|--------------|
| 1032 Release hygiene closeout | Complete | 1/1 | dependency/security gates, OpenAPI/SDK generation, compose health, Playwright smoke, MCP console check |

## Requirement Coverage

| Group | Requirements | Status |
|-------|--------------|--------|
| Dependency and security hygiene | REL-01..03 | 3/3 complete |
| Generated artifact hygiene | REL-04..05 | 2/2 complete |
| Runtime and browser hygiene | REL-06..09 | 4/4 complete |
| Closeout | REL-10 | 1/1 complete |

Total: 10/10 v1007 requirements complete.

## Key Accomplishments

1. Verified `urllib3` Dependabot alerts as locally remediated by `urllib3==2.7.0` plus a clean `pip-audit`.
2. Ran broad backend, frontend, security, and coverage gates, including the full backend pytest suite.
3. Regenerated OpenAPI and SDK artifacts for the server-side cluster tile route.
4. Fixed Docker Compose frontend health by changing the dev-server probe to IPv4 loopback.
5. Removed a brittle seeded-catalog assumption from the collections smoke spec by self-seeding a tiny dataset through the real ingest API.
6. Cleaned known temporary UAT/smoke datasets and confirmed the live search page is console-clean through Playwright MCP.

## Verification Summary

- Backend ruff check and format check passed.
- Backend bandit and pip-audit passed.
- Backend full pytest passed: 2564 passed, 31 skipped, 17 deselected, coverage 66.09%.
- Frontend i18n, changed namespace, lint, typecheck, and coverage passed.
- OpenAPI check passed after snapshot regeneration.
- SDK generation produced expected artifacts; `make sdks-check` passed after commit.
- Docker Compose `up -d --wait` passed with all long-running services healthy.
- Playwright collections spec passed: 8/8.
- Root Playwright smoke passed: 29 core, 26 builder, 6 fixture tests.
- Playwright MCP verified live search page render and 0 current-page warnings/errors.

## Known Caveats

- The existing Vitest `--localstorage-file` warning remains non-blocking.

## Follow-up Resolved 2026-05-12

- GitHub Dependabot alerts #36/#37 were dismissed as inaccurate after verifying `origin/main` resolves `urllib3==2.7.0` and `pip-audit` remains clean.
- `docs/testing-and-ci.md` now documents the local testing and CI command map; `.github/workflows/ci.yml` remains canonical.

## Recommendation

GO. v1007 is complete and ready for archive/tag.
