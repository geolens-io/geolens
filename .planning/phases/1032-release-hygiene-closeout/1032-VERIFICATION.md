# Phase 1032 Verification

## Automated Gates

- PASS — backend ruff:
  `cd backend && uv run ruff check .`
- PASS — backend format:
  `cd backend && uv run ruff format --check .`
  - 480 files already formatted.
- PASS — backend security scan:
  `cd backend && uv run bandit -r app/ -c pyproject.toml --severity-level high --confidence-level high`
  - High severity issues: 0.
- PASS — backend dependency audit:
  `cd backend && uv run pip-audit --strict --desc`
  - No known vulnerabilities found.
- PASS — backend full test coverage:
  `cd backend && POSTGRES_HOST=localhost POSTGRES_PORT=5434 POSTGRES_USER=geolens POSTGRES_PASSWORD=geolens POSTGRES_DB=geolens JWT_SECRET_KEY=test-secret-key-for-ci-padding-32chars GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=admin PYTHONPATH=. uv run pytest -v --tb=short -m 'not perf and not lifecycle' --cov=app --cov-report=term-missing --cov-fail-under=60`
  - 2564 passed, 31 skipped, 17 deselected, 19 warnings.
  - Coverage: 66.09%; required: 60%.
- PASS — frontend i18n and changed namespace gate:
  `cd frontend && npm run test:i18n && npm run check:i18n:changed`
  - 2 i18n tests passed.
  - No locale file changes detected.
- PASS — frontend lint:
  `cd frontend && npm run lint -- --quiet`
- PASS — frontend typecheck:
  `cd frontend && npx tsc --noEmit`
- PASS — frontend coverage:
  `cd frontend && npm run test:coverage`
  - 155 test files passed.
  - 1391 tests passed.
  - Coverage summary: statements 49%, branches 46.54%, functions 45.5%, lines 50.39%.
- PASS after regeneration — OpenAPI snapshot:
  `make openapi-check`
  - Initial run found drift; `make openapi` regenerated `backend/openapi.json`; rerun passed.
- PASS after commit — SDK check:
  `make sdks-check`
  - Before commit, the check generated expected SDK changes for `/tiles/clusters/{table_path}/{z}/{x}/{y}.pbf` and `SharedLayerResponse.id`, then failed on the uncommitted diff as designed.
  - After commit, the same command passed with no SDK drift.
- PASS — compose stack:
  `docker compose up -d --wait`
  - API, DB, frontend, titiler, worker healthy; migrate exited 0.
- PASS — targeted collections smoke after fix:
  `npx playwright test e2e/collections.spec.ts --project=chromium`
  - 8 passed.
- PASS — full Playwright smoke:
  `npm run e2e:smoke`
  - Core: 29 passed.
  - Builder: 26 passed.
  - Fixtures: 6 passed.

## Playwright MCP

- PASS — navigated to `http://localhost:8080/`.
- PASS — live search page rendered authenticated catalog results after temp dataset cleanup.
- PASS — current-page console had 0 warnings and 0 errors.
- Screenshot evidence: `v1007-release-hygiene-search-clean.png`.

## Dependency Verification

- GitHub Dependabot open alerts checked:
  - #36 `urllib3` high severity, patched in 2.7.0.
  - #37 `urllib3` high severity, patched in 2.7.0.
- Local dependency state:
  - `backend/pyproject.toml` requires `urllib3>=2.7.0`.
  - `backend/uv.lock` contains `urllib3==2.7.0`.
  - `uv lock --upgrade-package urllib3` produced no file changes.
  - `pip-audit --strict --desc` passed.

## Issues Found And Fixed

- OpenAPI snapshot was missing the v1006 cluster tile route.
  - Fixed by regenerating `backend/openapi.json`.
- SDK generated clients were missing the cluster tile endpoint and the shared-layer `id` field.
  - Fixed by regenerating Python and TypeScript SDK artifacts.
- Docker Compose frontend healthcheck used `localhost`, which resolved to `::1` in the container while Vite listened on IPv4.
  - Fixed by probing `http://127.0.0.1:5173/`.
- Collections smoke depended on a `Coastline` seed dataset that was not present in the local smoke DB.
  - Fixed by self-seeding a tiny GeoJSON dataset through the real ingest API and cleaning it up in `afterAll`.
- Authenticated search showed temporary smoke/UAT datasets with missing quicklook resources, creating browser console 404s.
  - Fixed by authenticated bulk-delete of the known temp datasets.

## Remaining Notes

- `make sdks-check` passed after commit; before commit, the drift gate correctly reported the generated diff.
- The `--localstorage-file` Vitest warning remains existing test-runner noise.
- The React DevTools info message in MCP is not a warning/error.
