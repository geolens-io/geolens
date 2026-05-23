---
phase: 1091-ingest-correctness-sweep
plan: 01
subsystem: ingest
tags: [sqlalchemy, asyncio, async-context, missing-greenlet, quicklook, procrastinate, postgis, spike]

# Dependency graph
requires:
  - phase: quick-260523-at1
    provides: live failed-job evidence (job_id 90254766-... on urban_areas_landscan_10m) preserved on running docker stack
provides:
  - .planning/audits/INGEST-QUICKLOOK-ASYNC-CONTEXT-v1021.md (root-cause audit doc consumed by Plan 1091-02 as its <action> source)
  - Hypothesis verdict matrix (H1 PARTIALLY TRUE, H2 TRUE, H3 TRUE, H4 TRUE, H5 FALSE)
  - Shape A fix proposal (open fresh session for quicklook block) — file/line/diff intent for Plan 1091-02
  - Regression-test shape (3 test functions named in backend/tests/test_quicklook_async_context.py)
  - 4 risks named (pool checkout doubling, dataset attribute persistence, session-bracket pattern divergence, expire_on_rollback footgun)
  - Stale-docstring finding (tasks_common.py:208-209 references nonexistent .planning/debug/worker-missing-greenlet-100.md — Plan 1091-02 to repoint at audit)
affects: 1091-02, 1091-03 (close-gate)

# Tech tracking
tech-stack:
  added: []  # spike — no code added
  patterns:
    - "Spike-first deliverable as 1091-01: machine-citable audit doc precedes any code change"
    - "Hypothesis verdict matrix as required spike-output shape — disciplined H1..HN scoring with line-pinned evidence"

key-files:
  created:
    - .planning/audits/INGEST-QUICKLOOK-ASYNC-CONTEXT-v1021.md (root-cause audit, status: COMPLETE)
    - .planning/phases/1091-ingest-correctness-sweep/1091-01-SUMMARY.md (this file)
  modified: []  # spike — no code modified

key-decisions:
  - "Committed to Shape A (open fresh session for the quicklook block via `_job_phase_session(job_uuid, phase='quicklook')`) over Shape B (set `expire_on_rollback=False` on the session factory) — Shape B is symptom-level + out of scope (would change app-wide session behavior); Shape A is structural + INGEST-01-scoped."
  - "Root cause is a compound mechanism — H2 (asyncio.wait_for cancellation poisoning the asyncpg cursor) + H3 (rollback expiring eagerly-loaded `dataset.record` relationship despite `expire_on_commit=False`, because `expire_on_rollback` defaults to True). H4 (6018-multipolygon shape) is the necessary trigger for H2 on this specific dataset; H5 (MissingGreenlet inside `_generate_quicklook`) is FALSE — the explosion is in `defer_embedding` (helpers.py:123), two function calls later."
  - "Did NOT recreate the missing `.planning/debug/worker-missing-greenlet-100.md` referenced from `tasks_common.py:208-209`. Plan 1091-02 will repoint that docstring at this v1021 audit instead."
  - "Did NOT rebuild docker stack or clear the failed-job row — Plan 1091-02's regression test needs to reproduce the bug shape against the preserved evidence."

patterns-established:
  - "Spike audit-doc shape — frontmatter (status: DRAFT → COMPLETE, line citations in frontmatter for cross-doc indexing) + 3 sections (Live Reproduction Evidence / Code Path Trace + Hypothesis Verdicts / Root Cause + Proposed Fix + Risks). Plan-checker pulls fields directly out of frontmatter for downstream plan generation."
  - "Hypothesis verdict honesty — when the planner's hypotheses are partially wrong (H5 here was FALSE; H1 was only PARTIALLY TRUE), the spike must say so and re-locate the actual root cause from the traceback, not paper over the mismatch."
  - "Pool-sizing risk calculation as part of the spike output — the proposed fix's worst-case connection demand is calculated against the app's `db_pool_size=10 + db_max_overflow=3 = 13` budget vs the seed-script's `Semaphore(3)` × 2 sessions = 6 connections. Plan 1091-02 inherits the verification step."

requirements-completed: []  # INGEST-01 spike portion is complete; full INGEST-01 closes in Plan 1091-02 (fix) and 1091-03 (close-gate) — traceability flip happens with the SUMMARY for the closing plan per v1019 TD-13 rule

# Metrics
duration: ~38 min
completed: 2026-05-23
---

# Phase 1091 Plan 01: Ingest Quicklook MissingGreenlet — Async-Context Boundary Spike Summary

**Identified the exact async-context boundary that produces `MissingGreenlet` on the `urban_areas_landscan_10m` post-commit flow — same session reused across an `asyncio.wait_for` cancellation at `tasks_common.py:826`, with the explosion deferred two lines later in `defer_embedding` because `expire_on_rollback` defaults to True.**

## Performance

- **Duration:** ~38 min
- **Started:** 2026-05-23T13:50Z (orchestrator dispatch)
- **Completed:** 2026-05-23T14:28:36Z
- **Tasks:** 3 (all auto, no checkpoints)
- **Files modified:** 0 (spike — observation only)
- **Files created:** 2 (audit doc + this SUMMARY)

## Accomplishments

- **Live evidence preserved** — failed job `90254766-ca62-4db4-86c5-411d1c9061fe` still visible at `/api/admin/jobs/?status=failed&total=1` at spike close; docker stack still healthy across all 5 services; no rebuild, no row mutation.
- **Root cause committed to ONE answer** — H2 (timeout cancellation poisoning the asyncpg cursor) compounded with H3 (`session.rollback()` expiring eagerly-loaded `dataset.record` relationship despite `expire_on_commit=False`). Bug detonates at `defer_embedding` (helpers.py:123) on the ORM relationship access, NOT inside `_generate_quicklook` as the planner's hypotheses had assumed.
- **Fix shape (Shape A) named at file:line resolution** — `backend/app/processing/ingest/tasks_common.py:824-828`: open a fresh `_job_phase_session(job_uuid, phase="quicklook")` for the quicklook call, merge `dataset` into the new session inside `_generate_quicklook`. Outer session never sees the cancellation; ORM attributes stay warm for `defer_embedding`.
- **4 risks named with mitigation paths** — most critical (Risk #1, the plan-checker's pool-sizing warning) is calculated against actual `db_pool_size=10 + db_max_overflow=3 = 13` budget vs seed `Semaphore(3) × 2 sessions = 6 worst-case`; well within headroom. No pool bump required (which would be Out-of-Scope per v1020 carry-over).
- **Hypothesis verdict matrix** — disciplined H1..H5 scoring corrected the planner's framing: the bug is NOT inside `_generate_quicklook` (H5 FALSE); the planner's H1 narrative was only PARTIALLY TRUE (the failed commit AT line 662 is symptom, not the explosion); H2+H3 are the real chain; H4 explains determinism on this one dataset.
- **Regression-test shape proposed at function-name resolution** — three test functions in `backend/tests/test_quicklook_async_context.py` (positive PASS post-fix, xfail-pin pre-fix, and 1000-row multipolygon shape regression). Plan 1091-02 inherits the pinning task and per-test node-ID validation per v1019 TD-13 `req_citation_pinning` rule.
- **Stale-docstring finding** — `tasks_common.py:208-209` references `.planning/debug/worker-missing-greenlet-100.md` which does NOT exist on disk; Plan 1091-02 will repoint that reference to the v1021 audit doc.

## Task Commits

Each task was committed atomically as part of the spike's single docs commit (no per-task commits — spike is observation-only):

1. **Task 1: Capture live failure state from running docker stack** — included in single docs commit below
2. **Task 2: Static analysis — trace failure path through tasks_common.py and quicklook.py** — included in single docs commit below
3. **Task 3: Commit to ONE root cause and propose fix shape for Plan 1091-02** — included in single docs commit below

**Single docs commit:** `3309fed8` (`docs(1091-01): spike — async-context boundary audit`)

_Note: Spike work is documentation-only by contract — the plan's <constraint> "NO production code modified in this plan" + "force-add `.planning/` files (gitignored)" pins the single-commit shape. Per-task commits would split the audit doc across mid-states which provides no review value._

## Files Created/Modified

- `.planning/audits/INGEST-QUICKLOOK-ASYNC-CONTEXT-v1021.md` (NEW, 282 lines) — root-cause audit doc, status: COMPLETE in frontmatter, consumed by Plan 1091-02 as its <action> source. Frontmatter exposes machine-readable fields: `job_id`, `dataset_id`, `dataset_table`, `feature_count`, `geometry_type`, `job_duration_seconds`, `generation_timeout_seconds`, `root_cause_file`, `root_cause_lines`, `fix_target_lines`, `test_file`.
- `.planning/phases/1091-ingest-correctness-sweep/1091-01-SUMMARY.md` (NEW, this file)

## Decisions Made

- **Shape A (fresh session for quicklook block) over Shape B (set `expire_on_rollback=False` on session factory).** Shape B is symptom-level (only fixes H3 detonation; H2 cursor poisoning would still leave the session in invalid-transaction state for the NEXT operation downstream of `defer_embedding`) AND out of INGEST-01 scope (session-factory change affects the whole app — request handlers would also stop expiring attributes on rollback, an unknown-impact behavior change). Shape A fixes both H2 and H3 by isolation and stays inside `tasks_common.py:824-828`.
- **Did NOT recreate the missing `worker-missing-greenlet-100.md` debug file** — the v1021 audit doc supersedes it; recreating a stale parallel doc would just be two sources of truth. Plan 1091-02 will repoint the docstring at `tasks_common.py:208-209` to this audit.
- **Did NOT rebuild the docker stack** — the plan's HARD INVARIANT explicitly preserved the failing-job evidence so Plan 1091-02's regression test can re-observe the bug shape before the fix lands. Verified at spike close that the row still has `total=1` failed and stack still healthy.
- **Recommended `_GENERATION_TIMEOUT_SECONDS` stays at 10** — Plan 1091-02 should NOT bump the timeout. The right fix is "the session is not poisoned by timeout cancellation"; the 10s budget on a 6018-multipolygon `ST_MakeValid(ST_Simplify(...))` operation is a separate (and arguably correct) decision. INGEST-01 acceptance criterion (b) "non-null quicklook URI" needs reframing in Plan 1091-02: option (iii) — `_generate_quicklook` uploads the blank canvas on timeout and writes the URI so the dataset gets a "blank but present" thumbnail. Recommended in Risk #2 of the audit.
- **Skipped Plan 1091-02 design** — that's the next plan's job. This SUMMARY hands off via the audit doc's Section 3.

## Deviations from Plan

None - plan executed exactly as written.

The plan's `<spike_hypotheses>` framing was partially wrong (it assumed the MissingGreenlet was inside `_generate_quicklook`'s commit phase, H5), but spike-first work is supposed to surface that mismatch and re-locate the actual root cause from observed evidence — which is what the H1..H5 verdict matrix does. That's the spike pattern working as designed, not a deviation.

## Issues Encountered

None. The live failed-job row was still in the admin ledger; worker logs from 3 hours ago were still in the rolling buffer; all referenced source files existed at their stated line numbers; the single missing referenced doc (`.planning/debug/worker-missing-greenlet-100.md`) was the documented stale-reference case the plan's Task 2 step 6 anticipated.

## User Setup Required

None.

## Next Phase Readiness

**Ready for Plan 1091-02 immediately.** Plan 1091-02's executor can:

1. Quote `.planning/audits/INGEST-QUICKLOOK-ASYNC-CONTEXT-v1021.md` Section 3 verbatim as the fix `<action>` — file, line range, what changes, what does NOT change are all named at file:lineno resolution.
2. Implement the three regression tests named in Section 3 — `backend/tests/test_quicklook_async_context.py` with `test_generate_quicklook_timeout_does_not_poison_outer_session` (PASS), `test_generate_quicklook_timeout_poisons_outer_session_pre_fix` (xfail pin), `test_generate_quicklook_completes_on_6018_multipolygon_shape`. Per v1019 TD-13 `req_citation_pinning`, planner must `git grep -n "def test_generate_quicklook_timeout_does_not_poison_outer_session" backend/tests/` AFTER the test file is created and BEFORE the close-gate commit, then pin the resolved `path::TestClass::test_name` node-IDs in REQUIREMENTS.md.
3. Verify the bug shape is reproduced — re-run the live seed (or use the preserved failed row) before the fix to confirm the regression test xfails as expected, then run after the fix to confirm it passes.
4. Risk-#1 verification step inherited — log peak concurrent SQLAlchemy connection count during the post-fix seed run; assert ≤13 of the `db_pool_size + db_max_overflow` budget; if exceeded, escalate per CONTEXT.md (NO pool-size bump — that's restated Out-of-Scope from v1020).

**Blockers/concerns for Plan 1091-02:**
- The Risk #2 reframing of INGEST-01(b) ("non-null quicklook URI for `urban_areas_landscan_10m`") — the spike recommends option (iii) but the operator should confirm. If the operator wants a real (non-blank) quicklook for this dataset, Plan 1091-02 would need to ALSO bump `_GENERATION_TIMEOUT_SECONDS` or optimize the `ST_Simplify(ST_MakeValid(...))` query. That's an architectural-shape question — defer to Plan 1091-02's discuss step (or the planner's discretion if discuss is skipped).

**HARD INVARIANT preserved:** Sequential pytest baseline `3047/0/38` not perturbed (no test changes in this plan; verification was informational only).

## Self-Check: PASSED

- FOUND: `.planning/audits/INGEST-QUICKLOOK-ASYNC-CONTEXT-v1021.md`
- FOUND: `.planning/phases/1091-ingest-correctness-sweep/1091-01-SUMMARY.md`
- FOUND: docker stack still healthy (api/db/frontend/titiler/worker = Up 3 hours (healthy); migrate = Exited (0))
- FOUND: failed-job row 90254766-... still present in `/api/admin/jobs/?status=failed` (total=1)
- Commit hash: `3309fed8` (recorded via `git rev-parse --short HEAD` post-commit).

---

*Phase: 1091-ingest-correctness-sweep*
*Completed: 2026-05-23*
