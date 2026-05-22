---
gsd_phase_summary_version: 1.0
phase: 1087
plan: 01
subsystem: test-infra
status: complete
date_completed: 2026-05-22
milestone: v1020
requirements: [FI-01]
tags: [test-infra, pytest-xdist, fixture-isolation, spike, audit-doc, v1020]
dependency_graph:
  requires: [v1019-close-gate-3036-0-38]
  provides: [phase-1088-fix-sequencing]
  affects: [v1020-FI-02-plan-sequencing, v1020-FI-03-regression-pin-shapes]
tech_stack:
  added: []
  patterns: [spike-first-audit-doc, junit-xml-parsing-for-failure-inventory, single-run-measurement-with-flake-hunt-deferred]
key_files:
  created:
    - .planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md
    - .planning/phases/1087-fixture-isolation-spike-taxonomy/1087-SUMMARY.md
  modified:
    - .planning/REQUIREMENTS.md
    - .planning/ROADMAP.md
decisions:
  - "Spike-first per v1019 Phase 1085 precedent — audit doc commits BEFORE any fix code lands; no production/test code changes in Phase 1087."
  - "JUnit XML parser MUST prepend `backend/` to rootdir-relative classname so node-IDs read as `backend/tests/test_x.py::TestY::test_name` everywhere downstream."
  - "Sequential baseline `failed == 0` is a HARD gate before parallel measurement — if M > 0, halt; otherwise document variance in N/K and proceed."
  - "Single-run measurement is the budget for this spike. Cross-run stability is Phase 1090 HYG-02 (3× flake hunt) — categories may reclassify there."
  - "Section 5 fix sequencing is impact-ranked (highest failure count first) AND structurally aware (downstream cascade categories sequenced after upstream with re-measure gates)."
metrics:
  duration_min: ~25 min (Task 1 measurement ~9 min sequential + ~5 min parallel + ~2 min sampler kill + ~10 min Task 2 categorization)
  total_failures_classified: 648
  total_categories: 6
  hypothesis_categories_reproduced: 0  # of 4 from v1019 spike — Redis/storage/dep_overrides/autouse all 0-count
  dominant_category_pct: 62.8  # per-worker DB lifecycle race (gw15)
  sequential_baseline_at_HEAD: "3036 passed / 0 failed / 38 skipped / 14 deselected in 539.74s"
  parallel_run_at_HEAD: "89 failed / 2401 passed / 27 skipped / 560 errors in 269.12s"
---

# Phase 1087 Plan 01: Fixture-Isolation Spike (Taxonomy) Summary

Spike-first audit doc that classifies all 648 fixture-scope failures under `pytest -n auto`
on HEAD `d340c22e` by root cause, recommending Phase 1088 fix sequencing.

## Overview

Phase 1087 is the v1020 fixture-isolation spike — sister to the v1019 connection-cascade
spike (`.planning/audits/PYTEST-XDIST-SPIKE-v1019.md`). The phase ships a single deliverable:
`.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md` — a 5-section audit doc that
measures and classifies every failing testcase under `pytest -n auto` against the
post-v1019 HEAD, with reproducibility commands a fresh operator can paste verbatim.

**Spike-first discipline:** no production-code changes, no test-code changes, no
`backend/tests/conftest.py` edits. The phase's only writes are to `.planning/audits/`,
`.planning/phases/1087-fixture-isolation-spike-taxonomy/`, `.planning/REQUIREMENTS.md`,
and `.planning/ROADMAP.md`. The `git diff HEAD~2..HEAD --name-only` gate confirms zero
non-`.planning/` files touched across the two phase commits.

**Key finding:** The 192-failure carry-forward estimate from v1019 close-gate was a lower
bound. Measurement against HEAD `d340c22e` produces **648 failures + errors** under
`pytest -n auto`. The dominant root cause (62.8% of failures) is a **per-worker
`_test_db_lifecycle` session-fixture race on gw15** — the silent-swallow path in
conftest.py:275-278 catches `OperationalError("too many clients already")` during the
staggered-startup window, fails to create the per-worker test DB, and 407 downstream
tests on that worker fail setup with `InvalidCatalogNameError`. The remaining 239
cascade errors (TooManyConnections at setup/teardown/in-test) are the proximate symptom
of concurrent fixture-setup demand still exceeding `max_connections=30` even with the
v1019 TD-10 NullPool + 5s startup stagger fixes.

**Hypothesis miss:** All 4 v1019-era hypothesis categories (Redis singleton state,
storage provider override, `app.dependency_overrides` leak, autouse-fixture coupling)
produced **0 failures** in this run. Each is named in Section 4 of the audit (4.5-4.8)
for traceability — Phase 1088 may revisit if a fix to category 4.1 reveals masked
failures.

## Per-category counts

Lifted from audit Section 2:

| Category | Failure count | % of total |
|----------|---------------|------------|
| per-worker DB lifecycle race (gw15 setup failed) | 407 | 62.8% |
| setup-phase connection contention (TooManyConnections during fixture setup) | 150 | 23.1% |
| in-test connection contention (TooManyConnections inside test body) | 87 | 13.4% |
| teardown-phase connection contention (TooManyConnections during fixture teardown) | 2 | 0.3% |
| sandbox subsystem error (non-cascade) | 1 | 0.2% |
| assertion failure (test logic — needs case-by-case inspection) | 1 | 0.2% |

**Total failures:** 648

## Section 5 Phase 1088 fix-sequencing extract

Lifted from audit Section 5:

1. **per-worker DB lifecycle race (gw15 setup failed)** — **407 failures (62.8%)** — **FIX FIRST.**
   Replace the silent `except Exception: yield; return` at `backend/tests/conftest.py:275-278`
   with a structured handler that distinguishes "Postgres unreachable" (skip) from
   "transient connection contention during stagger window" (retry-with-backoff up to N
   attempts, then fail loudly if still contended). This is a single-file fix with a clear
   regression-pin shape (mock `dev_engine.connect()` to raise `OperationalError("too many
   clients already")` once, then succeed; assert the per-worker DB IS created).

2-5. Cascade subcategories (4.2-4.5) sequenced behind re-measure gates because cascade
categories interact — fixing 4.1 may partially resolve 4.2/4.3/4.4, so each fix is
followed by a re-measure cycle (drop stale DBs → sequential baseline assert `failed == 0` →
parallel `pytest -n auto --junitxml=...` → re-categorize → cross-reference with this
audit's counts to report movement across ALL categories, not just the targeted one).

The audit's Section 5 IS the Phase 1087 → Phase 1088 handoff artifact. The Phase 1088
planner reads it and produces a sequenced plan from Section 5's ordered list.

## Reproducibility

See audit Section 1 for full reproducibility commands. Quick summary:

1. `docker compose ps db` healthy on `127.0.0.1:5434`.
2. Drop stale per-worker test DBs from prior runs (audit Section 1 Step 1b).
3. `cd backend && uv run pytest tests/` — assert `failed == 0` (sequential baseline gate).
4. Start `pg_stat_activity` background sampler (audit Section 1 Step 3).
5. `cd backend && env $(grep -v '^#' .env.test | xargs) uv run pytest -n auto --junitxml=/tmp/v1020-junit.xml tests/`.
6. Run the Section 1 Step-5 Python parser to extract `/tmp/v1020-failure-inventory.json`.
7. Match the per-category breakdown in audit Section 2 ±5% on N/M variance, ±1% on
   per-category counts.

## Acceptance criteria checklist

All five must_haves from `1087-01-PLAN.md` frontmatter satisfied:

- [x] **Developer can re-run the measurement from a fresh stack.** Audit Section 1 Steps
  1-11 are paste-ready shell commands. Verified by the parser shape, command lists, and
  reproducibility checklist. Determinism limitation documented in Section 1 (pytest-randomly
  NOT installed; single-run only — Phase 1090 HYG-02 covers cross-run stability).
- [x] **Every failing test cited as a `path::TestClass::test_name` node-ID.** Section 3
  table has **648 rows** (`grep -cE "^\| \`backend/tests/.*\.py::(?:[A-Za-z_][A-Za-z0-9_]*::)?test_"
  .planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md` returns 648, matching `len(/tmp/v1020-failure-inventory.json)`).
- [x] **Section 4 names ≥4 categories.** Sections 4.1-4.10 cover 6 observed categories +
  4 v1019 hypothesis categories named for traceability (Redis singleton state, storage
  provider override, `app.dependency_overrides` leak, autouse-fixture coupling — each
  documented as "0 failures observed; hypothesis not reproduced" in 4.5-4.8). Python-diff
  sketches present for the 4 observed cascade categories (4.1-4.4).
- [x] **Section 5 fix-sequencing recommendation.** Ordered list with rationale for each
  category, re-measure protocol between fixes, regression-pin shapes for FI-03 (Phase 1088).
- [x] **Sequential pytest baseline remains 0-failure.** Re-verified at start of Task 1
  (`3036 passed, 38 skipped, 14 deselected, 18 warnings in 539.74s — failed == 0`); no
  production or test code touched in this phase so invariant by construction.
- [x] **REQUIREMENTS.md FI-01 traceability flip + ROADMAP.md Phase 1087 flip land in the
  SAME commit as this SUMMARY** per v1019 TD-13 `requirements_traceability_flip` rule.
  Verified by the Task 3 `git diff-tree --no-commit-id --name-only -r HEAD` gate.

## TD-13 traceability flip

This SUMMARY commit lands three doc edits atomically per v1019 TD-13 `requirements_traceability_flip`:

1. **`1087-SUMMARY.md`** — this file (new).
2. **`.planning/REQUIREMENTS.md`** — two edits in the same file:
   - Line 18: `- [ ] **FI-01**:` → `- [x] **FI-01**:`
   - Line 72 (traceability table row): `| FI-01 | Phase 1087 | Pending |` → `| FI-01 | Phase 1087 | Complete |`
3. **`.planning/ROADMAP.md`** — two edits in the same file:
   - Line 90: `- [ ] **Phase 1087: Fixture-Isolation Spike (Taxonomy)**` → `- [x] **Phase 1087: Fixture-Isolation Spike (Taxonomy)**`
   - Line 107: `**Plans**: 1 plan` → `**Plans**: 1/1 plans complete (1087-01-PLAN.md — audit doc + SUMMARY)`

The same-commit invariant is enforced by `git diff-tree --no-commit-id --name-only -r HEAD`
(files-only output — NOT `git log -1 --name-only` which interleaves the commit message
body and would inflate counts when filename tokens appear in the message).

## Phase 1088 carry-forward

The audit doc's Section 5 IS the Phase 1087 → Phase 1088 handoff artifact. The Phase 1088
planner consumes it directly:

- **Category sequence:** 4.1 (per-worker DB lifecycle race, 407 failures) → 4.2 (setup-phase
  contention, 150) → 4.3 (in-test contention, 87) → 4.4 (teardown, 2; may collapse into
  4.2's fix) → 4.5 (single sandbox + assertion; verify-after-fix only).
- **Fix shapes (illustrative; planner owns the choice):** structured `OperationalError`
  handler at conftest.py:265-280; per-worker setup-phase semaphore OR widened stagger OR
  retry-with-backoff at `_make_test_async_engine`; retry-with-backoff wrapper around
  `override_get_db`.
- **Regression-pin shapes (FI-03):** one pin per category at `backend/tests/test_fixture_isolation_v1020.py`
  (or split per-category as the FI-02 plan directs). Each pin fails on pre-fix HEAD and
  passes on post-fix HEAD. Shape sketches in audit Section 5 final block.
- **Re-measure protocol:** drop stale per-worker DBs → sequential baseline `failed == 0` →
  `pytest -n auto --junitxml=...` → re-categorize → report movement across ALL categories
  in the Phase 1088 SUMMARY (cascade categories interact; fixing 4.1 likely perturbs
  4.2/4.3 counts).

## Self-Check

Performed at the end of execution:

- `.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md` exists at HEAD with frontmatter +
  5 sections + 648 inventory rows + per-category Section 4 + ordered Section 5.
- All 4 v1019 hypothesis categories named in Section 4 (4.5-4.8 each marked "0 failures
  observed; hypothesis not reproduced").
- Section 3 row count (648) == `total_failures_classified` frontmatter value (648) ==
  `len(/tmp/v1020-failure-inventory.json)` (648).
- `.planning/REQUIREMENTS.md` shows `[x] **FI-01**` checkbox + `| FI-01 | Phase 1087 | Complete |`.
- `.planning/ROADMAP.md` shows `[x] **Phase 1087:` checkbox + `**Plans**: 1/1 plans complete`.
- `git diff-tree --no-commit-id --name-only -r HEAD` on the SUMMARY commit must include
  exactly: `1087-SUMMARY.md`, `REQUIREMENTS.md`, `ROADMAP.md` (TD-13 SAME-commit invariant).
- `git diff HEAD~2..HEAD --name-only` shows ONLY `.planning/` files (code-pure spike per
  CONTEXT.md `<domain>` invariant).
