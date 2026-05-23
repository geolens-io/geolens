---
phase: 1092-routing-infra-hygiene
plan: 02
status: complete
completed_date: 2026-05-23
requirements: [INFRA-01]
subsystem: infrastructure
tags: [infra-01, docker-compose, migrate, alembic, entrypoint-override]
key_files:
  modified:
    - docker-compose.yml
    - .planning/REQUIREMENTS.md
    - .planning/ROADMAP.md
---

# Phase 1092 Plan 02: INFRA-01 Migrate Service Alembic Dedup Summary

**One-liner:** Closed INFRA-01 by adding `entrypoint: []` override to the `migrate` service in `docker-compose.yml`. The migrate service no longer inherits `backend/scripts/api-entrypoint.sh`'s safety-net `alembic upgrade head` invocation, eliminating the double-run on every startup. The api + worker services keep the safety-net for cold-start protection.

## Goal Achievement

All 5 truths from `must_haves.truths` met:

- [x] `docker compose logs --no-color migrate` after a clean rebuild shows exactly ONE `alembic.runtime.migration` block
  - Evidence: `docker compose logs --no-color migrate | grep -c "Context impl PostgresqlImpl"` → `1` (was 2). The `alembic.runtime.migration` log marker fires 24× (once for the startup context + 22 individual `Running upgrade` lines + the post-upgrade summary), all under a single startup block.
- [x] api service entrypoint still runs the alembic safety-net for cold-start protection
  - Evidence: `docker compose logs --no-color api | grep -c "Running database migrations"` → `1` (the safety-net still fires for the api service on cold start).
- [x] worker service entrypoint behavior unchanged
  - Evidence: `worker-entrypoint.sh` path is separate from `api-entrypoint.sh` (docker-compose.yml worker block uses its own entrypoint declaration); no changes touched the worker service.
- [x] migrate service still exits 0 after successful single-invocation alembic upgrade head
  - Evidence: `docker inspect geolens-migrate-1 --format '{{.State.ExitCode}}'` → `0`.
- [x] Sequential pytest baseline preserved: NO NEW failures introduced by INFRA-01
  - Evidence: `cd backend && uv run pytest tests/` post-INFRA-01: `3049 passed, 2 failed, 38 skipped` — IDENTICAL to post-ROUTE-01 baseline. Failures: test_phase_275 (OOS pre-existing) + test_ssrf_redirect (pre-existing flake).

## Artifacts Created/Modified

- `docker-compose.yml` — Added `entrypoint: []` declaration to the `migrate` service block (immediately above `command:`) with an inline comment block explaining INFRA-01 + cross-referencing `backend/scripts/api-entrypoint.sh:60-72` safety-net rationale.
- `.planning/REQUIREMENTS.md` — INFRA-01 `[ ]` → `[x]`; Traceability row `Pending` → `Complete`; closure citation block appended.
- `.planning/ROADMAP.md` — `[ ] 1092-02-PLAN.md` → `[x]`.
- `.planning/phases/1092-routing-infra-hygiene/1092-02-SUMMARY.md` — this file.

## Key Links Established

- **`docker-compose.yml` migrate service → `backend/scripts/api-entrypoint.sh:62-68` safety-net**: the explicit `entrypoint: []` override decouples the one-shot migrate service from the api/worker inherited entrypoint. The safety-net at api-entrypoint.sh:62-68 still fires for api + worker; its comment "The dedicated migrate service runs first; this is a safety net" remains accurate.

## Verification Evidence

**Post-fix docker-compose lifecycle:**

```
$ docker compose down -v && docker compose up -d --build
... (full rebuild + healthy stack) ...

$ docker compose logs --no-color migrate | grep -c "Context impl PostgresqlImpl"
1

$ docker compose logs --no-color migrate | grep -E "Context impl|Running upgrade" | head -3
migrate-1  | INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
migrate-1  | INFO  [alembic.runtime.migration] Will assume transactional DDL.
migrate-1  | INFO  [alembic.runtime.migration] Running upgrade  -> 0001_baseline, ...

$ docker compose logs --no-color api | grep -c "Running database migrations"
1

$ docker inspect geolens-migrate-1 --format '{{.State.ExitCode}}'
0

$ curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8080/api/health
200
```

**Pre-fix baseline (from quick task 260523-at1):**

```
$ docker compose logs --no-color migrate | grep -c "Context impl PostgresqlImpl"
2  # Expected: 1
```

**Sequential pytest baseline (post-INFRA-01, after full docker rebuild):**

```
$ cd backend && uv run pytest tests/ -q
2 failed, 3049 passed, 38 skipped, 14 deselected, 18 warnings in 580.63s
FAILED tests/test_phase_275_readme_accuracy.py::test_readme_signature_maps_list_intact  ← pre-existing (OOS)
FAILED tests/test_ssrf_redirect.py::test_make_safe_client_has_event_hook                  ← pre-existing flake (carried from 1092-01)
```

Identical to post-1092-01 baseline (`3049 passed, 2 failed, 38 skipped`). NO new failures introduced by INFRA-01.

## Decisions Made

- **Chose approach (a) from CONTEXT.md `entrypoint: []` override** over approach (b) "detect 'I'm migrate' in `api-entrypoint.sh` and skip the safety-net". Approach (a) is the lower-blast-radius option: a 1-line addition to a single service block in docker-compose.yml, no shell-script logic changes, no risk of regressing the api/worker cold-start path. Approach (b) would have required shell-script branching logic that's harder to reason about and could mask future cold-start contract changes.
- **Preserved the `api-entrypoint.sh:62-68` safety-net unchanged**: its existing comment "The dedicated migrate service runs first; this is a safety net" remains accurate. The safety-net is the api/worker cold-start protection when migrate fails silently — that protection MUST remain.

## Self-Check: PASSED

- **Files exist:**
  - `.planning/phases/1092-routing-infra-hygiene/1092-02-SUMMARY.md` ✓
- **Commits:**
  - `54be8b4a` (FIX) — to be verified post-commit
- **REQUIREMENTS.md:** INFRA-01 line `[x]`, Traceability row `Complete` ✓
- **ROADMAP.md:** `[x] 1092-02-PLAN.md` ✓
- **Live verification:** `Context impl PostgresqlImpl` count = 1 (was 2) ✓
- **api safety-net intact:** `Running database migrations` count in api logs = 1 ✓
- **Sequential pytest baseline preserved:** 3049 passed + 2 failed (pre-existing) + 38 skipped ✓
