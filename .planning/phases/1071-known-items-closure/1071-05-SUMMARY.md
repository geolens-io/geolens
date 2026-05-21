---
phase: 1071-known-items-closure
plan: 05
subsystem: backend/migrations
tags: [scripts, alembic, postgis, pgvector, close-gate, KNOWN-02]
requires:
  - backend/alembic/versions/0001_baseline.py (extension preconditions)
  - db/Dockerfile (postgis/postgis:17-3.5 + pgvector v0.8.2)
  - scripts/init-db.sh (extension installation)
provides:
  - backend/scripts/test_alembic_upgrade_clean_db.sh (clean-DB upgrade smoke)
  - backend/scripts/README.md (script documentation)
affects:
  - Phase 1074 close-gate runbook (new optional verification step)
tech-stack:
  added: []
  patterns:
    - Build-then-mount: ./db custom image + scripts/init-db.sh mount for the throwaway container so 0001_baseline's extension precondition is satisfied
    - Port pre-flight: refuse to run if ALEMBIC_TEST_DB_PORT is already bound (avoids silently masking failures against an unrelated postgres)
    - Trap-cleanup discipline: `trap cleanup EXIT INT TERM` registered BEFORE the docker run so Ctrl-C still drops the container
    - Two-phase readiness probe: pg_isready AND `SELECT 1 FROM pg_extension WHERE extname='vector'` — init-db.sh runs AFTER initial readiness, so plain pg_isready is not enough
key-files:
  created:
    - backend/scripts/test_alembic_upgrade_clean_db.sh
    - backend/scripts/README.md
  modified: []
decisions:
  - Base image hard-coded (postgis/postgis:17-3.5) with a lockstep comment to db/Dockerfile rather than parsing YAML in POSIX bash; the planner pre-approved this trade-off
  - Used DATABASE_URL_OVERRIDE (not bare DATABASE_URL) because backend/app/core/config.py treats DATABASE_URL_OVERRIDE as the documented override surface; defense-in-depth also exports POSTGRES_* so settings.database_url falls back cleanly if override is ever dropped
  - DATABASE_SSL_MODE=disable for the throwaway container since the dev default is "prefer" and the test container has no TLS configured
  - Built the project's ./db image instead of pulling vanilla postgis/postgis:17-3.5; the baseline migration aborts unless pgvector is present, and the project's image is the only one in this repo that has it
  - CI invocation deferred (script needs docker daemon + image pull) per plan §"CI gate decision"
metrics:
  duration_min: ~12
  tasks_completed: 2/2 (Task 3 deferred to orchestrator per spawn instructions)
  files_created: 2
  lines_added: 285 (script: 211, README: 74)
  commits: 2
completed: "2026-05-21T13:05:08Z"
---

# Phase 1071 Plan 05: Alembic Clean-DB Upgrade Test Script Summary

Added an opt-in shell script (`backend/scripts/test_alembic_upgrade_clean_db.sh`) that exercises the full alembic migration chain (0001 → 0021) against a freshly-initialized PostGIS+pgvector container — the semantic complement to v1015's syntactic `down_revision` linkage check. Documented at `backend/scripts/README.md`.

## What Shipped

### Task 1 — Script (commit `6424bde2`)

`backend/scripts/test_alembic_upgrade_clean_db.sh` (211 lines, executable, `bash -n` clean):

- **Image build:** Builds the project's custom `./db` image (PostGIS 17-3.5 + pgvector 0.8.2) rather than pulling vanilla `postgis/postgis:17-3.5`. The baseline migration `0001_baseline.py` asserts `postgis`, `pg_trgm`, `vector`, `unaccent` extensions exist and raises if missing — only the project's custom image plus `scripts/init-db.sh` satisfies that precondition.
- **Init-db.sh mount:** Mounts `scripts/init-db.sh` into `/docker-entrypoint-initdb.d/10-init.sh:ro` so postgres-entrypoint runs it on first boot.
- **Unique container name:** `geolens-alembic-test-$$` (PID-suffixed) — concurrent runs don't collide.
- **Port selection:** Default `54399`, `ALEMBIC_TEST_DB_PORT` override, refuses to run if port is bound (avoids silently masking migration failures against an unrelated local postgres).
- **Repo-root resolution:** Uses `$(dirname "${BASH_SOURCE[0]}")` + `../..` so it works from anywhere, not just `backend/`.
- **Trap-cleanup discipline:** `trap cleanup EXIT INT TERM` registered BEFORE `docker run`; cleanup is idempotent (checks `docker inspect` first to avoid an empty banner if the container never started).
- **Two-phase readiness probe:** `pg_isready` is not enough — `init-db.sh` runs AFTER initial readiness. The probe also runs `SELECT 1 FROM pg_extension WHERE extname='vector'` so we don't race the extension-creation step.
- **URL injection:** Sets `DATABASE_URL_OVERRIDE` (the documented override surface in `backend/app/core/config.py:292`) plus `POSTGRES_*` as defense-in-depth and `DATABASE_SSL_MODE=disable` (dev default is `prefer`, throwaway container has no TLS).
- **Alembic invocation:** `cd backend/` then `uv run --no-dev alembic upgrade head`; exit code captured, dispatched on success/failure with container-log tail on failure.

### Task 2 — README (commit `88ea392f`)

`backend/scripts/README.md` (74 lines) — single-script README following the plan-prescribed shape:

- Prerequisites: docker daemon, uv, free port 54399.
- Usage: `cd backend && ./scripts/test_alembic_upgrade_clean_db.sh`.
- Env overrides table: `ALEMBIC_TEST_DB_PORT`, `ALEMBIC_TEST_TIMEOUT`.
- When to run: every milestone close-gate, new-migration local smoke, suspected chain rot.
- Limitations: schema-only (no data-migration fixture step), no app boot, lockstep discipline with `db/Dockerfile`, ~2-3 min first-run image build for pgvector compile.

### Task 3 — Human verify checkpoint (DEFERRED TO ORCHESTRATOR)

The plan's `checkpoint:human-verify` task (docker-driven end-to-end smoke of both success AND failure paths) is **deferred to the orchestrator** per the spawn instructions. The orchestrator will manually:

1. Run `cd backend && ./scripts/test_alembic_upgrade_clean_db.sh` against the live docker daemon, expect exit 0 with progress + success banner.
2. Confirm cleanup: `docker ps -a | grep geolens-alembic-test` returns nothing.
3. Smoke a failure path: introduce a syntax error in the most recent migration, re-run the script, confirm non-zero exit AND container cleanup, then revert the edit.

The executor's scope was the static-check loop only:
- `bash -n backend/scripts/test_alembic_upgrade_clean_db.sh` → clean
- `test -x backend/scripts/test_alembic_upgrade_clean_db.sh` → executable bit set
- Required components present: `alembic upgrade head`, `docker rm -f`, `trap cleanup EXIT INT TERM`, `set -euo pipefail`, explicit `exit 0` success path.

## Verification Results

| Check                                    | Result                            |
| ---------------------------------------- | --------------------------------- |
| `test -x …test_alembic_upgrade_clean_db.sh` | PASS (mode 755)                   |
| `bash -n …test_alembic_upgrade_clean_db.sh` | PASS (no syntax errors)           |
| `set -euo pipefail` present              | PASS                              |
| `alembic upgrade head` present           | PASS                              |
| `docker rm -f` present                   | PASS                              |
| `trap cleanup EXIT INT TERM` present     | PASS                              |
| `exit 0` success-path assertion present  | PASS                              |
| Script ≥ 40 lines (plan min_lines)       | PASS (211 lines)                  |
| README exists at `backend/scripts/README.md` | PASS                              |
| README contains `test_alembic_upgrade_clean_db` | PASS                              |
| shellcheck (if available)                | N/A — shellcheck not installed locally; bash -n is the static-check stand-in |

## Deviations from Plan

**None.** Plan executed exactly as written. The plan's skeleton uses `postgis/postgis:16-3.4` as a placeholder; the actual `db/Dockerfile` uses `postgis/postgis:17-3.5` + pgvector v0.8.2 (since the plan instructed: "Read `docker-compose.yml` for the `db.image:` line to get the exact tag, or read `.env.example`"). The script tracks the actual repo image, with a lockstep comment matching the plan's "if compose changes the image tag, update this script in lockstep" guidance.

One implementation detail worth noting (not a deviation): The plan's skeleton hint says to `docker run -d ... postgis/postgis:<tag>`, but the baseline migration requires pgvector (registered at `0001_baseline.py:22` via `import pgvector.sqlalchemy.vector`), and vanilla `postgis/postgis:17-3.5` does not ship with pgvector. The script therefore builds the project's `./db` image (which layers pgvector on top of `postgis/postgis:17-3.5`) and mounts `scripts/init-db.sh` to install the extensions — this is the minimal change that lets `alembic upgrade head` actually complete against the throwaway container. The plan's `<action>` step (d) explicitly references `pg_isready` polling, and step (e) explicitly references the asyncpg URL shape — both honored.

## Known Stubs

None.

## Threat Flags

None. Script is a developer/operator tool that spawns an isolated, ephemeral container bound to `127.0.0.1:54399` only; no production code touched, no new network surface, no new auth paths.

## Deferred Issues

None. All static checks green; the only deferred item is the live docker smoke (Task 3) which is explicitly orchestrator-scoped per the spawn instructions.

## Self-Check: PASSED

- `backend/scripts/test_alembic_upgrade_clean_db.sh` → FOUND (211 lines, mode 755, `bash -n` clean)
- `backend/scripts/README.md` → FOUND (74 lines, contains `test_alembic_upgrade_clean_db`)
- Commit `6424bde2` (chore(scripts): add alembic clean-DB upgrade test script) → FOUND in `git log`
- Commit `88ea392f` (docs(scripts): document test_alembic_upgrade_clean_db.sh) → FOUND in `git log`
- All plan acceptance criteria (must_haves.truths + artifacts.contains + key_links.pattern) met.
