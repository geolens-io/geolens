# Repository Guidelines

## Project Structure & Module Organization

GeoLens mixes Python and TypeScript. Backend source is in `backend/app/`: `modules/` holds domain areas, `platform/` shared services, `processing/` ingest/export/tile work, and `standards/` OGC/STAC/DCAT integrations. Migrations are in `backend/alembic/`; tests are in `backend/tests/`.

The React/Vite frontend is in `frontend/src/`: `components/`, `pages/`, `hooks/`, `stores/`, `api/`, `assets/`, `i18n/`, and colocated `__tests__/`. Playwright specs are in `e2e/`. The CLI is in `cli/geolens_cli/`; generated SDKs are in `sdks/`; operations files are in `scripts/`, `docker/`, `db/`, and `.github/`.

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

When leaving an in-source comment that references a finding from a code review, audit, or smoke check, qualify the finding id with the phase id so future readers can locate the context:

```
// Phase {PHASE-ID} {FINDING-ID}: <one-line context>
// Phase 1050-rev WR-01: imperative companion sweep — getSourceIdForLayer …
// Phase 1051 CR-02: suppress basemap row click during multi-selection
```

Bare `// WR-02: …` references (without a phase id) are ambiguous because finding ids are scoped per phase. Prefer the qualified form in all new code; opportunistically upgrade legacy bare references when editing nearby code.

## Testing Guidelines

Backend tests use pytest with AnyIO; files follow `test_*.py`. Coverage in `backend/pyproject.toml` has a 58.5% minimum. For DB-backed tests, start Postgres with `docker compose up -d --wait db`; follow `.env.test.example` and `.github/workflows/ci.yml` for CI-style variables.

Frontend tests use Vitest and Testing Library as `*.test.ts(x)` files or under `__tests__/`. E2E tests use Playwright and follow `*.spec.ts` in `e2e/`.

## Commit & Pull Request Guidelines

History follows a Conventional Commit-like pattern, for example `feat(234-01): add schema gates for advanced sharing` or `docs(phase-233): complete phase execution`. Use an imperative subject and meaningful scope.

Pull requests should describe the change, call out schema/API/config impacts, link issues or phases, include screenshots for UI work, and list verification commands. Commit `backend/openapi.json` or SDK output only when the source change requires it.

## Security & Configuration Tips

Use `.env.example` and `.env.test.example` as templates. Never commit secrets, coverage output, Playwright reports, virtual environments, or dependency directories.

Keep assistant and internal planning state out of git. `.gitignore` must continue to cover `.claude/`, `.codex/`, `.agents/`, `.planning/`, `.gsd/`, and `docs-internal/`; if any of those paths become tracked again, untrack them before public release work continues.

Keep root repository docs single-purpose: `README.md` is the public overview, `SUPPORT.md` is support routing, and `CHANGELOG.md` is the release-note source of truth. README images live in `.github/assets/`, detailed product docs live on docs.getgeolens.com, and private/internal notes stay in ignored `docs-internal/`. Do not reintroduce a root `docs/` directory or standalone narrative feature docs that duplicate the docs site.

### Security pre-commit checklist

The audit at `docs-internal/audits/sec-audit-20260519.md` and the recurring-patterns ledger at `docs-internal/audits/security-lessons.md` codify the patterns below. Any code change that touches catalog data access, external URL fetching, or boot-time credential validation must satisfy these rules.

**Rule 1 — Visibility-filter coverage** *(audit's #1 regression surface; 5 of 7 HIGHs in the 2026-05-19 audit clustered here)*

Any new FastAPI handler that fetches a `Record`, `Dataset`, `Map`, or `RecordEmbedding` by ID must do ONE of:

- Call `check_dataset_access_or_anonymous(db, dataset, dataset_id, user)` from `backend/app/modules/catalog/authorization.py` (read-side endpoints), OR
- Call `check_dataset_access(db, dataset, dataset_id, user)` from the same module (write/destructive endpoints; raises 404 on access denial), OR
- Apply `apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)` to the underlying SQLAlchemy `Select` (list endpoints with their own query construction).

Reference implementations:
- `backend/app/standards/ogc/router.py` — OGC Features peer router (read path).
- `backend/app/standards/stac/router.py` — STAC router (read path; fixed in Phase 1061).
- `backend/app/modules/catalog/datasets/api/router_metadata.py` — 5 sibling mutation handlers (write path).

**Rule 2 — SSRF redirect-revalidation**

Any new `httpx.AsyncClient` configured with `follow_redirects=True` MUST be constructed via `make_safe_client()` from `backend/app/modules/catalog/sources/security.py` — never directly with `httpx.AsyncClient(follow_redirects=True, ...)`. The factory installs the per-hop `_revalidate_redirect` event hook that re-runs `validate_url_for_ssrf` against every 3xx `Location` header.

The same applies to ogr2ogr / GDAL subprocess calls that fetch user-supplied URLs: set `GDAL_HTTP_FOLLOWLOCATION=NO` in the subprocess env. Reference: `backend/app/processing/ingest/ogr.py` (service-ingest path).

**Rule 3 — Never reintroduce known-public credential literals**

The following literals leaked through git history when a demo deployment template shipped: `demo-only-do-not-use-in-production-change-me` (JWT), `demodemo` (admin password), `geolens-demo-2026` (postgres password), and `minioadmin/minioadmin` (MinIO root). Anyone with repo read access knows them. Never reintroduce any of these as a default, fallback, example, or test value.

**Two distinct enforcement layers (Phase 1061 WR-01 correction):**

- **Python boot guard** (`validate_known_bad_credentials` in `backend/app/core/config.py`): refuses to boot if `JWT_SECRET_KEY`, `GEOLENS_ADMIN_PASSWORD`, or `POSTGRES_PASSWORD` matches one of the three known-public literals. MinIO credentials are **not** `Settings` fields and are **not** inspected by this guard.
- **Docker Compose required-variable syntax** (`MINIO_ROOT_USER:?required` in `docker-compose.yml`): prevents `docker compose --profile cloud-dev up` from succeeding if the variable is unset. This does **not** block the Docker default of `minioadmin/minioadmin` if `MINIO_ROOT_USER=minioadmin` is explicitly set — the operator must supply a non-default value (e.g., via `openssl rand -base64 24`).

**Enforcement.** Both Rule 1 and Rule 2 have pre-commit grep hooks in `.pre-commit-config.yaml` (shipped in Phase 1061 Plan 06). Rule 1's hook excludes `backend/app/modules/catalog/datasets/api/router_reupload.py` — that file has a tracked IDOR gap (Phase 1061 SEC-FU, deferred to Phase 1063) and is intentionally in the exclude list until it is fixed. Rule 3 is enforced at backend boot — boot-failure is the signal.

See `docs-internal/audits/security-lessons.md` for the append-only ledger of recurring patterns + future rules.
