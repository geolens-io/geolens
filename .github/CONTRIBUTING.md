# Contributing to GeoLens

Thanks for your interest in contributing to GeoLens!

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/geolens.git`
3. Start the stack: `docker compose up -d --build`
4. Frontend runs at `http://localhost:8080`

## Development Setup

**Backend** (FastAPI + Python 3.12):
- Code lives in `backend/app/`
- Uses SQLAlchemy async with PostgreSQL/PostGIS
- Run tests: `docker compose exec api pytest`
- Lint: `ruff check backend/`
- Format: `ruff format backend/`

**Frontend** (React 19 + TypeScript + Vite):
- Code lives in `frontend/src/`
- Uses TanStack Query, Zustand, Tailwind, shadcn/ui
- Run tests: `docker compose exec frontend npm test`
- Type check: `npx tsc --noEmit`
- Lint: `npx eslint src`

## Code Style

- Follow existing conventions in each file
- Keep changes focused — one concern per PR
- Add i18n strings to all 4 locales (en, fr, es, de) for user-facing text
- Use parameterized queries — never interpolate user input into SQL

## Pull Requests

- Create a feature branch from `main`
- Write a clear PR description using the template
- Ensure all checks pass before requesting review
- Keep PRs small and reviewable when possible

## Reporting Issues

Use the [issue templates](https://github.com/geolens-io/geolens/issues/new/choose) for bug reports and feature requests.

## Security

If you discover a security vulnerability, please email security@geolens.io instead of opening a public issue.
