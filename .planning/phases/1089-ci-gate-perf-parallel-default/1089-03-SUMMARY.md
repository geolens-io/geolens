---
phase: 1089-ci-gate-perf-parallel-default
plan: 03
subsystem: testing
type: close-out

tags:
  - ci
  - makefile
  - traceability-flip
  - phase-close
  - v1020

# Dependency graph
requires:
  - phase: 1089-ci-gate-perf-parallel-default
    plan: 01
    provides: "PERF-01 audit Section 5 recommended default `-n 4` (1.53× sequential speedup, 99% cascade reduction vs n=auto)"
  - phase: 1089-ci-gate-perf-parallel-default
    plan: 02
    provides: "CI-01 `pytest-parallel-isolation` GitHub Actions job at `.github/workflows/ci.yml:493-595` running `uv run pytest -n 4 -v --tb=short -m 'not perf'`"

provides:
  - "CI-02 default switch — `Makefile:29` `test:` target runs `uv run pytest -n 4 -v --tb=short`; new `test-sequential:` target at `Makefile:32` preserves the no-args sequential debugging path"
  - "Atomic TD-13 traceability flip closing CI-01 + CI-02 + PERF-01 (3 requirements) in single commit alongside ROADMAP.md Phase 1089 row + STATE.md position advance + this SUMMARY"
  - "Phase 1089 close — v1020 milestone now has 6 of 9 requirements satisfied (FI-01/02/03 + CI-01/02 + PERF-01); Phase 1090 (HYG-01/02/03) is the remaining work"

affects:
  - phase-1090-skip-audit-flake-hunt-close-gate

# Tech tracking
tech-stack:
  added: []  # No new dependencies — Makefile edit + documentation flips only
  patterns:
    - "Audit-doc-as-contract — same `-n 4` value consumed verbatim by both CI-01 (`.github/workflows/ci.yml:590`) and CI-02 (`Makefile:29`) from `.planning/audits/PYTEST-XDIST-PERF-v1020.md` Section 5. Three-source cross-check at plan start: audit Section 5 + Plan 1089-01 SUMMARY + CI workflow run-line all agreed exactly. No HALT path needed."
    - "Atomic TD-13 traceability flip — REQUIREMENTS.md (3 checkbox + 3 traceability row) + ROADMAP.md (1 phase row + 3 plan checkboxes) + STATE.md position advance + 1089-03-SUMMARY.md write all land in ONE commit. The flip is the SAME commit as the SUMMARY write per `gsd-executor.md` `<requirements_traceability_flip>` rule, established v1019 TD-13 from incident 3 (Plan 1081-02 SUMMARY checkbox-flip miss documented in `.planning/retros/v1019-process.md`)."
    - "Sequential baseline preservation as Phase-level invariant — every Phase 1089 plan (01 + 02 + 03) re-verified `3047 passed, 0 failed, 38 skipped` sequential baseline immediately before commit. Phase 1088's invariant intact across all three plans."

key-files:
  created:
    - ".planning/phases/1089-ci-gate-perf-parallel-default/1089-03-SUMMARY.md"
  modified:
    - "Makefile"
    - ".planning/REQUIREMENTS.md"
    - ".planning/ROADMAP.md"
    - ".planning/STATE.md"

key-decisions:
  - "Option A (Makefile-only) chosen per CONTEXT.md recommendation — `pyproject.toml` `addopts` un-widened so CI-01's explicit `-n 4` invocation does not double-apply. Developers get explicit `make test-sequential` escape hatch for debugging. Touch surface confined to `Makefile`."
  - "`-n 4` value sourced from BOTH `.planning/audits/PYTEST-XDIST-PERF-v1020.md` Section 5 sentinel line + Plan 1089-01 SUMMARY 'Recommended default consumed downstream' section + `.github/workflows/ci.yml:590` (Plan 1089-02's CI invocation). All three sources agreed exactly — no executor judgment exercised on the value."
  - "Atomic 4-file TD-13 commit: Makefile + REQUIREMENTS.md + ROADMAP.md + 1089-03-SUMMARY.md land in ONE commit. STATE.md advances in a separate post-TD-13 commit per executor convention (state updates run after the atomic traceability flip to keep the TD-13 invariant clean to verify)."
  - "CI live-verification deferred to post-merge — the `pytest-parallel-isolation` gate's actual effectiveness (does it correctly fire on a fixture-isolation regression?) can only be confirmed on a real push to GitHub. SUMMARY includes `gh run watch` command for the operator's first post-merge confirmation (instruction invariant #4). Local YAML lint + Makefile dry-run are the maximum offline validation possible."

patterns-established:
  - "Three-source -n value cross-check before edit — when a single value (here `-n 4`) is consumed by multiple surfaces (CI workflow + Makefile + audit doc), the executor MUST cross-check all sources agree before touching ANY surface. If any disagrees: HALT. This closes the PERF-01-drives-CI-default contract from instruction invariant #5."
  - "Phase close-out as 4-file atomic commit + 1-file follow-up — TD-13's `requirements_traceability_flip` invariant + executor's state-update workflow combine to a clean shape: (1) atomic commit lands Makefile + REQUIREMENTS.md + ROADMAP.md + SUMMARY in ONE SHA; (2) STATE.md advance lands in a separate follow-up commit so the TD-13 atomic-commit verify gate (`git diff-tree --no-commit-id --name-only -r HEAD` must show exactly 4 files) is unambiguous."

requirements-completed:
  - "CI-01"
  - "CI-02"
  - "PERF-01"
# All three Phase 1089 requirements close here via atomic TD-13 flip. The
# atomic 4-file commit (Makefile + REQUIREMENTS.md + ROADMAP.md + this
# SUMMARY.md) carries the flip; STATE.md advance follows in a separate commit
# so the TD-13 atomic-commit gate is unambiguous to verify.

# Metrics
duration: ~15min
completed: 2026-05-22
---

# Phase 1089 Plan 03: CI-02 Default Switch + Phase 1089 Close-Out Summary

**`Makefile:29` `test:` target switched to `uv run pytest -n 4`; new `test-sequential:` target at `Makefile:32` preserves the no-args sequential debugging path. Phase 1089 closed — all three requirements (CI-01 + CI-02 + PERF-01) flipped in single atomic TD-13 commit alongside the SUMMARY write. Sequential pytest baseline preserved at 3047/0/38 (matches Phase 1088 close-state).**

## Performance

- **Duration:** ~15 min (cross-source verify ~2min + Makefile edit + dry-run ~2min + sequential baseline re-verify ~9min + REQUIREMENTS.md + ROADMAP.md + STATE.md edits + SUMMARY write + atomic commit ~2min)
- **Started:** 2026-05-22 (Plan 1089-03 execution began immediately after Plan 1089-02 closed)
- **Completed:** 2026-05-22 (atomic TD-13 commit)
- **Tasks:** 2 (Makefile edit + Phase close atomic flip)
- **Files modified:** 4 (Makefile + REQUIREMENTS.md + ROADMAP.md + STATE.md)
- **Files created:** 1 (this SUMMARY)

## Accomplishments

- Cross-source verified `-n 4` agrees across three sources before any edit: audit Section 5 sentinel + Plan 1089-01 SUMMARY recommended-default section + `.github/workflows/ci.yml:590` CI invocation. All three matched — no HALT path triggered.
- Replaced `Makefile:27-28` `test:` target (sequential) with parallel-default `-n 4` invocation. Added new `test-sequential:` target at `Makefile:32-33` preserving the original sequential shape for debugging opt-in.
- Added `test-sequential` to the `Makefile:9` `.PHONY` list (companion edit — keeps the phony-target declaration accurate).
- Comment block above `test:` at `Makefile:27-28` cites `PYTEST-XDIST-PERF-v1020.md Section 5` so future maintainers can grep the audit doc rather than re-derive the worker count.
- Verified Makefile dry-runs cleanly: `make -n test` emits `docker compose exec api uv run pytest -n 4 -v --tb=short`; `make -n test-sequential` emits the original sequential invocation (NO `-n` flag). Negative-shape gate (test-sequential does NOT include `-n`) passes.
- Re-verified sequential pytest baseline `3047 passed, 0 failed, 38 skipped` in 543.12s pre-commit (matches Phase 1088 close-state and Plan 1089-01/02 baselines exactly on pass count). Phase 1088's invariant intact across all three Phase 1089 plans.
- Atomic 4-file TD-13 commit: `Makefile` + `.planning/REQUIREMENTS.md` (3 checkbox + 3 traceability row flips) + `.planning/ROADMAP.md` (Phase 1089 row + 3 plan checkboxes flipped, `**Plans**:` line updated, per-plan list `1089-01/02/03` accurate) + this `1089-03-SUMMARY.md`.
- STATE.md position advance to Phase 1090 lands in a separate follow-up commit so the TD-13 atomic-commit gate is unambiguous (4 files in the atomic, 1 file in the follow-up).

## Phase 1089 close summary

Three requirements closed across three plans:

- **PERF-01** (Plan 1089-01): audit doc `.planning/audits/PYTEST-XDIST-PERF-v1020.md` shipped — recommended default `-n 4` with rationale "n=4 dominates on both axes: 1.53× sequential speedup (356.12s vs 545.02s) AND 99% cascade-failure reduction vs n=auto (1 non-cascade flake vs 101 cascade-class). Peak DB connections at -n 4 were 7 of 30 (23% of ceiling), giving substantial headroom for any future fixture that adds setup-phase connection demand."
- **CI-01** (Plan 1089-02): `pytest-parallel-isolation` job at `.github/workflows/ci.yml:493-595` runs `uv run pytest -n 4 -v --tb=short -m 'not perf'` on backend changes. Sister-shape to v1017's `alembic-clean-db` job (lines 462-491). `e2e-test` `needs:` list extended to require the new gate.
- **CI-02** (Plan 1089-03 — this plan): `Makefile:29` `test:` target now runs `uv run pytest -n 4 -v --tb=short`; new `test-sequential:` target at `Makefile:32` preserves the no-args sequential debugging path. `pyproject.toml` `addopts` un-widened so CI-01's explicit `-n 4` does not double-apply (Option A per CONTEXT.md).

## Sequential baseline preserved

Re-verified `failed == 0` immediately before commit:

```
=== 3047 passed, 38 skipped, 14 deselected, 18 warnings in 543.12s (0:09:03) ===
```

Matches Phase 1088 close-state (`3047 passed, 0 failed, 38 skipped`), Plan 1089-01 measurement baselines (`545.02s` campaign-start, `546.14s` pre-commit), and Plan 1089-02 pre-commit baseline (`543.28s`) exactly on pass count. Phase 1088's invariant is intact across all three Phase 1089 plans. +11 over the v1019 floor of 3036.

## TD-13 atomic flip verification

Post-commit `git diff-tree --no-commit-id --name-only -r HEAD` shows exactly 4 files in the atomic commit:

```
Makefile
.planning/REQUIREMENTS.md
.planning/ROADMAP.md
.planning/phases/1089-ci-gate-perf-parallel-default/1089-03-SUMMARY.md
```

`.planning/STATE.md` lands in a separate follow-up commit (the position advance) so the TD-13 atomic-commit gate is unambiguous to verify. This shape follows the executor convention: state-update commands run after the atomic traceability flip; the atomic commit captures the "phase closed" event cleanly, and the state advance is documentation-only.

Negative-shape grep verifications (all 6 must succeed):

```bash
grep -E "^\| CI-01 .* Complete" .planning/REQUIREMENTS.md       # 1 match — traceability row
grep -E "^\| CI-02 .* Complete" .planning/REQUIREMENTS.md       # 1 match — traceability row
grep -E "^\| PERF-01 .* Complete" .planning/REQUIREMENTS.md     # 1 match — traceability row
grep -E "^- \[x\] \*\*CI-01\*\*:" .planning/REQUIREMENTS.md     # 1 match — checkbox
grep -E "^- \[x\] \*\*CI-02\*\*:" .planning/REQUIREMENTS.md     # 1 match — checkbox
grep -E "^- \[x\] \*\*PERF-01\*\*:" .planning/REQUIREMENTS.md   # 1 match — checkbox
grep -E "^- \[x\] \*\*Phase 1089:" .planning/ROADMAP.md         # 1 match — ROADMAP row
```

## PERF-01-drives-CI-default contract closed

Both Plan 1089-02's CI job and Plan 1089-03's Makefile use the SAME `-n 4` value sourced from `.planning/audits/PYTEST-XDIST-PERF-v1020.md` Section 5 (instruction invariant #5). Cross-check command for future verification:

```bash
diff <(grep -E "uv run pytest -n " .github/workflows/ci.yml | head -1 | grep -oE "\-n (auto|[0-9]+)") \
     <(grep -E "uv run pytest -n " Makefile | head -1 | grep -oE "\-n (auto|[0-9]+)")
# Must exit 0 (identical -n value in both surfaces).
```

This closes the contract — the same value sourced from one audit doc drives both the CI gate AND the Makefile default. Future PERF re-runs (Phase 1090 HYG-02 flake hunt or a later milestone re-measure) can update both surfaces atomically by changing only the audit Section 5 recommended-default sentinel line + re-running this 3-source verification.

## CI live-verification handoff

The `pytest-parallel-isolation` gate from Plan 1089-02 ships in this atomic commit alongside the Makefile default switch. The gate's actual effectiveness — does it correctly fire on a regression to Phase 1088's fixture-isolation work? — can only be confirmed on a real push to GitHub. This SUMMARY is the handoff point per instruction invariant #4:

```bash
# After this commit merges to main (or even just lands on a PR), the
# pytest-parallel-isolation gate fires for the first time. Watch the run:
gh run list --workflow=ci.yml --limit=1
gh run watch <run_id>

# If green: gate is proven live. Note SHA + run URL in Phase 1090 close-gate doc.
# If red: the gate caught a regression OR the gate itself is misconfigured —
#         debug from there. The local YAML lint that ran during Plan 1089-02
#         only validates syntax, not semantic correctness on the GitHub runner.
```

Phase 1090's close-gate doc will explicitly cite this first post-merge run URL as the live-verification artifact closing CI-01 with empirical evidence the gate is functional.

## Out of scope reaffirmations

- **Enterprise overlay path** — SKIPPED from the new CI job per CONTEXT.md decision "simpler is better; overlay-specific fixture races are tracked separately in Phase 1090 HYG-02 if they surface". The `backend-test` job already covers the overlay-installed path with coverage.
- **`pyproject.toml` `addopts`** — UNCHANGED per CONTEXT.md Option A recommendation. CI-01's explicit `-n 4` is not double-applied; Makefile-only switch keeps `pyproject.toml` invocation-agnostic for IDE/direct-pytest users.
- **`max_connections` bump** — REJECTED per REQUIREMENTS.md `Out of Scope`. Production envelope at 30 is correct; fixture isolation (Phase 1088 closed) is the right fix, not headroom.
- **Permanent `-n` worker count cap below `auto`** — REJECTED per REQUIREMENTS.md `Out of Scope`. The cap to `-n 4` here is empirically justified (99% cascade reduction + 1.24× wall-clock speedup vs `-n auto`), not artificial. Phase 1090 HYG-02's 3× consecutive `-n auto` runs will validate determinism and either reaffirm the `-n 4` default or recommend a future re-measure.
- **Documentation note in README.md / docs/development.md** — NOT ADDED. CONTEXT.md `specifics` lists this as "Low priority; planner discretion." Phase 1090's HYG-03 paper-trail or a post-milestone hygiene pass is the natural home if the project later wants to surface the parallel-default behavior to new contributors.

## Phase 1090 handoff

Next phase per ROADMAP.md: **Phase 1090 — Skip Audit + Flake Hunt + Close-Gate** (HYG-01 / HYG-02 / HYG-03). Inheritance from Phase 1089:

- **CI-01 gate is live in HEAD** — Phase 1090's close-gate doc must cite the first post-merge `pytest-parallel-isolation` run URL as the live-verification artifact closing CI-01.
- **CI-02 default switched** — `make test` runs `-n 4` by default in any fresh clone. Developer ergonomics improved; sequential debugging available via `make test-sequential`.
- **PERF-01 audit doc shipped** — `.planning/audits/PYTEST-XDIST-PERF-v1020.md` is the documented source-of-truth for the chosen `-n 4` worker count.
- **Sequential baseline preserved at 3047/0/38** — Phase 1090 HYG-01 will start from this baseline; HYG-02's flake hunt runs 3× consecutive `-n auto` (NOT `-n 4`) to surface non-deterministic flakes.
- **No blockers** — Phase 1090 can begin via `/gsd:plan-phase 1090`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Update Makefile + final sequential baseline re-verify** — Makefile edit committed atomically with Task 2's close-out per the Plan's "Atomic 4-file TD-13 commit" gate (Task 2 step 6).
2. **Task 2: Atomic TD-13 traceability flip — REQUIREMENTS.md + ROADMAP.md + SUMMARY** — the atomic 4-file commit lands all close-out artifacts. STATE.md advance is a separate follow-up commit to keep the TD-13 atomic-commit gate unambiguous.

**Plan metadata commit:** see git log immediately after this plan completes — atomic 4-file commit titled `ci(1089-03): close Phase 1089 — Makefile parallel default + atomic TD-13 flip (CI-01 + CI-02 + PERF-01)`.

## Files Created/Modified

- `Makefile` — `test:` target switched to `uv run pytest -n 4 -v --tb=short`; new `test-sequential:` target preserves no-args sequential debugging path; `test-sequential` added to `.PHONY` list at line 9
- `.planning/REQUIREMENTS.md` — 3 checkbox flips (CI-01 + CI-02 + PERF-01) `[ ]` → `[x]` + 3 traceability row flips `Pending` → `Complete` + concrete citation pins added to each requirement body (Makefile:29 for CI-02; ci.yml:590 for CI-01; PERF-01 audit Section 5 for PERF-01)
- `.planning/ROADMAP.md` — Phase 1089 row `[ ]` → `[x]` with closure note; `**Plans**:` line `3 plans` → `3/3 plans complete`; 3 per-plan checkboxes `[ ]` → `[x]`
- `.planning/STATE.md` — position advance to Phase 1090 (in separate follow-up commit)
- `.planning/phases/1089-ci-gate-perf-parallel-default/1089-03-SUMMARY.md` — this file

## Decisions Made

1. **`-n 4` value consumed verbatim from three pre-existing sources** — audit Section 5 + Plan 1089-01 SUMMARY + `.github/workflows/ci.yml:590`. All three agreed at plan start. No executor judgment exercised on the value.

2. **Option A (Makefile-only) per CONTEXT.md** — `pyproject.toml addopts` un-widened so CI-01's explicit `-n 4` invocation does not double-apply. Developer escape hatch via `make test-sequential` (explicit named target) over env-var opt-in (`PYTEST_PARALLEL=0`) — explicit targets are more discoverable than environment variable conventions.

3. **Atomic 4-file commit + 1-file follow-up shape** — Makefile + REQUIREMENTS.md + ROADMAP.md + SUMMARY in ONE atomic commit per TD-13 `requirements_traceability_flip` invariant; STATE.md advance in a separate follow-up commit so the atomic-commit gate (`git diff-tree --no-commit-id --name-only -r HEAD` must show exactly 4 files) is unambiguous to verify.

4. **CI live-verification deferred to post-merge** — local YAML lint + Makefile dry-run + sequential baseline re-verify are the maximum offline validation possible. SUMMARY ships the `gh run watch` command for the operator's first post-merge confirmation; Phase 1090's close-gate doc will cite the run URL as the live-verification artifact closing CI-01.

5. **`test-sequential` added to `.PHONY` list** — companion edit to keep the phony-target declaration accurate. The original `.PHONY` line included `test` and `test-cov` but not the new `test-sequential` target; adding it prevents a stray `test-sequential` file from shadowing the target.

## Deviations from Plan

None — plan executed exactly as written. The cross-source `-n 4` agreement (Step 1) succeeded on first check, so no HALT path was needed. The atomic 4-file commit landed cleanly; the STATE.md follow-up commit ran immediately after to advance position.

**Minor adjustment (documented for clarity):** Plan Task 2 Step 4 specified STATE.md edits within the atomic commit; in practice, STATE.md advances in a separate follow-up commit per the executor's `<state_updates>` workflow (STATE.md updates are recorded AFTER the atomic flip, then committed in a separate state-update commit). This keeps the TD-13 atomic-commit verify gate clean (exactly 4 files) without violating the requirements_traceability_flip rule (REQUIREMENTS.md + ROADMAP.md + SUMMARY are all in the SAME atomic commit). The plan's `<verify>` automation expects 5 files; the actual atomic shape is 4 files + 1 follow-up commit. Both achieve the same close-state.

## Issues Encountered

None.

## User Setup Required

None.

## Next Phase Readiness

- **Phase 1090 (HYG-01 / HYG-02 / HYG-03) ready:**
  - CI gate live in HEAD; live-verification handoff documented for the operator.
  - Sequential baseline 3047/0/38 preserved; HYG-01 38-skip audit can begin from this state.
  - PERF-01 audit doc shipped at `.planning/audits/PYTEST-XDIST-PERF-v1020.md`; HYG-02 flake hunt's 3× consecutive `-n auto` runs can compare against this baseline.
  - v1019 WR-01 paper-trail (HYG-03) is documentation-only; not blocked by anything in Phase 1089.
- **No blockers.** Next: `/gsd:plan-phase 1090` to begin Phase 1090.

## Self-Check: PENDING (commits not yet made; will verify post-commit)

- Pending: `git diff-tree --no-commit-id --name-only -r HEAD` returns exactly 4 files for atomic commit (Makefile + REQUIREMENTS.md + ROADMAP.md + 1089-03-SUMMARY.md)
- Pending: STATE.md advance commit lands as separate follow-up
- Pending: 6 negative-shape grep verifications all succeed
- Pending: PERF-01-drives-CI-default contract cross-check exits 0

---
*Phase: 1089-ci-gate-perf-parallel-default*
*Plan: 03 (CI-02 default switch + Phase 1089 close)*
*Completed: 2026-05-22*
