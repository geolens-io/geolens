# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**The canonical guide is [`AGENTS.md`](AGENTS.md).** It covers project structure, build/test commands (including running a single test), architecture and service topology, coding style, testing, commit/PR conventions, and the security pre-commit rules. Read it first; everything below is a Claude-specific quick reference that points into it.

## Quick reference

- **Dev stack:** `make dev` (up), `make down`, `make reset-db`, `make status`. Frontend at http://localhost:8080. Backend commands run inside the `api` container.
- **Backend tests:** `make test` (parallel), `make test-sequential`. Single test: see AGENTS.md → *Running a single test*.
- **Frontend (from `frontend/`):** `npm run build` is the CI gate; also `npm run lint`, `npm run test`.
- **Before pushing schema-adjacent changes, run the drift gates:** `make openapi-check`, `make sdks-check`, `make alembic-check`, `make version-check`. Lint backend with `cd backend && uv run ruff check . && uv run ruff format --check .`.
- **Versions are single-sourced:** never edit a version string — use `make bump VERSION=X.Y.Z`.
- **i18n parity is a CI gate:** new `t()` keys need all four locales (en/es/fr/de); `defaultValue` alone fails `npm run test:i18n`.
- **Security guardrails** (visibility-filter coverage, SSRF redirect revalidation, no leaked credential literals) are enforced by pre-commit hooks — see AGENTS.md → *Security pre-commit checklist* before touching data access, URL fetching, or boot-time config.
