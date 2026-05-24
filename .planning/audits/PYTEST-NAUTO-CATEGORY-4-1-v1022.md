---
audit_date: 2026-05-23
milestone: v1022
phase: 1094
scope: pytest-nauto-cascade-on-current-head-categorized-and-pinned
status: COMPLETE
root_cause_file: backend/tests/test_tiles.py + backend/tests/test_embed_tokens.py + backend/tests/test_tile_signing.py
root_cause_lines: "test_tiles.py:142-156 + test_embed_tokens.py:38-66 + test_tile_signing.py:102-115 (3 sibling _init_tile_pool_for_tests fixtures with un-wrapped asyncpg.create_pool)"
fix_target_lines: "test_tiles.py:151 + test_embed_tokens.py:56 + test_tile_signing.py:107 (or consolidate to single shared fixture in backend/tests/conftest.py)"
fix_shape_chosen: "Shape A* — wrap _init_tile_pool_for_tests's asyncpg.create_pool call in the existing _run_with_too_many_clients_retry envelope (conftest.py:359)"
wr02_disposition: INDEPENDENT
test_file: backend/tests/test_fixture_isolation_v1020.py (extends existing test_engine_retry_* section with new test_init_tile_pool_* family)
pre_fix_baseline:
  run1_distinct: 14
  run2_distinct: 14
  run3_distinct: 21
host: macOS darwin/arm64 (Apple M4 Max, 16-core)
worker_count_under_n_auto: 16
postgres_max_connections: 30
head_sha: 49625d27
---

# Audit — pytest -n auto Cascade on Current HEAD: Surface Re-Classification + Fix Shape (v1022 / Phase 1094-01)

Spike-first investigation per v1019 Phase 1085 / v1020 Phase 1087 / v1021 Phase 1091 precedent. The plan-time hypothesis enumeration (CONTEXT.md H1-H5 + ROADMAP PARA-01 framing) anticipated the v1021 Phase 1093-02 Run 3 cascade shape (706 errors / 4787 `InvalidCatalogNameError` lines / per-worker DB CREATE/migrate). **The current HEAD does NOT reproduce that cascade.** A different, smaller surface is now dominant; this audit documents the actual reproduced cascade, names the fix shape, and addresses the WR-02 cascade-pressure question for PARA-02 (d).

**NO production code or test-fixture code is modified by Phase 1094.** The audit's Section 3 proposed fix and Section 5 proposed pin shape are consumed by Phase 1095.

---

## Section 1 — Root-cause hypothesis enumeration

### 1.1 Cross-run baseline summary (live reproduction on current HEAD)

3 runs of `cd backend && uv run pytest -n auto tests/` with stale-DB cleanup between runs, captured to `/tmp/v1022-1094-pre-fix-nauto-run{1,2,3}.{log,xml}` (artifacts preserved for Phase 1095 delta comparison):

| Run | passed | failed | errors | wallclock (s) | TMC exception lines | ICN exception lines | Distinct (failed+errors) |
|-----|--------|--------|--------|---------------|---------------------|---------------------|--------------------------|
| 1   | 3045   | 8      | 6      | 425.26        | 53                  | **0**               | **14**                   |
| 2   | 3046   | 12     | 2      | 414.63        | 35                  | **0**               | **14**                   |
| 3   | 3037   | 7      | 14     | 406.61        | 48                  | **0**               | **21**                   |

**3-run consistency:** All 3 runs satisfy the ≤30 distinct threshold (14 / 14 / 21). All 3 runs produced **0 actual `InvalidCatalogNameError` exception frames** (the raw `grep -c "InvalidCatalogNameError"` count of 4/8/0 matches only comment text inside `conftest.py:938-1109`). Cascade source is consistent across all 3 runs: `asyncpg.exceptions.TooManyConnectionsError` at the `_init_tile_pool_for_tests` fixture + downstream API request handlers.

### 1.2 Pre-fix vs v1021 Phase 1093-02 delta

| Run | v1021 Phase 1093-02 distinct | v1022 Phase 1094 distinct | Delta |
|-----|------------------------------|---------------------------|-------|
| 1   | 11                           | 14                        | +3    |
| 2   | 12                           | 14                        | +2    |
| 3   | 709                          | 21                        | **−688** |

The v1021 Phase 1093-02 Run 3 cascade (709 distinct / 706 errors / 4787 ICN lines) is **NOT reproducing on the current HEAD**. The cascade surface has shifted between v1021 close (HEAD `35596a7a`) and Phase 1094 spike (HEAD `49625d27`); the Phase 1094 reproduction shows a smaller, different cascade. Possible reasons (not investigated by this spike — escalate to Phase 1095 spike-update if necessary): (a) the v1021 close-state code changes (`_create_test_db_with_retry` + engine wrapper + dual-shape route aliases) reduced the per-worker DB CREATE pressure enough that Category 4.1 no longer fires at all on this HEAD; (b) infrastructure timing on the host (other processes / system load) influenced the v1021 Run 3 measurement.

### 1.3 Hypothesis Verdict Matrix

| Hypothesis | Verdict | Evidence (line citations + traceback frames) |
|------------|---------|----------------------------------------------|
| **H1** — `_test_db_lifecycle` (`backend/tests/conftest.py:906`) lacks retry coverage at `dev_engine.connect()` (per-worker DB CREATE path) | **FALSE** | Runs 1/2/3 produced 0 `InvalidCatalogNameError` exception frames (comment-text matches only). The `_create_test_db_with_retry` call at `backend/tests/conftest.py:959` is invoked inside `_test_db_lifecycle:906` and DOES use a retry envelope (`backend/tests/conftest.py:259-325`, budget=`_CREATE_DB_RETRY_BACKOFFS = (1.0, 2.0, 4.0)` at line 256). No per-worker DB CREATE failures observed across any of the 3 runs. **Category 4.1 (the planner-anticipated surface) is closed on this HEAD; the observed cascade has a different source.** |
| **H2** — Engine wrapper (`_RetryingAsyncEngine` at `backend/tests/conftest.py:711`) INCREASES pressure on per-worker DB CREATE/migrate by allowing more tests to enter warm-up SELECT 1 | **FALSE (for this HEAD)** | Distinct = 14/14/21 across the 3 runs (stable). The errors fire NOT at per-worker DB CREATE (no ICN frames) but at the application-layer `asyncpg.create_pool` call in `_init_tile_pool_for_tests` (see H6). The wrapper-pressure hypothesis was framed against the per-worker DB CREATE/migrate path — that path is not the failing surface. |
| **H3** — `_SETUP_STAGGER_SECONDS = 5.0` (`backend/tests/conftest.py:118`) × 16 workers = 75s window compounding pressure | **INCONCLUSIVE / unlikely** | Active workers list in Run 1: `gw6, gw7, gw9, gw11, gw12` (5 of 16 active); Run 3: `gw1, gw3, gw4, gw8, gw11, gw12, gw14` (7 of 16). The stagger window for these workers is 5-70s — these are well-AFTER the early workers should have completed their setup phase (~3-5s per worker per conftest.py:113). Errors fire at TEST-EXECUTION time inside `_init_tile_pool_for_tests` (the per-test-class fixture), NOT at per-worker DB CREATE/migrate. Stagger is not contributing to the observed failure mode. |
| **H4** — WR-02 blocking `time.sleep` at `_invoke_sleep_in_sync_context` (`backend/tests/conftest.py:624`) starves the asyncio loop, prolonging cascade | **INDEPENDENT** — see Section 4 | (full disposition + call-site map in Section 4) |
| **H5** — NullPool dispose timing on per-worker engine teardown | **INCONCLUSIVE / unlikely** | No NullPool dispose frames observed in TMC tracebacks (Runs 1+2+3 TMC frames all originate from `asyncpg/connect_utils.py:1102` → `TooManyConnectionsError` raised in the `await connected` line of `asyncpg.connect_utils._connect` — NOT from NullPool teardown). NullPool was specifically chosen at v1020 Phase 1088 to AVOID pool contention; the observed cascade does not implicate it. |
| **H6 (NEW)** — `_init_tile_pool_for_tests` fixture (3 sibling copies) bypasses ALL conftest.py retry envelopes | **TRUE — DOMINANT ROOT CAUSE** | All 6/2/14 errors across Runs 1/2/3 fire at `await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=3, command_timeout=10)` inside the 3 sibling fixture copies: `backend/tests/test_tiles.py:151`, `backend/tests/test_embed_tokens.py:56`, `backend/tests/test_tile_signing.py:107` (line numbers re-validated via `git grep -nE "asyncpg\.create_pool" backend/tests/test_tiles.py backend/tests/test_embed_tokens.py backend/tests/test_tile_signing.py` at audit-write time, HEAD `49625d27`). This call invokes `asyncpg.create_pool` directly — bypassing `_create_test_db_with_retry` (CREATE DB path), `_install_dbapi_connect_retry` (engine `do_connect` event), AND `_RetryingAsyncEngine.connect()` (engine method wrapper). Each pool opens up to `max_size=3` connections. With 16 workers × 3 conns = 48-conn demand vs `max_connections=30` ceiling, the cascade is direct. Run 3's burst of 13 errors all in `test_tile_signing.py` (one worker hit the tile-signing test class with all 12 sub-tests) confirms a single fixture's contention can chain through every test in the class. |
| **H7 (NEW)** — Downstream API integration tests' FastAPI app-engine pool drains during test execution | **TRUE — CONTRIBUTING CAUSE** | The 8 failures in Run 1 (`test_stac_*`, `test_records_related`, `test_layering`, `test_phase_275_readme_accuracy`) and 12 failures in Run 2 (similar spread + `test_oauth`, `test_tasks_common_phase_brackets`, `test_settings_router`) are API integration tests that go through the FastAPI request handler's engine in `backend/app/core/db/session.py` (pool_size=10, max_overflow=3). The app-side engine is NOT wrapped by `_RetryingAsyncEngine` (REQUIREMENTS.md Out-of-Scope: "Engine-level retry for application code (FastAPI request path)"); transient TMC exceptions through the request handler propagate unhandled. With 5-7 workers consuming combined ~30+ connections at peak, the headroom past `max_connections=30` is exhausted. This is a downstream consequence of H6, not an independent surface. |

### 1.4 Dominant Root Cause (one-paragraph commit)

**The cascade observed on Runs 1/2/3 of the current HEAD `49625d27` is NOT the v1021 Phase 1093-02 Run 3 cascade (Category 4.1 / per-worker DB CREATE / `InvalidCatalogNameError`). On this HEAD, distinct (failed+errors) = 14 / 14 / 21 with 0 ICN exception frames across all 3 runs. The dominant failure surface is `_init_tile_pool_for_tests` (defined identically in 3 test files: `backend/tests/test_tiles.py:142`, `backend/tests/test_embed_tokens.py:38`, `backend/tests/test_tile_signing.py:102`), which calls `await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=3, command_timeout=10)` DIRECTLY at the asyncpg layer at `backend/tests/test_tiles.py:151` (and the 2 sibling sites), bypassing all conftest.py retry envelopes (`_create_test_db_with_retry` at `backend/tests/conftest.py:259`, `_install_dbapi_connect_retry` at `backend/tests/conftest.py:664`, `_RetryingAsyncEngine` at `backend/tests/conftest.py:711`). Each fixture instance opens up to 3 concurrent connections, so when multiple xdist workers (Run 1: 5 of 16; Run 3: 7 of 16) hit tile-related tests at the same moment, the 21-48-conn demand exceeds `max_connections=30`. The errors fire at the pool-creation site (`asyncpg/connect_utils.py:1102` → `TooManyConnectionsError`); the failures are downstream API integration tests (e.g., `test_stac_search_no_auth_excludes_private` at `backend/tests/test_stac_visibility.py:129`, `test_records_related.TestKeywords.test_create_keyword_all_types`) whose HTTP requests to the FastAPI app-engine pool hit the same conn ceiling at request-handler time. This is a NEW Category 4.X surface NOT named in 1093-02-FINDINGS, NOT named in CONTEXT.md's H1-H5 hypotheses, and NOT closeable by the planner-proposed Shape A/B/C (which target per-worker DB CREATE/migrate; that path is already closed by `_create_test_db_with_retry`).**

---

## Section 2 — Reproduction recipe (verbatim)

### 2.0 — Prerequisites

**Docker stack health gate (5 services healthy + migrate exited 0):**
```bash
docker compose ps -a
```

**Env-loading prerequisite (MEMORY.md load-bearing note — failure to source `.env.test` results in `InvalidCatalogNameError: database "geolens_test_master_..." does not exist` on first pytest invocation):**
```bash
cd /Users/ishiland/Code/geolens/backend && set -a && source ../.env.test && set +a
```

### 2.1 — Stale-DB cleanup pattern (per-run, mirroring PYTEST-XDIST-PERF-v1020.md Section 1 Step 1b)

For each run RUN ∈ {1, 2, 3}, BEFORE invoking pytest:
```bash
# Enumerate stale per-worker test DBs
docker compose exec -T db psql -U geolens -d geolens -At -c \
  "SELECT datname FROM pg_database WHERE datname LIKE 'geolens%test_gw%' OR datname LIKE 'geolens%test_master%';" \
  > /tmp/v1022-1094-stale-dbs-run${RUN}.txt

# Generate DROP SQL
while read -r db; do
  [ -z "$db" ] && continue
  echo "DROP DATABASE IF EXISTS \"$db\";"
done < /tmp/v1022-1094-stale-dbs-run${RUN}.txt > /tmp/v1022-1094-drop-stale-run${RUN}.sql

# Apply
docker compose exec -T db psql -U geolens -d geolens < /tmp/v1022-1094-drop-stale-run${RUN}.sql
```

### 2.2 — Per-run pytest -n auto invocation (with both .log + .xml capture)

```bash
cd /Users/ishiland/Code/geolens/backend && set -a && source ../.env.test && set +a && \
  uv run pytest -n auto tests/ --junitxml=/tmp/v1022-1094-pre-fix-nauto-run${RUN}.xml \
  > /tmp/v1022-1094-pre-fix-nauto-run${RUN}.log 2>&1
```

### 2.3 — Per-run extraction (7 numbers per run for the Section 1.1 table)

```bash
echo "=== Run $RUN ==="
tail -1 /tmp/v1022-1094-pre-fix-nauto-run${RUN}.log  # passed/failed/errors/wallclock
echo "TMC exception lines: $(grep -cE '^E.*TooManyConnectionsError|^\|.*TooManyConnectionsError' /tmp/v1022-1094-pre-fix-nauto-run${RUN}.log)"
echo "ICN exception lines: $(grep -cE '^E.*InvalidCatalogNameError|^\|.*InvalidCatalogNameError' /tmp/v1022-1094-pre-fix-nauto-run${RUN}.log)"
```

The `grep -cE '^E.*'` regex anchor distinguishes actual exception frames from comment-text matches inside `conftest.py:938-1109` (where `InvalidCatalogNameError` appears as historical narrative in code comments).

### 2.4 — Sequential baseline preservation (32-test pin subset spot-check)

Per Phase 1094 success criterion 5 (sequential baseline 3055/0/38 preservation verified by subset spot-check, NOT full 9min sequential re-run — no code changes ship from this spike, so spot-check is sufficient):

```bash
cd /Users/ishiland/Code/geolens/backend && set -a && source ../.env.test && set +a && \
  uv run pytest -k "test_fixture_isolation_v1020 or test_conftest_pool_sizing or test_conftest_lifecycle" -v
```

Expected: `32 passed, 1 skipped, 3077 deselected in ~4s`. Verified GREEN pre-Run-1 AND post-Run-3 at this spike (`32 passed in 4.23s` pre / `32 passed in 3.97s` post).

### 2.5 — 3-run pre-fix baseline measurements (verbatim from Section 1.1)

| Run | passed | failed | errors | wallclock (s) | TMC exception lines | ICN exception lines | Distinct (failed+errors) |
|-----|--------|--------|--------|---------------|---------------------|---------------------|--------------------------|
| 1   | 3045   | 8      | 6      | 425.26        | 53                  | 0                   | **14**                   |
| 2   | 3046   | 12     | 2      | 414.63        | 35                  | 0                   | **14**                   |
| 3   | 3037   | 7      | 14     | 406.61        | 48                  | 0                   | **21**                   |

Stale-DB cleanup deltas per run: Run 1 = 0 stale DBs (clean start); Run 2 = 1 (`geolens_test_gw9_7ef406a3`); Run 3 = 2 (`geolens_test_gw3_b2039b15`, `geolens_test_gw8_572d7c1d`). Post-Run-3 stale count = 0.

---

## Section 3 — Line-numbered fix-shape proposal

### 3.0 Pre-spike planner-anticipated fix shapes (now mismatched to actual surface)

CONTEXT.md "Specific Ideas" Step 5 enumerated 3 candidate shapes targeting the per-worker DB CREATE/migrate path (`_test_db_lifecycle:906`):
- Shape A (planner): extend `_create_test_db_with_retry` to cover the failing `dev_engine.connect()` path
- Shape B (planner): re-architect `_test_db_lifecycle` (stagger tuning OR static DB pool)
- Shape C (planner): dynamic `max_connections` sizing in dev_engine

**These are all REJECTED** because the planner's hypothesis enumeration was built atop 1093-02-FINDINGS Run 3 (706 errors / 4787 ICN lines / per-worker DB CREATE cascade), and that surface is CLOSED on the current HEAD `49625d27`. The observed cascade on Runs 1/2/3 fires at a DIFFERENT surface that none of the planner-anticipated shapes addresses.

### 3.1 Documentation of CONTEXT.md line-number drift

CONTEXT.md "Specific Ideas" stated: `_test_db_lifecycle:~661-674` for the per-worker DB CREATE failing surface. **This is wrong.** The actual line ranges (re-validated at audit-write time via `git grep -n` on HEAD `49625d27`):

| Symbol | CONTEXT.md cited | Actual (HEAD 49625d27) | Notes |
|---|---|---|---|
| `_test_db_lifecycle` | `~661-674` | `906-1138` | CONTEXT.md cited the wrong function — `661-674` is sub-range of `_install_dbapi_connect_retry` |
| `_install_dbapi_connect_retry` | `~664` | `664-708` | Correct |
| `_invoke_sleep_in_sync_context` | `~615` | `624-661` | CONTEXT.md off by 9 lines |
| `_RetryingAsyncEngine` | `~711` | `711-903` | Correct |
| `_SETUP_PHASE_RETRY_BACKOFFS = (1.0, 2.0, 4.0)` | line 333 | line 333 | Correct |
| `_TRANSIENT_CONTENTION_EXCEPTIONS` | line 352 | line 352 | Correct |
| `_CREATE_DB_RETRY_BACKOFFS = (1.0, 2.0, 4.0)` | not cited | line 256 | NEW reference for audit |
| `_SETUP_STAGGER_SECONDS = 5.0` | not cited | line 118 | NEW reference for audit |
| `_run_with_too_many_clients_retry` | not cited | line 359-460 | NEW reference for audit (Section 3.2 reuses this envelope) |
| `_create_test_db_with_retry` | not cited | line 259-325 | NEW reference for audit |
| `_test_db_lifecycle` call to `_create_test_db_with_retry` | not cited | line 959 | NEW reference for audit (proves per-worker DB CREATE IS protected) |

Phase 1095's planner SHOULD start from this corrected line-number table (NOT CONTEXT.md's stale ranges).

### 3.2 Proposed Fix (Shape A* — wrap `_init_tile_pool_for_tests`'s `asyncpg.create_pool` in existing retry envelope)

| Field | Value |
|---|---|
| **File** | `backend/tests/test_tiles.py` + `backend/tests/test_embed_tokens.py` + `backend/tests/test_tile_signing.py` (3 sibling fixture copies; OR: consolidate into a single shared fixture in `backend/tests/conftest.py`) |
| **Lines to change** | `backend/tests/test_tiles.py:151` + `backend/tests/test_embed_tokens.py:56` + `backend/tests/test_tile_signing.py:107` (the 3 `await asyncpg.create_pool(...)` call sites; line numbers `git grep`-validated at audit-write time on HEAD `49625d27`) |
| **What changes** | Wrap each `await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=3, command_timeout=10)` call in `_run_with_too_many_clients_retry` (the existing async retry envelope at `backend/tests/conftest.py:359`). Alternatively (preferred): consolidate the 3 sibling fixtures into a single `_init_tile_pool_for_tests` fixture in `conftest.py` (one source of truth) and apply the retry envelope there. The retry envelope catches `_TRANSIENT_CONTENTION_EXCEPTIONS` (which already includes `asyncpg.exceptions.TooManyConnectionsError` at `backend/tests/conftest.py:354`) and retries with the existing `_SETUP_PHASE_RETRY_BACKOFFS = (1.0, 2.0, 4.0)` budget (line 333). Reuses ALL existing retry envelope infrastructure — no new helpers, no new constants. Optional additive knob: reduce `max_size=3` → `max_size=2` to give 1-conn headroom per pool (32-conn demand at 16 workers × 2 vs 30-`max_connections` ceiling); operator discretion at Phase 1095. |
| **Why this closes the root cause** | All 6/2/14 errors across Runs 1/2/3 fire at the `await asyncpg.create_pool` line (TMC raised from `asyncpg/connect_utils.py:1102` → caller in `_init_tile_pool_for_tests` fixture). Wrapping that call in `_run_with_too_many_clients_retry` gives the pool-creation 7s of retry budget under contention. The 7s budget covers 3 retries with backoffs (1.0, 2.0, 4.0) — long enough for early-burst workers to release pool conns back to the ceiling. The cascade in Runs 1/2/3 was bursty (5-7 workers active concurrently) but bounded — the contention window is short (concurrent fixture init for tile-related test classes). Retry-with-backoff is the canonical pattern for transient connection-pool saturation and matches the existing v1020/v1021 architecture (`_create_test_db_with_retry`, `_install_dbapi_connect_retry`, `_RetryingAsyncEngine`). The 7-12 downstream API integration test failures (`test_stac_*`, `test_records_related`, etc.) should also clear once the tile-pool-creation pressure drops because the connection ceiling will not be drained as deeply. |
| **What this intentionally does NOT fix** | (1) DOES NOT touch `_test_db_lifecycle` (the planner-anticipated surface is already closed by `_create_test_db_with_retry` at `backend/tests/conftest.py:259` + the v1020 close-state). (2) DOES NOT modify the engine wrapper `_RetryingAsyncEngine` or `_install_dbapi_connect_retry` (separate Category 4.3 surface; those work correctly per 1093-02-FINDINGS Runs 1+2). (3) DOES NOT change `max_connections` (out of scope per REQUIREMENTS.md Out-of-Scope). (4) DOES NOT change `-n auto` worker count (out of scope per REQUIREMENTS.md Out-of-Scope — "Artificial `-n` cap below `auto`"). (5) DOES NOT change the FastAPI request-handler engine wrapping (`backend/app/core/db/session.py:25-26` engine is not test-fixture machinery; production engine has different acceptance criteria per REQUIREMENTS.md Out-of-Scope — "Engine-level retry for application code (FastAPI request path) — Test-fixture engine only"). Downstream API integration test failures should drop as a SIDE-EFFECT of reduced pool-creation pressure; if they don't, a follow-up Phase 1096+ surface to wrap the FastAPI engine for test-execution mode is a separate hygiene decision that exceeds v1022 scope. |

### 3.3 Alternative Fix Shapes Considered (Rejected)

| Shape | Why rejected |
|---|---|
| **Shape A (planner, original) — extend `_create_test_db_with_retry` retry coverage at `dev_engine.connect()` path inside `_test_db_lifecycle`** | Rejected: the per-worker DB CREATE path is ALREADY protected by `_create_test_db_with_retry` (invoked at `backend/tests/conftest.py:959`) with `_CREATE_DB_RETRY_BACKOFFS = (1.0, 2.0, 4.0)` budget (line 256). Runs 1/2/3 produced ZERO `InvalidCatalogNameError` exception frames (only comment-text matches in conftest.py). The cascade source on this HEAD is NOT the per-worker DB CREATE path; targeting that path adds defense-in-depth but does not address the observed failure mode. |
| **Shape B (planner, original) — `_test_db_lifecycle` re-architecting (worker startup stagger tuning OR static DB pool)** | Rejected: the existing 5s stagger × 16 workers = 75s ceiling (`_SETUP_STAGGER_SECONDS = 5.0` at `backend/tests/conftest.py:118`) appears to be working correctly (active workers list in Run 1 shows only 5 of 16 workers triggered errors; Run 3 shows 7 of 16; the remaining workers completed setup without contention). Re-architecting the per-worker DB lifecycle would regress v1020's isolation invariants (each worker gets its own per-session DB; no cross-worker leakage) and is a significantly larger surface than the observed root cause warrants. |
| **Shape C (planner, original) — dynamic `max_connections` sizing in dev_engine** | Rejected: this is the test-side mirror image of the `max_connections=30` bump that REQUIREMENTS.md Out-of-Scope explicitly forbids ("Postgres `max_connections` bump … production envelope at 30 is correct"). Artificially capping the test-side connection demand would mask the actual contention point — the `_init_tile_pool_for_tests` fixture's direct asyncpg pool init — rather than fixing it. |
| **Shape D — bump per-test-class fixture `max_size=3` → `max_size=2`** | Considered but insufficient on its own. 16 workers × 2 = 32 still exceeds 30. May be useful as an additive knob on top of Shape A* (32-conn demand with 7s retry budget will tolerate 2-3 workers' simultaneous pool init dropping into a retry queue rather than failing). Operator-discretion at Phase 1095. |
| **Shape E — convert `_init_tile_pool_for_tests` to use a single shared module-scope pool across the xdist session** | Rejected as overreach: would require changes to `app.processing.tiles.pool` module structure (currently per-process global `_tile_pool`); test isolation across xdist workers becomes harder to reason about; risks regressing the test-fixture model that v1020 established. Defer to a future v1023+ requirement if the Shape A* retry envelope proves insufficient. |
| **Shape F — wrap the FastAPI app-engine `backend/app/core/db/session.py:25` engine in `_RetryingAsyncEngine` during test mode only** | Rejected for v1022 scope: would address the 7-12 downstream API integration test failures but expands the engine-wrapper surface to production-code, which REQUIREMENTS.md Out-of-Scope explicitly forbids ("Engine-level retry for application code (FastAPI request path) — Test-fixture engine only. Production engine has different acceptance criteria (request latency, not test determinism)"). Even monkey-patching the engine for tests-only would cross the conftest/production-code boundary. If Shape A* drops distinct (failed+errors) ≤ 30 deterministically, this shape becomes unnecessary; if not, it becomes a Phase 1096+ open question. |

---

## Section 4 — WR-02 prerequisite analysis (PARA-02 (d) preliminary disposition)

### 4.0 Question

Does WR-02's blocking `time.sleep` at `backend/tests/conftest.py:624` (re-validated at audit-write time: `def _invoke_sleep_in_sync_context(sleep_fn, seconds):` at exactly line 624) compound the observed cascade by freezing the asyncio loop up to 7s during `_SETUP_PHASE_RETRY_BACKOFFS = (1.0, 2.0, 4.0)` exhaustion?

### 4.1 Call-Site Map for `_invoke_sleep_in_sync_context`

Validated via `grep -n "_invoke_sleep_in_sync_context" backend/tests/conftest.py` on HEAD `49625d27`:

| Line | Caller | Context | Reaches per-worker DB CREATE? | Reaches `_init_tile_pool_for_tests` (observed cascade)? |
|------|--------|---------|-------------------------------|---------------------------------------------------------|
| 706 | `_install_dbapi_connect_retry._retry_do_connect` | engine `do_connect` event handler (Category 4.3) | **NO** — fires on session-engine connection acquisition through the test-engine wrapper, NOT on `dev_engine.connect()` for CREATE DATABASE | **NO** — `_init_tile_pool_for_tests` calls `asyncpg.create_pool()` directly; it does NOT route through any SQLAlchemy engine, so the `do_connect` event never fires for it |
| 843 | `_RetryingAsyncEngine.connect()` | engine wrapper method retry | **NO** — same — the wrapper wraps `AsyncEngine`, not the per-worker `dev_engine` used for CREATE DATABASE | **NO** — `asyncpg.create_pool` is not routed through `_RetryingAsyncEngine` at all |

### 4.2 Sleep paths in the actual failing surface

- `_create_test_db_with_retry` (per-worker DB CREATE, `backend/tests/conftest.py:259-325`): uses `sleep_fn=time.sleep` directly (line 262 default); invokes via `sleep_fn(backoffs[attempt])` at line 320 — does NOT route through `_invoke_sleep_in_sync_context`. The blocking sleep here IS already blocking, but the call site is at per-worker setup gate (before any other test work) so loop-starvation has no other tasks to starve.
- `_run_with_too_many_clients_retry` (in-test async session retry, `backend/tests/conftest.py:359-460`): uses `sleep_fn=asyncio.sleep` (async-native, line 361 default); invokes via `await sleep_fn(backoffs[attempt])` at line 457 — properly yields the loop. No WR-02 footgun here.
- `_test_db_lifecycle` teardown (`backend/tests/conftest.py:1130`): uses `time.sleep(0.05)` directly — 50ms blocking sleep to let `pg_terminate_backend` drain. Bounded by 50ms (3 orders of magnitude smaller than the 7s budget) — not a meaningful loop-starvation contributor.
- `_init_tile_pool_for_tests` (observed cascade surface, `backend/tests/test_tiles.py:142` + 2 siblings): no retry, no sleep. Single attempt at `await asyncpg.create_pool(...)`. Failure propagates immediately.

### 4.3 Disposition: **INDEPENDENT**

WR-02's blocking `time.sleep` is invoked ONLY inside the engine-wrapper Category 4.3 retry paths (`_install_dbapi_connect_retry._retry_do_connect` at line 706, and `_RetryingAsyncEngine.connect()` at line 843). The observed cascade on Runs 1/2/3 of HEAD `49625d27` (distinct = 14/14/21, all `TooManyConnectionsError` from `_init_tile_pool_for_tests` + downstream API integration tests) does NOT route through either of these code paths. Therefore:

- **WR-02 closure is NOT a prerequisite for the observed cascade to drop below ≤30 distinct.** The current HEAD already satisfies ≤30 on all 3 runs (14/14/21) without WR-02 closure.
- **WR-02 closure is INDEPENDENT of the PARA-01 fix shape (Shape A*).** PARA-02 can sequence either before, alongside, or after PARA-01 fix without changing the cascade threshold outcome.
- The original "cascade-pressure" hypothesis (`_invoke_sleep_in_sync_context` blocking sleep freezes asyncio loop during 7s budget exhaustion, prolonging connection saturation) requires the wrapper retry path to BE FIRING — which means the contention has to be hitting the SQLAlchemy engine layer. The observed cascade is at the asyncpg-pool layer, BEFORE any SQLAlchemy wrapper has a chance to engage.

### 4.4 Caveat: WR-02 is still a real footgun

The blocking sleep at `_invoke_sleep_in_sync_context:652` (`time.sleep(seconds)` when `sleep_fn is asyncio.sleep`) DOES freeze the asyncio loop for up to 7s under the `_SETUP_PHASE_RETRY_BACKOFFS` budget exhaustion. If the engine wrapper retry path were to fire (e.g., under a future scenario where the cascade source shifts back to Category 4.3 in-test contention), the loop-starvation would be real. So PARA-02 closure is still valuable for forward-safety — just NOT a Phase 1095 prerequisite.

### 4.5 Recommendation for Phase 1095 sequencing

Both PARA-01 (Shape A* — `_init_tile_pool_for_tests` pool-creation retry envelope) AND PARA-02 (`_invoke_sleep_in_sync_context` async-yielding fix) can land in Phase 1095 in either order. The CONTEXT.md decision to bundle them in Phase 1095 is correct on file-adjacency grounds: PARA-02 modifies `backend/tests/conftest.py:624` and PARA-01 fix modifies `backend/tests/test_tiles.py:151` + 2 siblings (different files but the bundle simplifies the `-n auto` measurement gate). **Sequencing inside Phase 1095 is operator-discretion: independent fixes, atomic measurement gate.**

### 4.6 Optional WR-02 isolated test — DEFERRED to Phase 1095

The CONTEXT.md option for a 20-line standalone `/tmp/v1022-1094-wr02-loopcheck.py` script to measure asyncio-loop freeze under blocking sleep is **not required** given the static evidence above. The disposition is INDEPENDENT, not UNCLEAR; the isolated test would confirm WR-02's loop-freeze behavior but would not change the Phase 1095 sequencing recommendation. The regression-pin shape in Section 5 includes a concurrent-task scheduling assertion (`test_init_tile_pool_retry_yields_event_loop_during_backoff`) that covers PARA-02 acceptance criterion (b) at the new pool-init helper surface, which is the stronger guarantee.

---

## Section 5 — Regression-pin shape proposal (PARA-01 (d) preview)

### 5.0 Adaptation to actual cascade surface

Since the dominant cascade source on the current HEAD is `_init_tile_pool_for_tests` (asyncpg.create_pool direct call), NOT per-worker DB lifecycle, the pin shape covers the actual failing surface — using the same `TooManyConnectionsError` injection model that v1020/v1021's existing 4 `test_engine_retry_*` pins already use.

### 5.1 Proposed Regression Pin Shape

| Field | Value |
|---|---|
| **Test file** | `backend/tests/test_fixture_isolation_v1020.py` (extends the existing `test_engine_retry_*` section to keep all retry-pin coverage in one file — matches v1021 Phase 1093 wave that added the 4 existing `test_engine_retry_*` pins at lines 904 / 977 / 1029 / 1070, validated via `git grep -nE "^def test_engine_retry_"` at audit-write time on HEAD `49625d27`). NEW pin lives co-located with the existing 4 engine-retry pins. |
| **Fixtures used** | `monkeypatch` (no DB-dependent fixtures because this is a fixture-machinery test) |
| **Test function (required)** | `test_init_tile_pool_retries_on_transient_too_many_clients` — call the Phase 1095 fix's tile-pool-init helper (e.g., a new `_init_tile_pool_with_retry(dsn, min_size, max_size, command_timeout)` helper that wraps `asyncpg.create_pool` in `_run_with_too_many_clients_retry`) with a monkey-patched `asyncpg.create_pool` that raises `asyncpg.exceptions.TooManyConnectionsError("sorry, too many clients already")` for the first 2 attempts then succeeds on the 3rd. Assert: (a) the helper returns a non-None pool, (b) `asyncpg.create_pool` was called exactly 3 times, (c) the injected `sleep_fn` was called exactly 2 times with the expected backoffs `(1.0, 2.0)`. **Should PASS post-fix.** |
| **Test function (additional — async-loop yield assertion for PARA-02)** | `test_init_tile_pool_retry_yields_event_loop_during_backoff` — set up a concurrent `asyncio.create_task(asyncio.sleep(0.1))` BEFORE invoking the helper; the helper's retry budget should `await` the sleep (NOT block via `time.sleep`), so the concurrent task should complete during the backoff window. Assert the concurrent task completes within `~2.1s` (well under the blocking-budget 7s + 0.1s ceiling). This covers PARA-02 acceptance criterion (b) at the new pool-init helper surface — gives Phase 1095 a single pin that exercises BOTH PARA-01 (d) retry coverage AND PARA-02 (b) loop-yield guarantee. |
| **(Optional) Test function (xfail pre-fix)** | `test_init_tile_pool_no_retry_pre_fix_raises_too_many_clients` — same injection setup but call the CURRENT `await asyncpg.create_pool(...)` directly (no retry envelope). `@pytest.mark.xfail(raises=asyncpg.exceptions.TooManyConnectionsError, reason="pre-fix regression pin: test_tiles.py:142 + sibling fixtures call asyncpg.create_pool without retry envelope; see .planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md")`. Documents the bug shape so any future regression that re-introduces unwrapped pool creation is caught immediately. **Recommended INCLUDE** — v1021 Phase 1091 spike used the xfail-pre-fix pattern and it landed as concrete regression evidence in the audit doc shape. Phase 1095 SHOULD include because the symmetric shape (positive pin + xfail pre-fix pin) gives reviewers a single-glance summary of "before/after" behavior. |

### 5.2 Naming convention rationale

The existing `test_engine_retry_*` family (4 pins at lines 904 / 977 / 1029 / 1070 in `backend/tests/test_fixture_isolation_v1020.py`) covers the engine wrapper layer. The new `test_init_tile_pool_*` family covers the pool-init layer. Naming the family `test_init_tile_pool_*` rather than continuing the `test_engine_retry_*` shape signals to a reviewer that this is a DIFFERENT retry surface (pool init vs engine connect), not a variant of an existing one. Function names are `git grep`-friendly per v1019 TD-13 `req_citation_pinning`.

### 5.3 Why not a new file `test_per_worker_db_lifecycle_v1022.py`?

REQUIREMENTS.md PARA-01 (d) names the file as an alternative ("a new `test_per_worker_db_lifecycle_v1022.py`"). The rationale for the alternative was: cleaner separation if pin set is large. Since this spike's analysis identified ONE pin family (`test_init_tile_pool_*`) with 2-3 pins, the existing `test_fixture_isolation_v1020.py` file is the natural home — extending an existing test family is lower-cognitive-load than creating a new file for 2-3 pins. Note also: the file's name (`per_worker_db_lifecycle`) does not match the actual cascade surface (`tile_pool_init`); creating a misnamed file would mislead future planners. If Phase 1095 discovers additional retry surfaces during implementation (e.g., the FastAPI app-engine wrapping in Shape F is added), the file-split decision can be revisited.

### 5.4 Phase 1095 task ordering (informational, for the Phase 1095 planner)

1. **Implement helper** — add `_init_tile_pool_with_retry(...)` to `backend/tests/conftest.py` (uses existing `_run_with_too_many_clients_retry` infrastructure at `backend/tests/conftest.py:359`).
2. **Add RED pin** — write `test_init_tile_pool_retries_on_transient_too_many_clients` in `backend/tests/test_fixture_isolation_v1020.py`; verify it RED-FAILS against the un-wrapped `asyncpg.create_pool` (TDD step).
3. **Wire helper into fixtures** — replace `await asyncpg.create_pool(...)` in `backend/tests/test_tiles.py:151`, `backend/tests/test_embed_tokens.py:56`, `backend/tests/test_tile_signing.py:107` (or consolidate to a single shared fixture in conftest.py) with the new helper.
4. **Verify GREEN** — re-run the new pin; verify PASS.
5. **Add xfail-pre-fix pin** — write `test_init_tile_pool_no_retry_pre_fix_raises_too_many_clients` as documentation evidence (optional but recommended).
6. **Add async-yield pin** — write `test_init_tile_pool_retry_yields_event_loop_during_backoff` for PARA-02 acceptance criterion (b) coverage.
7. **Re-run `pytest -n auto` 3-run baseline** — measure distinct (failed+errors) per run; target ≤30 deterministic across 3 consecutive runs per PARA-01 acceptance criterion (a).

### 5.5 Anchoring assumption

This pin shape assumes the Phase 1095 fix uses the existing `_run_with_too_many_clients_retry` envelope (the planner-proposed Shape A* path). If Phase 1095 chooses a different architectural approach (e.g., consolidated shared-pool model — Shape E rejected here, or FastAPI-engine wrapping — Shape F rejected here), the pin signature changes accordingly. The PIN SHAPE is "retry-on-injected-TMC succeeds + sleep_fn called as expected + asyncio loop yields during backoff"; the specific helper name and signature are determined at Phase 1095 implementation time.

---

## Artifacts

- `/tmp/v1022-1094-pre-fix-nauto-run{1,2,3}.{log,xml}` — 3 baseline `pytest -n auto` runs (preserved for Phase 1095 post-fix delta-comparison)
- `/tmp/v1022-1094-stale-dbs-run{1,2,3}.txt` + `/tmp/v1022-1094-drop-stale-run{1,2,3}.sql` — stale-DB enumeration + DROP SQL per run
- `/tmp/v1022-1094-pre-flight-pins.log` — pre-flight git-grep validation log + 32-test pin subset spot-check result
- `/tmp/v1022-1094-icn-tracebacks.log` — ICN traceback corpus (mostly empty — 0 actual ICN exception frames across 3 runs)
- `/tmp/v1022-1094-hypothesis-evidence.md` — Task 2 scratch (Section 1.3 verdict matrix + dominant root cause)
- `/tmp/v1022-1094-wr02-evidence.md` — Task 3 Step 1 scratch (Section 4 disposition)
- `/tmp/v1022-1094-fix-shape-proposal.md` — Task 3 Step 2 scratch (Section 3.2 + 3.3 fix shape)
- `/tmp/v1022-1094-pin-shape-proposal.md` — Task 3 Step 3 scratch (Section 5 pin shape)

---

## Plan 1095 implements the fix proposed in Section 3.2.

Specifically, Plan 1095's executor consumes this audit doc as:

1. **The PARA-01 fix `<action>`:** apply Shape A* — wrap `asyncpg.create_pool` in `_init_tile_pool_for_tests` (3 sibling sites) in `_run_with_too_many_clients_retry`. Preferred: consolidate to a single shared fixture in `conftest.py`. (Section 3.2 + 5.4 task ordering.)
2. **The PARA-01 regression-pin `<action>`:** add `test_init_tile_pool_retries_on_transient_too_many_clients` + (recommended) `test_init_tile_pool_no_retry_pre_fix_raises_too_many_clients` + `test_init_tile_pool_retry_yields_event_loop_during_backoff` to `backend/tests/test_fixture_isolation_v1020.py`. (Section 5.1.)
3. **The PARA-02 sequencing decision:** WR-02 is INDEPENDENT of PARA-01; can land in any order in Phase 1095. (Section 4.3.)
4. **The PARA-02 fix `<action>`:** refactor `_invoke_sleep_in_sync_context` at `backend/tests/conftest.py:624` to yield the asyncio loop (either via `anyio.sleep` / `asyncio.get_event_loop().run_in_executor()` / equivalent), with a regression pin asserting concurrent-task scheduling. (Section 5.1 `test_init_tile_pool_retry_yields_event_loop_during_backoff` doubles as the PARA-02 (b) pin.)
5. **The CONTEXT.md line-number drift correction:** Phase 1095's planner SHOULD use the corrected line-number table at Section 3.1, NOT CONTEXT.md's stale ranges (`_test_db_lifecycle:~661-674` is wrong by ~250 lines).

---

*Phase: 1094-cascade-spike*
*Plan: 01 (status: COMPLETE)*
*Captured: 2026-05-23 — HEAD `49625d27`*
