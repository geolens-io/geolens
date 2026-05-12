# Testing and CI

This runbook maps the current GeoLens CI gates to local commands. The canonical source remains `.github/workflows/ci.yml`; update this page when the workflow changes.

## Quick smoke

Use this when checking a branch before a focused review:

```bash
docker compose up -d --wait db
(cd backend && uv run ruff check . && uv run ruff format --check .)
(cd frontend && npm ci && npm run lint && npx tsc --noEmit)
npm run e2e:smoke:core
```

Use `make dev` to bring up the full development stack and `make down` to stop it.

## Backend gates

CI runs backend lint and tests against PostgreSQL with PostGIS and pgvector. Locally, start the repo database first:

```bash
docker compose up -d --wait db
```

Run lint and format checks:

```bash
cd backend
uv sync --locked --dev
uv run ruff check .
uv run ruff format --check .
```

Run the backend test gate:

```bash
cd backend
POSTGRES_HOST=localhost \
POSTGRES_PORT=5434 \
POSTGRES_USER=geolens \
POSTGRES_PASSWORD=geolens \
POSTGRES_DB=geolens \
JWT_SECRET_KEY=test-secret-key-for-ci-padding-32chars \
GEOLENS_ADMIN_USERNAME=admin \
GEOLENS_ADMIN_PASSWORD=admin \
PYTHONPATH=. \
uv run pytest -v --tb=short -m "not perf and not lifecycle" \
  --cov=app --cov-report=term-missing --cov-fail-under=60
```

Use `-m "not perf"` instead when the enterprise overlay is installed and lifecycle tests are available.

Run security scanners:

```bash
cd backend
uv run bandit -r app/ -c pyproject.toml --severity-level high --confidence-level high
uv run pip-audit --strict --desc
```

## Frontend gates

```bash
cd frontend
npm ci
npm run test:i18n
npm run check:i18n:changed
npm run lint
npx tsc --noEmit
npm run test:coverage
npm run build
```

`npm run build` is a release sanity check. The CI workflow runs lint, typecheck, and coverage as separate frontend jobs.

## OpenAPI and SDK drift

OpenAPI and SDK artifacts are generated from the backend runtime schema. For local checks, provide the same padding settings the workflow uses:

```bash
JWT_SECRET_KEY=openapi-snapshot-padding-key-32chars \
POSTGRES_PASSWORD=ci-padding-no-db \
GEOLENS_ADMIN_USERNAME=admin \
GEOLENS_ADMIN_PASSWORD=admin \
make openapi-check
```

If the snapshot legitimately changes, regenerate and commit it:

```bash
JWT_SECRET_KEY=openapi-snapshot-padding-key-32chars \
POSTGRES_PASSWORD=ci-padding-no-db \
GEOLENS_ADMIN_USERNAME=admin \
GEOLENS_ADMIN_PASSWORD=admin \
make openapi
```

Run SDK drift checks after API changes:

```bash
JWT_SECRET_KEY=sdks-check-padding-key-32characters-here \
POSTGRES_PASSWORD=ci-padding-no-db \
GEOLENS_ADMIN_USERNAME=admin \
GEOLENS_ADMIN_PASSWORD=admin \
make sdks-check
```

If the SDKs drift intentionally, run `make sdks`, review the generated diff, and commit the affected `sdks/` files.

## Browser and E2E

Start the full stack before browser tests:

```bash
docker compose up -d --wait
```

Root scripts:

```bash
npm ci
npm run e2e
npm run e2e:smoke
npm run e2e:smoke:core
npm run e2e:smoke:builder
npm run e2e:smoke:fixtures
npm run e2e:smoke:audit
npm run e2e:export
```

For UI-heavy changes, also run a Playwright MCP browser pass on the changed flow and check the current page console for warnings and errors.

## CLI and manifest checks

The CLI tests need the local PostgreSQL service:

```bash
docker compose up -d --wait db
make cli-test
```

Manifest contract checks:

```bash
docker compose up -d --wait db
make manifest-contract-check
```

## Notes

- Keep `.github/workflows/ci.yml` as the source of truth for job selection and exact environment variables.
- Use `backend/pyproject.toml` for the local coverage policy. The current project threshold is `60`.
- Use `uv lock --check` before treating dependency scanner output as authoritative.
- Do not commit local reports such as `htmlcov/`, Playwright reports, virtual environments, or dependency directories.
