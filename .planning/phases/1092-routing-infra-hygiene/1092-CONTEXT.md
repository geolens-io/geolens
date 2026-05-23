# Phase 1092: Routing + Infra Hygiene - Context

**Gathered:** 2026-05-23
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

A reader of `MEMORY.md` can see one consistent rule for trailing-slash behavior across all `/api/*` routes (no internal-hostname leak in any 307 `Location` header), and an operator running `docker compose down -v && up -d --build` sees exactly one alembic upgrade block in `migrate` logs plus a documented (no longer surprising) `--platform=linux/amd64` warning on the `db` image.

**Three requirements (per REQUIREMENTS.md):**

- **ROUTE-01** — Stop the 307 trailing-slash redirect from leaking `http://api:8000` in the `Location` header. Surface includes `/api/collections/` AND `/api/auth/login/` (broader than the documented `/collections/datasets` exception in MEMORY.md). Root cause is FastAPI's default `redirect_slashes=True` combined with the Vite dev-proxy passing `Location` through unmodified. Acceptance: (a) `curl -sI http://localhost:8080/api/collections/` returns `200` directly OR a `307` with Location rewritten to `localhost:8080`; (b) same for `/api/auth/login/`; (c) `/collections/datasets` exception is either eliminated or explicitly preserved with a regression test; (d) MEMORY.md updated to reflect post-fix invariant; (e) backend test `backend/tests/test_redirect_slashes.py` pins no-leak behavior. **Closes Issues 2 + 5 from quick task `260523-at1`.**

- **INFRA-01** — Eliminate the double `alembic upgrade head` invocation in the `migrate` service. Service runs `command: sh -c "uv run --no-dev alembic upgrade head"` AND inherits `backend/scripts/api-entrypoint.sh:62-68` safety-net that ALSO runs the upgrade. Acceptance: (a) `docker compose logs --no-color migrate` after a clean rebuild shows exactly ONE `alembic.runtime.migration` block; (b) chosen approach (entrypoint override on migrate service OR detect "I'm migrate" in api-entrypoint.sh and skip) is documented inline; (c) `api`/`worker` entrypoint still runs the safety-net for cold-start protection.

- **INFRA-02** — ACCEPT — formally accept the `db` image's `--platform=linux/amd64` pin on `./db/Dockerfile:1` so the build warning + Apple Silicon emulation warning are no longer surprises. Acceptance: (a) inline comment on the Dockerfile explaining the pin (pgvector build reproducibility against `postgis/postgis:17-3.5`) + TODO link to future multi-arch path; (b) one project-level doc (CHANGELOG `[1.5.6]`, `./db/README.md`, or MEMORY.md) carries the operator-facing rationale; (c) build still warns but the warning is expected.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per user setting. Use ROADMAP phase goal, REQUIREMENTS.md acceptance criteria, and codebase conventions to guide decisions.

### Locked from REQUIREMENTS.md / ROADMAP.md
- **ROUTE-01 root-cause:** FastAPI `redirect_slashes=True` (the default) issues a 307 with the canonical no-slash URL. The Vite dev proxy at `frontend/vite.config.ts` (or wherever it lives) does NOT rewrite the `Location` header on responses — it forwards the upstream `Location: http://api:8000/...` verbatim. Two viable fix shapes:
  - (a) **Disable `redirect_slashes` on the FastAPI app** and explicitly register both slash and no-slash variants for routes that have it currently. Behavior: no redirect, both shapes return 200 directly. Cleanest from the client's perspective. May require touching multiple routers if many routes currently rely on default redirect.
  - (b) **Patch the Vite dev proxy** to rewrite `Location` headers on 307 responses (`http://api:8000` → `http://localhost:8080`). Smaller blast radius; preserves FastAPI's redirect behavior. But only fixes the dev-server surface; production deployment still leaks if behind a similar proxy. Add a production-proxy note.
  - (c) **Hybrid:** disable `redirect_slashes` at the app level (closes the canonical surface) AND add the proxy `Location` rewrite (defense in depth for any code path that still issues a 307). MEMORY.md note becomes simpler.
- Planner should choose between (a) / (b) / (c) at plan-time based on a scout of how many routers currently issue 307s and how disruptive disabling `redirect_slashes` would be to the existing surface. Default recommendation: **(c) hybrid** — close the canonical bug, add defense in depth.

- **INFRA-01 chosen approach:** the `entrypoint:` override on the `migrate` service is the lower-blast-radius option. `api-entrypoint.sh`'s safety-net stays for `api`/`worker` cold starts.

- **INFRA-02 doc location:** prefer the inline `./db/Dockerfile:1` comment + CHANGELOG `[1.5.6]` block. The MEMORY.md update is for ROUTE-01 (consolidates the trailing-slash rule); INFRA-02 rationale is small enough to fit a CHANGELOG bullet.

- **Out of scope (carried from REQUIREMENTS.md):** Vite dev-proxy rewrite for non-API routes; multi-arch `db` build pipeline; frontend redirect_slashes UX; documentation site changes.

</decisions>

<code_context>
## Existing Code Insights

Codebase context will be gathered during plan-phase research. Known seed surfaces:
- `backend/app/main.py` — FastAPI app factory; `redirect_slashes` lives in `FastAPI(redirect_slashes=...)` constructor (or wherever the app is built).
- `backend/app/api/` — routers; current 307 surfaces include `/api/collections/` (catalog), `/api/auth/login/` (auth), `/api/collections/datasets` (OGC — documented exception).
- `frontend/vite.config.ts` (or `vite.config.js`) — dev proxy config; `configure(proxy, options)` hook can intercept response headers.
- `docker-compose.yml` — `migrate` service entrypoint config.
- `backend/scripts/api-entrypoint.sh` — line 62-68 contains the safety-net `uv run --no-dev alembic upgrade head`.
- `./db/Dockerfile` — line 1 has `FROM --platform=linux/amd64 postgis/postgis:17-3.5` (build warning `FromPlatformFlagConstDisallowed`).
- `MEMORY.md` — the user's auto-memory file with the stale trailing-slash rule. Needs an update at the project_v1013_post_smoke_fixes memory or the FastAPI trailing-slash bullet.

</code_context>

<specifics>
## Specific Ideas

**Reproduction state (still live on the running stack):**
- `curl -sI http://localhost:8080/api/collections/` → 307 with `Location: http://api:8000/collections`
- `curl -sI http://localhost:8080/api/auth/login/` → 307 with `Location: http://api:8000/auth/login`
- `curl -sI http://localhost:8080/api/collections/datasets` → 200 (the documented no-slash route)
- `docker compose logs migrate` → 2× `alembic.runtime.migration` blocks
- `docker compose up -d --build` output includes `FromPlatformFlagConstDisallowed` warning

**Verification:** the live stack already has 109 datasets + zero failed jobs from Phase 1091. Phase 1092 verification can:
1. Run the curl probes against the existing stack to confirm pre-fix state, apply fixes, re-probe to confirm post-fix.
2. For INFRA-01: `docker compose restart migrate` is enough to re-trigger migrate startup without a full rebuild.
3. For INFRA-02: just rebuild and check the build output for the warning + check the inline comment.

</specifics>

<deferred>
## Deferred Ideas

None — discuss phase skipped. The "Vite dev-proxy rewrite for non-API routes" item in REQUIREMENTS.md Out of Scope catches the boundary of what Phase 1092 will NOT touch.

</deferred>
