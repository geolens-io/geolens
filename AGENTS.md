# Repository Guidelines

## Project Structure

GeoLens mixes Python and TypeScript. Backend source is `backend/app/`: `modules/` (domain areas), `platform/` (shared services), `processing/` (ingest/export/tiles), `standards/` (OGC/STAC/DCAT), `core/` (config, DB, permissions, edition). Migrations are in `backend/alembic/`, tests in `backend/tests/`. The React/Vite frontend is `frontend/src/` (`components/`, `pages/`, `hooks/`, `stores/`, `api/`, `i18n/`, colocated `__tests__/`); Playwright specs are in `e2e/`. The CLI is `cli/geolens_cli/`, the read-only MCP server `mcp/geolens_mcp/`, generated SDKs `sdks/`, operations files `scripts/`, `db/`, `.github/`.

## Architecture

Nginx (Vite proxy in dev) fronts the FastAPI `api` (catalog, search, OGC/STAC, vector tiles) and Titiler (COG raster tiles). A `worker` runs GDAL/ogr2ogr ingestion via the Procrastinate queue, which lives inside PostgreSQL. PostgreSQL 18 (PostGIS, pgvector, pg_trgm) is the single source of truth; MinIO/S3 holds objects; Valkey caches tiles and queries.

Backend: `catalog` is the core module (`datasets`/`collections`/`records`/`features`/`maps`/`layers`/`search`/`sources`/`validation`); access control is `catalog/authorization.py`. The `datasets` domain splits into `api/` (routers) and `domain/`, where `service_X` sub-modules sit behind the façade `domain/service.py`. Import the façade, never a sub-module; `backend/tests/test_layering.py` enforces this and the other layer boundaries.

Frontend (React 19, `@vis.gl/react-maplibre` v8, maplibre-gl v6, TanStack Query, zustand, Tailwind): the map builder is `builder/`; every API call goes through `apiFetch()` in `api/client.ts`; the auth token lives in `useAuthStore` (persisted `geolens-auth`; outside React read `useAuthStore.getState().token`); reuse `components/ui/`.

SDKs are generated from `backend/openapi.json` with `make sdks`; never hand-edit generated files (only the `auth.*`, `__init__` and `index` wrappers are hand-maintained). The CLI and MCP server are hand-maintained and wrap the SDK.

## Commands

- `make dev` / `make down`: start or stop the Docker Compose stack.
- `make migrate`: run Alembic migrations in the API container; `make alembic-check` catches model/migration drift (run it for schema changes).
- `make test` / `make test-cov`: backend pytest and coverage. `make ai-evals`: live NL→SQL evals (costs tokens, needs `ANTHROPIC_API_KEY` and the dev DB).
- `cd frontend && npm ci && npm run dev`; gates: `npm run build && npm run lint && npm run typecheck && npm run test:coverage` (`npx tsc --noEmit` is a no-op; `typecheck` is the real gate).
- `npm run e2e` / `npm run e2e:smoke`: Playwright.
- `make openapi-check`, `make sdks-check`, `make cli-test`: API snapshot and SDK/CLI drift.
- `make bump VERSION=X.Y.Z` rewrites every version site; never edit one by hand (`make version-check` is the CI gate).

Single tests: host backend `cd backend && set -a && source ../.env.test && set +a && uv run pytest tests/test_foo.py -v` (Postgres at localhost:5434); in-container `docker compose exec api env UV_CACHE_DIR=/app/staging/uv-cache UV_PROJECT_ENVIRONMENT=/app/staging/geolens-api-test-venv uv run pytest -o cache_dir=/app/staging/.pytest_cache tests/test_foo.py::test_bar -v`; frontend `cd frontend && npx vitest run src/path/foo.test.ts`; e2e `npx playwright test e2e/foo.spec.ts --project=chromium`.

After touching anything under `backend/app/`, run the tree-wide gates a focused run cannot see:

```bash
cd backend && set -a && source ../.env.test && set +a && uv run pytest tests/test_layering.py -q
python3 backend/tests/finding_markers.py
```

Neither needs a database. A missing `.env.test` (gitignored; `make env-test` creates it) kills `test_layering.py` before collection, which looks like a gate failure and is not. Two ledgers are exact in both directions: `_MODULE_LOC_CAPS` (module line counts) and `UNANCHORED_MARKER_DEBT` (bare tracker ids per module). When a file grows or shrinks, set its entry to the new value in the same commit with a line saying what the change bought.

### Worktrees

The dev stack bind-mounts the main checkout, so `localhost:8080` and the API on `:8001` always serve `main`. Playwright refuses to run from a linked worktree unless `E2E_ALLOW_WORKTREE=1`; it does not try to detect whether your change is in the stack. Frontend change: run Vite on the host at `:5174` with `API_PROXY_TARGET=http://localhost:8001`, then `E2E_ALLOW_WORKTREE=1 E2E_BASE_URL=http://localhost:5174 npx playwright test` (backend is still main's). Backend change: build a stack from the worktree (own compose project or a host-run API). Spec-only change: the shared stack is valid with the flag set. The host pytest recipe cannot `source` outside the worktree, so run `make env-test` inside it and call pytest from a wrapper script.

## Coding Principles

- Build what was asked, nothing speculative. The shortest correct diff wins; deletion beats addition; boring beats clever.
- Reach for what exists, in order: the standard library, a native platform feature (a Postgres constraint over an application check, HTML and CSS over JavaScript), a dependency already installed, then new code. Never add a dependency for what a few lines do.
- Keep it simple: no interface with one implementation, no factory for one product, no configuration for a value that never changes, no scaffolding for later.
- One definition per fact inside a domain. Reuse `platform/` helpers, the service façades, `components/ui/` and `apiFetch()` before writing a sibling. Where a layer boundary forbids the import, a small copy beats a violation.
- Never simplify away a trust boundary: input validation, access checks, SSRF gating, error handling that prevents data loss, accessibility basics.
- Non-trivial logic ships with the one test that fails if it breaks, and no fixtures or suites the change does not need.

## Style

Python: 4 spaces, `cd backend && uv run ruff check . && uv run ruff format --check .` before a change is complete. The McCabe gate is 15; the `per-file-ignores` baseline in `backend/pyproject.toml` may shrink, never grow. Frontend: TypeScript, ESLint, React Hooks and JSX a11y rules; `PascalCase` components, `use*` hooks, `_` prefix for intentionally unused names.

### Comments and docstrings

Every comment and docstring is read by every agent on every turn, so each line has a recurring token cost. Write the fewest lines that stop a reader from making a mistake.

- A comment says why, never what. If the code needs a what, rename or split the code.
- A docstring is the contract: one summary line, then only what a caller cannot infer from the signature (a non-obvious input, output or error, and the one trap). No narrative, motivation or history. A private helper whose name says it all gets none; a module docstring is a few lines on what the module holds.
- A trap comment naming a concrete failure the code guards against (a lock order, a race, a driver quirk) stays, in one to three lines.
- Route handler docstrings and Pydantic `Field(description=...)` strings are the published OpenAPI text. Editing one changes `backend/openapi.json`, both SDKs and `frontend/src/types/api.generated.ts`, so regenerate all four, and never write an absolute you cannot trace to a line.
- Pinned markers: `# codeql[...]` on its own line directly above the line it covers (prose goes above the marker); `# broad: <reason>` on the same line as every `except Exception`.

### Inline review-comment convention

A comment that references a review or audit finding carries a stable anchor (a PR or issue number) plus the invariant the code now holds, three lines at most:

```
// fix(#1234): suppress basemap row click during multi-selection
```

The history behind it goes in the PR or issue the anchor names. Never write a comment that restates the next line, and trim any comment you touch to this rule. Bare tracker ids that only resolve in a private tracker are refused by the `no-unscoped-finding-markers` hook and `backend/tests/finding_markers.py`.

## Testing

Backend: pytest with AnyIO, `test_*.py`, 80% coverage floor (`fail_under` in `backend/pyproject.toml`); DB-backed tests need `docker compose up -d --wait db` and the variables in `.env.test.example`. Frontend: Vitest and Testing Library, `*.test.ts(x)` or `__tests__/`. E2E: Playwright, `e2e/*.spec.ts`.

New `t()` keys go in all four locales (en/es/fr/de); a `defaultValue` alone fails `npm run test:i18n`. Plural suffixes follow the same all-four-or-none rule: there is no `_many`→`_other` fallback, and French resolves count 0 to `_one`, so `_one` values interpolate `{{count}}` rather than hardcoding "1".

## Commits, PRs and Docs

Conventional Commit subjects with a meaningful scope, e.g. `feat(sharing): add schema gates for advanced sharing`. PRs describe the change, call out schema/API/config impacts, link issues, include screenshots for UI work and list verification commands. Commit `backend/openapi.json` or SDK output only when the source change requires it.

Root docs are single-purpose: `README.md` (public overview), `SUPPORT.md`, `CHANGELOG.md` (release-note source of truth), `EDITIONS.md` (open-core boundary, REL-01) and `RUNBOOK.md` (operator recovery, BKP-04). README images live in `.github/assets/`, contributor docs under `.github/`, product docs on docs.getgeolens.com, private notes in ignored `docs-internal/`. Do not reintroduce a root `docs/` directory or narrative feature docs that duplicate the docs site. Brand assets come from a tagged release of the sibling `geolens-io/branding` repo, never re-authored here; changes propagate branding → this repo → marketing → docs.

## Security & Configuration

Use `.env.example` and `.env.test.example` as templates. Never commit secrets, coverage output, Playwright reports, virtual environments or dependency directories. `.gitignore` covers assistant and internal-notes directories (`.claude/`, `.planning/`, `docs-internal/`); untrack any that slip in before committing.

### Security pre-commit checklist

Any change touching catalog data access, external URL fetching or boot-time credential validation must satisfy these.

**Rule 1: Visibility-filter coverage.** Any new FastAPI handler that fetches a `Record`, `Dataset`, `Map` or `RecordEmbedding` by ID does ONE of: `check_dataset_access_or_anonymous(db, dataset, dataset_id, user)` (reads), `check_dataset_access(...)` (writes; 404 on denial), `check_dataset_write_access(...)` (owner-or-admin mutations), all from `backend/app/modules/catalog/authorization.py`, or `apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)` on its own `Select` (list endpoints). Reference: `standards/ogc/router.py`, `standards/stac/router.py` (read), `catalog/datasets/api/router_metadata.py` (write). Enforced by a pre-commit grep and, per handler, by `backend/tests/test_rule1_structural.py` (#822).

**Rule 2: SSRF redirect-revalidation.** Any `httpx.AsyncClient` with `follow_redirects=True` comes from `make_safe_client()` in `backend/app/platform/security.py`, which re-runs `validate_url_for_ssrf` on every 3xx `Location`. A pre-commit grep enforces this half. `security.py`, `gdal_env.py` and `gdal_drivers.py` stay in `platform/`: their callers span auth, config_ops, catalog and processing, and `modules/catalog/` may not import `app.processing.*` (#435, #1857).

GDAL, ogr2ogr and rasterio cannot be made redirect-safe from the inside. `GDAL_HTTP_FOLLOWLOCATION` is not a GDAL option, setting it does nothing (#937), and no test catches it: never re-add it. The defenses are structural, in this order, and `backend/tests/test_rule2_structural.py` (#936) enforces them per call and per argv with an EMPTY allowlist (#1857):

1. Never hand a caller-controlled URL to GDAL. Read managed storage only (`/vsis3/`, `/vsiaz/`, validated local keys); never probe remote sources in-process.
2. Where a user-supplied service URL must be fetched, `validate_url_for_ssrf` gates it at submission; the worker egress firewall bounds the rest.
3. Subprocess envs come from `gdal_safe_env()` / `gdal_safe_open_env()` (`backend/app/processing/raster/vrt.py`).
4. A vector argv also bounds WHICH driver may open its source, because several OGR drivers treat the document as instructions naming somewhere else to read. Both halves are required: `local_input_driver_args()` (`backend/app/processing/ingest/gdal_drivers.py`) adds `-if <driver>` arguments from the declared extension, and `gdal_vector_safe_env()` / `gdal_service_safe_env()` (`backend/app/platform/gdal_env.py`) set `GDAL_SKIP` so pointer-following and network drivers never register. Traps: `GDAL_SKIP` tokenises on spaces, and an unrecognised driver name is a silent warning (#1846). `backend/tests/test_gdal_driver_clamp_1846.py` measures both halves against a real GDAL.
5. `GPKG` and `SQLite` are pointer-following through virtual tables and cannot be clamped, because GeoPackage is the primary upload format. `validate_content_directives()` (`backend/app/processing/ingest/validation.py`) reads `sqlite_master` through the stdlib driver (read-only, immutable) and refuses any virtual-table module outside a small allowlist, for top-level databases and for every archive member whose BYTES are one. Identify members by content, never by name (GDAL never reads the name; the OGR VRT driver finds its root by substring search, so a BOM hides nothing). It also refuses VRT-shaped members, runs `validate_zip_safety` first under one byte budget, and runs at the upload doors AND the three staged-upload GDAL entry points. Read the raw `sql` column, never `PRAGMA`. Measured ineffective: `SPATIALITE_SECURITY=strict`, `OGR_SQLITE_LOAD_EXTENSIONS=NONE`, `OGR_SQLITE_LIST_ALL_TABLES=NO` (#1846).

**Rule 3: Known-public credential literals.** A few demo credentials leaked through git history and are public knowledge; never reintroduce one as a default, fallback, example or test value. `validate_known_bad_credentials` in `backend/app/core/config.py` holds the list and refuses to boot when `JWT_SECRET_KEY`, `GEOLENS_ADMIN_PASSWORD` or `POSTGRES_PASSWORD` matches. MinIO credentials are not `Settings` fields; the minio entrypoint in `docker-compose.yml` refuses blank `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD` instead, referenced as parse-safe `${MINIO_ROOT_USER:-}` because `:?required` broke `compose config` even with the profile inactive (INST-01).

**Standing CodeQL policy** (2026-08-03, adopted in #1615): a validated-identifier `py/sql-injection` alert on a dynamic `text()` site is suppressed with `# codeql[py/sql-injection]` on its own line directly above the site; a trailing marker is silently ignored. `.github/codeql/python-suppression/` holds the vendored query (the stock one reads every `# noqa` as a bare `lgtm`) and `.github/workflows/codeql.yml` dismisses what it marks, because GitHub does not honour SARIF `suppressions[]` on its own. `backend/tests/test_codeql_qtable_suppressions.py` pins all of it.
