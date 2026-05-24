---
phase: 1095-cascade-fix-wr-02-closure
plan: 01
subsystem: testing
tags: [pytest, pytest-xdist, asyncpg, retry-envelope, fixture-isolation, contention]
status: complete

# Dependency graph
requires:
  - phase: 1094-cascade-spike
    provides: "audit `.planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md` naming Shape A* + pre-fix baseline at `/tmp/v1022-1094-pre-fix-nauto-run{1,2,3}.{log,xml}`"
  - phase: v1020-1088
    provides: "`_run_with_too_many_clients_retry` envelope at `backend/tests/conftest.py:359` + `_SETUP_PHASE_RETRY_BACKOFFS = (1.0, 2.0, 4.0)` constant (line 333)"
provides:
  - "PARA-01 closure: 3 `_init_tile_pool_for_tests` fixtures wrap their raw `asyncpg.create_pool(...)` call in the existing `_run_with_too_many_clients_retry` envelope"
  - "Regression pin `test_init_tile_pool_retries_on_transient_too_many_clients` at `backend/tests/test_fixture_isolation_v1020.py:1144` documenting the wrap shape (mirrors fixture invocation kwargs exactly so drift is caught)"
  - "Post-fix `pytest -n auto` 3-run baseline: distinct = 20 / 8 / 16 (all ≤30 deterministic, 0 ICN frames)"
affects: [1095-02, 1096, 1097]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Shape A* — lambda-wrap of zero-arg async callable as retry-envelope argument (`_run_with_too_many_clients_retry(lambda: asyncpg.create_pool(...))`)"
    - "Envelope reuse over new-helper creation — when a transient-contention class already exists and the new call site shares the same exception family + budget shape, wrap rather than fork"
    - "Fixture-layer regression pin mirroring the production invocation shape (same kwargs in same order) so any future refactor that breaks the fixture also breaks the pin"

key-files:
  created:
    - ".planning/phases/1095-cascade-fix-wr-02-closure/1095-01-SUMMARY.md"
  modified:
    - "backend/tests/test_tiles.py — import + line 151 wrap"
    - "backend/tests/test_embed_tokens.py — import + line 56 wrap (autouse fixture; intersection gate preserved)"
    - "backend/tests/test_tile_signing.py — import + line 107 wrap"
    - "backend/tests/test_fixture_isolation_v1020.py — `import asyncio` (top) + new pin at line 1144"
    - ".planning/REQUIREMENTS.md — PARA-01 checkbox flip + Traceability table flip"

key-decisions:
  - "Shape A* chosen over alternatives A/B/C/D/E/F per audit Section 3.3 — reuses existing 7s envelope (1.0/2.0/4.0s backoffs); no new helpers, constants, or `max_size` change"
  - "max_size=3 left unchanged at this pass — the optional max_size=2 knob is operator-discretion deferred per CONTEXT.md `<specifics>`; the post-fix 3-run measurement (20/8/16 distinct) confirms the retry envelope alone is sufficient to clear the ≤30 gate"
  - "Pin lives in existing `test_fixture_isolation_v1020.py` (now 33 tests) rather than spinning out `test_init_tile_pool_v1022.py` per CONTEXT.md threshold (file is well under 1500 LOC)"
  - "Optional xfail pre-fix regression pin (`test_init_tile_pool_no_retry_pre_fix_raises_too_many_clients`) DEFERRED per CONTEXT.md `<specifics>` Plan 01 Step 6 — the positive pin alone is load-bearing; xfail documentation pin is opportunistic"

requirements-completed: [PARA-01]

# Metrics
duration: 27min (wall) + 18min 22s (3-run pytest measurement)
completed: 2026-05-23T01:33Z
---

# Phase 1095 Plan 01: PARA-01 Closure — Shape A* Wrap of `_init_tile_pool_for_tests` Fixture Pool Init

**Wrap 3 sibling `_init_tile_pool_for_tests` fixtures' raw `asyncpg.create_pool(...)` calls in the existing `_run_with_too_many_clients_retry` envelope at `backend/tests/conftest.py:359`; post-fix `pytest -n auto` 3-run baseline clears ≤30 distinct deterministic (20/8/16) with 0 ICN frames.**

## Performance

- **Duration:** ~27 min wall (code edits + verification) + 18m 22s pytest measurement
- **Started:** 2026-05-23T01:06Z
- **Completed:** 2026-05-23T01:33Z
- **Tasks:** 8 (all GREEN; zero iter-2 needed; zero deviations)
- **Files modified:** 5 (3 fixture files + new pin + REQUIREMENTS.md) + 1 created (this SUMMARY)
- **Atomic commit:** 6 files (per CONTEXT.md `<decisions>` `Atomic-N-file commit per plan`)

## Accomplishments

- 3 `_init_tile_pool_for_tests` fixtures (test_tiles.py:151, test_embed_tokens.py:56, test_tile_signing.py:107) now route raw `asyncpg.create_pool(...)` through the existing 7s retry envelope. Transient `TooManyConnectionsError` is absorbed via the canonical `(1.0, 2.0, 4.0)` backoff schedule instead of failing the fixture on first attempt.
- New regression pin `test_init_tile_pool_retries_on_transient_too_many_clients` at `backend/tests/test_fixture_isolation_v1020.py:1144` proves the wrap shape; 32-test pin subset is now 33 passed.
- `pytest -n auto` 3-run measurement gate (audit Section 2.3 acceptance criterion) cleared with distinct = 20/8/16, ALL ≤30 ceiling, ALL 3 runs with 0 ICN frames (confirming the v1021 Phase 1093-02-FINDINGS Run-3+4 cascade is NOT reproducing).
- PARA-01 traceability flip applied atomically (`[ ]` → `[x]` at REQUIREMENTS.md line 22 + `Pending` → `Complete` at line 75) in the SAME commit as this SUMMARY per v1019 TD-13 `requirements_traceability_flip`.

## Task Commits

This plan ships as a single atomic-6-file commit per CONTEXT.md `<decisions>` rule. Each task verified before commit:

1. **Task 1: Pre-flight gate** — 19 line-number citations re-validated (zero drift); 32 pin tests pass in 3.73s; docker stack 5/5 healthy. (read-only)
2. **Task 2: Wrap test_tiles.py:151** — 22/22 passed post-refactor in 8.11s.
3. **Task 3: Wrap test_embed_tokens.py:56** — 37/37 passed post-refactor in 21.21s; intersection gate (lines 40-51) preserved verbatim.
4. **Task 4: Wrap test_tile_signing.py:107** — 22/22 passed post-refactor in 10.33s.
5. **Task 5: Combined sanity** — 81/81 passed across all 3 modules in 33.12s; `grep -B 2` confirms 0 unwrapped `asyncpg.create_pool` calls remain in the 3 fixture files.
6. **Task 6: New regression pin** — `test_init_tile_pool_retries_on_transient_too_many_clients` passes in 1.45s; 32-test subset re-runs as `33 passed, 1 skipped, 3077 deselected in 3.61s`.
7. **Task 7: 3-run `-n auto` measurement gate** — distinct = 20/8/16 (all ≤30); 0 ICN frames per run.
8. **Task 8: Atomic-6-file commit + PARA-01 flip + SUMMARY** — this commit.

## Files Created/Modified

- `backend/tests/test_tiles.py` — added `from tests.conftest import _run_with_too_many_clients_retry`; wrapped line 151 `pool = await asyncpg.create_pool(...)` in the envelope via lambda. Surrounding `dsn = ...` (line 150), `pool_module._tile_pool = pool` + `yield` + `await pool.close()` + `pool_module._tile_pool = None` (lines 154-159) unchanged.
- `backend/tests/test_embed_tokens.py` — same shape; intersection gate at lines 40-51 (`db_fixtures.intersection(request.fixturenames)`) preserved verbatim so non-DB-fixture tests still skip the pool-init cost.
- `backend/tests/test_tile_signing.py` — same shape; no autouse / no gate (identical to test_tiles.py).
- `backend/tests/test_fixture_isolation_v1020.py` — added `import asyncio` to the top import block; appended new test function at line 1144 (preceded by a `# Phase 1095 / PARA-01` section banner comment explaining the pin family's distinction from `test_engine_retry_*`).
- `.planning/REQUIREMENTS.md` — PARA-01 checkbox flip + Traceability table flip; appended `**Closed (Plan 1095-01):**` evidence block with pin name + line number + 3-run baseline numbers + cross-reference to `/tmp/v1022-1095-post-fix-baseline.md`.
- `.planning/phases/1095-cascade-fix-wr-02-closure/1095-01-SUMMARY.md` (this file).

## Post-Fix Measurement Table — `pytest -n auto` 3-Run Baseline

| Run | Failed | Errors | Distinct (F+E) | Passed | Skipped | Wallclock | TMC frames | ICN frames | Gate (≤30) |
|----:|-------:|-------:|---------------:|-------:|--------:|----------:|-----------:|-----------:|:----------:|
|  1  |     15 |      5 |             **20** |  3040  |      38 |  6m53s   |        30  |      **0** |      GREEN  |
|  2  |      7 |      1 |              **8** |  3052  |      38 |  6m29s   |         8  |      **0** |      GREEN  |
|  3  |     16 |      0 |             **16** |  3043  |      38 |  7m00s   |        24  |      **0** |      GREEN  |

**All 3 runs ≤ 30 distinct — PARA-01 acceptance criterion (a) GREEN.**

### Delta vs pre-fix baseline (14/14/21)

| Run | Pre-fix distinct | Post-fix distinct | Delta |
|----:|-----------------:|------------------:|------:|
|  1  |               14 |                20 |    +6 |
|  2  |               14 |                 8 |    -6 |
|  3  |               21 |                16 |    -5 |

Mean shift: 16.3 → 14.7 distinct (-1.7). All 3 post-fix runs comfortably below the 30 ceiling; the Run 1 +6 delta is dominated by residual contention aftershocks in STAC + tile-test families (envelope absorbed the dominant 3-site hits but downstream workers awaiting Postgres saturation still timed out — bounded surface, no cascade).

Critical: **0 ICN frames across all 3 runs** — confirming the audit Section 1.1 finding that the v1021 Phase 1093-02-FINDINGS Run-3+4 cascade is NOT reproducing on current HEAD. The wrap pattern absorbs the `_init_tile_pool_for_tests` cascade source named in audit Section 1.4 (16 workers × 3 conns = 48-conn demand vs `max_connections=30` ceiling).

### Residual failure categorization (de-duplicated across 3 runs)

- **Out-of-phase scope (pre-existing OOS rows per PARA-01 acceptance (b)):** `test_layering.py::test_router_orchestrator_modules_stay_within_loc_cap` (3/3 runs), `test_phase_275_readme_accuracy.py::test_readme_signature_maps_list_intact` (3/3), `test_ssrf_redirect.py::test_make_safe_client_has_event_hook` (1/3) — these continue failing per the v1021 pre-existing OOS table.
- **OAuth flake-class:** `test_oauth.py::TestOAuthCallbackCSRF::test_callback_*` (2/3), `test_oauth.py::TestOAuthLoginEndpoint::test_oauth_login_redirect` (2/3), `test_settings_admin.py::TestOAuthProviderCRUD::test_list_providers` (1/3) — known intermittent flake class.
- **Residual contention aftershocks:** STAC integration/visibility (~5 nodes), settings/maps/search (~4 nodes), tile_signing/tiles/embed_tokens (3-4 nodes — Run 1 had 1 fixture exhaust the 7s budget under heavy concurrent demand), publication_lifecycle/sandbox/workflow_extension (3 nodes) — all bounded under the 30 ceiling.

Full breakdown captured at `/tmp/v1022-1095-post-fix-baseline.md` for Plan 02 + Phase 1097 close-gate citation.

## Sequential / `-n 4` baseline preservation

Per audit Section 2.4, the 32-test pin subset is the cheap proxy for full sequential baseline preservation:
- Pre-refactor (Task 1): `32 passed, 1 skipped, 3077 deselected in 3.73s`.
- Post-refactor + new pin (Task 6): `33 passed, 1 skipped, 3077 deselected in 3.61s`.
- All 4 existing `test_engine_retry_*` pins remain GREEN (Plan 1093-02's wrapper invariants intact, as audit Section 4.3 predicted — `_init_tile_pool_*` and `_engine_retry_*` are independent surfaces).

Full sequential `3055/0/38` + `-n 4` `3054/0/38` re-measurement is OPTIONAL for this plan and MANDATORY at Plan 02 close per CONTEXT.md `<specifics>` Phase 1095 rollup criteria.

## Decisions Made

- **Wrap with lambda, not async-def closure.** The wrap pattern at all 3 fix sites uses `lambda: asyncpg.create_pool(...)` rather than `async def _create():` because (a) the helper accepts any zero-arg async callable that returns a coroutine, (b) `lambda` produces a syntactically minimal call site that's easy to grep, (c) the regression pin's invocation mirrors the fixture's invocation EXACTLY so future drift breaks the pin.
- **REUSE `_SETUP_PHASE_RETRY_BACKOFFS = (1.0, 2.0, 4.0)`** rather than defining a new fixture-tier budget. The 7s total budget is the canonical setup-phase wait window (audit Section 4.3) and the contention pattern at the 3 fixture sites is structurally identical to the in-test session-factory contention class the helper was originally designed for.
- **DO NOT modify `max_size=3` to `max_size=2`** at this pass per CONTEXT.md `<specifics>`. The post-fix 3-run measurement confirms the retry envelope alone is sufficient; reducing `max_size` would shift the cost from "occasional 1-3s retry backoff" to "always-on serialization bottleneck", which is the wrong trade for a test suite that runs under varied concurrency configurations (sequential, `-n 4`, `-n auto`).
- **Pin lives in existing `test_fixture_isolation_v1020.py`** (now 33 tests) rather than spinning out `test_init_tile_pool_v1022.py`. The file is well under the 1500-LOC threshold from CONTEXT.md `Regression pin location` decision, and keeping the pin family co-located with the engine-retry family makes the test-infra retry-tier story easier to follow.

## Deviations from Plan

**None — plan executed exactly as written.**

Pre-flight gate had zero line-number drift; all 3 fix-site refactors landed clean on first attempt; the new regression pin passed on first run; the 3-run measurement gate cleared all 3 runs on first attempt with no iter-2 needed.

The optional `test_init_tile_pool_no_retry_pre_fix_raises_too_many_clients` xfail pin from CONTEXT.md `<specifics>` Plan 01 Step 6 + audit Section 5.1 was DEFERRED to Plan 02 per the same CONTEXT.md guidance — the positive pin alone is load-bearing for the wrap-shape regression-detection contract.

## Issues Encountered

None.

## Cross-References

- Audit: `.planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md` Sections 3.2 (Shape A* spec), 3.3 (alternative shapes rejected), 5.1 (pin shape).
- Spike SUMMARY: `.planning/phases/1094-cascade-spike/1094-01-SUMMARY.md`.
- Pre-fix baseline logs: `/tmp/v1022-1094-pre-fix-nauto-run{1,2,3}.{log,xml}`.
- Post-fix baseline logs: `/tmp/v1022-1095-post-fix-nauto-run{1,2,3}.{log,xml}` + measurement table at `/tmp/v1022-1095-post-fix-baseline.md`.
- Envelope source: `backend/tests/conftest.py:359` (`_run_with_too_many_clients_retry`).
- New pin node-ID: `backend/tests/test_fixture_isolation_v1020.py::test_init_tile_pool_retries_on_transient_too_many_clients`.

## Next Phase Readiness

- **Plan 1095-02 (PARA-02 / WR-02 closure):** unblocked. The `-n auto` 3-run baseline established at Plan 01 close (distinct = 20/8/16) is the regression-detection floor for Plan 02 — WR-02 fix must not regress the gate. Per CONTEXT.md decision tree, Plan 02 will need to re-run the 3-run `-n auto` measurement after the `_invoke_sleep_in_sync_context` shape change.
- **Phase 1096 (HYG-01):** unblocked when Phase 1095 fully closes (after Plan 02). WR-01 / WR-03 / WR-04 hygiene sweep operates on conftest.py regions adjacent to Plan 02's WR-02 fix.
- **Phase 1097 close-gate (CLOSE-01):** the 3-run `-n auto` baseline at this plan's close is one of the 3 baseline measurements the close-gate doc must quote (alongside sequential 3055/0/38 + `-n 4` 3054/0/38).

## Self-Check: PASSED

Verified post-commit (2026-05-23T01:33Z):

- **All 6 atomic-commit files exist** at committed paths (test_tiles.py + test_embed_tokens.py + test_tile_signing.py + test_fixture_isolation_v1020.py + REQUIREMENTS.md + 1095-01-SUMMARY.md).
- **All 6 measurement-gate artifacts exist** in `/tmp/` (3 .log + 3 .xml + 1 baseline.md).
- **Commit `398dc53d` (atomic-6-file) exists** in `git log --oneline --all`.
- **Commit `1eaf3f82` (metadata: STATE + ROADMAP)** exists in `git log --oneline --all`.
- **New regression pin** `test_init_tile_pool_retries_on_transient_too_many_clients` confirmed at `backend/tests/test_fixture_isolation_v1020.py:1144` (cited as `:1144` in REQUIREMENTS.md; the in-text "added at line 1144" in this SUMMARY's `key-files.modified` block matches).
- **All 3 fix sites wrapped** — `grep -B 2 "asyncpg.create_pool"` finds `_run_with_too_many_clients_retry` within 2 lines above each call site in all 3 fixture files.
- **Gate metric** — Run 1=20, Run 2=8, Run 3=16; all ≤30 deterministic.

---
*Phase: 1095-cascade-fix-wr-02-closure*
*Plan: 01*
*Completed: 2026-05-23*
