# Phase 1078: CI Alembic Clean-DB Upgrade Workflow - Context

**Gathered:** 2026-05-21
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via `workflow.skip_discuss`)

<domain>
## Phase Boundary

Single requirement: **CI-01 — Wire `backend/scripts/test_alembic_upgrade_clean_db.sh` into GitHub Actions.**

The script was built in v1016 Phase 1071 (KNOWN-02). It builds the project's custom PostGIS+pgvector image, spins up a throwaway DB, and runs `alembic upgrade head` against it. Until now it could only be exercised locally.

This phase wires it into `.github/workflows/ci.yml` as a job that runs:
- On push to `main`
- On PRs touching `backend/alembic/**`, `backend/scripts/test_alembic_upgrade_clean_db.sh`, `backend/app/models/**`, or `db/**` (the PostGIS image build context)

Closes SEC-OBSV-03 from v1016 Phase 1072 triage.

**Out of scope:**
- Refactoring the script itself — already shipped in Phase 1071
- Caching the test DB image build (initial build is ~2-3min; CI can absorb the cost; revisit if it becomes a blocker)
- Wiring into other workflows (publish.yml, release.yml, etc.) — only ci.yml for v1017

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices at Claude's discretion. The script already self-contains the docker build + run + cleanup logic; the workflow job's responsibility is just: checkout, install uv, run the script.

### Known Defaults

- **Runner:** `ubuntu-latest` (Docker daemon available by default).
- **uv setup:** Use the existing `astral-sh/setup-uv@v8.1.0` action with the same `version: "0.10.2"` pin as other backend jobs (see `backend-lint` job at `ci.yml:60-64`).
- **Python setup:** `actions/setup-python@v6` with `python-version: "3.13"` (matching `backend-lint`).
- **Working dir:** `backend/` for the alembic command; the script itself works from any cwd (per its README).
- **Job naming:** `alembic-clean-db` (matches the kebab-case convention of existing jobs like `backend-lint`, `openapi-snapshot`).
- **Path filter:** Add to the `changes` job's `filters:` block — only run when migration paths change OR on push to main:
  ```yaml
  alembic:
    - 'backend/alembic/**'
    - 'backend/scripts/test_alembic_upgrade_clean_db.sh'
    - 'backend/app/models/**'
    - 'db/**'
  ```
- **Triggering condition:** `if: needs.changes.outputs.alembic == 'true' || github.event_name == 'push'`
- **Failure mode:** The script exits non-zero on any migration failure; the job inherits that exit code and fails the build.

### Investigation order

1. Read `ci.yml` to understand existing job patterns (backend-lint is the closest analog).
2. Add the `alembic` path filter to the `changes` job.
3. Add the new `alembic-clean-db` job mirroring `backend-lint` style.
4. Verify YAML syntax (`actionlint` if available, or manual lint).

</decisions>

<code_context>
## Existing Code Insights

- `.github/workflows/ci.yml` — primary CI workflow with: `changes`, `backend-lint`, `openapi-snapshot`, `backend-tests`, `frontend-build`, `frontend-tests`, `e2e-smoke`, `cli-publish` (per common patterns).
- `backend/scripts/test_alembic_upgrade_clean_db.sh` — the script. Requires docker, uv. Self-contained.
- `db/Dockerfile` — custom PostGIS+pgvector image; built by the script.
- `scripts/init-db.sh` — mounted by the script as `/docker-entrypoint-initdb.d/10-init.sh`.

The script is ~219 lines and handles all the docker lifecycle internally. The CI job's role is just orchestration: checkout → install uv → invoke script.

</code_context>

<specifics>
## Specific Ideas

- 2 plans:
  - Plan 01: Add the workflow job + path filter
  - Plan 02: Close-gate (verify YAML, document SEC-OBSV-03 closure, update STATE/ROADMAP/REQUIREMENTS)
- Verification: the new job's first PR will be Phase 1078's own commits — we don't get a clean "did it run on a real PR?" signal until Phase 1079 close-gate. That's acceptable; the structural correctness is verifiable via `actionlint` or YAML parsing.

</specifics>

<deferred>
## Deferred Ideas

- Docker layer caching for the PostGIS image — adds 2-3 min savings per run; revisit if v1017 close-gate shows the job is a CI bottleneck
- Matrix testing across multiple Postgres versions (17, 16) — not needed until we support multiple in production
- Wire into `release.yml` for tag-push verification — separate scope

</deferred>
