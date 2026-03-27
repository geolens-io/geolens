# Contributing to GeoLens

Thanks for your interest in contributing to GeoLens. This guide covers the development setup, code conventions, and pull request process.

No CLA required -- the Apache 2.0 license covers all contributions.

## Development Setup

GeoLens runs entirely in Docker -- you don't need Python, Node.js, or PostgreSQL installed locally.

### 1. Fork and clone

```bash
git clone https://github.com/<your-username>/geolens.git
cd geolens
```

### 2. Start the stack

```bash
cp .env.example .env
docker compose up -d
```

The app will be available at [http://localhost:8080](http://localhost:8080). Default credentials: `admin` / `admin`.

### 3. Verify services are running

```bash
docker compose ps
```

All services (db, api, worker, frontend, titiler, nginx) should show as healthy.

### Making changes

- **Backend (FastAPI):** Edit files under `backend/`. The API container mounts the source directory and reloads on changes.
- **Frontend (React):** Edit files under `frontend/`. Vite provides hot module replacement through the Nginx proxy.
- **Migrations:** Add new Alembic migrations under `backend/alembic/versions/`. Run with `docker compose exec api alembic upgrade head`.

### Running tests

**Backend:**

```bash
docker compose exec api pytest
docker compose exec api pytest tests/unit -v     # Unit tests only
docker compose exec api pytest tests/api -v      # API integration tests
```

**Frontend:**

```bash
docker compose exec frontend npm test
docker compose exec frontend npm run test -- --watch  # Watch mode
```

## Code Style

Code style is enforced by linters and formatters. Run them before submitting a PR:

- **Backend:** `ruff check` and `ruff format` (configured in `pyproject.toml`)
- **Frontend:** ESLint and Prettier (configured in project root)
- **All user-facing strings** must be added to all 4 locale files (en, fr, es, de) under `frontend/src/i18n/locales/`

Check both before committing:

```bash
# Backend
docker compose exec api ruff check .
docker compose exec api ruff format --check .

# Frontend
docker compose exec frontend npx eslint src/
docker compose exec frontend npx prettier --check src/
```

## Commit Messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add bbox spatial filter to catalog search
fix: correct CRS reprojection for EPSG:4326 exports
docs: update install guide with MinIO configuration
test: add unit tests for tile token validation
chore: bump maplibre-gl to v5.1
refactor: extract tile URL builder into shared utility
```

Keep the subject line under 72 characters. Use the body for additional context when needed.

## Pull Requests

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feat/my-feature
   ```
2. Make your changes, commit with conventional commit messages.
3. Push your branch and open a pull request against `main`.
4. Fill out the PR description -- explain what changed and why.
5. Ensure CI checks pass (linting, tests, build).

If a PR template exists at `.github/PULL_REQUEST_TEMPLATE.md`, your PR description will be pre-populated with the template.

### PR guidelines

- Keep PRs focused -- one feature or fix per PR.
- Include tests for new functionality.
- Update documentation if your change affects user-facing behavior.
- Add locale strings to all 4 language files if you introduce new UI text.

## First Contribution

New to the project? Look for issues labeled **good-first-issue** in the [issue tracker](https://github.com/geolens-io/geolens/issues). These are scoped, well-described tasks suitable for getting familiar with the codebase.

If you're unsure where to start, open an issue describing what you'd like to work on and we'll point you in the right direction.

## Reporting Security Issues

If you discover a security vulnerability, please report it responsibly. **Do not open a public issue.** Instead, email the maintainers directly at the address listed in the repository's security policy.

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact

We will acknowledge your report within 48 hours and work with you on a fix before any public disclosure.

## Questions?

Open a [discussion](https://github.com/geolens-io/geolens/discussions) or file an issue. We're happy to help.
