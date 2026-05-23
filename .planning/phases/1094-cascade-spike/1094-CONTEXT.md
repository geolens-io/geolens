# Phase 1094: Cascade Spike - Context

**Gathered:** 2026-05-23
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Architectural audit produces `.planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md` identifying the exact race surface in `_test_db_lifecycle:~661-674` and naming the chosen fix shape with line numbers BEFORE any code-fix lands. Also addresses whether WR-02 closure is a prerequisite for PARA-01's ≤30 threshold (the cascade-pressure hypothesis must be validated or ruled out, satisfying PARA-02 acceptance criterion (d) early).

**This is a spike phase — no production-code or test-code changes ship from this phase.** The deliverable is an audit document. The fix lands in Phase 1095. Per v1019 Phase 1085 / v1020 Phase 1087 / v1021 Phase 1091 precedent: measurement before fix for architectural items.

### Requirements satisfied at this phase

- **PARA-01 acceptance criterion (e) only** — the spike deliverable. Full PARA-01 closure (acceptance criteria a/b/c/d) happens at Phase 1095. The REQUIREMENTS.md `[x]` flip does NOT land at Phase 1094 close.
- **PARA-02 acceptance criterion (d) — partial** — Phase 1094 must address whether WR-02 closure is a prerequisite for PARA-01's threshold. Full PARA-02 closure also lands at Phase 1095.

### Out-of-scope reaffirmations

- No code changes to `backend/tests/conftest.py` from this phase.
- No CI/Makefile changes.
- No new pytest fixtures or test files.
- The audit doc MUST cite line numbers + function signatures verbatim — paraphrase will not satisfy planner's REQ citation pinning rule (v1019 TD-13).
</domain>

<decisions>
## Implementation Decisions

### Audit document location

`.planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md` per REQUIREMENTS.md PARA-01 acceptance criterion (e). Follow the same shape as `.planning/audits/INGEST-QUICKLOOK-ASYNC-CONTEXT-v1021.md` (the v1021 spike-first precedent) and `.planning/audits/PYTEST-XDIST-PERF-v1020.md`.

### Audit document structure

5 sections per REQUIREMENTS.md ROADMAP phase 1094 success criterion 1:
1. **Root-cause hypothesis enumeration** — list candidate hypotheses (H1, H2, ...) from `.planning/milestones/v1021-phases/1093-engine-level-retry-envelope/1093-02-FINDINGS.md`. Most-likely from the findings doc: H1 = `_test_db_lifecycle:~661-674` lacks retry coverage at `dev_engine.connect()` path; H2 = engine wrapper INCREASES pressure on per-worker DB CREATE/migrate by allowing more tests to enter warm-up SELECT 1 (Plan 1089 PERF-01 Section 4 "timing-driven race-window collisions"). New hypotheses welcome.
2. **Reproduction recipe** — exact `cd backend && uv run pytest -n auto tests/` invocation with stale-DB cleanup recipe (mirror PYTEST-XDIST-PERF-v1020.md Section 1 Step 1b).
3. **Line-numbered fix-shape proposal** — chosen fix shape with exact `backend/tests/conftest.py` line numbers + ≥2 alternatives rejected with rationale. Acceptance: planner can `git grep -n "def <function_name>" backend/tests/conftest.py` to confirm line numbers before plans commit (v1019 TD-13 REQ citation pinning).
4. **WR-02 prerequisite analysis** — silent deferral not acceptable per REQUIREMENTS.md PARA-02 (d). Must validate or rule out the cascade-pressure hypothesis (WR-02's blocking `time.sleep` starves asyncio loop, prolonging connection saturation on per-worker DB lifecycle).
5. **Regression-pin shape proposal** — propose pin shape for the per-worker DB lifecycle retry per PARA-01 (d). Naming convention follows existing pins in `backend/tests/test_fixture_isolation_v1020.py`.

### Reproduction must be live

Spike must run pre-fix `pytest -n auto` 3-run baseline against the live docker stack with stale-DB cleanup between runs. Recipe documented verbatim in the audit doc per Phase 1094 success criterion 2. Use the same procedure as PYTEST-XDIST-PERF-v1020.md Section 1.

### Sequential baseline preservation HARD GATE

Spike is audit-only; no code changes. Sequential pytest baseline `3055 passed / 0 NEW failed / 38 skipped` MUST remain green at audit-doc commit time (no incidental changes to non-audit files). Phase 1094 success criterion 5.

### Playwright MCP usage

Not applicable to this phase — Phase 1094 is a backend-test-infra spike. Playwright MCP is reserved for frontend-touching phases (Phase 1097's close-gate may use it for live docker stack health spot-check per CLOSE-01 (d)).
</decisions>

<code_context>
## Existing Code Insights

Key files the spike will read (no edits):

- `backend/tests/conftest.py` — particularly `_test_db_lifecycle` (~661-674), `_install_dbapi_connect_retry` (~664), `_invoke_sleep_in_sync_context` (~615), `_RetryingAsyncEngine` (~711), `_TRANSIENT_CONTENTION_EXCEPTIONS` (line 352), `_SETUP_PHASE_RETRY_BACKOFFS = (1.0, 2.0, 4.0)` (line 333). Exact line numbers may shift; spike must `git grep -n` to confirm at audit time.
- `backend/tests/test_fixture_isolation_v1020.py` — existing 4 `test_engine_retry_*` pins + 11 v1020 fixture pins. Naming convention reference for new PARA-01 pin proposal.
- `.planning/milestones/v1021-phases/1093-engine-level-retry-envelope/1093-02-FINDINGS.md` — the authoritative findings doc with pre-fix vs post-fix delta table + Run 3+4 cascade diagnostic. Spike's hypothesis enumeration starts here.
- `.planning/audits/PYTEST-XDIST-PERF-v1020.md` — Section 1 reproduction recipe + Section 2 oauth flake-class table + Section 4 timing-driven race-window collisions hypothesis.
- `.planning/audits/INGEST-QUICKLOOK-ASYNC-CONTEXT-v1021.md` — v1021 spike-first format reference (Section 3 fix-shape naming, line-number specificity).
- `Makefile:30` + `.github/workflows/ci.yml:493-595` — referenced by REQUIREMENTS.md PARA-01 (c)/(d) for `-n 4` CI default preservation. Not edited by spike.

### Why the v1021 fix didn't close Category 4.1

The `_RetryingAsyncEngine` wrapper closes Category 4.3 (in-test post-commit `bind.connect()` contention) — the v1021 -91% reduction on Runs 1+2 confirms this architecture. Category 4.1 (per-worker DB CREATE/migrate race) fires BEFORE any test enters the engine wrapper's scope — the wrapper's `do_connect` event handler hasn't been installed on the per-worker dev_engine at the point of failure. This is the architectural escalation v1021 explicitly scoped OUT and the spike must confirm.
</code_context>

<specifics>
## Specific Ideas

### Spike workflow

1. **Read findings + baseline docs** — `.planning/milestones/v1021-phases/1093-engine-level-retry-envelope/1093-02-FINDINGS.md`, `.planning/audits/PYTEST-XDIST-PERF-v1020.md`, `backend/tests/conftest.py:~615-720`.
2. **Reproduce pre-fix baseline** — run `cd backend && uv run pytest -n auto tests/` 3 times with stale-DB cleanup. Capture log + xml output to `/tmp/v1022-1094-pre-fix-nauto-run{1,2,3}.{log,xml}`.
3. **Diagnose cascade source** — analyze raw `InvalidCatalogNameError` traceback to confirm Category 4.1 surface (per-worker DB CREATE/migrate path, not in-test contention path).
4. **WR-02 prerequisite test** — design a small isolated test that measures whether `_invoke_sleep_in_sync_context` blocking sleep contributes to cascade timing. Document findings (validates or rules out).
5. **Propose fix shape** — pick one of: (a) retry coverage at `dev_engine.connect()` inside `_test_db_lifecycle`; (b) `_test_db_lifecycle` re-architecting (worker startup stagger; static DB pool); (c) dynamic `max_connections` sizing in dev_engine. Reject ≥2 alternatives with rationale.
6. **Propose pin shape** — name the new regression test + describe what it asserts. `git grep -n "def test_engine_retry_" backend/tests/test_fixture_isolation_v1020.py` confirms the existing naming convention.
7. **Write audit doc** — 5 sections per REQUIREMENTS.md, line numbers verbatim, hypothesis-by-hypothesis disposition (TRUE/FALSE/INCONCLUSIVE).
8. **Commit audit doc** — `.planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md` only.

### Reproduction baseline preservation

Sequential pytest baseline `3055/0/38` MUST remain green at spike-commit time. The spike does not touch test or production code; only the audit doc is added. Phase 1094 success criterion 5 verification: `cd backend && uv run pytest -k "test_fixture_isolation_v1020 or test_conftest_pool_sizing or test_conftest_lifecycle"` should still pass (32 tests).

### Out of phase 1094 scope

- ANY code change to `backend/tests/conftest.py`, `backend/tests/test_fixture_isolation_v1020.py`, or any production file.
- Makefile / CI yaml changes.
- New pytest fixtures or test scaffolding.
- All of these land in Phase 1095 per the roadmap.
</specifics>

<deferred>
## Deferred Ideas

None for Phase 1094 — the spike is bounded to the 8-step workflow above. If the spike surfaces an architectural issue larger than per-worker DB lifecycle retry (e.g., a fundamental conflict between asyncio + asyncpg + xdist worker count > N), promote that to a v1023+ requirement per REQUIREMENTS.md Future Requirements language — do NOT bloom Phase 1094 scope.
</deferred>
