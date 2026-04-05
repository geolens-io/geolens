# Contributing to GeoLens

GeoLens is an open-source geospatial data catalog that helps teams find, explore, and share spatial datasets. Contributions of all kinds are welcome.

## Reporting Bugs

Open a [GitHub Issue](https://github.com/geolens-io/geolens/issues) with:
- A clear description of what happened vs. what you expected
- Steps to reproduce
- GeoLens version and environment (Docker version, OS)

## Suggesting Features

Open a GitHub Issue with the `enhancement` label. Describe the use case, not just the solution.

## Development Setup

See [docs/install-guide.md](docs/install-guide.md) for the full setup guide.

**Quick start:**

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/)
2. Copy `.env.example` to `.env` and adjust as needed
3. Start all services:
   ```bash
   docker compose up -d
   ```
4. Frontend dev server (hot reload):
   ```bash
   cd frontend && npm install && npm run dev
   ```

The app runs at `http://localhost:8080` by default.

## Pull Request Process

1. Fork the repository and create a branch from `main`
2. Make your changes with focused, well-described commits
3. Ensure all tests pass:
   ```bash
   # Backend
   docker compose exec api pytest

   # Frontend
   cd frontend && npm run test
   ```
4. Open a PR against `main` with a clear description of what changed and why
5. PRs require one approval before merging

## Code Style

- **Python:** Follow [ruff](https://docs.astral.sh/ruff/) rules (config in `pyproject.toml`). Run `ruff check .` before committing.
- **TypeScript/React:** ESLint + Prettier (config in `frontend/`). Run `npm run lint` before committing.
- Follow existing conventions in the file you are editing — consistency beats novelty.

## Security Vulnerabilities

Do NOT open a public issue for security vulnerabilities. See [SECURITY.md](SECURITY.md) for responsible disclosure instructions.

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating you agree to uphold it.
