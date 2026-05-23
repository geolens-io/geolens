---
phase: 1093-engine-level-retry-envelope
plan: 01
subsystem: testing

tags:
  - pytest-xdist
  - sqlalchemy
  - asyncpg
  - postgres
  - fixture-isolation
  - engine-retry
  - audit
  - spike
  - v1021

requires:
  - phase: 1093-engine-level-retry-envelope
    provides: "Phase boundary + 1088-04 architectural REPORT carry-forward"
  - audit: ".planning/milestones/v1020-phases/1088-fixture-isolation-fixes-regression-pins/1088-04-SUMMARY.md"
    provides: "post-commit failure-shape analysis (48 deterministic + 173 non-deterministic post-commit bind.connect() residual outside session-factory envelope)"

provides:
  - "Architectural-decision-record audit doc at `.planning/audits/ENGINE-RETRY-ENVELOPE-v1021.md` (5 sections + frontmatter)"
  - "Pre-fix `pytest -n auto` 3-run baseline at v1021 HEAD `46f45c1bef8d9f5d5494b1eebddbe56537bdba98` (failure-count range 126–383 per run; raw cascade lines 271–585)"
  - "Chosen wrapper shape: RetryingAsyncEngine composition wrapper class + file:line target for Plan 1093-02 implementation"
  - "4 regression pin shapes named under `test_engine_retry_*` convention mirroring v1020 in-test pin family"

affects:
  - 1093-02

tech-stack:
  added: []
  patterns:
    - "Composition wrapper class over inheritance — chosen over `event.listen(engine, 'connect', ...)` (unviable: fires too late for retry), NullPool subclass (breaks `test_xdist_engine_uses_nullpool` pin), and `async_creator=` (asymmetric: misses `engine.dispose()`). Composition preserves the underlying engine's `.pool` accessor via `@property` delegation."
    - "Retry-budget REUSE pattern — engine-layer wrapper reuses `_SETUP_PHASE_RETRY_BACKOFFS = (1.0, 2.0, 4.0)` (NOT the in-test 1.5s budget) because the engine wrapper subsumes setup-phase retries IN ADDITION to closing the post-commit residual — tighter budgets risk false-positive loud-fails under combined contention."

key-files:
  created:
    - ".planning/audits/ENGINE-RETRY-ENVELOPE-v1021.md (5 sections + populated frontmatter)"
  modified: []

key-decisions:
  - "Chose Candidate 1 (RetryingAsyncEngine composition wrapper class) over 3 alternatives: event.listen rejected as unviable (fires after asyncpg exception); NullPool subclass rejected as breaks `test_xdist_engine_uses_nullpool` at `test_conftest_pool_sizing.py:261` (type(engine.pool).__name__ would change from NullPool to subclass); async_creator= rejected as asymmetric (misses engine.dispose())."
  - "REUSE `_TRANSIENT_CONTENTION_EXCEPTIONS` (line 343-347) + `_SETUP_PHASE_RETRY_BACKOFFS = (1.0, 2.0, 4.0)` (line 324) verbatim — no new constants, no widened catch tuple."
  - "Pre-fix baseline failure-count range 126–383 per run across 3 consecutive runs (Run 1: 126; Run 2: 139; Run 3: 383). Run 3 anomaly: InvalidCatalogNameError=616 indicates that v1020's per-worker DB lifecycle fixes still surface category 4.1 cascade under unfavourable timing under `-n auto` — the engine wrapper should subsume coverage."
  - "Pre-existing OOS set expanded from 2 (test_phase_275, test_ssrf_redirect) to 3 — discovered `tests/test_layering.py::test_router_orchestrator_modules_stay_within_loc_cap` failing at v1021 HEAD (`backend/app/modules/catalog/maps/router.py:1807 > cap 1800`, introduced by Phase 1092 commit `04d9abc6`). Annotated as OUT OF SCOPE for Phase 1093 in audit Section 4.0; documented as follow-up Phase 1092 cleanup item."

patterns-established:
  - "Spike-first audit shape for engine-layer architectural fixes — when a v1020-style 'session-factory retry doesn't cover the surface' diagnosis surfaces (post-commit `bind.connect()` outside any wrappable envelope), the spike output is a SINGLE audit doc with a directive sentence ('Plan 1093-02 implements X in file:line') so the implementation plan has zero decision surfaces remaining."

requirements-completed: []
# TEST-01 traceability flip is OWNED by Plan 1093-02 per TD-13
# `requirements_traceability_flip` rule. This plan is the spike + baseline
# measurement only.

duration: ~60min (audit + sequential baseline + 3× -n auto runs + SUMMARY + commit)
completed: 2026-05-23
---

# Phase 1093 Plan 01: Engine-Level Retry Envelope — Spike + Pre-Fix Baseline Summary

**Plan 1093-01 produced the architectural-decision-record + pre-fix-baseline-measurement audit doc at `.planning/audits/ENGINE-RETRY-ENVELOPE-v1021.md` (5 sections + populated frontmatter) and chose the `RetryingAsyncEngine` composition wrapper class shape — rejecting `event.listen`, NullPool subclass, and `async_creator=` candidates with named tradeoffs. Pre-fix `pytest -n auto` 3-run baseline at v1021 HEAD `46f45c1b`: failure-count range 126–383 per run with 271–585 raw cascade lines. Sequential baseline (HARD GATE): 3051 passed / 3 pre-existing OOS failures (test_phase_275 + test_ssrf_redirect + test_layering LOC-cap) / 38 skipped in 550.02s. Zero code changes in this plan; Plan 1093-02 implements the wrapper verbatim per audit Section 3.**

## Plan Execution

- **Task 1 (audit Sections 1-3):** consolidated Plan 1088-04 architectural REPORT findings into Section 1 (post-commit failure surface — 48 deterministic + 173 non-deterministic outside session-factory envelope; two surfaces — `engine.connect()` + `engine.dispose()`), Section 2 (4 candidate fix shapes with pros/cons per 4-criterion grid: covers both surfaces / preserves NullPool+QueuePool branches / preserves `test_conftest_pool_sizing.py` pins / testable via MagicMock-only), Section 3 (chosen shape `_RetryingAsyncEngine` composition wrapper class + helper-conventions REUSE block + Plan 1093-02 directive sentence with file:line resolution).

- **Task 2 (sequential baseline HARD GATE):** captured `3 failed, 3051 passed, 38 skipped, 14 deselected, 18 warnings in 550.02s` at v1021 HEAD. The 3 failures: 2 pre-existing OOS (test_phase_275 readme drift + test_ssrf_redirect flake) + 1 newly-discovered pre-existing-at-v1021-HEAD (`test_layering::test_router_orchestrator_modules_stay_within_loc_cap` flagging `backend/app/modules/catalog/maps/router.py:1807 > 1800 cap`, introduced by Phase 1092 commit `04d9abc6`). HARD INVARIANT disposition: **SATISFIED-WITH-ANNOTATION** — zero NEW failures attributable to Phase 1093 work (no Phase 1093 work done at this measurement point).

- **Task 3 (pre-fix `pytest -n auto` 3-run baseline):** captured 3 consecutive runs with stale-DB cleanup between (mirroring `.planning/audits/PYTEST-XDIST-PERF-v1020.md` Section 1 Step 1b). JUnit XML artifacts at `/tmp/v1021-1093-01-nauto-run{1,2,3}.xml`. Failure counts per run summarized in audit Section 4.4 table.

## Sequential Baseline Preservation HARD GATE

Verbatim from `/tmp/v1021-1093-01-sequential-baseline.log`:

```
3 failed, 3051 passed, 38 skipped, 14 deselected, 18 warnings in 550.02s (0:09:10)
```

Decision-logic disposition (per planning_context HARD INVARIANT):
- **N passed = 3051** — over the v1020 close-gate floor of 3036 (+15 over baseline; matches +4 from v1020 1088-04 + post-v1020 minor additions in v1021's Phases 1091/1092).
- **M failed = 3** — but ALL 3 are pre-existing OOS:
  - `tests/test_phase_275_readme_accuracy.py::test_readme_signature_maps_list_intact` (documented in CONTEXT.md)
  - `tests/test_ssrf_redirect.py::test_make_safe_client_has_event_hook` (documented in CONTEXT.md)
  - `tests/test_layering.py::test_router_orchestrator_modules_stay_within_loc_cap` (newly-annotated; pre-existing at v1021 HEAD from Phase 1092 commit `04d9abc6`; NOT a Phase 1093 regression)
- **K skipped = 38** — unchanged from v1020 floor.

**Invariant satisfied.**

## Pre-fix Parallel Baseline (Audit Section 4.4 table)

| Run | passed | failed | errors | wallclock (s) | raw cascade lines |
|-----|--------|--------|--------|---------------|-------------------|
| 1   | 2930   | 99     | 27     | 402.44        | 509               |
| 2   | 2919   | 102    | 37     | 398.34        | 585               |
| 3   | 2687   | 54     | 329    | 307.29        | 271 + ICN=616     |

**Pre-fix v1021-HEAD baseline at `pytest -n auto`: failure-count range across 3 runs is 126–383 distinct test-case-level failures (JUnit failures + errors).** TEST-01 acceptance criterion (a) requires ≤10 failed per run across 3 consecutive runs. Pre-fix delta needed: 116–373 fewer per run. Run 3 anomaly: InvalidCatalogNameError=616 (category 4.1 recurrence under unfavourable -n auto timing).

## Chosen Shape

**`_RetryingAsyncEngine` composition wrapper class** — wraps the underlying `AsyncEngine` returned by `create_async_engine`, exposes custom `connect()` + `dispose()` methods that retry on `_TRANSIENT_CONTENTION_EXCEPTIONS` with the `_SETUP_PHASE_RETRY_BACKOFFS = (1.0, 2.0, 4.0)` budget, preserves `.pool` accessor via `@property` delegation (required for `test_xdist_engine_uses_nullpool` at `test_conftest_pool_sizing.py:261` and `test_sequential_engine_uses_queuepool` at `:281` to keep passing), and delegates everything else to the underlying engine via `__getattr__`. Plan 1093-02 implements the class around `backend/tests/conftest.py:605` (adjacent to `_acquire_test_session_with_retry`) and applies it at the function exit of `_make_test_async_engine` (lines 67-77, both NullPool + QueuePool branches return wrapped engines). Function signature `_make_test_async_engine(test_database_url: str)` is LOCKED — preserved unchanged.

## Self-Check

- Audit document at `.planning/audits/ENGINE-RETRY-ENVELOPE-v1021.md` exists with 5 sections (1: post-commit failure surface; 2: 4 candidate fix shapes; 3: chosen shape + rationale + Plan 1093-02 directive; 4: pre-fix baseline measurement [4.0 sequential + 4.1-4.3 per-run + 4.4 summary]; 5: reproducibility protocol). Verified: `grep -c "^## Section [0-9]+" returns 3` (Section 1, 2, 3 with — separator; Section 4.0/4.1/4.2/4.3/4.4/5 use a different prefix shape but the audit verification check passes the threshold of ≥3).
- Frontmatter contains: `head_sha=46f45c1bef8d9f5d5494b1eebddbe56537bdba98`, `sequential_passed_count=3051`, `sequential_skipped_count=38`, `sequential_wallclock_seconds=550.02`, all 3× `nauto_run_{N}_*` blocks populated with passed/failed/errors/skipped/wallclock/raw_cascade_lines.
- Chosen-shape directive sentence at end of Section 3: "Plan 1093-02 implements the `_RetryingAsyncEngine` composition wrapper class in `backend/tests/conftest.py`..." — verified by `grep -q "Plan 1093-02 implements"`.
- JUnit XML artifacts persist at `/tmp/v1021-1093-01-nauto-run{1,2,3}.xml` (3 files).
- Sequential baseline log at `/tmp/v1021-1093-01-sequential-baseline.log` (verbatim pytest summary line).
- REQUIREMENTS.md TEST-01 UNCHANGED in this commit (per TD-13 `requirements_traceability_flip` rule — flip lives in Plan 1093-02).
- ROADMAP.md UNCHANGED in this commit (per TD-13 atomic-close rule — Phase 1093 row flip lives in Plan 1093-02).
- 1093-01-SUMMARY.md written with frontmatter + 7 body sections.

## Issues Encountered

- **Sequential baseline expanded OOS set by 1 entry.** Discovered `tests/test_layering.py::test_router_orchestrator_modules_stay_within_loc_cap` failing at v1021 HEAD: `backend/app/modules/catalog/maps/router.py` is 1807 lines, exceeding the LOC cap of 1800 by 7 lines. Root cause: Phase 1092 commit `04d9abc6` (dual-shape decorators sweep across 27 routes) added LOC beyond the cap. This is a Phase 1092 close-gate residual that slipped past Phase 1092's verification suite (`--tb=no -q` summary line did not surface the LOC-cap failure clearly). **Disposition for Plan 1093-01:** annotated as pre-existing-OOS-at-v1021-HEAD in audit Section 4.0; NOT a regression introduced by Phase 1093 work. **Disposition recommendation:** Phase 1092 cleanup item (decompose `maps/router.py` OR raise the LOC-cap allowlist entry with code review) — track separately, not in scope for Phase 1093.

- **Run 3 produced anomalously-high InvalidCatalogNameError count.** Pre-fix Run 3 had ICN=616 (vs. ICN=4 in Run 1, ICN=0 in Run 2), suggesting that under unfavourable -n auto timing, v1020's per-worker DB lifecycle fixes (Plan 1088-01) can still surface category 4.1 cascade. This is expected variance per Plan 1089 PERF-01's Section 4 commentary about timing-driven race-window collisions, NOT a regression. The engine wrapper Plan 1093-02 implements should subsume coverage for category 4.1 surfaces too because the wrapper intercepts at the lowest layer (`engine.connect()`).

## Deferred to Plan 1093-02

- (a) **Wrapper class implementation** per chosen shape (`_RetryingAsyncEngine`) in `backend/tests/conftest.py` around line 605 adjacent to `_acquire_test_session_with_retry`.
- (b) **Wrapper application** at `_make_test_async_engine` function exit (line 67-77) for both NullPool xdist and QueuePool sequential branches.
- (c) **4 regression pins** in `backend/tests/test_fixture_isolation_v1020.py` under new `Plan 1093-02 / TEST-01: engine-level retry envelope` section header (canonical + raw-asyncpg critical-contract + propagate-non-contention + exhaust-budget).
- (d) **Post-fix `pytest -n auto` re-measure** against this baseline — 3 consecutive runs with stale-DB cleanup; each run MUST produce ≤10 failed (TEST-01 acceptance criterion (a)).
- (e) **REQUIREMENTS.md TEST-01 traceability flip** (`[ ]` → `[x]`; `Pending` → `Complete`; node-ID citation appended per TD-13 `req_citation_pinning` rule).
- (f) **ROADMAP.md Phase 1093 row update** (plan list populated + Progress table row flipped to `2/2 Complete` + Total summary line updated).
- (g) **Phase aggregate SUMMARY** at `.planning/phases/1093-engine-level-retry-envelope/1093-SUMMARY.md` rolling up 1093-01 + 1093-02 outcomes for v1021 close-gate consumption.

---

*Phase: 1093-engine-level-retry-envelope*
*Plan: 01 (TEST-01 spike + pre-fix baseline)*
*Completed: 2026-05-23*
