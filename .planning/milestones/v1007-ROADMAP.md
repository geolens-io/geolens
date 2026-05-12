# v1007 Release Hygiene

**Shipped:** 2026-05-12

## Goal

Close release hygiene after v1006 by proving dependency/security state, generated artifacts, stack health, smoke coverage, Playwright MCP browser health, and temporary data cleanup.

## Scope

- Verify `urllib3` Dependabot alerts against lockfile and scanners.
- Run broad backend/frontend/security/release gates.
- Regenerate OpenAPI and SDK artifacts after v1006 route changes.
- Fix local compose health if release smoke cannot run.
- Run root Playwright smoke and Playwright MCP browser sanity.
- Archive evidence and caveats.

## Phase 1032: release-hygiene-closeout

**Goal:** Close the post-v1006 release hygiene milestone with CI-parity evidence and local browser validation.

Requirements: REL-01, REL-02, REL-03, REL-04, REL-05, REL-06, REL-07, REL-08, REL-09, REL-10
Status: completed 2026-05-12

**Success Criteria:**
1. Dependency scanners are clean and Dependabot alert state is reconciled.
2. Backend/frontend/security gates pass.
3. OpenAPI and SDK generated artifacts are current.
4. Compose `up --wait` succeeds.
5. Playwright smoke and MCP console checks pass.
6. Milestone artifacts document all evidence and caveats.

Phase 1032 verified scanner-clean `urllib3==2.7.0`, regenerated OpenAPI/SDK artifacts for the v1006 cluster tile route, fixed the frontend compose healthcheck, made collections smoke self-seeding, ran broad CI-like gates plus root Playwright smoke, cleaned temp UAT/smoke datasets, and passed a Playwright MCP live search console check.

## Verification

- Backend ruff/format/bandit/pip-audit/full pytest coverage passed.
- Frontend i18n/changed namespace/lint/typecheck/coverage passed.
- `make openapi-check` passed after regeneration.
- `make sdks-check` passed after committing the generated artifacts.
- `docker compose up -d --wait` passed.
- `npm run e2e:smoke` passed: 29 core, 26 builder, 6 fixture tests.
- Playwright MCP live browser sanity passed with 0 current-page warnings/errors.

## Known Caveats

- GitHub Dependabot may need a default-branch rescan to close stale `urllib3` alerts.
- `docs/testing-and-ci.md` is referenced by the ship workflow skill but absent from the repository.
- Existing Vitest localstorage warning remains non-blocking.

## Requirement Coverage

10/10 requirements satisfied: REL-01..10.

Audit: passed / GO.
