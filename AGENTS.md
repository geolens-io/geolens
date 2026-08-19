# Repository Guidelines

## Project Structure & Module Organization

GeoLens mixes Python and TypeScript. Backend source is in `backend/app/`: `modules/` holds domain areas, `platform/` shared services, `processing/` ingest/export/tile work, and `standards/` OGC/STAC/DCAT integrations. Migrations are in `backend/alembic/`; tests are in `backend/tests/`.

The React/Vite frontend is in `frontend/src/`: `components/`, `pages/`, `hooks/`, `stores/`, `api/`, `assets/`, `i18n/`, and colocated `__tests__/`. Playwright specs are in `e2e/`. The CLI is in `cli/geolens_cli/`; the read-only MCP server is in `mcp/geolens_mcp/`; generated SDKs are in `sdks/`; operations files are in `scripts/`, `db/`, and `.github/`.

## Build, Test, and Development Commands

- `make dev` / `make down`: start or stop the Docker Compose development stack.
- `make migrate`: run Alembic migrations in the API container. `make alembic-check` fails if the ORM models have drifted from the migration scripts (run it for schema-adjacent changes).
- `make test` / `make test-cov`: run backend pytest and coverage.
- `make ai-evals`: live-provider NL→SQL regression evals in `backend/tests/evals/` (skipped in normal test runs; costs provider tokens, needs `ANTHROPIC_API_KEY` and the dev DB).
- `npm run e2e` or `npm run e2e:smoke`: run Playwright suites.
- `cd frontend && npm ci && npm run dev`: install frontend dependencies and start Vite.
- `cd frontend && npm run build && npm run lint && npm run typecheck && npm run test:coverage`: run frontend gates (`npx tsc --noEmit` is a no-op here; `npm run typecheck` is the real type gate).
- `make openapi-check`, `make sdks-check`, `make cli-test`: validate API snapshots and SDK/CLI drift.
- `make bump VERSION=X.Y.Z`: rewrite every version site atomically. Never edit a version string by hand; `make version-check` is the CI gate.

### Running a single test

- Backend, in-container: mirror `make test`'s env (the container's default uv cache is read-only), e.g. `docker compose exec api env UV_CACHE_DIR=/app/staging/uv-cache UV_PROJECT_ENVIRONMENT=/app/staging/geolens-api-test-venv uv run pytest -o cache_dir=/app/staging/.pytest_cache tests/test_foo.py::test_bar -v`.
- Backend, on the host (needs Postgres at localhost:5434): `cd backend && set -a && source ../.env.test && set +a && uv run pytest tests/test_foo.py -v`.
- Frontend: `cd frontend && npx vitest run src/path/foo.test.ts`.
- E2E: `npx playwright test e2e/foo.spec.ts --project=chromium` (stack must be running).

A focused selection is blind to the module-size gates. `backend/tests/test_layering.py` caps the size of the largest backend modules, and CI runs it on every PR that triggers `backend-test`, so a change that adds lines to a ratcheted file passes locally and fails there.

If you touched anything under `backend/app/`, finish with:

```bash
cd backend && set -a && source ../.env.test && set +a && uv run pytest tests/test_layering.py -q
```

- It needs no database.
- It does boot `app.core.config`, so a bare run dies on missing env vars with a non-zero exit before collecting anything. That reads exactly like a gate failure and is not one.
- In a fresh clone `.env.test` does not exist yet (it is gitignored). Create it once with `make env-test` from the repo root.
- Growth is allowed. Raise the file's cap in `_MODULE_LOC_CAPS` in the same commit, with a comment saying what the lines bought.

### Working from a git worktree

The dev stack bind-mounts the MAIN checkout (`./frontend` → `/app`, and `backend/app` → `/app/app` with `--reload`), so `localhost:8080` always serves `main` no matter which branch your worktree is on. Running `npx playwright test` from a worktree therefore validates code you did not write. Treat the result as meaningless: it has produced a false FAILURE, and the symmetric case is worse, because a worktree change that breaks e2e passes when the stack never had it. `playwright.config.ts` and `playwright.builder-hardening.config.ts` both call `assertWorktreeMatchesStack()` (`playwright.worktree-guard.ts`), which refuses to run from a linked worktree unless you set `E2E_ALLOW_WORKTREE=1`. It does not try to work out whether your changes are in the stack — that question spans git reporting, filesystem semantics and compose configuration, and an earlier revision got it wrong eleven different ways. Acknowledging costs one variable; a silent false pass costs an answer you cannot see.

To exercise worktree **frontend** code, run Vite on the host at `:5174` with `API_PROXY_TARGET=http://localhost:8001`, then `E2E_ALLOW_WORKTREE=1 E2E_BASE_URL=http://localhost:5174 npx playwright test`. That recipe is frontend-only: `:8001` is the MAIN checkout's API container (`docker-compose.yml`, `host :8001 -> api:8000`), so a change under `backend/app/` or `backend/alembic/` still would not be under test. Exercising a worktree **backend** change needs a stack built from that worktree — a separate compose project with its own ports, or a host-run API serving the worktree's backend.

A spec-only change (editing `e2e/*.spec.ts` with no app-code change) is the one case where running against the shared stack from a worktree is genuinely valid, because Playwright reads the specs from your worktree while the app code is whatever the main checkout is serving. That still needs `E2E_ALLOW_WORKTREE=1`: the guard cannot tell a spec-only branch from any other, and deliberately does not try.

The host backend recipe above is also unrunnable verbatim from a worktree — the sandbox refuses `source` on a path outside the worktree and denies reading `.env*`. Run `make env-test` inside the worktree instead (it is gitignored; delete it when you are done) and run pytest from a wrapper script.

## Architecture

Services (`docker-compose.yml`): Nginx (prod proxy; Vite proxy in dev) fronts the FastAPI `api` (catalog, search, OGC/STAC, vector tiles) and Titiler (COG raster tiles). A `worker` runs GDAL/ogr2ogr ingestion, dispatched via the Procrastinate job queue that lives *inside* PostgreSQL (no separate broker). PostgreSQL 18 (PostGIS + pgvector + pg_trgm) is the single source of truth; object storage is MinIO/S3; Valkey is the tile/query cache.

Backend `backend/app/`: `modules/` (domain areas — `catalog` is the core, with `datasets`/`collections`/`records`/`features`/`maps`/`layers`/`search`/`sources`/`validation`), `platform/` (shared services), `processing/` (ingest/export/raster/tiles/embeddings/ai), `standards/` (OGC/STAC/DCAT), `core/` (config, DB, permissions, edition). Access control is in `catalog/authorization.py`. The `datasets` domain is split into `api/` (routers) and `domain/`, where service logic lives in `service_X` sub-modules behind a re-export façade in `domain/service.py` — import via the façade, never the sub-modules (`backend/tests/test_layering.py` enforces this).

Frontend `frontend/src/` (React 19, `@vis.gl/react-maplibre` v8 / maplibre-gl v5, TanStack Query, zustand, Tailwind): the map builder is `builder/`; all API calls go through `apiFetch()` in `api/client.ts`; the auth token lives in `useAuthStore` (persisted `geolens-auth`, read outside React via `useAuthStore.getState().token`); reuse UI primitives from `components/ui/`.

CLI (`cli/geolens_cli/`) and SDKs (`sdks/`) wrap the API. SDKs are generated from `backend/openapi.json` — regenerate with `make sdks`, never hand-edit generated files (only `auth.*`/`__init__`/`index` wrappers are hand-maintained). The read-only MCP server (`mcp/geolens_mcp/`) is a hand-maintained package (like the CLI) that exposes catalog/feature/map reads to coding agents; it depends on the `geolens` SDK and is NOT generated.

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

Backend tests use pytest with AnyIO; files follow `test_*.py`. Coverage in `backend/pyproject.toml` has an 80% minimum (`fail_under`). For DB-backed tests, start Postgres with `docker compose up -d --wait db`; follow `.env.test.example` and `.github/workflows/ci.yml` for CI-style variables.

Frontend tests use Vitest and Testing Library as `*.test.ts(x)` files or under `__tests__/`. E2E tests use Playwright and follow `*.spec.ts` in `e2e/`.

New `t()` translation keys must be added to all four locales (en/es/fr/de); a `defaultValue` alone fails the `npm run test:i18n` locale-parity CI gate.

Plural-suffix keys follow the same all-four-or-none rule, with two i18next facts to respect: there is no `_many`→`_other` fallback (a `_many` added to es/fr alone renders the raw key or English for exact millions), and French resolves count 0 to `_one` — so `_one` values must interpolate `{{count}}`, never hardcode "1".

## Commit & Pull Request Guidelines

History follows a Conventional Commit-like pattern, for example `feat(sharing): add schema gates for advanced sharing` or `docs(readme): clarify the install steps`. Use an imperative subject and meaningful scope.

Pull requests should describe the change, call out schema/API/config impacts, link issues, include screenshots for UI work, and list verification commands. Commit `backend/openapi.json` or SDK output only when the source change requires it.

## Cross-Repo Brand Assets

Brand assets (logos, color tokens, font references, brand-usage rules, press materials) live in the sibling [`geolens-io/branding`](https://github.com/geolens-io/branding) repository — not here. When an app feature needs a logo, palette token, or identity element, copy from a tagged branding release rather than re-authoring locally. The propagation order for any change that touches brand identity is **branding → this repo → marketing → docs**. Cross-surface brand canon lives in branding's `BRAND-GUIDE.md`.

## Repository Docs Policy

Keep root repository docs single-purpose:

- `README.md` is the public overview.
- `SUPPORT.md` is support routing.
- `CHANGELOG.md` is the release-note source of truth.
- `EDITIONS.md` is the open-core/commercial boundary. Sanctioned at the root because licensing transparency requires it in-repo (REL-01).
- `RUNBOOK.md` is the operator backup/restore and disaster-recovery runbook. Sanctioned at the root because a self-hoster must be able to recover offline (BKP-04).

Everything else has a home:

- README images live in `.github/assets/`.
- Detailed product docs live on docs.getgeolens.com.
- Contributor-facing architecture and onboarding docs live under `.github/` (e.g. `.github/CONTRIBUTING.md`, `.github/ARCHITECTURE.md`).
- Private and internal notes stay in ignored `docs-internal/`.

Do not reintroduce a root `docs/` directory, and do not add standalone narrative feature docs that duplicate the docs site.

## Security & Configuration Tips

Use `.env.example` and `.env.test.example` as templates. Never commit secrets, coverage output, Playwright reports, virtual environments, or dependency directories.

Keep assistant and internal-notes state out of git. `.gitignore` covers AI-assistant and internal directories (e.g. `.claude/`, `.planning/`, `docs-internal/`); if any of those become tracked, untrack them before committing.

### Security pre-commit checklist

The rules below codify recurring security-review patterns. Any code change that touches catalog data access, external URL fetching, or boot-time credential validation must satisfy them.

**Rule 1 — Visibility-filter coverage** *(the most common access-control regression surface)*

Any new FastAPI handler that fetches a `Record`, `Dataset`, `Map`, or `RecordEmbedding` by ID must do ONE of:

- Call `check_dataset_access_or_anonymous(db, dataset, dataset_id, user)` from `backend/app/modules/catalog/authorization.py` (read-side endpoints), OR
- Call `check_dataset_access(db, dataset, dataset_id, user)` from the same module (write/destructive endpoints; raises 404 on access denial), OR
- Call `check_dataset_write_access(db, dataset, dataset_id, user)` from the same module (owner-or-admin mutation endpoints), OR
- Apply `apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)` to the underlying SQLAlchemy `Select` (list endpoints with their own query construction).

Reference implementations:
- `backend/app/standards/ogc/router.py` — OGC Features peer router (read path).
- `backend/app/standards/stac/router.py` — STAC router (read path).
- `backend/app/modules/catalog/datasets/api/router_metadata.py` — 5 sibling mutation handlers (write path).

**Rule 2 — SSRF redirect-revalidation**

Any new `httpx.AsyncClient` configured with `follow_redirects=True` MUST be constructed via `make_safe_client()` from `backend/app/platform/security.py` — never directly with `httpx.AsyncClient(follow_redirects=True, ...)`. The factory installs the per-hop `_revalidate_redirect` event hook that re-runs `validate_url_for_ssrf` against every 3xx `Location` header.

*Keep `security.py` in `platform/`; do not move it back under a product domain.* It is cross-cutting infrastructure that auth, config_ops, catalog, and processing all depend on, and it contains no catalog logic. While it lived at `modules/catalog/sources/security.py` this rule contradicted the layering burndown installed by #435, which listed each `processing/` importer as debt to be routed through `ProcessingPort`, and that indirection would stop the Rule 2 grep hook from matching.

*GDAL and ogr2ogr CANNOT be made redirect-safe from the inside.* `GDAL_HTTP_FOLLOWLOCATION` is not a GDAL option, so setting it does nothing (#937), and GDAL exposes no option that disables redirect-following. **Never re-add `GDAL_HTTP_FOLLOWLOCATION` anywhere: it reads as a defense and is a no-op.** No structural test catches this one, so the rule is the only guard.

For any GDAL/ogr2ogr/rasterio path the defenses are structural, in this order:

1. Prefer never handing a caller-controlled URL to GDAL at all. Fetch only managed storage (`/vsis3/`, `/vsiaz/`, local paths with validated keys) and never probe remote sources in-process.
2. Where a user-supplied service URL must be fetched (service ingest/preview), `validate_url_for_ssrf` gates it at submission time, and residual redirect/DNS-rebinding exposure is bounded operationally (worker egress firewall).
3. Subprocess envs come from `gdal_safe_env()` / `gdal_safe_open_env()` in `backend/app/processing/raster/vrt.py`, which apply the real clamps (`CPL_VSIL_CURL_ALLOWED_EXTENSIONS`, `VRT_VIRTUAL_OVERVIEWS`).

**Rule 3 — Never reintroduce known-public credential literals**

A handful of demo credential literals leaked through git history when an early demo deployment template shipped, so they must be treated as public knowledge. Never reintroduce a known-leaked credential as a default, fallback, example, or test value. The canonical list and the boot-time check live in `validate_known_bad_credentials` in `backend/app/core/config.py`.

**Two distinct enforcement layers:**

- **Python boot guard** (`validate_known_bad_credentials` in `backend/app/core/config.py`): refuses to boot if `JWT_SECRET_KEY`, `GEOLENS_ADMIN_PASSWORD`, or `POSTGRES_PASSWORD` matches a known-public literal. MinIO credentials are **not** `Settings` fields and are **not** inspected by this guard.
- **MinIO runtime entrypoint guard** (`docker-compose.yml`, minio service): the entrypoint refuses to start MinIO when `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD` are blank, so it can never silently boot with the well-known `minioadmin` defaults. The operator must supply a non-default value (e.g. via `openssl rand -base64 24`). The compose file references them as parse-safe `${MINIO_ROOT_USER:-}`; the older `:?required` syntax aborted `compose config` at parse time even when the cloud-dev profile was inactive, which broke a verbatim-`.env.example` install (INST-01).

**Enforcement.** Both Rule 1 and Rule 2 have pre-commit grep hooks in `.pre-commit-config.yaml`.

- **Rule 1** — the hook matches any `@*router.<verb>` handler that calls `get_dataset(` and greps the file for an access/visibility check (it has no `exclude:` clause). The authoritative per-handler layer is `backend/tests/test_rule1_structural.py` (#822), which walks the FastAPI route table and also covers `db.get`/`select`/service-layer fetch paths plus `processing/` routes.
- **Rule 2, httpx half** — the hook fails any non-excluded file that constructs `httpx.AsyncClient(` while `follow_redirects=True` appears in the file. This is the ONLY half the hook covers.
- **Rule 2, GDAL/rasterio half** — `backend/tests/test_rule2_structural.py` (#936) walks `backend/app/` ASTs and requires every `rasterio.open`/`rasterio.Env` and every GDAL CLI argv to go through the safe-env helpers in `backend/app/processing/raster/vrt.py`, or to carry an explicit allowlisted justification.
- **Rule 3** — enforced at backend boot; boot-failure is the signal.

Standing CodeQL policy (decided 2026-08-03): if the validated-identifier `py/sql-injection` class fires again on an ingest-adjacent PR, adopt the alert-suppression query pack (workflow config plus `# codeql[py/sql-injection]` comments at the `_qtable` sites) instead of another round of manual dismissals. It fired again on 2026-08-11 (12 alerts across `metadata_projection.py` and `metadata_extent.py`) and the pack was adopted in #1615. A `# codeql[py/sql-injection]` comment on its own line directly above a dynamic `text()` site suppresses that site; `.github/codeql/python-suppression/` holds the query that reads those comments, and `.github/workflows/codeql.yml` runs it and dismisses what it marks.

Three parts of that mechanism are easy to get wrong. First, GitHub does not honour SARIF `suppressions[]` by itself: the property is absent from the supported-properties list, `github/codeql-action` carries no suppression handling, and GitHub staff confirmed the gap in May 2025. Without the dismissal step in the workflow, the markers are inert. Second, the query is vendored rather than pulled from `codeql/python-queries`, because the stock one reads every `# noqa` as a bare `lgtm` covering the whole line, and a bare annotation suppresses every rule on that line rather than one named rule. `backend/` has 332 of those, written for ruff by people deciding nothing about code scanning. Third, placement is exact: a marker on its own line above the alert works, a trailing marker on the flagged line is silently ignored. `backend/tests/test_codeql_qtable_suppressions.py` pins all three, plus the marker at every dynamic `text()` site in the two modules.
