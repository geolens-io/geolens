# Phase 1095: Cascade Fix + WR-02 Closure - Context

**Gathered:** 2026-05-23
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss); consumes Phase 1094 spike audit

<domain>
## Phase Boundary

Land the PARA-01 fix at the line(s) named in Phase 1094's audit doc (`.planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md`) + close PARA-02's WR-02 footgun. Bundled because:
- (a) Both surfaces live in adjacent regions of `backend/tests/conftest.py` (and now 3 test files for PARA-01 per spike).
- (b) The `-n auto` measurement gate (PARA-01 (a)) must re-run AFTER both changes land — splitting them across phases would double the gate cost and obscure which change moved the threshold.
- (c) Phase 1094 disposition: WR-02 is INDEPENDENT of the cascade (not a prerequisite). PARA-01 and PARA-02 can land in any order within Phase 1095; recommend single combined commit per atomic-measurement principle.

### Spike findings consumed (verbatim from `.planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md`)

**Root cause (NEW — supersedes v1021 Phase 1093-02-FINDINGS hypothesis):** The Run 3+4 cascade documented in 1093-02-FINDINGS is NOT reproducing on current HEAD (`49625d27`). Pre-fix 3-run baseline: distinct = 14/14/21 (all already ≤30 threshold; 0 actual `InvalidCatalogNameError` exception frames across all 3 runs — earlier raw `grep -c` counts matched comment text inside conftest.py:938-1109, not real cascade).

**However, baseline IS above the existing `test_oauth.py` flake-class noise floor** — the residual 14/14/21 still includes connection-contention failures at a different code path than v1021's Category 4.3 surface. The dominant source is `_init_tile_pool_for_tests` (3 sibling fixtures):

| Call site | Line | Pattern |
|---|---|---|
| `backend/tests/test_tiles.py` | 142 (fixture) → 151 (`asyncpg.create_pool`) | `asyncpg.create_pool(dsn=dsn, min_size=1, max_size=3, command_timeout=10)` |
| `backend/tests/test_embed_tokens.py` | 38 (fixture) → 56 (`asyncpg.create_pool`) | Same shape |
| `backend/tests/test_tile_signing.py` | 102 (fixture) → 107 (`asyncpg.create_pool`) | Same shape |

All 3 bypass conftest.py retry envelopes (`_create_test_db_with_retry`, `_install_dbapi_connect_retry`, `_RetryingAsyncEngine`). 16 workers × 3 conns = up to 48 concurrent connection attempts vs `max_connections=30` ceiling.

**PARA-01 fix — Shape A* (chosen):** Wrap the 3 `asyncpg.create_pool` call sites in the existing `_run_with_too_many_clients_retry` envelope at `backend/tests/conftest.py:359`. Reuses existing infrastructure. 6 alternative shapes (planner's A/B/C + spike's D/E/F) rejected with rationale in audit Section 3.3.

**WR-02 disposition: INDEPENDENT.** `_invoke_sleep_in_sync_context` (line 624) is invoked only from `_install_dbapi_connect_retry._retry_do_connect` (line 706) and `_RetryingAsyncEngine.connect()` (line 843) — both are Category 4.3 engine-wrapper paths that the new cascade source (`_init_tile_pool_for_tests`) bypasses. PARA-02 fix can land independently; recommend bundling because both touch `backend/tests/conftest.py`.

**Regression-pin family — `test_init_tile_pool_*` (distinct from existing `test_engine_retry_*`):**
- `test_init_tile_pool_retries_on_transient_too_many_clients` (PARA-01 (d) — covers per-tile-pool retry)
- `test_init_tile_pool_retry_yields_event_loop_during_backoff` (PARA-02 (b) — doubles as loop-yield coverage)
- Optional `test_init_tile_pool_propagates_non_transient_error` if envelope's behavior differs

**Line-number corrected reference table** (from spike audit Section 3.1 — supersedes CONTEXT.md approximate lines):

| Function/constant | Actual line (HEAD `49625d27`) | CONTEXT.md said |
|---|---|---|
| `_SETUP_PHASE_RETRY_BACKOFFS` | 333 | 333 ✓ |
| `_TRANSIENT_CONTENTION_EXCEPTIONS` | 352 | 352 ✓ |
| `_run_with_too_many_clients_retry` | 359 | (not cited) |
| `_invoke_sleep_in_sync_context` | 624 | ~615 (drift +9) |
| `_install_dbapi_connect_retry` | 664 | 664 ✓ |
| `_retry_do_connect` (inner) | 706 | (not cited) |
| `_RetryingAsyncEngine` (class) | 711 | 711 ✓ |
| `_RetryingAsyncEngine.connect` | 843 | (not cited) |
| `_test_db_lifecycle` | 906 | ~661-674 (drift +245) |

### Requirements satisfied at this phase

- **PARA-01 full closure** — acceptance criteria (a) `-n auto` ≤30 distinct across 3 consecutive runs deterministic; (b) sequential 3055/0/38 preserved; (c) `-n 4` 3054/0/38 preserved; (d) regression pin lands. (e) already satisfied at Phase 1094 via spike audit. `[ ]` → `[x]` flip + `Pending` → `Complete` lands at Phase 1095 close per v1019 TD-13.
- **PARA-02 full closure** — acceptance criteria (a) WR-02 footgun closed (non-blocking yield OR load-bearing rationale); (b) regression pin asserts loop continues processing during retry-backoff; (c) zero regression on 4 existing `test_engine_retry_*` pins; (d) already preliminary at Phase 1094 (INDEPENDENT). `[ ]` → `[x]` flip + `Pending` → `Complete` lands at Phase 1095 close.

### Out-of-scope reaffirmations

- Postgres `max_connections` bump (production envelope at 30 stays).
- Artificial `-n` cap below `auto`.
- App-engine retry (FastAPI request path).
- Pre-existing OOS rows (`test_layering`, `test_phase_275`, `test_ssrf_redirect`).
- Production-code refactor beyond conftest/test-fixture layer.
- HYG-01 / CI-01 / CLOSE-01 — these land in Phases 1096 / 1097.
</domain>

<decisions>
## Implementation Decisions

### Fix sequencing within Phase 1095

Two plans recommended:
- **Plan 01: PARA-01 fix (Shape A*)** — wrap 3 `asyncpg.create_pool` call sites in `_run_with_too_many_clients_retry` envelope. Land + commit + measure post-fix `pytest -n auto` 3-run baseline → must show ≤30 distinct deterministic.
- **Plan 02: PARA-02 fix (WR-02 closure)** — non-blocking sleep alternative OR load-bearing rationale + loop-yield regression pin.

Bundled because both touch `backend/tests/conftest.py` (PARA-02) + 3 test files (PARA-01); single phase atomic measurement gate is cleaner than splitting.

**Why Plan 01 first:** PARA-01 is the primary acceptance criterion (`-n auto` ≤30 threshold). PARA-02 is hygiene-shape against an INDEPENDENT footgun. Measuring after PARA-01 alone confirms Shape A* works; measuring again after PARA-02 confirms WR-02 didn't regress the gate.

### Regression pin location

PARA-01 + PARA-02 pins land in `backend/tests/test_fixture_isolation_v1020.py` (extends the existing 15-test file with v1020 naming convention) UNLESS the file grows past 1500 LOC, in which case spin out `backend/tests/test_init_tile_pool_v1022.py`. Planner decides.

### Measurement gate

Post-fix `pytest -n auto` 3-run baseline with stale-DB cleanup between runs per PYTEST-XDIST-PERF-v1020.md Section 1 Step 1b. Acceptance: ≤30 distinct (failed + errors) per run across 3 consecutive runs. Captured to `/tmp/v1022-1095-post-fix-nauto-run{1,2,3}.{log,xml}`.

**Delta comparison:** spike captured pre-fix at `/tmp/v1022-1094-pre-fix-nauto-run{1,2,3}.{log,xml}`. Post-fix run delta should show: residual cascade source eliminated; remaining failures are pre-existing OOS (`test_layering`, `test_phase_275`, `test_ssrf_redirect`) + oauth flake-class.

### WR-02 fix shape

Two candidates per REQUIREMENTS.md PARA-02 (a):
- **Shape Y1: yield via `asyncio.get_event_loop().run_in_executor()` / `anyio.sleep()` / non-blocking equivalent**. Cleaner semantically; eliminates the 7s loop starvation window entirely.
- **Shape Y2: load-bearing rationale inline-commented + mitigation in engine wrapper**. Keeps blocking sleep with documented intent.

Planner picks based on test-runtime evidence. Default: Shape Y1 (non-blocking yield).

### HARD INVARIANT (v1019 TD-13)

- Sequential pytest `failed == 0` non-negotiable. Baselines: sequential 3055/0/38, `-n 4` 3054/0/38.
- REQ citation pinning: planner MUST validate `path::TestClass::test_name` node-IDs via `git grep -n "def <test_name>" <path>` BEFORE plans commit. Applies to new `test_init_tile_pool_*` pins.
- Traceability flip: executor MUST flip REQUIREMENTS.md `[ ]` → `[x]` and `Pending` → `Complete` for PARA-01 AND PARA-02 in the SAME commit as SUMMARY.md.

### Atomic-N-file commit per plan

- Plan 01: `backend/tests/test_tiles.py` + `backend/tests/test_embed_tokens.py` + `backend/tests/test_tile_signing.py` + `backend/tests/test_fixture_isolation_v1020.py` (new pin) + `.planning/phases/1095-cascade-fix-wr-02-closure/1095-01-SUMMARY.md` + `.planning/REQUIREMENTS.md` (PARA-01 traceability flip). 6 files.
- Plan 02: `backend/tests/conftest.py` (WR-02 fix at line 624) + `backend/tests/test_fixture_isolation_v1020.py` (new pin) + `.planning/phases/1095-cascade-fix-wr-02-closure/1095-02-SUMMARY.md` + `.planning/REQUIREMENTS.md` (PARA-02 traceability flip). 4 files.

### Playwright MCP

Not applicable — backend test-infra phase. Live MCP smoke is reserved for Phase 1097's close-gate (CLOSE-01 (d) — live docker stack health spot-check via `docker compose ps` + `curl /api/health/`).
</decisions>

<code_context>
## Existing Code Insights

### Files to edit

- `backend/tests/test_tiles.py:142-160` — `_init_tile_pool_for_tests` fixture; wrap line 151's `asyncpg.create_pool` call in `_run_with_too_many_clients_retry`. Import the helper from `backend.tests.conftest`.
- `backend/tests/test_embed_tokens.py:38-60` — same pattern at line 56.
- `backend/tests/test_tile_signing.py:102-115` — same pattern at line 107.
- `backend/tests/conftest.py:624` — `_invoke_sleep_in_sync_context` WR-02 fix.
- `backend/tests/test_fixture_isolation_v1020.py` — append new `test_init_tile_pool_*` pin family (existing file has 15 tests).

### Files to read only

- `backend/tests/conftest.py:333,352,359,664,711,843,906` — existing retry envelope + helper definitions.
- `.planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md` Sections 3.2 (Shape A* spec), 4.3 (WR-02 INDEPENDENT), 5.1 (pin shape).
- `.planning/audits/PYTEST-XDIST-PERF-v1020.md` Section 1 (reproduction recipe template) + Section 2 (oauth flake-class baseline numbers).
- `/tmp/v1022-1094-pre-fix-nauto-run{1,2,3}.{log,xml}` — pre-fix baseline preserved for delta-comparison.

### Reference patterns

- `_run_with_too_many_clients_retry` at `backend/tests/conftest.py:359` — the existing envelope being reused. Read its signature + usage at `_acquire_test_session_with_retry` (the existing canonical caller) to mirror the wrap pattern.
- Existing 4 `test_engine_retry_*` pins at `backend/tests/test_fixture_isolation_v1020.py:904,977,1029,1070` — naming convention reference for new `test_init_tile_pool_*` pins.
- `backend/tests/conftest.py:_SETUP_PHASE_RETRY_BACKOFFS` (line 333) + `_TRANSIENT_CONTENTION_EXCEPTIONS` (line 352) — REUSE verbatim, no new definitions.
</code_context>

<specifics>
## Specific Ideas

### PARA-01 fix workflow (Plan 01)

1. **Read** `backend/tests/conftest.py:359` (`_run_with_too_many_clients_retry` signature + docstring).
2. **Read** `backend/tests/test_tiles.py:142-160` + `test_embed_tokens.py:38-60` + `test_tile_signing.py:102-115` — confirm 3 sites have identical structure.
3. **Refactor** each site: wrap `asyncpg.create_pool(...)` call in `await _run_with_too_many_clients_retry(...)`. Import the helper. Three near-identical 5-10 LOC changes.
4. **Add regression pin** `test_init_tile_pool_retries_on_transient_too_many_clients` to `test_fixture_isolation_v1020.py`. Inject `TooManyConnectionsError` on first attempt; assert retry succeeds.
5. **Verify sequential baseline**: `cd backend && uv run pytest -k "test_tiles or test_embed_tokens or test_tile_signing"` (sanity check post-refactor).
6. **Verify 32-test pin subset**: `cd backend && uv run pytest -k "test_fixture_isolation_v1020 or test_conftest_pool_sizing or test_conftest_lifecycle"` → 33 passed (32 existing + 1 new pin).
7. **Run post-fix `pytest -n auto` 3-run baseline**: stale-DB cleanup between runs; capture to `/tmp/v1022-1095-post-fix-nauto-run{1,2,3}.{log,xml}`. Distinct ≤30 per run.
8. **Atomic commit**: 3 test files + 1 regression pin + SUMMARY.md + REQUIREMENTS.md PARA-01 flip = 6 files.

### PARA-02 fix workflow (Plan 02)

1. **Read** `backend/tests/conftest.py:624-660` (`_invoke_sleep_in_sync_context` + surrounding context).
2. **Pick shape Y1 or Y2** based on whether the sync-context constraint allows asyncio yield. Recommended Y1: yield via `loop.run_in_executor(None, time.sleep, n)` OR replace blocking with `asyncio.sleep()` if invocation context is async.
3. **Add regression pin** `test_init_tile_pool_retry_yields_event_loop_during_backoff` (or `test_engine_retry_yields_event_loop_during_backoff` if PARA-01 is closed at conftest level): assert concurrent task scheduling proceeds during retry-backoff window.
4. **Verify 32-test pin subset** unchanged.
5. **Verify 4 existing `test_engine_retry_*` pins** still pass (PARA-02 (c)).
6. **Re-run `pytest -n auto` 3-run baseline** (delta vs Plan 01 post-fix — should show no regression).
7. **Atomic commit**: conftest.py + 1 regression pin + SUMMARY.md + REQUIREMENTS.md PARA-02 flip = 4 files.

### Phase 1095 close criteria (rollup)

- PARA-01 (a/b/c/d) GREEN (e already done at Phase 1094).
- PARA-02 (a/b/c) GREEN (d already preliminary at Phase 1094, finalized at Plan 02 close).
- REQUIREMENTS.md PARA-01 + PARA-02 = `[x]` + `Complete`.
- Sequential pytest `3055/0/38` preserved.
- `-n 4` `3054/0/38` preserved.
- `-n auto` ≤30 distinct deterministic across 3 runs.

### Out of phase 1095 scope

- WR-01 / WR-03 / WR-04 (HYG-01) — Phase 1096.
- CI-01 / CLOSE-01 — Phase 1097.
- CHANGELOG `[1.5.7]` write — Phase 1097.
- Tag cut — Phase 1097.
</specifics>

<deferred>
## Deferred Ideas

None for Phase 1095 — scope is bounded by PARA-01 + PARA-02 closure. If the post-fix `-n auto` measurement does NOT hit ≤30 deterministic across 3 runs:
- **Iter-2 in-checkpoint**: tweak the retry budget (`_SETUP_PHASE_RETRY_BACKOFFS`) OR add additional `_run_with_too_many_clients_retry` sites if the audit Section 5.3 missed a 4th call site. Land inline per v1021 Phase 1091 iter-2 precedent.
- **Escalate to v1023+**: if iter-2 doesn't close, document the residual surface and defer to a future hygiene milestone.

Do NOT bloom Phase 1095 scope with additional surface — keep the change-set focused on what the spike named.
</deferred>
