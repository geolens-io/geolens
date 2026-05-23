---
gsd_state_version: 1.0
milestone: v1021
milestone_name: Docker Rebuild Sweep + Engine-level Retry
status: "1091-01 spike complete (audit doc at .planning/audits/INGEST-QUICKLOOK-ASYNC-CONTEXT-v1021.md, commit 3309fed8); ready for /gsd:execute-phase 1091 plan 02"
stopped_at: "1091-01 spike complete; awaiting 1091-02 (fix)"
last_updated: "2026-05-23T14:32:04.030Z"
last_activity: 2026-05-23 — v1021 ROADMAP.md created (3 phases, 6 reqs, coverage 6/6 — no orphans)
progress:
  total_phases: 3
  completed_phases: 0
  total_plans: 3
  completed_plans: 1
  percent: 0
---

# State

## Current Position

Phase: 1091 (in progress — Ingest Correctness Sweep)
Plan: 01 complete (spike) — next: 02 (fix)
Status: 1091-01 spike complete (audit doc at `.planning/audits/INGEST-QUICKLOOK-ASYNC-CONTEXT-v1021.md`, commit `3309fed8`); ready for `/gsd:execute-phase 1091 plan 02`
Last activity: 2026-05-23 — 1091-01 spike committed (`3309fed8` audit + `1fa787ab` SUMMARY backfill); root cause identified, Shape A fix proposed for 1091-02

## Project Reference

See: .planning/PROJECT.md

**Core value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** v1021 Docker Rebuild Sweep + Engine-level Retry — close operational findings from quick task `260523-at1` + retire v1020's engine-level retry carry-forward.

## Last Shipped Milestone

**Version:** v1020 Fixture Isolation
**Shipped:** 2026-05-22
**Phases:** 1087-1090 (4 phases, 11 plans, 9/9 reqs)
**Tag:** `v1020` (local) + `v1.5.5` (public) at commit `8a924bb6`
**Close-gate doc:** `.planning/phases/1090-skip-audit-flake-hunt-close-gate/1090-01-CLOSE-GATE.md`
**Phase summary:** `.planning/phases/1090-skip-audit-flake-hunt-close-gate/1090-SUMMARY.md`

**Previous:** v1019 Hygiene Tail — v1018 Frontend + xdist + Process (shipped 2026-05-22, public tag `v1.5.4` at `02cb25db`).

## Phase Plan (v1021)

| Phase | Goal | Requirements | Depends on |
|-------|------|--------------|------------|
| 1091 | Ingest Correctness Sweep — fix `urban_areas_landscan_10m` quicklook `MissingGreenlet` (spike-first) + seed-script post-loop reconciliation against `/api/admin/jobs/` | INGEST-01, OPS-01 | — (v1020 close-gate `3047/0/38` sequential is start state) |
| 1092 | Routing + Infra Hygiene — stop 307 internal-hostname leak (`/api/collections/` + `/api/auth/login/`); dedupe double alembic `upgrade head` in `migrate` service; ACCEPT `db --platform=linux/amd64` pin with rationale | ROUTE-01, INFRA-01, INFRA-02 | 1091 |
| 1093 | Engine-level Retry Envelope — close v1020 carry-forward; engine-layer retry for `pytest -n auto` (test-fixture engine only); preserve `-n 4` CI default | TEST-01 | 1092 |

**Coverage:** 6/6 requirements mapped — no orphans, no duplicates.

**Public tag target:** `v1.5.6` (patch — bug fixes + ops hygiene; no API/schema changes, no migrations beyond docker-compose/entrypoint fixes).

## Accumulated Context

### Decisions

- **2026-05-23 (v1021 roadmap):** Phase 1091 bundles INGEST-01 + OPS-01 — natural dependency: OPS-01's reconciliation regression test needs the `MissingGreenlet` shape from INGEST-01 to verify failures surface. Spike-first per v1019 Phase 1085 / v1020 Phase 1087 precedent — short audit deliverable identifies the exact async-context boundary line(s) in `app/processing/ingest/tasks_common.py` BEFORE the fix lands.
- **2026-05-23 (v1021 roadmap):** Phase 1092 bundles ROUTE-01 + INFRA-01 + INFRA-02 — three hygiene items that share the `docker compose down -v && up -d --build` verification surface. ROUTE-01 is the largest item; INFRA-01 + INFRA-02 ride the same docker-compose change-set to minimize rebuild noise. MEMORY.md update (post-fix invariant) lands inside Phase 1092's TD-13 atomic close commit.
- **2026-05-23 (v1021 roadmap):** Phase 1093 is the v1020 carry-forward closure — engine-level retry envelope for `pytest -n auto` per Phase 1088-04 architectural escalation REPORT. Scope is the test-fixture engine ONLY (`backend/tests/conftest.py` factory level); app-engine FastAPI request path is out of scope (different acceptance criteria — request latency vs test determinism).
- **2026-05-23 (v1021 roadmap):** Public tag target `v1.5.6` (SemVer patch) — hygiene only; no user-facing features, no migrations, no schema changes, no API contract changes.
- **2026-05-23 (v1021 roadmap):** Sequential pytest baseline that MUST stay green throughout v1021: **3047/0/38** (v1020 close-gate). TEST-01 acceptance criterion (b) explicitly preserves this. HARD INVARIANT: `failed == 0` non-negotiable.
- **2026-05-23 (v1021 roadmap):** Out-of-scope reaffirmations from v1020: Postgres `max_connections` bump rejected (production envelope at 30 is correct); artificial `-n` cap below `auto` rejected (masks contention); multi-arch `db` image future TODO only (INFRA-02 is ACCEPT-only). Plus v1021-specific out-of-scope: app-code engine retry (different acceptance criteria), production-code refactor beyond `MissingGreenlet` fix, frontend 307 UX (backend leak is the user-visible bug).
- **2026-05-23 (v1021 roadmap):** v1019 TD-13 rules are LIVE for v1021 from Day 1: REQ citation pinning (planner MUST validate `path::TestClass::test_name` node-IDs via `git grep -n "def <test_name>" <path>` BEFORE plans commit; applies to INGEST-01 `test_quicklook_async_context.py`, OPS-01 seed-script reconciliation test, ROUTE-01 `test_redirect_slashes.py`, TEST-01 engine-retry pin) + traceability flip (executor MUST flip REQUIREMENTS.md `[ ]` → `[x]` and `Pending` → `Complete` in the SAME commit as SUMMARY.md). Atomic-4-file invariant maintained across 7 phases of v1019/v1020.
- **2026-05-23 (1091-01 spike):** MissingGreenlet on `urban_areas_landscan_10m` quicklook root-caused: H2 (asyncio.wait_for cancellation poisoning asyncpg cursor at `quicklook.py:163`) + H3 (`session.rollback` expiring eagerly-loaded `dataset.record` despite `expire_on_commit=False`; `expire_on_rollback` defaults True). Detonates at `defer_embedding` `helpers.py:123`, NOT inside `_generate_quicklook` (H5 FALSE). Fix Shape A (open fresh session at `tasks_common.py:824-828` via `_job_phase_session(phase='quicklook')`) named in `.planning/audits/INGEST-QUICKLOOK-ASYNC-CONTEXT-v1021.md` Section 3. Plan 1091-02 implements.

### Pending Todos

None at v1021 roadmap-create. Quick task 260523-at1 produced the source-of-scope SUMMARY; its operational findings became v1021 REQUIREMENTS.md. No backlog promotion needed.

### Blockers/Concerns

None at v1021 start. **CI live-verification of `pytest-parallel-isolation`** (deferred from v1020 Phase 1089) still pending first post-merge run — independent operator action, does not block v1021 execution.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260523-at1 | Rebuild docker containers + import all seed data; surface errors/issues/gaps | 2026-05-23 | `e9817603` | [260523-at1-rebuild-the-docker-containers-and-import](./quick/260523-at1-rebuild-the-docker-containers-and-import/) |

## Session Continuity

Last session: 2026-05-23T14:31:50.165Z
Stopped at: v1021 ROADMAP.md created; ready for `/gsd:plan-phase 1091`
Resume file: None

## Operator Next Steps

- **`/gsd:execute-phase 1091 --plan 02`** — execute Plan 1091-02 (apply Shape A fix per `.planning/audits/INGEST-QUICKLOOK-ASYNC-CONTEXT-v1021.md` Section 3 + create regression tests in `backend/tests/test_quicklook_async_context.py`). Audit doc names file, line range, fix shape, and test function names at file:lineno resolution.
- **Post-merge CI live-verification (v1020 deferred):** after v1021 closes, run `gh run list --workflow=ci.yml --limit=1 && gh run watch <run_id>` to confirm the `pytest-parallel-isolation` gate fires green for the first time.

## Deferred Items

v1021 inherits the following from v1020 close-state (still open at v1021 start):

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| ci-live-verify | `pytest-parallel-isolation` gate first post-merge run | Pending operator action (`gh run watch`) | v1020 Phase 1089 |

Items closed by v1021 scope:

- **Cascade flake-class residual at `-n auto`** (v1020 carry-forward) — addressed by Phase 1093 TEST-01 (engine-level retry envelope).
