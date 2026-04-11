---
phase: 221-get-sample-values-sparse-column-observation
plan: 01
subsystem: backend-ingest
tags: [postgresql, postgis, sqlalchemy, pytest, cte, sample-values]

# Dependency graph
requires:
  - phase: PERF-1 (commit 180cfa97, 2026-03-xx)
    provides: CTE-batched get_sample_values implementation (~N× speedup on wide tables)
provides:
  - Bumped get_sample_values default sample_size from 1000 to 10000
  - Docstring caveat documenting the base-scan-width / RAM trade-off
  - TestSparseColumnSampleValues regression class (2 async test methods)
  - INGEST-N6-01 and INGEST-N6-02 requirement IDs backfilled into REQUIREMENTS.md
affects: [ingest pipelines (vector, raster, reupload, ArcGIS service ingest), Dataset detail UI sample-value display]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Narrow default bump: change only the default parameter value when all callers already use the default and the new value is strictly safer"
    - "Pure-SQL synthetic integration test via CREATE TABLE + INSERT ... FROM generate_series (no ogr2ogr fixture needed)"

key-files:
  created: []
  modified:
    - "backend/app/ingest/metadata.py — line 208 default bumped 1000 -> 10000; docstring extended with scan-width caveat paragraph"
    - "backend/tests/test_ingest_column_preservation.py — new TestSparseColumnSampleValues class (2 async methods, 114 lines)"
    - ".planning/REQUIREMENTS.md — new Backend Ingest Quality section + 2 traceability rows mapping INGEST-N6-01/02 to Phase 221"

key-decisions:
  - "Bumped default only — no new config surface, no call-site overrides, no per-caller parameters (D-01)"
  - "Test placed in test_ingest_column_preservation.py (inherits ogr2ogr pytestmark) for unified 'sample values' suite colocation (D-04)"
  - "Used 99.95% null density (1-in-2000) not 99% to ensure pre-bump test FAILS reliably and post-bump test PASSES reliably (Pitfall 3)"
  - "Two-method test shape (sparse + dense-control) over parametrize to keep bug-fix signal separate from regression-guard signal"

patterns-established:
  - "Default-value bump pattern: grep all call sites for explicit overrides first, then bump in-place with zero call-site churn"
  - "Synthetic sparse-column test pattern: generate_series + CASE WHEN for deterministic null-density fixtures"

requirements-completed:
  - INGEST-N6-01
  - INGEST-N6-02

# Metrics
duration: 5min
completed: 2026-04-11
---

# Phase 221 Plan 01: get_sample_values Sparse-Column Default Bump Summary

**Bumped get_sample_values default sample_size from 1000 to 10000 to reliably fill the 10-value per-column display cap on 99%+ null columns, with regression test class and docstring caveat.**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-11T12:38:43Z
- **Completed:** 2026-04-11T12:44:09Z
- **Tasks:** 5 (4 content-bearing + 1 verification-only)
- **Files modified:** 3

## Accomplishments

- `get_sample_values()` default `sample_size` bumped to 10000 so that 99.9%-null columns reliably fill the per-column LIMIT 10 display cap
- Docstring extended with a fourth paragraph explaining the CTE materializes `sample_size` rows up-front, so base-scan width and peak query RAM grow linearly; operators have a discoverable explanation for future incident analysis
- New `TestSparseColumnSampleValues` class with two async integration tests exercising real PostgreSQL via the `test_db_session` fixture:
  - `test_sparse_column_yields_at_least_one_sample` — 99.95%-null column (1-in-2000 density) must yield its one non-null value (regression guard)
  - `test_dense_column_unchanged_by_bump` — dense 12-distinct column must still yield exactly 10 samples (LIMIT 10 cap preserved)
- `INGEST-N6-01` and `INGEST-N6-02` requirement IDs backfilled into `.planning/REQUIREMENTS.md` under a new "Backend Ingest Quality" section with two matching traceability table rows
- Full `test_ingest_column_preservation.py` suite (12 tests across 5 classes) green with no regressions

## Task Commits

Each task was committed atomically with `--no-verify` (parallel executor mode):

1. **Task 1: Bump default sample_size from 1000 to 10000** — `5a5fb23f` (feat)
2. **Task 2: Append scan-width/RAM caveat paragraph to docstring** — `fa689649` (docs)
3. **Task 3: Add TestSparseColumnSampleValues regression test class** — `4c076206` (test)
4. **Task 4: Run full test_ingest_column_preservation.py suite** — no commit (verification-only gate, no file changes)
5. **Task 5: Backfill INGEST-N6-01 and INGEST-N6-02 into REQUIREMENTS.md** — `e26c31f1` (docs)

**Test run:** `docker compose exec -T api uv run pytest tests/test_ingest_column_preservation.py -xvs` → `12 passed in 5.13s`

## Files Created/Modified

- `backend/app/ingest/metadata.py` — Line 208 default bumped 1000 → 10000; docstring extended with a 4th paragraph warning about base-scan width, peak query RAM, and the multi-million-row trade-off. CTE shape (lines 269-274), per-column `LIMIT 10` cap (line 266), and `bindparams(sample_size=sample_size)` binding (line 276) preserved byte-for-byte.
- `backend/tests/test_ingest_column_preservation.py` — New `TestSparseColumnSampleValues` class (114 lines) inserted between `TestUnicodeSampleValues` (ends line 402) and the `§2.3 DBF truncation` banner comment (now line 522). Class ordering preserved: TestBasicAttrsRoundTrip → TestReservedNameAutoRename → TestUnicodeSampleValues → TestSparseColumnSampleValues → TestDbfTruncationCollision.
- `.planning/REQUIREMENTS.md` — New `### Backend Ingest Quality` section (after `### Accessibility`, before `## Future Requirements`) defining INGEST-N6-01 and INGEST-N6-02; two traceability table rows appended after the A11Y-04 row; coverage block annotated with a Backend Ingest Quality summary line. Existing 27 v14.0 requirement roster unchanged.

## Decisions Made

- **D-01 satisfied — bumped default only.** No new parameters, no new config surface, no per-caller overrides. The grep audit confirmed all 4 production callers use the default (verified at `backend/app/ingest/tasks.py:429,1246,1453` and `backend/app/ingest/service.py:329`).
- **D-02 satisfied — 0 call-site changes.** None of the 4 production callers pass an explicit `sample_size` argument, so the bump propagates automatically.
- **D-03 satisfied — docstring caveat added.** The exact prose from `221-RESEARCH.md §Code Examples` was used verbatim (3 sentences, ~60 words, 4 lines of ~70-char wrap).
- **D-04 satisfied — test class colocated with TestUnicodeSampleValues.** New class placed in the same file per CONTEXT.md's "unified sample values suite" intent. Inherits the module-level `pytestmark` that skips on missing `ogr2ogr`, which is acceptable because tests run inside the backend Docker image where `gdal-bin` is always installed.
- **Test density chosen at 99.95% null (1-in-2000), not 99%.** Per RESEARCH Pitfall 3: a 99% density could deterministically yield 10 non-null values at `sample_size=1000` since `LIMIT` without `ORDER BY` is typically sequential-scan-ordered. At 1-in-2000 density with a 2000-row insert, the single non-null row (row 1) is outside the pre-bump 1000-row scan window but inside the post-bump 10000-row window — giving the test a crisp boundary.
- **Two-method shape over `@pytest.mark.parametrize` across null densities.** Per RESEARCH §Code Examples: parametrizing over 90/95/99/99.95% adds noise; only the 99.95% case is load-bearing. Keeping the dense control in its own method separates the "bump didn't regress the common case" signal from the "bump fixed the bug" signal.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Corrected docker compose test invocation from `pytest` to `uv run pytest`**

- **Found during:** Task 3 (running the new test class) and Task 4 (running the full file)
- **Issue:** The plan's verification commands called `docker compose exec -T api pytest ...` directly, but the api container does NOT have `pytest` on PATH or as a top-level Python module. The Dockerfile installs dependencies via `uv sync --no-dev`, which excludes test dependencies from the runtime image. Attempting `docker compose exec -T api pytest` returns `OCI runtime exec failed: exec: "pytest": executable file not found in $PATH`; attempting `python -m pytest` returns `No module named pytest`.
- **Fix:** Used the project-canonical invocation `docker compose exec -T api uv run pytest tests/...`, which matches the pattern defined in the repo root `Makefile` (lines 20 and 23: `docker compose exec api uv run pytest -v --tb=short`). `uv run` resolves the dev-dependency pytest from the locked dev environment at execution time.
- **Files modified:** None (invocation change only — no file edits)
- **Verification:** `uv run pytest --version` returned `pytest 9.0.2`; subsequent `uv run pytest tests/test_ingest_column_preservation.py -xvs` ran all 12 tests to completion with `12 passed in 5.13s`.
- **Committed in:** N/A — no files changed; documented here for future plans/executors in this repo.

**2. [Rule 3 - Blocking] Acceptance-criteria grep count for `INGEST-N6-01` drifted from plan's own ACTION instructions**

- **Found during:** Task 5 (REQUIREMENTS.md backfill verification)
- **Issue:** The plan's `<action>` block for Task 5 explicitly instructed adding a third line under the `**Coverage:**` block: `- Backend Ingest Quality: 2 total (INGEST-N6-01, INGEST-N6-02 — Phase 221)`. This line contains both IDs, raising the total `grep -c 'INGEST-N6-01'` count to 3 (bullet + traceability row + coverage note). However, the plan's `<acceptance_criteria>` block for the same task states the count should be `2` (bullet + traceability row only). The two instructions inside the same task are internally inconsistent.
- **Fix:** Followed the more specific `<action>` block instructions (which explicitly listed the verbatim coverage-block text with the IDs in it). The IDs appear in 3 places per ID total, matching the action block and the `<done>` criterion that all three anchor changes land in the file. Plan-internal drift is logged here for future audits.
- **Files modified:** `.planning/REQUIREMENTS.md` — unchanged in outcome, only the verification-count expectation was adjusted
- **Verification:** `grep -n '### Backend Ingest Quality'` returns 1 match (line 58); `grep -n '| INGEST-N6-01 | Phase 221 | Pending |'` returns 1 match (line 130); `grep -n '| INGEST-N6-02 | Phase 221 | Pending |'` returns 1 match (line 131); bullet `**INGEST-N6-01**` on line 62; bullet `**INGEST-N6-02**` on line 63. All other acceptance criteria (section placement between Accessibility and Future Requirements; A11Y-04 row intact; SITE-01 intact) pass as written.
- **Committed in:** `e26c31f1` (Task 5 commit)

**3. [Rule 3 - Blocking] Copied phase 221 planning files from main worktree to the executor's worktree before starting execution**

- **Found during:** Before Task 1 (initial context loading)
- **Issue:** This phase's planning documents (`221-01-PLAN.md`, `221-CONTEXT.md`, `221-RESEARCH.md`, `221-VALIDATION.md`, `221-DISCUSSION-LOG.md`) exist on disk in the main worktree but are `.gitignore`d under `.planning/`, so they are untracked and NOT visible in this executor's isolated git worktree directory. Attempting to `Read` the plan file at the worktree path returned "File does not exist". The executor cannot load its primary task spec without these files.
- **Fix:** Copied the five `.md` files plus `.gitkeep` from `/Users/ishiland/Code/geolens/.planning/phases/221-get-sample-values-sparse-column-observation/` into the worktree path so the `Read` tool could load them. This is a one-time setup fix — files remain untracked in both the main repo and the worktree, so there is no cross-contamination.
- **Files modified:** `.planning/phases/221-get-sample-values-sparse-column-observation/*.md` (copied, not edited; remain untracked per `.gitignore`)
- **Verification:** `Read` successfully loaded all four required planning files in parallel after the copy.
- **Committed in:** N/A — files remain untracked per `.gitignore` rule; no git state change.

**4. [Rule 3 - Blocking] File sync between worktree and main repo for docker container volume mounts**

- **Found during:** Task 2 (syntax check via docker) through Task 4 (test runs)
- **Issue:** The docker compose api container mounts the **main repo's** `backend/app` and `backend/tests` directories (verified via `docker inspect geolens-api-1` — mounts `/Users/ishiland/Code/geolens/backend/app -> /app/app` and `.../backend/tests -> /app/tests`). Edits made in the executor's isolated worktree directory are NOT visible to the running api container. Running `pytest` from this worktree's perspective would exercise the stale, unchanged files in the main repo — not the new code.
- **Fix:** After each file edit in the worktree, I `cp`-synced the changed file into the main repo path BEFORE running docker tests. After the final task commit, I restored the main repo files with `git checkout --` so the main repo working tree remains unchanged by this phase's execution. All commits landed on the worktree branch (`worktree-agent-aafa1bf6`) as intended.
- **Files modified:** None permanently — the sync/restore is a staging/unstaging operation; git history on the worktree branch contains all three file changes and the main repo working tree was restored to its pre-sync state (only the unrelated `.planning/ROADMAP.md` and `.planning/STATE.md` background changes remain there, which are not touched by this phase).
- **Verification:** Final `cd /Users/ishiland/Code/geolens && git status backend/` returned no output (main repo clean on backend paths). Worktree `git status --short` returned no output (nothing uncommitted). `git log 788661af..HEAD` shows exactly 4 phase-221-plan-01 task commits.
- **Committed in:** N/A — workflow/environment mechanics, not content.

**5. [Rule 3 - Blocking] Worktree branch base reset from `main` (aa74d33e) to target commit (788661af)**

- **Found during:** Initial worktree-base verification (per the `<worktree_branch_check>` instructions)
- **Issue:** The worktree branch `worktree-agent-aafa1bf6` was initially pointed at `aa74d33e` (main HEAD at worktree creation time). The orchestrator requires the branch to be based on `788661af` (the feature-branch HEAD for the wave). The executor's initial `git merge-base HEAD 788661af04171afdd2e11e405203bdf7d61ef66f` returned `aa74d33e`, confirming the branch was ~3 commits behind the target.
- **Fix:** Since `788661af` is a descendant of `aa74d33e` with no divergent commits, a clean fast-forward via `git reset --hard 788661af04171afdd2e11e405203bdf7d61ef66f` was safe and sufficient. After reset, the merge-base check confirmed the branch is now properly based at the target commit.
- **Files modified:** None (base change only — worktree files reset to match target commit)
- **Verification:** `git rev-parse HEAD` returned `788661af04171afdd2e11e405203bdf7d61ef66f`; `git log --oneline -3` confirmed the correct commit chain.
- **Committed in:** N/A — base reset, not a content change.

---

**Total deviations:** 5 (all Rule 3 — blocking environment/workflow issues, zero content-scope changes)
**Impact on plan:** All 5 deviations are environment/workflow mechanics (test invocation syntax, worktree/container volume topology, planning-file staging, branch base). ZERO of them change the phase's scope, the task list, the code changes, or the success criteria. The five tasks in `221-01-PLAN.md` were executed exactly as written, in order, with all acceptance criteria satisfied and all verification gates green. No scope creep. No architectural changes. No new dependencies.

## Issues Encountered

- **pytest not directly available in api container** — see Deviation #1. Resolved by using the project-canonical `uv run pytest` invocation from the Makefile.
- **Task 4 is verification-only with no file changes** — the plan explicitly says "no files modified — verification only" so there is nothing to commit for this task. The full test-suite run was recorded in this SUMMARY and the gate passed (`12 passed in 5.13s`). The executor completed all 4 content-bearing commits (Tasks 1, 2, 3, 5) plus an implicit Task 4 gate.
- **Plan acceptance-criteria count drift for Task 5** — see Deviation #2. The plan's ACTION block and acceptance_criteria block had a minor off-by-one count discrepancy on `INGEST-N6-01` occurrences. Resolved by following the ACTION block's explicit text verbatim.

## User Setup Required

None — no external service configuration, no env var changes, no credential rotation, no database migrations. The change propagates automatically to all 4 production ingest call sites on the next `docker compose up --build api worker` cycle.

## Stored-Data Observation (from RESEARCH §Runtime State Inventory)

Existing `Dataset.sample_values` rows in `catalog.datasets` will **NOT** be backfilled. Sample values are cosmetic display-only data stored as a JSON column; they refresh on re-ingest or reupload. Datasets already in the catalog will continue to display their pre-bump narrow samples until their next reupload/re-ingest. This is **intentional** per CONTEXT.md's Deferred Ideas (none — explicitly no backfill in scope) and documented here so QA does not file a "bump didn't fix my old dataset" bug. A future quick task can optionally backfill existing rows; not required for Phase 221 closure.

## Threat Model Disposition (from PLAN.md <threat_model>)

| Threat ID | Category | Disposition | Outcome |
|-----------|----------|-------------|---------|
| T-221-01 | Tampering (SQL construction) | accept | No new surface. `_validate_table_name`, `_sql_quote_ident`, and `bindparams` all preserved byte-for-byte. Verified: `grep -n 'LIMIT :sample_size\|bindparams(sample_size=sample_size)' backend/app/ingest/metadata.py` returns both pre-existing lines unchanged. |
| T-221-02 | Denial of Service (base scan width) | accept (LOW) | 10× CTE scan-width increase bounded by (a) CTE constant cap, (b) FastAPI auth gate, (c) once-per-ingest-job invocation pattern. Documented in the Task 2 docstring caveat so operators have a discoverable explanation. |
| T-221-03 | Information Disclosure | accept | Return shape unchanged — still `dict[str, list[str]]` with per-column `LIMIT 10` cap. Bump only affects which rows are SAMPLED, not how many are RETURNED. No new PII surface. |
| T-221-04 | Repudiation / Auditability | **mitigate** | Task 5 backfills INGEST-N6-01 and INGEST-N6-02 into REQUIREMENTS.md + traceability table. Future auditors can trace the bump to Phase 221 with full validation contract. |

All STRIDE threats accepted or mitigated. No blocking threats. The one LOW-severity DoS observation is rate-limited at the router layer and documented in the function docstring.

## Next Phase Readiness

- Phase 221 is complete. No follow-up phases required.
- Existing `Dataset.sample_values` backfill (optional) can be a future quick task if QA reports a sparse-column display gap on legacy datasets.
- No downstream dependencies: this phase is independent of v14.0 marketing site work (Phases 212-217) and Phase 218 (demo themed collections).

## Self-Check: PASSED

**File existence checks:**
- `backend/app/ingest/metadata.py` — FOUND (line 208 bumped, docstring extended)
- `backend/tests/test_ingest_column_preservation.py` — FOUND (TestSparseColumnSampleValues at line 410)
- `.planning/REQUIREMENTS.md` — FOUND (Backend Ingest Quality section at line 58, traceability rows at lines 130-131, coverage annotation at line 137)

**Commit existence checks:**
- `5a5fb23f` — FOUND (`feat(221-01): bump get_sample_values default sample_size from 1000 to 10000`)
- `fa689649` — FOUND (`docs(221-01): add scan-width/RAM caveat to get_sample_values docstring`)
- `4c076206` — FOUND (`test(221-01): add TestSparseColumnSampleValues regression class`)
- `e26c31f1` — FOUND (`docs(221-01): backfill INGEST-N6-01 and INGEST-N6-02 into REQUIREMENTS.md`)

**Phase-level verification gates:**
- Gate 1 (`grep sample_size: int = 10000`): PASS (1 match on line 208)
- Gate 2 (`grep base-scan width|peak query RAM|multi-million-row`): PASS (3 matches on lines 225, 225, 227)
- Gate 3 (`pytest TestSparseColumnSampleValues`): PASS (2 tests passed in `uv run pytest`)
- Gate 4 (`pytest test_ingest_column_preservation.py` full file): PASS (`12 passed in 5.13s`)
- Gate 5 (`grep INGEST-N6-0[12]`): PASS (5 matches — 2 bullets + 2 traceability rows + 1 coverage-block mention)
- Gate 6 (`grep ### Backend Ingest Quality`): PASS (1 match on line 58)

**Negative checks:**
- No stale `sample_size: int = 1000[^0]` default: PASS (0 matches)
- No `@pytest.mark.asyncio` on new sparse tests: PASS (0 matches)
- CTE `LIMIT :sample_size` preserved: PASS (1 match on line 280)
- `bindparams(sample_size=sample_size)` preserved: PASS (1 match)
- Per-column `LIMIT 10` cap preserved: PASS (1 match in UNION ALL branch)

---
*Phase: 221-get-sample-values-sparse-column-observation*
*Completed: 2026-04-11*
