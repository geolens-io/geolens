---
phase: 1087-fixture-isolation-spike-taxonomy
verified: 2026-05-22T00:00:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: null  # initial verification — no previous VERIFICATION.md
notes:
  - "Spike measured 648 actual failures, not 192. The 192 number was the v1019 audit's lower-bound estimate captured under different stack state. ROADMAP SC #2 explicitly anticipates this: 'spike may discover more or fewer than 192 once classified under fresh measurement'. The 648 number is the correct baseline going forward; the 192 in CONTEXT.md/REQUIREMENTS.md prose is preserved as historical lower-bound and audit Section 2 reconciles the variance."
  - "All 4 v1019-era hypothesis categories produced 0 failures each — this is a CORRECT spike outcome (it validates measurement-before-fix discipline). The dominant root cause turned out to be a per-worker DB lifecycle race accounting for 407/648 = 62.8% of failures, NOT the four hypotheses. Section 4.5-4.8 still name each hypothesis category with explicit '0 failures observed' for traceability. Phase 1088 must consume Section 5's revised sequencing (lifecycle race first), NOT the original Redis-singleton-first hypothesis sequencing."
---

# Phase 1087: Fixture-Isolation Spike (Taxonomy) Verification Report

**Phase Goal:** Developer can read `.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md` and see every one of the 192 failures classified by root cause, with sufficient evidence to drive Phase 1088 sequencing.

**Verified:** 2026-05-22
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

The phase goal is observably achieved. The audit doc exists at the expected path with all 5 sections, classifies 648 failures (the actual measured count — superseding the lower-bound 192 estimate from v1019 per ROADMAP SC #2's explicit allowance), and Section 5 provides ordered fix sequencing that Phase 1088 can directly consume. All TD-13 invariants hold; the spike is code-pure (zero non-`.planning/` files touched across 6 commits).

### Observable Truths (ROADMAP Success Criteria)

| #   | Success Criterion                                                                                                                                                  | Status     | Evidence                                                                                                                                                                                                                                                              |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Audit doc committed before any fix code lands (spike-first per v1019 Phase 1085 precedent).                                                                       | ✓ VERIFIED | Audit doc committed at `6c400062` (`docs(1087): commit FI-01 fixture-isolation audit doc — 648-failure taxonomy`). `git diff 8977e5ff^..HEAD --name-only` shows ZERO non-`.planning/` files across all 6 phase commits. Phase 1088 (the first fix-code phase) is unstarted. |
| 2   | Audit lists every failing test by exact `path::TestClass::test_name` node-ID — total count equals measured failure count.                                          | ✓ VERIFIED | `grep -cE "^\\| \`backend/tests/.*\\.py::(?:[A-Za-z_][A-Za-z0-9_]*::)?test_" PYTEST-XDIST-FIXTURE-AUDIT-v1020.md` returns 648, matching `total_failures_classified: 648` in frontmatter. All 5 sampled node-IDs grep-validated against working tree (see Section 3b below). |
| 3   | Each node-ID tagged with exactly one root-cause category; the four v1019 hypotheses are each named (even if 0 failures observed).                                  | ✓ VERIFIED | Section 4 names all 4 hypotheses: §4.5 Redis singleton state, §4.6 storage provider override, §4.7 `app.dependency_overrides` leak, §4.8 autouse-fixture coupling — each explicitly marked "0 failures observed; hypothesis not reproduced". Six total observed categories (4.1-4.4 cascade subcategories + 4.9 sandbox + 4.10 assertion). |
| 4   | Reproducibility section mirrors `PYTEST-XDIST-SPIKE-v1019.md` Section 1.                                                                                          | ✓ VERIFIED | v1020 Section 1 mirrors v1019 shape: Step 1 (max_connections), Step 2 (sequential baseline) [new gate], Step 3 (background sampler — identical SQL), Step 4 (xdist run — adds `--junitxml`), Step 5 (failure extraction — new), Reproducibility checklist. Three v1019 command shapes (`docker compose ps db`, `pytest -n auto --junitxml`, `pg_stat_activity`) appear 10× in the doc. |
| 5   | Section 5 recommends Phase 1088 fix sequencing.                                                                                                                    | ✓ VERIFIED | Section 5 contains ordered numbered list 1-5 with rationale: 1 (per-worker DB lifecycle race, 407/62.8%, FIX FIRST), 2 (setup contention, 150/23.1%, FIX SECOND), 3 (in-test contention, 87/13.4%, FIX THIRD), 4 (teardown, 2/0.3%, DEFER), 5 (sandbox+assertion, 2/0.4%, VERIFY-AFTER). Includes re-measure protocol and FI-03 regression-pin shapes. |

**Score:** 5/5 truths verified

### Plan-frontmatter Must-Haves (Truths)

These supplement the ROADMAP SCs with plan-specific detail.

| #   | Truth                                                                                                                                                                                 | Status     | Evidence                                                                                                                                                                                                                                                                                                  |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T1  | Developer can re-run measurement from fresh stack using only Section 1 commands.                                                                                                      | ✓ VERIFIED | Section 1 Steps 1-5 + Reproducibility checklist contain paste-ready shell. Stability declaration explicitly documents single-run scope + Phase 1090 HYG-02 verification deferral.                                                                                                                       |
| T2  | Section 3 row count equals total failure count.                                                                                                                                       | ✓ VERIFIED | `wc -l` of `^\| \`backend/tests/` pattern = 648; matches `total_failures_classified: 648` frontmatter; matches log summary `89 failed + 559 errors = 648` (1 testcase has both `<failure>` and `<error>` nodes per audit Section 2 explanation).                                                          |
| T3  | Section 4 names ≥4 categories with Python-diff sketches.                                                                                                                              | ✓ VERIFIED | 10 sections (4.1-4.10). Python-diff sketches present in 4.1, 4.2, 4.3, 4.4. Hypothesis categories 4.5-4.8 each named with "0 failures observed" + speculation on why hypothesis didn't reproduce.                                                                                                       |
| T4  | Section 5 ordered fix-sequencing with rationale.                                                                                                                                      | ✓ VERIFIED | 5 numbered items with `**FIX FIRST**` / `**FIX SECOND**` / etc. markers. Each entry contains rationale paragraph + suggested approach + interaction notes with prior fix's re-measure gate. FI-03 regression-pin shapes block at lines 1330-1351.                                                       |
| T5  | Sequential pytest baseline `failed == 0` at end of plan.                                                                                                                              | ✓ VERIFIED | Per audit Section 2: sequential baseline at HEAD `d340c22e` = `3036 passed / 0 failed / 38 skipped / 14 deselected in 539.74s`. Re-verify is invariant by construction since no production or test code was touched (verified by spike-only invariant below).                                          |
| T6  | REQUIREMENTS.md FI-01 + ROADMAP.md Phase 1087 flip in SAME commit as SUMMARY.md.                                                                                                      | ✓ VERIFIED | `git diff-tree --no-commit-id --name-only -r e40c4630` returns exactly 3 files: `1087-SUMMARY.md`, `REQUIREMENTS.md`, `ROADMAP.md`. TD-13 SAME-commit invariant atomically satisfied.                                                                                                                  |

### Required Artifacts

| Artifact                                                                                | Expected                                            | Status     | Details                                                                                                                                                                                       |
| --------------------------------------------------------------------------------------- | --------------------------------------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.planning/audits/PYTEST-XDIST-FIXTURE-AUDIT-v1020.md`                                  | 5-section spike audit doc, 648 inventory rows       | ✓ VERIFIED | 1369 lines. Sections 1-5 all present at expected line numbers. Frontmatter declares `total_failures_classified: 648` matching inventory row count. Required category names appear 8× across doc. |
| `.planning/phases/1087-fixture-isolation-spike-taxonomy/1087-SUMMARY.md`                | Phase closure summary with per-category counts      | ✓ VERIFIED | 213 lines. Per-category table, Section 5 extract, 6 acceptance-criteria checkboxes (all `[x]`), TD-13 traceability-flip explanation, Phase 1088 carry-forward subsection.                       |
| `.planning/REQUIREMENTS.md` — FI-01 flip                                                | `[x] **FI-01**` + `\| FI-01 \| Phase 1087 \| Complete \|` | ✓ VERIFIED | Both lines present. FI-01 still reads "192 fixture-scope failures" in description (historical lower-bound preserved); audit doc reconciles to actual 648.                                     |
| `.planning/ROADMAP.md` — Phase 1087 flip                                                | `[x] **Phase 1087:` + `Plans: 1/1 plans complete`   | ✓ VERIFIED | Line 90 checkbox flipped to `[x]`. Line 107 reads `**Plans**: 1/1 plans complete (1087-01-PLAN.md — audit doc + SUMMARY)`.                                                                  |

### Key Link Verification

| From                                       | To                                | Via                                          | Status   | Details                                                                                                                                                            |
| ------------------------------------------ | --------------------------------- | -------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `PYTEST-XDIST-FIXTURE-AUDIT-v1020.md`      | Section 1 reproducibility         | shell-fenced commands a fresh operator runs  | ✓ WIRED  | Patterns `docker compose ps db`, `pytest -n auto.*--junitxml`, `pg_stat_activity` all appear (10 total matches; required ≥3).                                       |
| `PYTEST-XDIST-FIXTURE-AUDIT-v1020.md`      | Section 3 failure inventory       | markdown table of `path::TestClass::test_name` rows | ✓ WIRED  | 648 rows match function-or-class form regex. Sampled 5 node-IDs (test_insert_feature, test_share_idempotent, test_download_token_private_non_owner, test_truncation_at_5000, test_drop_column_owner_returns_200) — all grep-validated against working tree. |
| `REQUIREMENTS.md`                          | FI-01 row marked Complete         | atomic same-commit flip                      | ✓ WIRED  | `git diff-tree e40c4630` shows REQUIREMENTS.md + ROADMAP.md + 1087-SUMMARY.md all in commit (3 files exactly).                                                       |

### Behavioral Spot-Checks

Spike-only phase — no runnable code introduced. Behavioral checks operate on the audit doc shape rather than executable behavior.

| Behavior                                                       | Command                                                                                                                                | Result | Status |
| -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ------ | ------ |
| Five Section headings present                                  | `grep -cE "^## Section [12345] " PYTEST-XDIST-FIXTURE-AUDIT-v1020.md`                                                                  | 5      | ✓ PASS |
| Four hypothesis category names present                         | `grep -cE "Redis singleton state\|storage provider override\|app\.dependency_overrides leak\|autouse-fixture coupling" .../v1020.md`   | 8      | ✓ PASS |
| Section 3 row count equals frontmatter count                   | rows=`grep -cE "^\| \`backend/tests/.*\.py::(?:[A-Za-z_][A-Za-z0-9_]*::)?test_" .../v1020.md`; expect 648                              | 648    | ✓ PASS |
| Reproducibility-section anchor count ≥3                        | `grep -cE "docker compose ps db\|pytest -n auto.*--junitxml\|pg_stat_activity" .../v1020.md`                                            | 10     | ✓ PASS |
| Section 5 ordered list present                                 | `grep -cE "^[0-9]\. \*\*" Section-5-extract`; expect ≥4                                                                                | 5      | ✓ PASS |
| REQUIREMENTS.md FI-01 checkbox flipped                         | `grep -cE "^- \[x\] \*\*FI-01\*\*" REQUIREMENTS.md`                                                                                    | 1      | ✓ PASS |
| REQUIREMENTS.md FI-01 traceability row Complete                | `grep -cE "^\| FI-01 \| Phase 1087 \| Complete \|" REQUIREMENTS.md`                                                                    | 1      | ✓ PASS |
| ROADMAP.md Phase 1087 checkbox flipped                         | `grep -cE "^- \[x\] \*\*Phase 1087:" ROADMAP.md`                                                                                       | 1      | ✓ PASS |
| ROADMAP.md Plans line reads `1/1 plans complete`               | `grep -cE "^\*\*Plans\*\*: 1/1 plans complete" ROADMAP.md`                                                                              | 2      | ✓ PASS |
| TD-13 SAME-commit invariant                                    | `git diff-tree --no-commit-id --name-only -r e40c4630 \| grep -cE "(1087-SUMMARY\.md\|REQUIREMENTS\.md\|ROADMAP\.md)"`                  | 3      | ✓ PASS |
| Spike-only invariant (entire phase window)                     | `git diff 8977e5ff^..HEAD --name-only \| grep -v "^\.planning/" \| wc -l`                                                              | 0      | ✓ PASS |
| Random node-ID grep-validation (5 samples)                     | `git grep "def <test_name>" <path>` for 5 randomly sampled inventory rows                                                              | 5/5    | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan        | Description                                                                                                                                 | Status      | Evidence                                                                                                                                                                                                                                                            |
| ----------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| FI-01       | `1087-01-PLAN.md`  | Spike — measure and classify the 192 fixture-scope failures by root cause; commit audit doc before any fix code lands.                       | ✓ SATISFIED | Audit doc committed at `6c400062`; flipped `[x]` and Complete at `e40c4630`. Variance reconciliation in Section 2 explains why measurement found 648 vs the v1019 lower-bound estimate of 192 (ROADMAP SC #2 explicitly anticipates this: "≥ 192; spike may discover more or fewer"). |

No orphaned requirements — REQUIREMENTS.md maps only FI-01 to Phase 1087, and the plan declares FI-01.

### Anti-Patterns Found

No source-code files modified — anti-pattern scan returns clean. The audit doc itself contains illustrative Python-diff sketches with NEGATIVE markers (e.g., `# offending pattern observed in <fixture name>:` and `# Phase 1088 might fix toward:`) which are intentional documentation patterns, not stubs.

| File                                              | Line | Pattern                          | Severity | Impact                                                                                              |
| ------------------------------------------------- | ---- | -------------------------------- | -------- | --------------------------------------------------------------------------------------------------- |
| `PYTEST-XDIST-FIXTURE-AUDIT-v1020.md`             | 1042–1057 | `# offending pattern` / `# Phase 1088 might fix toward` | ℹ️ Info  | Illustrative diff sketches, not debt markers. Section 5 explicitly labels these "illustrative — Phase 1088 plan owns the actual shape choice". |

No `TBD`/`FIXME`/`XXX` debt markers found in modified files. No empty implementations, no console.log stubs.

### Probe Execution

No probes declared for this phase (spike-only, no executable code). The plan's `<verify><automated>` shell-gate chains have already been validated by the executor; this verifier re-ran a subset (see Behavioral Spot-Checks table). No conventional `scripts/*/tests/probe-*.sh` apply.

### Human Verification Required

The audit doc is large (1369 lines), but every machine-verifiable invariant has been confirmed via the spot-checks above. Section 4 narrative quality (whether the mechanism explanations are technically sound) is a judgment call, but:

- The dominant-category Section 4.1 explanation traces the `conftest.py:265-280` `except Exception: yield; return` silent-swallow path with a specific commit citation and reproducible mechanism.
- The hypothesis-miss explanations in Section 4.5-4.8 are appropriately speculative ("Possible reasons: (a)... (b)... (c)...") and explicitly mark themselves for Phase 1088 revisit if the dominant fix unmasks failures.
- Section 5's re-measure protocol (drop stale DBs → sequential baseline → parallel → re-categorize → cross-reference) is structurally rigorous and the right shape for cascade-category interaction.

No human verification items required. Section 4 narrative is technically coherent on file-citation review.

### Spike Outcome: Hypothesis Miss is a Correct Outcome

The user's verification instructions explicitly call this out: the four v1019 hypotheses produced 0 failures each, while the per-worker DB lifecycle race accounted for 407/648 = 62.8% of failures. **This is the correct outcome of a spike** — it validates that measurement-before-fix was the right discipline. Had Phase 1088 been planned to fix Redis singletons first (per the v1019 hypothesis ordering), 0 of the 648 failures would have closed.

Phase 1088's planner MUST consume Section 5's revised sequencing:
1. per-worker DB lifecycle race (lifecycle-race-first, NOT Redis-singleton-first)
2. setup-phase contention (with re-measure gate)
3. in-test contention (with re-measure gate)
4. teardown-phase (defer if 4.2 fix collapses it)
5. sandbox+assertion (verify-after-fix only)

The 192 → 648 reconciliation is documented in audit Section 2 "Variance from v1019 close-gate estimate" with two contributing-factor explanations.

### Gaps Summary

No gaps. All 5 ROADMAP success criteria PASS, all 6 plan-frontmatter must-haves PASS, all 12 behavioral spot-checks PASS. TD-13 SAME-commit invariant holds (verified via `git diff-tree`). Spike-only invariant holds across the entire phase window (verified via `git diff 8977e5ff^..HEAD`).

### Deferred Items

None. All work for Phase 1087 lands in 1087; Phase 1088 (fix code) is the explicit handoff target via Section 5's sequencing, which is intentional architecture rather than a deferred gap.

---

_Verified: 2026-05-22_
_Verifier: Claude (gsd-verifier)_
