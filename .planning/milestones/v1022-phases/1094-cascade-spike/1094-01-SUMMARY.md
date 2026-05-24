---
phase: 1094-cascade-spike
plan: 01
subsystem: testing
tags: [pytest, xdist, parallel, asyncpg, sqlalchemy, conftest, fixture-isolation, spike, audit, test-infra]

# Dependency graph
requires:
  - phase: 1093-engine-level-retry-envelope
    provides: "v1021 Phase 1093-02 Run 3 cascade diagnostic (706 errors / 4787 ICN lines / per-worker DB CREATE) — the spike's hypothesis-enumeration starting point. Discovered drift: that surface is closed on current HEAD; new cascade surface dominant."
provides:
  - "Audit doc at .planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md with 5 sections (root-cause hypothesis enumeration / reproduction recipe / line-numbered fix-shape proposal / WR-02 prerequisite analysis / regression-pin shape proposal) + frontmatter status: COMPLETE"
  - "Dominant root cause identified: _init_tile_pool_for_tests fixture (3 sibling copies at test_tiles.py:142, test_embed_tokens.py:38, test_tile_signing.py:102) calls asyncpg.create_pool() directly bypassing all conftest.py retry envelopes"
  - "Fix shape proposal: Shape A* — wrap each call site in existing _run_with_too_many_clients_retry envelope (conftest.py:359); reuses existing _TRANSIENT_CONTENTION_EXCEPTIONS + _SETUP_PHASE_RETRY_BACKOFFS infrastructure"
  - "WR-02 disposition: INDEPENDENT — blocking sleep at conftest.py:624 is only invoked from engine-wrapper Category 4.3 paths (lines 706, 843); the observed cascade source bypasses those entirely. PARA-02 can sequence either order in Phase 1095"
  - "Regression-pin shape: test_init_tile_pool_retries_on_transient_too_many_clients + test_init_tile_pool_retry_yields_event_loop_during_backoff (PARA-02 (b) coverage) + (recommended) test_init_tile_pool_no_retry_pre_fix_raises_too_many_clients xfail-pre-fix pin"
  - "CONTEXT.md line-number drift correction: _test_db_lifecycle is at line 906 (not ~661-674); 8-row corrected line-number table in audit Section 3.1"
  - "3 pre-fix baseline runs preserved at /tmp/v1022-1094-pre-fix-nauto-run{1,2,3}.{log,xml} for Phase 1095 post-fix delta comparison"
affects: [1095-cascade-fix-wr02-closure, 1096-hygiene-tail, 1097-live-verify-close-gate]

# Tech tracking
tech-stack:
  added: []  # spike-only; no new libraries or tools
  patterns:
    - "Spike-first per v1019/v1020/v1021 precedent: measurement before fix for architectural items"
    - "Hypothesis verdict matrix with TRUE/FALSE/PARTIALLY TRUE/INCONCLUSIVE dispositions cited inline with line numbers"
    - "Re-validate planner-cited line numbers via git grep AT audit-write time (v1019 TD-13 req_citation_pinning); document drift explicitly"
    - "Atomic-2-file docs commit pattern: audit doc + plan SUMMARY.md only (no code/test/CI changes from spike)"

key-files:
  created:
    - ".planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md (5 sections + frontmatter status: COMPLETE)"
    - ".planning/phases/1094-cascade-spike/1094-01-SUMMARY.md (this file)"
  modified: []  # spike is observation-only; no source-file edits

key-decisions:
  - "Audit reclassified observed cascade — planner's H1-H5 (all framed against per-worker DB CREATE) are FALSE/INCONCLUSIVE; new H6 (_init_tile_pool_for_tests bypassing retry envelopes) is TRUE/dominant"
  - "Fix shape pivoted from planner's Shape A (per-worker DB lifecycle) to Shape A* (tile-pool init wrapping); reuses existing _run_with_too_many_clients_retry envelope (no new helpers, no new constants)"
  - "WR-02 disposition INDEPENDENT (not PREREQUISITE or UNCLEAR) — call-site map shows _invoke_sleep_in_sync_context is only invoked from Category 4.3 engine-wrapper paths, NOT from observed cascade surface"
  - "Pin file destination: extend existing backend/tests/test_fixture_isolation_v1020.py (NOT new test_per_worker_db_lifecycle_v1022.py — file name would mismatch actual surface)"
  - "CONTEXT.md line-number drift documented explicitly (8-row corrected table in audit Section 3.1) so Phase 1095 planner does NOT re-encode stale ranges"

patterns-established:
  - "Spike-discovery-reclassification pattern: when measurement contradicts plan-time hypothesis enumeration, RECLASSIFY in audit doc (don't force-fit observed evidence into anticipated framing); audit doc Section 1.4 commits to a one-paragraph dominant root cause based on actual evidence"
  - "Hypothesis verdict family extension: H1-H5 from plan + H6/H7 NEW hypotheses from spike evidence; preserve all hypotheses with explicit verdicts (TRUE/FALSE/INCONCLUSIVE) so future planners see what was considered"
  - "WR-02 disposition by call-site map: enumerate every caller of the suspect function + cross-reference against observed cascade traceback frames; INDEPENDENT vs PREREQUISITE follows directly from whether call sites intersect"
  - "Anti-Shape pattern: explicitly cite + reject ≥2 planner-anticipated shapes by name with rationale (NOT silent abandonment); reviewer can re-evaluate if Phase 1095 discovers Shape A* insufficient"
  - "Sequential baseline preservation via subset spot-check: 32-test pin family (test_fixture_isolation_v1020 + test_conftest_pool_sizing + test_conftest_lifecycle) is the cheap proxy for full 9min sequential re-run; appropriate when no code changes ship from the plan"

requirements-completed: []  # PARA-01 (e) is spike portion; full PARA-01 closure (a/b/c/d) lands at Phase 1095. Per CONTEXT.md rule #2 and v1019 TD-13 requirements_traceability_flip: empty at Phase 1094 close.

# Metrics
duration: ~25 min (3 × 7min pytest -n auto baseline + analysis + audit-doc write)
completed: 2026-05-23
---

# Phase 1094-01: Cascade Spike Summary

**Audit-doc spike that reclassified the v1021 carry-forward cascade surface — the observed pytest -n auto cascade on current HEAD is `_init_tile_pool_for_tests` direct asyncpg.create_pool contention (14/14/21 distinct across 3 runs), NOT the per-worker DB CREATE cascade the planner anticipated; WR-02 disposition INDEPENDENT; Shape A* fix shape proposed for Phase 1095.**

## Performance

- **Duration:** ~25 min (3 × 7min pytest -n auto baseline runs + Tasks 1-3 analysis + audit-doc write)
- **Started:** 2026-05-23T20:05Z
- **Completed:** 2026-05-23T20:35Z
- **Tasks:** 4 (all auto, observation-only)
- **Files created:** 2 (.planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md + this SUMMARY.md)

## Accomplishments

- **Pre-fix 3-run baseline captured + cascade surface reclassified.** All 3 runs satisfy ≤30 distinct threshold (14 / 14 / 21) on HEAD `49625d27`. ZERO actual `InvalidCatalogNameError` exception frames across all 3 runs — the v1021 Phase 1093-02 Run 3 cascade (706 errors / 4787 ICN) is NOT reproducing on current HEAD; a different cascade surface (`_init_tile_pool_for_tests` direct asyncpg.create_pool) is now dominant.
- **Hypothesis verdict matrix committed.** H1 (per-worker DB CREATE retry coverage) FALSE; H2 (engine-wrapper pressure increase) FALSE; H3 (stagger window mismatch) INCONCLUSIVE/unlikely; H4 (WR-02 starvation) deferred to Section 4 → INDEPENDENT; H5 (NullPool dispose timing) INCONCLUSIVE/unlikely; H6 NEW (_init_tile_pool_for_tests bypassing envelopes) TRUE/dominant; H7 NEW (downstream FastAPI app-engine drain) TRUE/contributing.
- **Fix shape proposal Shape A*** committed with `git grep`-validated line numbers (test_tiles.py:151, test_embed_tokens.py:56, test_tile_signing.py:107) + ≥2 alternatives rejected with rationale (Shapes A/B/C planner-original, D/E/F new alternatives all rejected per REQUIREMENTS.md Out-of-Scope or scope-creep grounds).
- **WR-02 disposition INDEPENDENT** named with call-site map (only 2 invocation sites at conftest.py:706 and 843, both in Category 4.3 engine-wrapper paths that the observed cascade bypasses).
- **Regression-pin shape proposal** committed: `test_init_tile_pool_retries_on_transient_too_many_clients` + `test_init_tile_pool_retry_yields_event_loop_during_backoff` (doubles as PARA-02 (b) loop-yield pin) + recommended xfail-pre-fix pin. File destination: extend existing `backend/tests/test_fixture_isolation_v1020.py` (not a new file).
- **CONTEXT.md line-number drift documented** in audit Section 3.1 — `_test_db_lifecycle` was cited at `~661-674`, actual is `906`; 8-row corrected table prevents Phase 1095 planner from repeating the stale citation.
- **Sequential baseline preservation verified** via 32-test pin subset spot-check (pre-Run-1: 32 passed in 4.23s; post-Run-3: 32 passed in 3.97s — both GREEN, no environmental drift).
- **Live docker stack healthy throughout** (5/5 services healthy at audit-commit time).

## Task Commits

Single atomic docs commit per CONTEXT.md rule #3 (atomic-2-file invariant; spike is observation-only with no per-task commits).

1. **All 4 tasks (Pre-flight + 3-run baseline / Hypothesis verdict matrix / WR-02 + Fix + Pin shape proposals / Audit doc synthesis):** single docs commit at this phase close. Hash recorded in this SUMMARY's final task-commit log entry after `git commit`.

## Files Created/Modified

**Created:**
- `.planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md` — 5-section audit doc with frontmatter `status: COMPLETE`; ~550 lines; identifies dominant root cause + Shape A* fix + WR-02 INDEPENDENT disposition + pin shape proposal for Phase 1095.
- `.planning/phases/1094-cascade-spike/1094-01-SUMMARY.md` — this file (plan summary with PARA-01 (e) traceability note + frontmatter dependency graph).

**Modified:** None (spike is observation-only).

**Scratch artifacts in /tmp/ (NOT committed; preserved for Phase 1095 reference):**
- `/tmp/v1022-1094-pre-fix-nauto-run{1,2,3}.{log,xml}` — 3 baseline `pytest -n auto` runs (~700KB each .log + ~700KB each .xml). Preserved for Phase 1095 post-fix delta comparison.
- `/tmp/v1022-1094-stale-dbs-run{1,2,3}.txt` + `/tmp/v1022-1094-drop-stale-run{1,2,3}.sql` — stale-DB enumeration + DROP SQL per run.
- `/tmp/v1022-1094-pre-flight-pins.log` — pre-flight git-grep validation log + 32-test pin subset spot-check result.
- `/tmp/v1022-1094-icn-tracebacks.log` — ICN traceback corpus (mostly empty — 0 actual ICN exception frames across 3 runs; preserved for forensic reference).
- `/tmp/v1022-1094-hypothesis-evidence.md` — Task 2 scratch (drives audit Section 1.3 verdict matrix + Section 1.4 dominant root cause).
- `/tmp/v1022-1094-wr02-evidence.md` — Task 3 Step 1 scratch (drives audit Section 4 disposition).
- `/tmp/v1022-1094-fix-shape-proposal.md` — Task 3 Step 2 scratch (drives audit Section 3.2 + 3.3 fix shape).
- `/tmp/v1022-1094-pin-shape-proposal.md` — Task 3 Step 3 scratch (drives audit Section 5 pin shape).

## Decisions Made

- **Reclassified observed cascade surface in audit Section 1.4** — planner's H1-H5 hypothesis enumeration (all framed against per-worker DB CREATE per 1093-02-FINDINGS Run 3) does not match observed evidence on HEAD `49625d27`. Audit doc commits to a new H6 (`_init_tile_pool_for_tests` bypassing retry envelopes) as dominant root cause. This is the v1019/v1020/v1021 spike-first pattern at work: discover the actual surface, don't force-fit observed evidence into plan-time framing.
- **Pivoted fix shape from planner's Shape A → Shape A*** — Shape A targeted per-worker DB CREATE retry coverage (already protected by `_create_test_db_with_retry` at conftest.py:259); Shape A* targets the actual failing surface (3 sibling fixtures' `asyncpg.create_pool`). Reuses existing `_run_with_too_many_clients_retry` envelope (no new helpers, no new constants).
- **WR-02 disposition INDEPENDENT** based on call-site map — `_invoke_sleep_in_sync_context` is only invoked from `_install_dbapi_connect_retry._retry_do_connect` (line 706) and `_RetryingAsyncEngine.connect()` (line 843); neither path intersects the observed cascade source. PARA-02 sequencing in Phase 1095 is operator-discretion (independent fixes, atomic measurement gate).
- **Pin file destination: extend existing `test_fixture_isolation_v1020.py`** (NOT new `test_per_worker_db_lifecycle_v1022.py` per REQUIREMENTS.md PARA-01 (d) alternative). Rationale: a new file named `per_worker_db_lifecycle` would mislabel the actual surface (`tile_pool_init`); extending the existing engine-retry family keeps all retry-pin coverage in one searchable place.
- **CONTEXT.md line-number drift documented inline (audit Section 3.1)** rather than silently corrected — Phase 1095 planner should grep the corrected table, not re-encode CONTEXT.md's stale ranges. v1019 TD-13 `req_citation_pinning` rule application at audit-write time, NOT only at plan-time.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Reclassified cascade surface — planner's hypothesis enumeration did not match observed evidence**
- **Found during:** Task 2 (Diagnose cascade source)
- **Issue:** CONTEXT.md `<spike_hypotheses>` framed H1-H5 around the v1021 Phase 1093-02 Run 3 cascade (per-worker DB CREATE / `InvalidCatalogNameError`). The pre-fix 3-run baseline produced 0 actual ICN exception frames across all 3 runs; the observed cascade is `TooManyConnectionsError` from `_init_tile_pool_for_tests` direct `asyncpg.create_pool` calls.
- **Fix:** Added H6 (NEW: tile-pool init bypassing envelopes) and H7 (NEW: downstream FastAPI app-engine drain) to the verdict matrix; committed to H6 as dominant root cause. Pivoted Shape A → Shape A* fix shape to address actual failing surface. Rejected planner Shapes A/B/C with rationale in audit Section 3.3.
- **Files modified:** `.planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md` (sections 1.3, 1.4, 3.0, 3.2, 3.3) + scratch files in `/tmp/`.
- **Verification:** All 3 runs' TMC traceback frames originate from `_init_tile_pool_for_tests` line locations (test_tiles.py:151, test_embed_tokens.py:56, test_tile_signing.py:107 — all 3 `git grep`-validated). 0 ICN frames in any run. Cascade source is consistent across runs.
- **Committed in:** Single atomic docs commit (this phase close).

**2. [Rule 3 - Blocking] Re-validated planner's line numbers at audit-write time; documented CONTEXT.md drift**
- **Found during:** Task 1 Step 2 (pre-flight line validation)
- **Issue:** CONTEXT.md `<spike_hypotheses>` cited `_test_db_lifecycle:~661-674`. Actual location on HEAD `49625d27` is line 906 (function header); the cited `~661-674` range is sub-range of `_install_dbapi_connect_retry` (different function entirely). Several other CONTEXT.md `~` approximations were also off by 1-9 lines (`_invoke_sleep_in_sync_context` cited `~615`, actual is 624).
- **Fix:** Added audit Section 3.1 with an 8-row corrected line-number table; every numeric line citation in the audit doc is `git grep`-validated at audit-write time per v1019 TD-13 `req_citation_pinning` rule.
- **Files modified:** `.planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md` (Section 3.1 — corrected table) + frontmatter `root_cause_lines` / `fix_target_lines` fields.
- **Verification:** Final line-validation pass: every `backend/tests/*.py:N` and `at line N` citation in the audit doc resolves to the correct symbol on HEAD `49625d27` (verified via `git grep -nE`).
- **Committed in:** Single atomic docs commit (this phase close).

---

**Total deviations:** 2 auto-fixed (both Rule 3 — blocking diagnostic adjustments based on observed evidence). Both essential for the audit doc to ship truthful guidance to Phase 1095.

**Impact on plan:** Plan structure preserved (4 tasks, 5-section audit doc, atomic-2-file commit). Hypothesis enumeration deepened (5 plan-time hypotheses + 2 new from spike evidence). Fix shape adjusted from planner's Shape A → Shape A* to address actual cascade surface. No scope creep — all changes stay within the spike's audit-doc-only deliverable boundary.

## Issues Encountered

- **None.** The 3-run baseline reproduced cleanly with stale-DB cleanup between runs. Stack remained 5/5 healthy throughout. The reclassification of cascade surface is documented as a planning deviation, not an execution issue.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- **Phase 1095 (Cascade Fix + WR-02 Closure)** has 4 audit-doc inputs ready:
  - Section 3.2 fix `<action>`: Shape A* — wrap `asyncpg.create_pool` in `_init_tile_pool_for_tests` (3 sibling sites or consolidate to shared fixture) with existing `_run_with_too_many_clients_retry` envelope at `backend/tests/conftest.py:359`.
  - Section 4.3 WR-02 sequencing decision: INDEPENDENT — can land in any order in Phase 1095 (bundled per CONTEXT.md).
  - Section 5.1 pin shape `<action>`: 2-3 pins in `backend/tests/test_fixture_isolation_v1020.py` covering PARA-01 (d) retry coverage + PARA-02 (b) loop-yield assertion.
  - Section 3.1 line-number table: corrected; Phase 1095 planner SHOULD NOT re-encode CONTEXT.md's stale ranges.
- **Pre-fix baseline preserved** at `/tmp/v1022-1094-pre-fix-nauto-run{1,2,3}.{log,xml}` for Phase 1095 post-fix delta-comparison measurement.

## Mandatory Traceability Note (per CONTEXT.md rule #2 / v1019 TD-13 requirements_traceability_flip)

**PARA-01 (e) satisfied** — the spike deliverable (`.planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md` with chosen fix shape + line numbers) shipped at this phase close.

**PARA-01 (a/b/c/d) deferred to Phase 1095** — the actual code fix + `pytest -n auto` measurement gate + sequential and `-n 4` baseline preservation + regression pin land at Phase 1095 close. Acceptance criteria (a) ≤30 distinct deterministic across 3 runs, (b) sequential `3055/0/38`, (c) `-n 4` `3054/0/38`, (d) regression pin in `backend/tests/test_fixture_isolation_v1020.py` all flip at Phase 1095, not here.

**PARA-02 (d) preliminary disposition shipped** — audit Section 4.3 commits WR-02 disposition as INDEPENDENT. Full PARA-02 closure (acceptance criteria a/b/c — non-blocking sleep implementation + regression pin + zero regression on the 4 existing `test_engine_retry_*` pins) deferred to Phase 1095.

**REQUIREMENTS.md `[ ]` → `[x]` flip + `Pending` → `Complete` does NOT land at Phase 1094 close.** Both flips land at Phase 1095 close (when all 5 PARA-01 acceptance criteria are satisfied). Phase 1094's role is the spike deliverable only.

## Self-Check: PASSED

**File existence verified:**
- FOUND: `.planning/audits/PYTEST-NAUTO-CATEGORY-4-1-v1022.md` (audit doc)
- FOUND: `.planning/phases/1094-cascade-spike/1094-01-SUMMARY.md` (this file)
- FOUND: `/tmp/v1022-1094-pre-fix-nauto-run1.xml` (Run 1 baseline)
- FOUND: `/tmp/v1022-1094-pre-fix-nauto-run2.xml` (Run 2 baseline)
- FOUND: `/tmp/v1022-1094-pre-fix-nauto-run3.xml` (Run 3 baseline)

**Audit doc structure verified:**
- 5 sections present (`## Section 1` through `## Section 5`)
- Frontmatter `status: COMPLETE`
- Frontmatter `wr02_disposition: INDEPENDENT`
- Frontmatter `fix_shape_chosen: "Shape A* — wrap _init_tile_pool_for_tests's asyncpg.create_pool call in the existing _run_with_too_many_clients_retry envelope (conftest.py:359)"`

**Out-of-phase-1094-scope guard verified:**
- `git diff --cached --name-only | grep -vE "^.planning/(audits|phases)/" | wc -l = 0` — only audit doc + this SUMMARY staged

**Line-number citations validated:** all 17 unique `backend/tests/*.py:N` + 5 `at line N` citations in the audit doc resolve to the correct symbol at HEAD `49625d27` via `git grep -nE`.

**Sequential baseline preservation verified:** 32-test pin subset spot-check: pre-Run-1 32 passed in 4.23s; post-Run-3 32 passed in 3.97s. Both GREEN, no environmental drift.

---
*Phase: 1094-cascade-spike*
*Plan: 01 (status: complete — spike deliverable)*
*Completed: 2026-05-23*
