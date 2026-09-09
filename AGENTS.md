# Repository Guidelines

Shared instructions live here; keep `CLAUDE.md` as only `@AGENTS.md`. Retain actionable conventions and traps; link to existing sources for detail.

## Project Map

Backend: `backend/app/{api,core,modules,platform,processing,standards}/`; migrations: `backend/alembic/`; tests: `backend/tests/`. React/Vite frontend: `frontend/src/` (builder: `builder/`, colocated Vitest tests); Playwright: `e2e/`. CLI: `cli/geolens_cli/`; read-only MCP server: `mcp/geolens_mcp/`; generated SDKs: `sdks/`; operations: `scripts/`, `db/`, `.github/`.

FastAPI serves catalog, standards and vector tiles; Titiler serves COG tiles. The worker runs Procrastinate jobs using PostgreSQL as its queue. Storage defaults to local files, with S3/MinIO and Azure options; Valkey provides caching. See [.github/ARCHITECTURE.md](.github/ARCHITECTURE.md) for topology and extension seams; manifests/lockfiles own dependency versions.

Import domain service façades, never another domain's split internals (datasets: `backend/app/modules/catalog/datasets/domain/service.py`). `backend/tests/test_layering.py` enforces boundaries, including no `app.processing.*` imports from catalog. Shared security helpers belong in `platform/`.

Frontend API calls use `apiFetch()` in `frontend/src/api/client.ts`. Auth comes from `useAuthStore` (persisted as `geolens-auth`); outside React use `useAuthStore.getState().token`. Reuse `components/ui/`, TanStack Query and existing zustand stores.

## Working Principles

- Inspect relevant code and the working tree; preserve unrelated edits. Build requested behavior with the smallest correct diff; avoid speculative features and unrelated refactors.
- Prefer project helpers, standard library/native platform features, then installed dependencies. Add a dependency only when these cannot reasonably meet the need; explain why and update its manifest and lockfile together.
- Avoid abstractions, factories and configuration without a current need. Keep one definition per domain fact; a small copy beats violating a layer boundary.
- Preserve validation, authorization, SSRF defenses, accessibility and error handling that prevents data loss. Test non-trivial behavior, not implementation trivia.
- Use `rg`/`rg --files` and bounded reads. Load detailed docs/skills when relevant; avoid dumping generated files or entire trees into context.

### Subagents

- Keep small or tightly coupled tasks local. Delegate bounded independent work; avoid duplicate exploration and unnecessary nested delegation.
- Pass the objective, owned files, constraints, relevant paths and expected verification. Prefer a concise brief over full conversation history when supported; ensure applicable `AGENTS.md` instructions are available without copying them twice.
- Tell workers they share the workspace: preserve others' edits and avoid overlapping ownership. Coordinate shared files and generated artifacts through the parent.
- Request concise findings/changes, file references, checks/results and blockers. Reuse agents for follow-ups; the parent runs shared gates after integration, repeating only when changes or failures warrant it.

## Commands and Verification

Commands start at the repository root unless specified. Setup: [.github/CONTRIBUTING.md](.github/CONTRIBUTING.md). Reuse existing environments; run `npm ci` in the relevant package when dependencies need installing/syncing.

- Stack: `make dev-init` bootstraps; `make dev` starts; `make down` stops.
- Schema changes: `make migrate`, then `make alembic-check` against a compatible DB at migration heads.
- Backend: `make test` / `make test-cov` use the API container. Python changes require `cd backend && uv run ruff check . && uv run ruff format --check .`. Coverage floor: 80%; McCabe limit: 15; `backend/pyproject.toml`'s `per-file-ignores` may only shrink.
- Frontend: `cd frontend && API_PROXY_TARGET=http://localhost:8001 npm run dev`. Gates: `npm run build && npm run lint && npm run typecheck && npm run test:coverage` from `frontend/`; `npx tsc --noEmit` does not check this project. Focused test: `npx vitest run src/path/foo.test.ts`.
- E2E needs a running stack: `npm run e2e` / `npm run e2e:smoke`; focused: `npx playwright test e2e/foo.spec.ts --project=chromium`. Run relevant smoke groups for user-flow changes; see the contributor guide.
- Contracts: `make openapi-check`, `make sdks-check` (regenerates files), `make cli-test` (includes DB integration), `make mcp-test`.
- Versions: `make bump VERSION=X.Y.Z`; never edit versions individually. Gate: `make version-check`.

Run focused tests during development and affected package gates before completion. Documentation-only edits need link/command checks and `git diff --check`, not application suites. Report failed or unrun checks accurately.

Host backend: `make env-test` creates gitignored `.env.test` without overwriting it. DB-backed tests need matching test DB credentials/port (template: 5434). `docker compose up -d --wait db` starts the dev DB; generated dev credentials may differ from the test template.

```bash
(cd backend && set -a && source ../.env.test && set +a && uv run pytest tests/test_foo.py -v)
```

Container tests require writable paths:

```bash
docker compose exec api env UV_CACHE_DIR=/app/staging/uv-cache UV_PROJECT_ENVIRONMENT=/app/staging/geolens-api-test-venv uv run pytest -o cache_dir=/app/staging/.pytest_cache tests/test_foo.py::test_bar -v
```

After any `backend/app/` edit, also run these database-free gates (pytest still needs test environment settings):

```bash
make env-test
(cd backend && set -a && source ../.env.test && set +a && uv run pytest tests/test_layering.py -q)
python3 backend/tests/finding_markers.py
```

Keep tracked `_MODULE_LOC_CAPS` entries in `test_layering.py` at exact line counts with a brief rationale; follow its inclusion test for newly oversized modules. `UNANCHORED_MARKER_DEBT` in `finding_markers.py` counts markers, not lines: lower/delete entries when debt is removed; never increase them to pass a gate.

`make ai-evals` costs live provider tokens and needs the dev DB/provider key (normally `ANTHROPIC_API_KEY`). Ensure `.env.test`, if present, does not override working dev credentials.

### Worktrees

The shared stack serves the checkout it bind-mounts, usually the primary checkout, regardless of your linked worktree's branch. Template ports: frontend 8080, API 8001, DB 5434; verify configured ports. `E2E_ALLOW_WORKTREE=1` acknowledges this risk; it does not select the code under test.

Frontend change: from the worktree run `cd frontend && API_PROXY_TARGET=http://localhost:8001 npm run dev -- --port 5174 --strictPort`; from its root run `E2E_ALLOW_WORKTREE=1 E2E_BASE_URL=http://localhost:5174 npx playwright test`. The API still serves the shared checkout. Backend changes need a worktree Compose project with separate ports or a host API. Spec-only changes may use the shared stack. Run `make env-test` inside each worktree before host pytest.

## Contracts and Comments

- API schema changes, including published route docstrings/Pydantic field descriptions, require `make sdks` (refreshes OpenAPI and both SDKs), then `cd frontend && npm run types:generate`. Frontend drift gate: `npm run types:check`. Commit generated changes only when source changes require them.
- Never hand-edit generated SDK code or `frontend/src/types/api.generated.ts`. SDK auth/entry wrappers (`auth.py`, `__init__.py`, `auth.ts`, `index.ts`) are hand-maintained; CLI and MCP wrap the SDK.
- New UI strings use `t()` with keys in all four locales (en/es/fr/de); run `cd frontend && npm run test:i18n`. `defaultValue` is insufficient. Keep plural suffixes consistent; `_many` does not fall back to `_other`. French count 0 uses `_one`, so interpolate `{{count}}` instead of hardcoding 1.
- Comments explain non-obvious reasons/traps; docstrings state contracts. Avoid narration/history. Review references need an issue/PR anchor plus the invariant, at most three lines: `// fix(#1234): suppress basemap row click during multi-selection`. Bare private tracker IDs fail finding-marker checks. Outside `backend/app/`, `no-agent-tag-markers` needs the `fix(#issue)` anchor on the same line as the tag; a bare tag fails there too.
- Put `# broad: <reason>` on the same line as every `except Exception`. Follow CodeQL marker placement below.

## Security

Apply these rules to data access, URL fetching, ingestion and credential changes. Structural checks supplement behavioral tests; they do not prove every path is authorized.

**Rule 1 — Access control.** Guard each handler's `Dataset`, `Record`, `Map`, `RecordEmbedding` and `IngestJob` fetch using sanctioned domain checks in `backend/tests/test_rule1_structural.py`. Dataset guards live in `backend/app/modules/catalog/authorization.py`:

- Reads: `check_dataset_access_or_anonymous(...)`, or `check_dataset_access(...)` for authenticated callers; denial is 404. The latter checks visibility only and cannot authorize writes.
- Mutations: `check_dataset_write_access(...)` enforces visibility (404) and owner/admin rights (403).
- Lists: execute the statement returned by `apply_visibility_filter(...)`; discarding its return provides no protection. Use corresponding sanctioned guards for maps, records and tiles.

Invalid supplied credentials must not silently become anonymous access; preserve `get_optional_user` behavior and exceptions pinned in `backend/tests/test_optional_auth_failure_mode_1518.py`.

**Rule 2 — SSRF and GDAL.** Redirect-following `httpx.AsyncClient` instances come from `make_safe_client()` in `backend/app/platform/security.py` for per-hop validation and connection-time IP pinning. Pass `credential_header` when forwarding custom credential headers. Keep submission-time `validate_url_for_ssrf` checks.

GDAL/ogr2ogr/rasterio need structural defenses; never add the ineffective `GDAL_HTTP_FOLLOWLOCATION`:

1. Prefer managed storage (`/vsis3/`, `/vsiaz/`, validated local keys); never probe caller-controlled remote sources in-process.
2. Remote service imports/previews require URL validation, `gdal_service_safe_env()` and worker egress restrictions.
3. Raster subprocesses/opens use `gdal_safe_env()` / `gdal_safe_open_env()` from `backend/app/processing/raster/vrt.py`. Local vector subprocesses require both `local_input_driver_args()` from `processing/ingest/gdal_drivers.py` and `gdal_vector_safe_env()` from `platform/gdal_env.py` (paths under `backend/app/`). Service drivers use the service environment. `GDAL_SKIP` splits on spaces/commas; unknown driver names only warn.
4. GPKG/SQLite virtual tables can follow pointers. Preserve `validate_content_directives()` in `processing/ingest/validation.py` at upload and staged-upload GDAL entry points: read raw `sqlite_master.sql` read-only/immutable, allow only sanctioned virtual-table modules, identify SQLite archive members by bytes and reject VRT despite disguised names/BOMs. Run `validate_zip_safety` first under a shared byte budget. `PRAGMA`, `SPATIALITE_SECURITY=strict`, `OGR_SQLITE_LOAD_EXTENSIONS=NONE` and `OGR_SQLITE_LIST_ALL_TABLES=NO` are not substitutes.

Run `backend/tests/test_rule2_structural.py` and relevant `backend/tests/test_gdal_driver_clamp_1846.py` tests for these changes; the latter needs real GDAL. Only the GDAL CLI exception allowlist is empty; rasterio exceptions are separately counted.

**Rule 3 — Credentials.** Never introduce known-public credential literals as defaults, fallbacks, examples or new test values; `validate_known_bad_credentials` in `backend/app/core/config.py` rejects them. MinIO credentials are outside `Settings`: preserve entrypoint blank-credential rejection and parse-safe `${MINIO_ROOT_USER:-}` / `${MINIO_ROOT_PASSWORD:-}` in `docker-compose.yml`; `:?required` breaks parsing even with the profile inactive.

**CodeQL.** Suppress `py/sql-injection` only where dynamic identifiers are validated. Put `# codeql[py/sql-injection]` on its own line directly above the `text()` site; trailing markers are ignored. Preserve `.github/codeql/python-suppression/` and `.github/workflows/codeql.yml`; verify with `backend/tests/test_codeql_qtable_suppressions.py`.

## Commits and Documentation

Use scoped Conventional Commits and DCO sign-off (`git commit -s`). Follow `.github/PULL_REQUEST_TEMPLATE.md`: describe behavior, link issues, note schema/API/config impacts, list verification and include screenshots for UI work.

Root docs: `README.md` (overview), `SUPPORT.md`, `CHANGELOG.md` (release notes), `EDITIONS.md` (open-core boundary), `RUNBOOK.md` (recovery). Contributor docs: `.github/`; README images: `.github/assets/`; product docs: docs.getgeolens.com; private notes: ignored `docs-internal/`. Do not add root `docs/` or duplicate product docs. Brand assets come from a tagged `geolens-io/branding` release; changes flow branding → this repo → marketing → docs.

Use `.env.example` / `.env.test.example` as templates. Never commit secrets, environments, dependencies, coverage or Playwright output. Keep ignored assistant/internal directories (`.claude/`, `.planning/`, `docs-internal/`) out of tracked changes.
