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
