# GeoLens Testing and CI Guide

This guide documents the current local verification workflow that matches the CI gates in `.github/workflows/ci.yml`.

If CI and this file ever disagree, update both in the same change.

## Source of Truth

- CI workflow: `.github/workflows/ci.yml`
- Frontend i18n contributor workflow: `frontend/docs/i18n.md`

## Prerequisites

### Backend

- Python `3.13+`
- `uv`
- `gdal-bin`
- A Postgres instance with `postgis` and `pg_trgm`

### Frontend

- Node `22`
- `npm`

### Local services

For local verification, the simplest path is to run the project database with Docker Compose:

```bash
docker compose up -d --wait db
```

If you use the Compose database from the host, backend test commands should normally point at:

```bash
export POSTGRES_HOST=localhost
export POSTGRES_PORT="${DB_PORT:-5434}"
```

When you point backend tests at the Compose database from the host, keep using the
Compose credentials from `.env` unless you have explicitly changed them. Out of the
box that means:

```bash
export POSTGRES_USER="${POSTGRES_USER:-geolens}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-geolens}"
export POSTGRES_DB="${POSTGRES_DB:-geolens}"
```

`backend/tests/conftest.py` creates and recreates `geolens_test` during the full
suite, so local host-based runs should connect to the primary dev database, not
directly to `geolens_test`.

## Install Dependencies

```bash
cd backend
uv sync --locked --dev
```

```bash
cd frontend
npm ci
```

## Frontend Gate Matrix

Run from `frontend/`:

```bash
npm run test:i18n
npm run check:i18n:changed
npm run lint
npx tsc --noEmit
npm run test:coverage
```

### Frontend notes

- `npm run test:i18n` checks locale parity across supported languages.
- `npm run check:i18n:changed` depends on git history. In CI, `actions/checkout` uses `fetch-depth: 0` for the frontend lint job so changed namespaces can be detected correctly.
- Frontend lint currently passes with warnings only. Treat new errors as blocking.
- Coverage output is generated under `frontend/coverage/` and should not be committed.

## Backend Gate Matrix

Run from `backend/`.

### Lint and security

```bash
uv run ruff check .
uv run ruff format --check .
uv run bandit -r app/ -c pyproject.toml --severity-level high --confidence-level high
uv run pip-audit --strict --desc
```

### Full test run

For the closest match to CI when using the local Compose database from the host,
run the full coverage command with explicit local env:

```bash
env \
  PYTHONPATH=. \
  POSTGRES_USER="${POSTGRES_USER:-geolens}" \
  POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-geolens}" \
  POSTGRES_HOST=localhost \
  POSTGRES_PORT="${DB_PORT:-5434}" \
  POSTGRES_DB="${POSTGRES_DB:-geolens}" \
  JWT_SECRET_KEY=test-secret-key-for-ci \
  GEOLENS_ADMIN_USERNAME=admin \
  GEOLENS_ADMIN_PASSWORD=admin \
  uv run pytest -v --tb=short --cov=app --cov-report=term-missing --cov-report=html:htmlcov --cov-report=xml:coverage.xml
```

### Backend notes

- The full coverage command is the one that matters most. Do not substitute a partial run when you are trying to prove CI is green.
- The local Compose path and CI use different bootstrap shapes. CI starts a dedicated
  `geolens_test` database with test credentials; the local Compose path connects to
  the primary dev database and lets `backend/tests/conftest.py` recreate
  `geolens_test` for the suite.
- `backend/tests/conftest.py` wires test storage and staging to temp directories. Filesystem-sensitive ingest/export tests rely on that fixture behavior.
- Coverage output is generated under `backend/htmlcov/`, plus `backend/.coverage` and `backend/coverage.xml`. Do not commit those artifacts.
- Warning-only output is currently expected from some third-party deprecations and the intentionally short JWT test secret.

## Recommended Local Order

When validating a branch before merging:

1. Start the database: `docker compose up -d --wait db`
2. Run backend lint/security commands
3. Run the backend full coverage command
4. Run the frontend gate matrix

This matches CI intent better than running only targeted tests.

## Common Failure Modes

### Frontend changed-namespace check fails in CI but not locally

Make sure the CI job has full history available. The current workflow does this with:

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0
```

### Backend ingest/export tests fail only on the full suite

Check:

- staging dir writability
- temp file cleanup for uploaded/remote validation paths
- whether you are using the same env vars as the CI-style backend command

### A targeted backend test passes but the full suite fails

Always rerun the exact coverage command. Several regressions only show up there because of full-suite ordering, shared state, or database collation behavior.

## When Adding or Changing Gates

- Update `.github/workflows/ci.yml`
- Update this document
- If the change affects frontend translations or locale structure, update `frontend/docs/i18n.md`
- If a new command produces generated artifacts, add a note here so they are not accidentally committed
