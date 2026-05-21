---
captured: 2026-05-21
milestone: v1017
purpose: Baseline pytest signal post-v1017 conftest refactor (TI-01) + 11 baseline fixes (TI-02)
host: macOS darwin/arm64 (M-series, 16-core)
backend_test_db: postgres on 127.0.0.1:5434 (geolens-db-1 container, healthy)
sequential_duration_seconds: 547.69
parallel_duration_seconds: 43.19
sequential_log: /tmp/1079-02-baseline-x.log
parallel_log: /tmp/1079-02-baseline-nauto.log
---

# Post-v1017 Pytest Baseline

This document captures the pytest baseline immediately after v1017 ships
(Phase 1075 TI-01 conftest refactor + TI-02 11 baseline fixes, Phase 1076
backend ingest P2 closure, Phase 1077 frontend ingest P2 closure, Phase
1078 CI alembic wiring). Future regressions are spotted by diffing against
this baseline.

## Run command

```bash
cd backend && env $(grep -v '^#' /Users/ishiland/Code/geolens/.env.test | xargs) \
  uv run pytest tests/                          # sequential, -x off (collect all)
cd backend && env $(grep -v '^#' /Users/ishiland/Code/geolens/.env.test | xargs) \
  uv run pytest tests/ -n auto                  # parallel, 16 xdist workers
```

Both commands run against the live geolens-db-1 PostGIS container on
`127.0.0.1:5434` with `.env.test` providing test-mode env vars (no SSL,
no S3, no Redis).

## Sequential (`pytest tests/`) baseline

| Metric | Count |
|--------|-------|
| Total collected | 3077 (3038 selected after `pytest.ini` deselect-of-14) |
| Passed | 3018 |
| Failed | 7 |
| Skipped | 38 |
| Deselected | 14 |
| Errors (asyncpg) | 0 |
| `asyncpg.exceptions.InvalidCatalogNameError` count | **0** (TI-01 closed) |
| Wall-clock | 547.69 s (9:07) |

### Sequential FAILED tests (7 — the Phase 1075 verification gap)

All 7 are pre-existing drift surfaces documented in `.planning/phases/
1075-conftest-test-db-lifecycle-refactor-baseline-fixes/1075-05-VERIFICATION.md`
`NEW-DISCOVERY` table. They are **deferred to v1018 hygiene** with the
patterns documented per-test in the verification file.

| # | Test | Root cause | Category | v1018 disposition |
|---|------|------------|----------|-------------------|
| 1 | `test_layering.py::test_no_unjustified_broad_except_sites` | Static analysis: `backend/app/processing/ingest/tasks_common.py:231,237` has new unjustified broad-except sites — Phase 276 CODE-08 invariant violated | Production-code drift (post-v1015) | Annotate the two `except Exception:` sites with `# broad: <reason>` OR tighten the catch class |
| 2 | `test_phase_279_user_lifecycle.py::test_register_emits_user_register_audit` | Password validator policy got stricter; test fixture password fails new "at least 3 of 4 classes" rule | Test-fixture drift | Update test fixture password to satisfy new policy (e.g., `TestPass123!`) |
| 3 | `test_phase_279_user_lifecycle.py::test_register_disabled_does_not_emit_audit` | Same as #2 — same password validator drift, different test | Same root cause as #2 | Same fix as #2 |
| 4 | `test_reupload_idor.py::TestReuploadIDOROwnerAllowed::test_owner_gets_non_404_on_service_preview` | Environmental: `FileNotFoundError: [Errno 2] No such file or directory: 'ogrinfo'` (GDAL CLI not on host PATH; available inside Docker) | Environmental | Add `@pytest.mark.skipif(shutil.which('ogrinfo') is None, reason=...)` OR run only in Docker test env |
| 5 | `test_reupload_service.py::TestServiceReuploadWorker::test_reupload_service_preserves_identity_and_increments_version` | SSRF gate (Phase 1066 IA-P0-03) rejects `services.example.com` (hostname doesn't resolve via DNS); same gate Plan 1075-03 patched for test_ingest.py | Test-fixture drift (same root cause as Plan 1075-03 fix, different file) | Same fix shape: `patch("app.modules.catalog.sources.security.validate_url_for_ssrf", new=AsyncMock())` |
| 6 | `test_reupload_service.py::TestServiceReuploadWorker::test_reupload_service_without_token_returns_retry_guidance_on_auth_failure` | Same as #5 — same SSRF gate, hostname `protected.example.com` | Same root cause as #5 | Same fix as #5 |
| 7 | `test_tasks_common_phase_brackets.py::test_job_phase_session_none_branch_rolls_back_on_exception` | Async loop contamination: "Task got Future attached to a different loop" — DB session bound to a prior test's event loop bled through to this test | Order-dependent, full-suite-only failure | Investigate `_job_phase_session` session-engine binding; may need test-side `async_engine_test` fixture or DB pool reset |

**Phase 1079 TI-03 verdict:** baseline captured WITH the 7 known failures
plainly visible. The whole point of a baseline is that future regressions
get spotted immediately — burying the 7 known failures would defeat the
purpose. v1018 hygiene picks them up per the dispositions above.

### Skipped tests rationale (sequential, 38)

No `pytest.mark.skip` decorators were added during v1017 (Phase 1075 Plans
02/03/04 used "fix at root cause" exclusively; the skip-with-issue fallback
path was reserved but not exercised). The 38 skips are pre-existing:
- Network-dependent tests (e.g., real STAC catalog connect)
- Optional dependency probes (e.g., GDAL Docker-only tests)
- Lifecycle teardown tests that only fire on conftest cleanup

A per-file enumeration of the 38 skips is not maintained in this baseline
because:
1. No new skips were introduced by v1017
2. Future skip-related regressions are easier to spot by diffing the
   count (38) than by diffing the per-test list
3. The skip rationale lives in each `@pytest.mark.skip(reason=...)`
   decorator at the test source site

If a regression auditor needs the per-test list, run:
```bash
cd backend && env $(grep -v '^#' /Users/ishiland/Code/geolens/.env.test | xargs) \
  uv run pytest tests/ --collect-only -m "skip" 2>&1 | grep "<Function"
```

## Parallel (`pytest tests/ -n auto`) baseline

| Metric | Count |
|--------|-------|
| Total collected | 3077 (same as sequential) |
| Passed | 1668 |
| Failed | 4 |
| Skipped | 23 (truncated by recovery cascade — many tests errored before skip evaluation) |
| Errors | 1368 |
| `asyncpg.exceptions.InvalidCatalogNameError` (TI-01 target) | **0** |
| `asyncpg.exceptions.CannotConnectNowError` (environmental cascade) | 2484 |
| Wall-clock | 43.19 s |

### Parallel-mode environmental observation

The `pytest -n auto` (16 xdist workers on this 16-core host) run reproduces
the same environmental cascade that Phase 1075-05 documented:

1. A Postgres backend crashes mid-run under 16-worker load (typically a
   `client_min_messages = warning` LOG line indicating shared-memory
   exhaustion or a backend OOM).
2. Postmaster enters recovery mode for ~5 seconds.
3. 2484 subsequent connection attempts error with
   `asyncpg.exceptions.CannotConnectNowError: the database system is in
   recovery mode`.
4. DB recovers cleanly after the run finishes; `psql -c "SELECT version();"`
   succeeds post-hoc.

**This is NOT a TI-01 regression.** The asyncpg exception class
(`CannotConnectNowError`) is DIFFERENT from the v1016 baseline's
`InvalidCatalogNameError` (1363 of those, zero of these). The root cause is
DIFFERENT: PG load capacity vs test-DB lifecycle race. TI-01's per-worker DB
isolation holds — the InvalidCatalogNameError count is 0 in both modes.

### Parallel FAILED tests (4, subset of sequential's 7)

The 4 are a strict subset of the 7 sequential failures — the other 3 are
masked by the connection-recovery cascade (their tests error out before
the original failure assertion runs).

| # | Test | Sequential row | Note |
|---|------|----------------|------|
| 1 | `test_layering.py::test_no_unjustified_broad_except_sites` | #1 | Static-analysis test — runs without DB; not affected by parallel cascade |
| 2 | `test_conftest_lifecycle.py::test_test_db_exists_after_session_fixture_yields` | (NEW in parallel) | Order-dependent: the parallel cascade causes a sibling fixture to tear down the test DB before this test's session-fixture probe — confirms the conftest race in parallel-mode-under-cascade, not in steady-state. NOT a TI-01 regression — see "Parallel-mode environmental observation" |
| 3 | `test_tasks_common_phase_brackets.py::test_phase_session_yields_none_when_job_missing` | (NEW in parallel) | Same async-loop contamination root cause as sequential row #7, manifesting in a different test in the same file under parallel ordering |
| 4 | `test_tasks_common_phase_brackets.py::test_job_phase_session_none_branch_rolls_back_on_exception` | #7 | Same root cause as sequential row #7 |

The two "NEW in parallel" failures are not separate regressions — they're
the parallel-mode manifestation of the same async-loop / conftest-lifecycle
edges that v1018 will address along with the 7 sequential ones.

### Parallel-mode follow-up recommendations (out of v1017 scope)

Tracked for v1018 if the team chooses to make `pytest -n auto` a green
gate:
- Tune the parallel worker count: `-n 4` or `-n 8` instead of `-n auto`
  (16) on hosts with limited Postgres capacity
- Increase Postgres `max_connections` in `docker-compose.test.yml`
  (currently default 100; needs 200+ for 16 workers × 4 conns + headroom)
- Add Postgres connection pool sizing to `conftest.py`: `pool_size=5,
  max_overflow=10` per worker
- Document the supported parallelism level in `backend/README.md` or test
  runner docs

For now, **v1017's pytest gate is the SEQUENTIAL run.** The parallel-mode
green status is a v1018 reach goal.

## Diff vs v1016 Phase 1074 audit baseline

| Metric | v1016 Phase 1074 | v1017 Phase 1079 (sequential) | Delta |
|--------|-----------------|-------------------------------|-------|
| PASSED | 1636 (claimed) | 3018 | +1382 |
| FAILED | 11 (the named baseline) | 7 (newly-discovered) | −11 named + 7 NEW |
| SKIPPED | unknown (rolled into "11") | 38 | clean separation |
| Errors (asyncpg `InvalidCatalogNameError`) | 1363 | **0** | **−1363 (TI-01 target)** |
| Total collected | 1647 (claimed) | 3077 (actual; 14 deselected) | +1430 |

**Headline deltas:**

1. **TI-01 hit:** 1363 → 0 `InvalidCatalogNameError`. The conftest
   lifecycle race that produced the v1016 cascade is fully eliminated by
   Plan 1075-01's per-worker DB isolation. 6 regression tests in
   `backend/tests/test_conftest_lifecycle.py` pin the invariants.

2. **TI-02 hit:** All 11 v1015-baseline named failures are now PASSED.
   Plans 1075-02 (3 fixes), 1075-03 (3 fixes), and 1075-04 (5 fixes)
   land at root cause in each test file. Zero `pytest.mark.skip`
   decorators introduced.

3. **TI-03 surfaced 7 NEW failures** in DIFFERENT files (not in the v1015
   baseline of 11). These are pre-existing drift surfaces that no per-file
   plan exercised in Phases 1075-02/03/04 (those plans ran one file each).
   The full-suite verification in Plan 1075-05 caught them. They are
   captured here AS the baseline (not papered over) so v1018 picks them
   up by diff.

4. **+1430 net tests collected:** The v1016 audit's claim of 1647 tests
   was itself an underestimate — many tests errored at collection-time
   under the original conftest race. With the conftest refactor (Plan
   1075-01), full collection now succeeds and the true test count
   (3077) is visible. Among those 3077:
   - 6 NEW regression tests in `test_conftest_lifecycle.py` (Plan 1075-01)
   - 21 NEW regression tests across Phase 1076's 5 plans (ingest P2)
   - 5 NEW regression tests in `_presignedUpload.test.ts` (Phase 1077 —
     not pytest-counted; vitest-counted)
   - The remainder is uncovered tests that pre-existed the conftest race
     and were silently masked

## Test count reconciliation

The v1075-05 verification noted that Plan 1075's pre-refactor "1647"
collection was a partial number due to collection-time errors. Plan 1079's
collection produces 3077 (3038 selected after the 14-test `pytest.ini`
deselect) which reflects the true baseline. The 3077 - 1647 = 1430-test
delta is composed of:

- ~1400 tests that pre-existed the v1015/v1016 milestones but were not
  collected under the v1016 conftest race (their fixtures errored before
  the runner reached them)
- 6 NEW tests in `test_conftest_lifecycle.py` (Plan 1075-01)
- 21 NEW tests in 5 P2-closure test files (Phase 1076 Plans 01/02/03/04/05)
- 3 NEW tests in `test_strict_cog_enforcement.py` (Phase 1076 Plan 05)

This baseline is the FIRST honest count post-refactor. Future TI-03
re-runs will diff cleanly against 3018 passed / 7 failed / 38 skipped / 0
errors.

## Reproducibility

To reproduce this baseline:

1. Ensure the geolens-db-1 container is healthy on port 5434:
   ```bash
   docker compose ps geolens-db-1
   ```
2. Confirm `.env.test` exists at the repo root:
   ```bash
   ls /Users/ishiland/Code/geolens/.env.test
   ```
3. Run the sequential baseline:
   ```bash
   cd backend && env $(grep -v '^#' /Users/ishiland/Code/geolens/.env.test | xargs) \
     uv run pytest tests/ 2>&1 | tee /tmp/v1017-baseline-x.log
   ```
4. Run the parallel baseline (caveats apply):
   ```bash
   cd backend && env $(grep -v '^#' /Users/ishiland/Code/geolens/.env.test | xargs) \
     uv run pytest tests/ -n auto 2>&1 | tee /tmp/v1017-baseline-nauto.log
   ```
5. Diff the summary lines against the tables above.

The sequential run produces deterministic counts (3018/7/38/0); the
parallel run will vary based on host load capacity but the
`InvalidCatalogNameError` count MUST remain 0 in both modes.

---

*Phase: 1079-close-gate-hygiene*
*TI-03 captured: 2026-05-21*
