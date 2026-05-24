---
phase: 1097-live-verify-close-gate
plan: 01
status: in-progress
captured: 2026-05-24
requirements_addressed: [CLOSE-01]
---

# Phase 1097: Close-Gate Evidence Document

**Status:** IN PROGRESS (Plan 01 — baselines captured; CI-01 live-verify pending Plan 02)
**Captured:** 2026-05-24

## CLOSE-01 (a) — Sequential baseline

Verbatim final summary from `/tmp/v1022-1097-close-gate-sequential.log`:

```
FAILED tests/test_layering.py::test_router_orchestrator_modules_stay_within_loc_cap
FAILED tests/test_phase_275_readme_accuracy.py::test_readme_signature_maps_list_intact
FAILED tests/test_ssrf_redirect.py::test_make_safe_client_has_event_hook - At...
= 3 failed, 3060 passed, 38 skipped, 14 deselected, 18 warnings in 543.92s (0:09:03) =
```

| Metric  | Phase 1096 Close | Phase 1097 Close | Delta  |
|---------|------------------|------------------|--------|
| passed  | 3060             | 3060             | 0 NEW  |
| failed  | 3 OOS            | 3 OOS            | 0 NEW  |
| skipped | 38               | 38               | 0      |
| runtime | 540s             | 544s             | +4s    |

Pre-existing OOS failures (documented in REQUIREMENTS.md Out of Scope table):
1. `tests/test_layering.py::test_router_orchestrator_modules_stay_within_loc_cap` (LOC-cap decomposition tech-debt)
2. `tests/test_phase_275_readme_accuracy.py::test_readme_signature_maps_list_intact` (README sync drift)
3. `tests/test_ssrf_redirect.py::test_make_safe_client_has_event_hook` (flake-class)

**HARD INVARIANT preserved:** 0 NEW failures attributable to v1022. CLOSE-01 (a) SATISFIED.

## CLOSE-01 (b) — `-n 4` baseline

Verbatim final summary from `/tmp/v1022-1097-close-gate-n4.log`:

```
FAILED tests/test_layering.py::test_router_orchestrator_modules_stay_within_loc_cap
FAILED tests/test_oauth.py::TestOAuthCallbackCSRF::test_callback_missing_state_returns_error
FAILED tests/test_oauth.py::TestOAuthCallbackCSRF::test_callback_invalid_code_returns_error
FAILED tests/test_phase_275_readme_accuracy.py::test_readme_signature_maps_list_intact
===== 4 failed, 3059 passed, 38 skipped, 15 warnings in 325.89s (0:05:25) ======
```

| Metric  | Phase 1096 Close              | Phase 1097 Close            | Delta  |
|---------|-------------------------------|-----------------------------|--------|
| passed  | 3057                          | 3059                        | +2     |
| failed  | 6 (3 OOS + ~3 oauth/flake)    | 4 (2 OOS + 2 oauth/flake)   | -2     |
| skipped | 38                            | 38                          | 0      |
| runtime | 328s                          | 326s                        | -2s    |

Failure breakdown:
- 2 documented OOS rows (`test_layering` + `test_phase_275_readme_accuracy` — both pre-existing)
- 2 oauth flake-class (`test_callback_missing_state_returns_error` + `test_callback_invalid_code_returns_error` per PYTEST-XDIST-PERF-v1020.md Section 2)
- `test_ssrf_redirect` did NOT fire under `-n 4` this run (flake-class behavior; passes intermittently in parallel mode — expected per Section 2 flake taxonomy)

**HARD INVARIANT preserved:** 0 NEW failures attributable to v1022. CLOSE-01 (b) SATISFIED.

## CLOSE-01 (c) — `-n auto` 3-run measurement

Captured to `/tmp/v1022-1097-close-gate-nauto-run{1,2,3}.{log,xml}` with stale-DB cleanup between every run (per PYTEST-XDIST-PERF-v1020.md Section 1 Step 1b).

| Run | distinct (failed+errors) | ICN frames | Phase 1096 floor | PARA-01 gate | wallclock |
|-----|--------------------------|------------|------------------|--------------|-----------|
| 1   | 2                        | 0          | 5                | ≤30 PASS     | 449s      |
| 2   | 3                        | 0          | 2                | ≤30 PASS     | 449s      |
| 3   | 2                        | 0          | 2                | ≤30 PASS     | 443s      |

Run 1 failures (distinct=2): both pre-existing OOS (`test_layering` + `test_phase_275_readme_accuracy`).
Run 2 failures (distinct=3): 2 pre-existing OOS + 1 parallel-load flake (`test_settings_router::test_put_settings_same_embedding_dims_does_not_delete` — 422 vs 200 under contention; not in OOS triad but well under ≤30 gate; flake-shape pattern matches PYTEST-XDIST-PERF-v1020.md Section 2 parallel-validation-timing class).
Run 3 failures (distinct=2): both pre-existing OOS (`test_layering` + `test_phase_275_readme_accuracy`).

**PARA-01 acceptance gate PASSED:** each run ≤30 distinct deterministically across 3 consecutive runs (2/3/2 — IMPROVED vs Phase 1096 floor 5/2/2). Zero `InvalidCatalogNameError` cascade frames across all 3 runs. CLOSE-01 (c) SATISFIED.

## CLOSE-01 (d) — Live docker stack health spot-check

```
$ docker compose ps
NAME                 IMAGE                                   COMMAND                  SERVICE    CREATED        STATUS                  PORTS
geolens-api-1        geolens-api                             "/app/scripts/api-en…"   api        12 hours ago   Up 3 hours (healthy)    127.0.0.1:8001->8000/tcp
geolens-db-1         geolens-db                              "docker-entrypoint.s…"   db         12 hours ago   Up 12 hours (healthy)   127.0.0.1:5434->5432/tcp
geolens-frontend-1   geolens-frontend                        "docker-entrypoint.s…"   frontend   12 hours ago   Up 10 hours (healthy)   0.0.0.0:8080->5173/tcp, [::]:8080->5173/tcp
geolens-titiler-1    ghcr.io/developmentseed/titiler:2.0.2   "uvicorn titiler.app…"   titiler    12 hours ago   Up 12 hours (healthy)
geolens-worker-1     geolens-worker                          "/app/scripts/worker…"   worker     12 hours ago   Up 3 hours (healthy)

$ curl -sI -X GET http://localhost:8080/api/health
HTTP/1.1 200 OK
```

**Endpoint-shape note (doc drift, not a regression):** The CLOSE-01 (d) acceptance criterion literally cites `curl http://localhost:8080/api/health/` (with trailing slash). The actual API surface is `/api/health` (no trailing slash). The trailing-slash shape returns 404 because the health endpoint is outside the `_add_trailing_slash_aliases` hook scope from v1021 ROUTE-01 (which sweeps `/api/maps`, `/api/auth/*`, `/api/admin/*`, etc. but not `/api/health`). The canonical no-slash shape returns `200 OK` with a healthy provider rollup: `{"status":"healthy","providers":{"database":{"status":"ok","latency_ms":1.0},"storage":{"status":"ok","latency_ms":0.2},"cache":{"status":"ok","latency_ms":0.0}}}`. Doc drift to fix in a future hygiene pass; not load-bearing for CLOSE-01 (d).

**HEAD method note:** The endpoint only handles `GET` (HEAD returns 405 Method Not Allowed). This is expected FastAPI behavior — health endpoints in this codebase are declared with `@router.get()` only, not `@router.head()`. Using `GET` is the canonical way to call a health endpoint.

Optional Playwright MCP visit to `http://localhost:8080`: SKIPPED — symbolic confirmation only. v1022 is test-infra-hygiene-only (no production code path); curl 200 + 5 healthy services is load-bearing CLOSE-01 (d) evidence on its own.

**CLOSE-01 (d) SATISFIED.**

## CLOSE-01 (e) — CHANGELOG `[1.5.7]` cross-reference

See `CHANGELOG.md` `[1.5.7]` block (this commit). Lists PARA-01 + PARA-02 + HYG-01 closures with the test pin names + line numbers per CLOSE-01 (e):

- `test_init_tile_pool_retries_on_transient_too_many_clients` at line 1144 (PARA-01 / Phase 1095-01)
- `test_engine_retry_yields_event_loop_during_backoff` at line 1253 (PARA-02 / Phase 1095-02 — Shape Y2 token-assertion pin)
- `test_engine_retry_do_connect_event_handler_retries_on_transient_error` at line 1391 (HYG-01 WR-01 / Phase 1096-01)
- `test_init_tile_pool_catches_raw_asyncpg_too_many_connections` at line 1557 (HYG-01 WR-01-1095 carry / Phase 1096-01)
- `test_init_tile_pool_propagates_non_transient_error` at line 1666 (HYG-01 WR-01-1095 carry / Phase 1096-01)

CI-01 status placeholder will be replaced by Plan 02.

**CLOSE-01 (e) SATISFIED (partial — CI-01 status pending Plan 02).**

## CLOSE-01 (f) — CI-01 live-verify

**PENDING Plan 1097-02.** Plan 02 will:
1. AskUserQuestion confirmation before `git push origin main` (this commit is the close-gate commit; Plan 02 push triggers CI).
2. `gh run watch $RUN_ID` for the `pytest-parallel-isolation` job at `.github/workflows/ci.yml:499-590`.
3. Embed the relevant log block in a new section appended to this file (CLOSE-01 (f) section).

## CLOSE-01 (g) — Tags cut

**PENDING Plan 1097-02.** Tags `v1022` (local) + `v1.5.7` (public) will be cut at the close-gate commit SHA (this commit) AFTER CI-01 is GREEN. Recorded in `.planning/MILESTONES.md`.

---

## Log file pointers (for re-verification)

All capture files at `/tmp/` (not committed; tmp-cleared on reboot per T-1097-03):

- Sequential: `/tmp/v1022-1097-close-gate-sequential.log` (3 failed / 3060 passed / 38 skipped / 544s)
- `-n 4`: `/tmp/v1022-1097-close-gate-n4.log` (4 failed / 3059 passed / 38 skipped / 326s)
- `-n auto` Run 1: `/tmp/v1022-1097-close-gate-nauto-run1.{log,xml}` (2 distinct / 0 ICN / 449s)
- `-n auto` Run 2: `/tmp/v1022-1097-close-gate-nauto-run2.{log,xml}` (3 distinct / 0 ICN / 449s)
- `-n auto` Run 3: `/tmp/v1022-1097-close-gate-nauto-run3.{log,xml}` (2 distinct / 0 ICN / 443s)

Reproducer recipe (per T-1097-02 mitigation):
```bash
cd backend && set -a && source ../.env.test && set +a && uv run pytest tests/  # sequential
cd backend && set -a && source ../.env.test && set +a && uv run pytest -n 4 tests/  # -n 4
# stale-DB cleanup then 3x:
docker compose exec -T db psql -U geolens -d geolens -At -c \
  "SELECT datname FROM pg_database WHERE datname LIKE 'geolens%test_gw%' OR datname LIKE 'geolens%test_master%';" \
  | xargs -I{} docker compose exec -T db psql -U geolens -d geolens -c "DROP DATABASE IF EXISTS \"{}\" WITH (FORCE);"
cd backend && set -a && source ../.env.test && set +a && uv run pytest -n auto tests/
```

---

_Plan 01 close (this commit): baselines captured, CHANGELOG written, ready for Plan 02 push gate._
