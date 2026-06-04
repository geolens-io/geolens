# Repository Guidelines

## Project Structure & Module Organization

GeoLens mixes Python and TypeScript. Backend source is in `backend/app/`: `modules/` holds domain areas, `platform/` shared services, `processing/` ingest/export/tile work, and `standards/` OGC/STAC/DCAT integrations. Migrations are in `backend/alembic/`; tests are in `backend/tests/`.

The React/Vite frontend is in `frontend/src/`: `components/`, `pages/`, `hooks/`, `stores/`, `api/`, `assets/`, `i18n/`, and colocated `__tests__/`. Playwright specs are in `e2e/`. The CLI is in `cli/geolens_cli/`; generated SDKs are in `sdks/`; operations files are in `scripts/`, `db/`, and `.github/`.

## Build, Test, and Development Commands

- `make dev` / `make down`: start or stop the Docker Compose development stack.
- `make migrate`: run Alembic migrations in the API container.
- `make test` / `make test-cov`: run backend pytest and coverage.
- `npm run e2e` or `npm run e2e:smoke`: run Playwright suites.
- `cd frontend && npm ci && npm run dev`: install frontend dependencies and start Vite.
- `cd frontend && npm run build && npm run lint && npm run test:coverage`: run frontend gates.
- `make openapi-check`, `make sdks-check`, `make cli-test`: validate API snapshots and SDK/CLI drift.

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

Backend tests use pytest with AnyIO; files follow `test_*.py`. Coverage in `backend/pyproject.toml` has a 58.5% minimum. For DB-backed tests, start Postgres with `docker compose up -d --wait db`; follow `.env.test.example` and `.github/workflows/ci.yml` for CI-style variables.

Frontend tests use Vitest and Testing Library as `*.test.ts(x)` files or under `__tests__/`. E2E tests use Playwright and follow `*.spec.ts` in `e2e/`.

## Commit & Pull Request Guidelines

History follows a Conventional Commit-like pattern, for example `feat(sharing): add schema gates for advanced sharing` or `docs(readme): clarify the install steps`. Use an imperative subject and meaningful scope.

Pull requests should describe the change, call out schema/API/config impacts, link issues, include screenshots for UI work, and list verification commands. Commit `backend/openapi.json` or SDK output only when the source change requires it.

## Cross-Repo Brand Assets

Brand assets (logos, color tokens, font references, brand-usage rules, press materials) live in the sibling [`geolens-io/branding`](https://github.com/geolens-io/branding) repository — not here. When an app feature needs a logo, palette token, or identity element, copy from a tagged branding release rather than re-authoring locally. The propagation order for any change that touches brand identity is **branding → this repo → marketing → docs**. Cross-surface brand canon lives in branding's `BRAND-GUIDE.md`.

## Security & Configuration Tips

Use `.env.example` and `.env.test.example` as templates. Never commit secrets, coverage output, Playwright reports, virtual environments, or dependency directories.

Keep assistant and internal-notes state out of git. `.gitignore` covers AI-assistant and internal directories (e.g. `.claude/`, `.planning/`, `docs-internal/`); if any of those become tracked, untrack them before committing.

Keep root repository docs single-purpose: `README.md` is the public overview, `SUPPORT.md` is support routing, and `CHANGELOG.md` is the release-note source of truth. README images live in `.github/assets/`, detailed product docs live on docs.getgeolens.com, and private/internal notes stay in ignored `docs-internal/`. Do not reintroduce a root `docs/` directory or standalone narrative feature docs that duplicate the docs site.

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
- **Docker Compose required-variable syntax** (`MINIO_ROOT_USER:?required` in `docker-compose.yml`): prevents `docker compose --profile cloud-dev up` from succeeding if the variable is unset. The operator must supply a non-default value (e.g. via `openssl rand -base64 24`).

**Enforcement.** Both Rule 1 and Rule 2 have pre-commit grep hooks in `.pre-commit-config.yaml`. Rule 1's hook excludes one file with a tracked, separately-managed access-control gap until it is fixed. Rule 3 is enforced at backend boot — boot-failure is the signal.
