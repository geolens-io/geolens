---
captured: 2026-05-21
milestone: v1018
purpose: Baseline pytest signal post-v1018 TD-01..07 closures (all 7 New-Discovery failures from Plan 1075-05 fixed)
host: macOS darwin/arm64 (M-series, 16-core)
backend_test_db: postgres on 127.0.0.1:5434 (geolens-db-1 container, healthy)
sequential_duration_seconds: 539.01
sequential_log: /tmp/v1018-baseline-x.log
---

# Post-v1018 Pytest Baseline

This document captures the pytest baseline immediately after v1018 ships
(Phase 1080 TD-01 + TD-07, Phase 1081 TD-02 + TD-03 + TD-05 + TD-06,
Phase 1082 TD-04, Phase 1083 TD-08 close gate). All 7 failures that were
visible in the v1017 baseline are now PASSED. Future regressions are spotted
by diffing against this baseline.

## Run command

```bash
cd backend && env $(grep -v '^#' /Users/ishiland/Code/geolens/.env.test | xargs) \
  uv run pytest tests/ 2>&1 | tee /tmp/v1018-baseline-x.log
```

Both commands run against the live geolens-db-1 PostGIS container on
`127.0.0.1:5434` with `.env.test` providing test-mode env vars (no SSL,
no S3, no Redis).

## Sequential (`pytest tests/`) baseline

| Metric | Count |
|--------|-------|
| Total collected | 3076 (3062 selected after `pytest.ini` deselect-of-14 + 1 collection-time skip) |
| Passed | 3025 |
| Failed | **0** |
| Skipped | 38 |
| Deselected | 14 |
| Errors (asyncpg) | 0 |
| `asyncpg.exceptions.InvalidCatalogNameError` count | **0** (TI-01 closed, invariant holds) |
| Wall-clock | 539.01 s (8:59) |

### TD-01..07 attributable failures: **0**

**Full close-gate green.** All 7 failures from the v1017 baseline have been
resolved by the v1018 hygiene phases. No `pytest.mark.skip` decorators were
added to make any gate pass.

### Named TD invocations (7 + companion tests — run together, exit 0)

The following invocation confirms all 7 TD-targeted tests pass in a single
sequential run (16 collected, 16 passed, exit 0):

```bash
cd backend && env $(grep -v '^#' /Users/ishiland/Code/geolens/.env.test | xargs) \
  uv run pytest \
    tests/test_layering.py::test_no_unjustified_broad_except_sites \
    tests/test_phase_279_user_lifecycle.py::test_register_emits_user_register_audit \
    tests/test_phase_279_user_lifecycle.py::test_register_disabled_does_not_emit_audit \
    tests/test_reupload_service.py::TestServiceReuploadWorker::test_reupload_service_preserves_identity_and_increments_version \
    tests/test_reupload_service.py::TestServiceReuploadWorker::test_reupload_service_without_token_returns_retry_guidance_on_auth_failure \
    tests/test_tasks_common_phase_brackets.py::test_job_phase_session_none_branch_rolls_back_on_exception \
    tests/test_reupload_idor.py::TestReuploadIDOROwnerAllowed::test_owner_gets_non_404_on_service_preview \
    tests/test_config.py::TestDatabaseConnectArgs tests/test_config.py::TestExternalPooler \
    -x
# Result: 16 passed in 5.24s — exit 0
```

### NEW-DISCOVERY table

| # | Test / Finding | Root cause | Category | Disposition |
|---|---------------|------------|----------|-------------|
| 0 | — | — | — | **0 unexpected failures — full close-gate green** |

No new failures surfaced. Zero items to escalate to v1019.

### REQUIREMENTS.md test-name reconciliation

| Item | REQUIREMENTS.md name | Actual test name | Status |
|------|---------------------|-----------------|--------|
| TD-02 | `test_register_password_too_short` | `test_register_emits_user_register_audit` | Name drift — docs stale |
| TD-03 | `test_register_password_diversity` | `test_register_disabled_does_not_emit_audit` | Name drift — docs stale |

**Finding:** REQUIREMENTS.md TD-02 and TD-03 names (`test_register_password_too_short`,
`test_register_password_diversity`) do not exist in the codebase —
`grep -rln "test_register_password_too_short\|test_register_password_diversity" backend/`
returns zero hits. The actual failing-then-fixed tests are
`test_register_emits_user_register_audit` and
`test_register_disabled_does_not_emit_audit`
(confirmed in Phase 1081-01 SUMMARY at "Path Correction Surfaced").

**No functional impact** — the same SEC-S16 password fixture fix applied to
both actual tests. The password literals in `test_phase_279_user_lifecycle.py`
were updated from `"securepass123"` (2 classes, fails 3-of-4 rule) to
`"TestPass1234!"` (4 classes, passes). Only the REQUIREMENTS.md test-name
documentation was stale; the spirit of TD-02/TD-03 ("align password tests to
SEC-S16") is fully satisfied. Reconciliation note logged here per
1083-CONTEXT.md decision.

## Skipped tests rationale (sequential, 38)

No `pytest.mark.skip` decorators were added during v1018 (Phases 1080-1083
used "fix at root cause" exclusively; the skip-with-issue fallback path was
reserved but not exercised). The 38 skips are pre-existing:
- Network-dependent tests (e.g., real STAC catalog connect)
- Optional dependency probes (e.g., GDAL Docker-only tests)
- Lifecycle teardown tests that only fire on conftest cleanup
- SAML overlay tests requiring enterprise edition overlay

A per-file enumeration of the 38 skips is not maintained in this baseline
because:
1. No new skips were introduced by v1018
2. Future skip-related regressions are easier to spot by diffing the
   count (38) than by diffing the per-test list
3. The skip rationale lives in each `@pytest.mark.skip(reason=...)` decorator
   at the test source site

If a regression auditor needs the per-test list, run:
```bash
cd backend && env $(grep -v '^#' /Users/ishiland/Code/geolens/.env.test | xargs) \
  uv run pytest tests/ --collect-only -m "skip" 2>&1 | grep "<Function"
```

## Diff vs v1017 baseline (PYTEST-BASELINE-2026-05-21.md)

| Metric | v1017 Phase 1079 (sequential) | v1018 Phase 1083 (sequential) | Delta |
|--------|-------------------------------|-------------------------------|-------|
| Total collected | 3077 (3038 selected) | 3076 (3062 selected) | −1 collected; +24 selected (deselect-14 unchanged; 1 collection-skip now excluded from selected) |
| Passed | 3018 | **3025** | **+7** (the 7 TD-01..07 fixes) |
| Failed | 7 (the v1017 NEW-DISCOVERY table) | **0** | **−7** (all TD-01..07 fixed) |
| Skipped | 38 | 38 | 0 |
| Errors (asyncpg `InvalidCatalogNameError`) | 0 | **0** | 0 (TI-01 invariant holds) |
| Wall-clock | 547.69 s | 539.01 s | −8.68 s (fewer failures = less traceback output) |

### Headline deltas

1. **TD-01..07 cleared: 7 → 0 failures.** All 7 NEW-DISCOVERY items from the
   v1017 Phase 1079 baseline are now PASSED. Zero `pytest.mark.skip` decorators
   added — all fixed at root cause per the v1017 Phase 1075-05 protocol.

2. **TI-01 invariant holds:** `asyncpg.exceptions.InvalidCatalogNameError` count
   is 0 in v1018 sequential mode, same as v1017. No conftest lifecycle regression.

3. **WR-01 inline bonus (Phase 1080 code review):** `tasks_common.py:1030`
   broad-except justification added + `test_layering.py` macOS `\s` portability
   fix — both outside the original 8-TD scope but landed in v1018 as inline
   fixes during code review.

4. **WR-02 inline bonus (Phase 1080 code review):** `test_verify_full_returns_ssl_context_with_verify`
   now actually calls `database_connect_args` on a verify-full settings object —
   a pre-existing defect in TD-07-touched code, fixed inline during code review.

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
     uv run pytest tests/ 2>&1 | tee /tmp/v1018-baseline-x.log
   ```
4. Verify summary line:
   ```
   === 3025 passed, 38 skipped, 14 deselected, 18 warnings in 539.01s ===
   ```
5. Diff the summary lines against the tables above.

The sequential run produces deterministic counts (3025/0/38/0); future regressions
are spotted immediately by diffing against this baseline.

---

*Phase: 1083-close-gate*
*TD-08 captured: 2026-05-21*
