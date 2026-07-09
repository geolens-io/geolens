# Repository Guidelines

## Project Structure & Module Organization

GeoLens mixes Python and TypeScript. Backend source is in `backend/app/`: `modules/` holds domain areas, `platform/` shared services, `processing/` ingest/export/tile work, and `standards/` OGC/STAC/DCAT integrations. Migrations are in `backend/alembic/`; tests are in `backend/tests/`.

The React/Vite frontend is in `frontend/src/`: `components/`, `pages/`, `hooks/`, `stores/`, `api/`, `assets/`, `i18n/`, and colocated `__tests__/`. Playwright specs are in `e2e/`. The CLI is in `cli/geolens_cli/`; generated SDKs are in `sdks/`; operations files are in `scripts/`, `db/`, and `.github/`.

## Build, Test, and Development Commands

- `make dev` / `make down`: start or stop the Docker Compose development stack.
- `make migrate`: run Alembic migrations in the API container. `make alembic-check` fails if the ORM models have drifted from the migration scripts (run it for schema-adjacent changes).
- `make test` / `make test-cov`: run backend pytest and coverage.
- `npm run e2e` or `npm run e2e:smoke`: run Playwright suites.
- `cd frontend && npm ci && npm run dev`: install frontend dependencies and start Vite.
- `cd frontend && npm run build && npm run lint && npm run test:coverage`: run frontend gates.
- `make openapi-check`, `make sdks-check`, `make cli-test`: validate API snapshots and SDK/CLI drift.
- `make bump VERSION=X.Y.Z`: rewrite every version site atomically. Never edit a version string by hand; `make version-check` is the CI gate.

### Running a single test

- Backend, in-container: mirror `make test`'s env (the container's default uv cache is read-only), e.g. `docker compose exec api env UV_CACHE_DIR=/app/staging/uv-cache UV_PROJECT_ENVIRONMENT=/app/staging/geolens-api-test-venv uv run pytest -o cache_dir=/app/staging/.pytest_cache tests/test_foo.py::test_bar -v`.
- Backend, on the host (needs Postgres at localhost:5434): `cd backend && set -a && source ../.env.test && set +a && uv run pytest tests/test_foo.py -v`.
- Frontend: `cd frontend && npx vitest run src/path/foo.test.ts`.
- E2E: `npx playwright test e2e/foo.spec.ts --project=chromium` (stack must be running).

## Architecture

Services (`docker-compose.yml`): Nginx (prod proxy; Vite proxy in dev) fronts the FastAPI `api` (catalog, search, OGC/STAC, vector tiles) and Titiler (COG raster tiles). A `worker` runs GDAL/ogr2ogr ingestion, dispatched via the Procrastinate job queue that lives *inside* PostgreSQL (no separate broker). PostgreSQL 17 (PostGIS + pgvector + pg_trgm) is the single source of truth; object storage is MinIO/S3; Valkey is the tile/query cache.

Backend `backend/app/`: `modules/` (domain areas — `catalog` is the core, with `datasets`/`collections`/`records`/`features`/`maps`/`layers`/`search`/`sources`), `platform/` (shared services), `processing/` (ingest/export/raster/tiles/embeddings/ai), `standards/` (OGC/STAC/DCAT), `core/` (config, DB, permissions, edition). Access control is in `catalog/authorization.py`. The `datasets` domain is split into `service_X` sub-modules behind a re-export façade in `service.py` — import via the façade, never the sub-modules (architecture-guard test enforces this).

Frontend `frontend/src/` (React 19, `@vis.gl/react-maplibre` v8 / maplibre-gl v5, TanStack Query, zustand, Tailwind): the map builder is `builder/`; all API calls go through `apiFetch()` in `api/client.ts`; the auth token lives in `useAuthStore` (persisted `geolens-auth`, read outside React via `useAuthStore.getState().token`); reuse UI primitives from `components/ui/`.

CLI (`cli/geolens_cli/`) and SDKs (`sdks/`) wrap the API. SDKs are generated from `backend/openapi.json` — regenerate with `make sdks`, never hand-edit generated files (only `auth.*`/`__init__`/`index` wrappers are hand-maintained).

## Coding Style & Naming Conventions

Use 4 spaces for Python and keep code inside existing backend domain boundaries. Run `cd backend && uv run ruff check .` and `uv run ruff format --check .` before backend changes are complete.

Frontend code uses TypeScript, React, ESLint, React Hooks rules, and JSX accessibility checks. Prefer `PascalCase` components, `use*` hooks, and existing primitives from `frontend/src/components/ui/`. Prefix intentionally unused variables or parameters with `_`.

### Inline review-comment convention

When an in-source comment references a finding from a code review or audit, anchor it to a stable, lookup-able reference (a PR or issue number) plus a one-line context, so future readers can find the rationale:

```
// fix(#1234): suppress basemap row click during multi-selection
```

Avoid bare, unscoped finding ids that only resolve in a private tracker.

## Testing Guidelines

Backend tests use pytest with AnyIO; files follow `test_*.py`. Coverage in `backend/pyproject.toml` has a 60% minimum (`fail_under`). For DB-backed tests, start Postgres with `docker compose up -d --wait db`; follow `.env.test.example` and `.github/workflows/ci.yml` for CI-style variables.

Frontend tests use Vitest and Testing Library as `*.test.ts(x)` files or under `__tests__/`. E2E tests use Playwright and follow `*.spec.ts` in `e2e/`.

New `t()` translation keys must be added to all four locales (en/es/fr/de); a `defaultValue` alone fails the `npm run test:i18n` locale-parity CI gate.

## Commit & Pull Request Guidelines

History follows a Conventional Commit-like pattern, for example `feat(sharing): add schema gates for advanced sharing` or `docs(readme): clarify the install steps`. Use an imperative subject and meaningful scope.

Pull requests should describe the change, call out schema/API/config impacts, link issues, include screenshots for UI work, and list verification commands. Commit `backend/openapi.json` or SDK output only when the source change requires it.

## Cross-Repo Brand Assets

Brand assets (logos, color tokens, font references, brand-usage rules, press materials) live in the sibling [`geolens-io/branding`](https://github.com/geolens-io/branding) repository — not here. When an app feature needs a logo, palette token, or identity element, copy from a tagged branding release rather than re-authoring locally. The propagation order for any change that touches brand identity is **branding → this repo → marketing → docs**. Cross-surface brand canon lives in branding's `BRAND-GUIDE.md`.

## Security & Configuration Tips

Use `.env.example` and `.env.test.example` as templates. Never commit secrets, coverage output, Playwright reports, virtual environments, or dependency directories.

Keep assistant and internal-notes state out of git. `.gitignore` covers AI-assistant and internal directories (e.g. `.claude/`, `.planning/`, `docs-internal/`); if any of those become tracked, untrack them before committing.

Keep root repository docs single-purpose: `README.md` is the public overview, `SUPPORT.md` is support routing, and `CHANGELOG.md` is the release-note source of truth. Two further root docs are sanctioned because product requirements mandate them in-repo: `EDITIONS.md` (the open-core/commercial boundary — required at the repo root for licensing transparency, REL-01) and `RUNBOOK.md` (the operator backup/restore & disaster-recovery runbook — must ship in-repo so a self-hoster can recover offline, BKP-04). README images live in `.github/assets/`, detailed product docs live on docs.getgeolens.com, contributor-facing architecture/onboarding docs live under `.github/` (e.g. `.github/CONTRIBUTING.md`, `.github/ARCHITECTURE.md`), and private/internal notes stay in ignored `docs-internal/`. Do not reintroduce a root `docs/` directory or standalone narrative feature docs that duplicate the docs site.

### Security pre-commit checklist

The rules below codify recurring security-review patterns. Any code change that touches catalog data access, external URL fetching, or boot-time credential validation must satisfy them.

**Rule 1 — Visibility-filter coverage** *(the most common access-control regression surface)*

Any new FastAPI handler that fetches a `Record`, `Dataset`, `Map`, or `RecordEmbedding` by ID must do ONE of:

- Call `check_dataset_access_or_anonymous(db, dataset, dataset_id, user)` from `backend/app/modules/catalog/authorization.py` (read-side endpoints), OR
- Call `check_dataset_access(db, dataset, dataset_id, user)` from the same module (write/destructive endpoints; raises 404 on access denial), OR
- Apply `apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)` to the underlying SQLAlchemy `Select` (list endpoints with their own query construction).

Reference implementations:
- `backend/app/standards/ogc/router.py` — OGC Features peer router (read path).
- `backend/app/standards/stac/router.py` — STAC router (read path).
- `backend/app/modules/catalog/datasets/api/router_metadata.py` — 5 sibling mutation handlers (write path).

**Rule 2 — SSRF redirect-revalidation**

Any new `httpx.AsyncClient` configured with `follow_redirects=True` MUST be constructed via `make_safe_client()` from `backend/app/modules/catalog/sources/security.py` — never directly with `httpx.AsyncClient(follow_redirects=True, ...)`. The factory installs the per-hop `_revalidate_redirect` event hook that re-runs `validate_url_for_ssrf` against every 3xx `Location` header.

The same applies to ogr2ogr / GDAL subprocess calls that fetch user-supplied URLs: set `GDAL_HTTP_FOLLOWLOCATION=NO` in the subprocess env. Reference: `backend/app/processing/ingest/ogr.py` (service-ingest path).

**Rule 3 — Never reintroduce known-public credential literals**

A handful of demo credential literals leaked through git history when an early demo deployment template shipped, so they must be treated as public knowledge. Never reintroduce a known-leaked credential as a default, fallback, example, or test value. The canonical list and the boot-time check live in `validate_known_bad_credentials` in `backend/app/core/config.py`.

**Two distinct enforcement layers:**

- **Python boot guard** (`validate_known_bad_credentials` in `backend/app/core/config.py`): refuses to boot if `JWT_SECRET_KEY`, `GEOLENS_ADMIN_PASSWORD`, or `POSTGRES_PASSWORD` matches a known-public literal. MinIO credentials are **not** `Settings` fields and are **not** inspected by this guard.
- **MinIO runtime entrypoint guard** (`docker-compose.yml`, minio service): the compose file uses parse-safe `${MINIO_ROOT_USER:-}` references (the old `:?required` syntax aborted `compose config` at parse time even when the cloud-dev profile was inactive, breaking a verbatim-`.env.example` install — INST-01), and the entrypoint refuses to start MinIO when `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD` are blank, so it can never silently boot with the well-known `minioadmin` defaults. The operator must supply a non-default value (e.g. via `openssl rand -base64 24`).

**Enforcement.** Both Rule 1 and Rule 2 have pre-commit grep hooks in `.pre-commit-config.yaml`. Rule 1's hook matches any `@*router.<verb>` handler that calls `get_dataset(` and greps the file for an access/visibility check (it has no `exclude:` clause). Rule 2's hook fails any non-excluded file that constructs `httpx.AsyncClient(` while `follow_redirects=True` appears in the file. Rule 3 is enforced at backend boot — boot-failure is the signal.
