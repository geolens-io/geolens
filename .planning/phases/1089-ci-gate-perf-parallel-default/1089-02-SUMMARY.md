---
phase: 1089-ci-gate-perf-parallel-default
plan: 02
subsystem: ci
type: ci-gate-wiring

tags:
  - ci
  - github-actions
  - pytest-xdist
  - regression-gate
  - v1020

# Dependency graph
requires:
  - phase: 1089-ci-gate-perf-parallel-default
    plan: 01
    provides: "PERF-01 audit Section 5 recommended default `-n 4` (1.53× sequential speedup, 99% cascade reduction vs n=auto)"
  - phase: 1088-fixture-isolation-fixes-regression-pins
    provides: "Fixture-isolation infrastructure (NullPool branch, 5s stagger, lifecycle race fix) that this gate defends against regression"

provides:
  - "New `pytest-parallel-isolation` GitHub Actions job in `.github/workflows/ci.yml` running `uv run pytest -n 4 -v --tb=short -m 'not perf'`"
  - "`e2e-test` job needs-list update to require the new gate (forward-compatibility — `e2e-test` is currently `if: false` but will require this gate when re-enabled)"

affects:
  - 1089-03-ci-02-makefile-default-and-traceability-flip

# Tech tracking
tech-stack:
  added: []  # No new dependencies — CI workflow YAML edit only
  patterns:
    - "Audit-doc-as-contract — the new job's `-n 4` value is consumed verbatim from `.planning/audits/PYTEST-XDIST-PERF-v1020.md` Section 5 (PERF-01 baseline). Downstream plan grep-extracts the value rather than re-deriving it."
    - "Sister-shape CI job pattern — the new `pytest-parallel-isolation` job mirrors `backend-test`'s env + Postgres + Python+uv + migrations shape (lines 292-410), but replaces the coverage step with a single `pytest -n 4` invocation. Same trunk, different leaf. Matches v1017's `alembic-clean-db` sister-shape precedent."
    - "Forward-compat needs-list wiring — `e2e-test` is currently disabled (`if: false`), but the `needs:` list is extended now so when e2e is re-enabled in the future the gate is automatically a required check."

key-files:
  created:
    - ".planning/phases/1089-ci-gate-perf-parallel-default/1089-02-SUMMARY.md"
  modified:
    - ".github/workflows/ci.yml"

key-decisions:
  - "PERF_N = 4 sourced from BOTH the audit Section 5 sentinel line `Recommended default for CI-01 + CI-02: \\`-n 4\\`` AND Plan 1089-01 SUMMARY 'Recommended default consumed downstream' section. Both sources agree exactly — no halt needed."
  - "Job triggers on `backend == 'true' || alembic == 'true' || github.event_name == 'push'` — `alembic` filter included because Phase 1088's NullPool branch + 5s stagger interact with migration timing; a future alembic change could regress fixture-setup race characteristics."
  - "Enterprise overlay path SKIPPED from the new job — per CONTEXT.md decision 'simpler is better; overlay-specific fixture races are tracked separately in Phase 1090 HYG-02 if they surface'. The `backend-test` job already exercises the overlay-installed path with coverage; this gate is a regression-pin for the fixture-isolation work, not a coverage gate."
  - "REQUIREMENTS.md CI-01 row STAYS `Pending` in this plan's commit — atomic traceability flip for CI-01 + CI-02 + PERF-01 is deferred to Plan 1089-03 per TD-13 `requirements_traceability_flip` rule + instruction invariant #3. Verified via `grep -E '^\\| CI-01 .* Pending' .planning/REQUIREMENTS.md` (exactly one match)."
  - "CI live-verification deferred — the gate's actual effectiveness can only be confirmed on a real push to GitHub. Plan 1089-03's SUMMARY will reference the first post-merge CI run as the live-verification artifact with a `gh run watch <run_id>` command for the operator."

patterns-established:
  - "PERF→CI handoff via grep-able sentinel — Plan 1089-02 consumed `-n 4` deterministically from Plan 1089-01's audit Section 5 sentinel line (`Recommended default for CI-01 + CI-02: \\`-n 4\\``) AND the SUMMARY's 'Recommended default consumed downstream' section. Both sources cross-verified before edit. This is the contract that instruction invariant #5 codifies (PERF-01-drives-CI-default)."
  - "Atomic CI-job insertion at a stable insertion point — the new job is inserted between `alembic-clean-db` (lines 462-491) and `# ---------- frontend ----------` (line 493 pre-edit), which is the canonical sister-job placement per v1017 precedent. No surrounding lines modified; YAML lint passes."

requirements-completed: []
# CI-01 is SATISFIED by this plan's deliverable (the new GitHub Actions job in
# .github/workflows/ci.yml) but the traceability flip in REQUIREMENTS.md is
# DEFERRED to Plan 1089-03's atomic TD-13 commit (alongside CI-02 + PERF-01
# flips). This plan ships the deliverable; the requirement row flips when ALL
# three Phase 1089 requirements are simultaneously satisfied (per TD-13
# atomicity invariant + instruction invariant #3).

# Metrics
duration: ~25min
completed: 2026-05-22
---

# Phase 1089 Plan 02: CI-01 Pytest Parallel Isolation Job Summary

**Added the `pytest-parallel-isolation` GitHub Actions job to `.github/workflows/ci.yml` running `uv run pytest -n 4 -v --tb=short -m 'not perf'` — the regression gate that prevents future fixture-isolation regressions to Phase 1088's work. `-n 4` value consumed verbatim from Plan 1089-01's PERF-01 audit Section 5 recommendation (1.53× sequential speedup with 1 non-cascade flake vs n=auto's 101 cascade-class failures).**

## Performance

- **Duration:** ~25 min (sequential baseline re-verify ~9min + audit/SUMMARY/CI cross-reads ~5min + YAML edit + lint ~3min + Task 2 close steps ~8min)
- **Started:** 2026-05-22T15:15Z (sequential baseline re-verify began)
- **Completed:** 2026-05-22T15:40Z (atomic commit)
- **Tasks:** 2 (Task 1: resolve PERF_N + write the CI job; Task 2: re-verify sequential + commit + write SUMMARY)
- **Files modified:** 1 (`.github/workflows/ci.yml`, +100/-1)
- **Files created:** 1 (this SUMMARY)

## Accomplishments

- Resolved `PERF_N = 4` from BOTH `.planning/audits/PYTEST-XDIST-PERF-v1020.md` Section 5 sentinel line AND Plan 1089-01 SUMMARY's "Recommended default consumed downstream" section — sources agreed exactly, no HALT needed.
- Inserted the `pytest-parallel-isolation` job at line 493 in `.github/workflows/ci.yml` (between `alembic-clean-db` block ending at line 491 and `# ---------- frontend ----------` comment).
- Job shape mirrors `backend-test`'s env + Postgres + Python+uv + migrations setup, replaces the coverage step with `uv run pytest -n 4 -v --tb=short -m 'not perf'`, and uses `timeout-minutes: 30`.
- Extended `e2e-test` `needs:` list at line ~641 to include `pytest-parallel-isolation` in second backend position (between `backend-test` and `frontend-lint`).
- YAML lint passes: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` exits 0.
- Re-verified sequential pytest baseline TWICE — once before edits (HARD GATE per CONTEXT.md "Sequential baseline preservation") and once pre-commit. Both: `3047 passed, 0 failed, 38 skipped` in ~545s.

## Job specifics

- **Job name:** `pytest-parallel-isolation` (matches REQUIREMENTS.md CI-01 "sister to alembic-clean-db")
- **Trigger:** `if: needs.changes.outputs.backend == 'true' || needs.changes.outputs.alembic == 'true' || github.event_name == 'push'`
- **Shape mirror:** `backend-test` env + Postgres + Python+uv + alembic upgrade (no coverage; no enterprise overlay)
- **Test invocation:** `uv run pytest -n 4 -v --tb=short -m 'not perf'`
- **Timeout:** 30 minutes (vs alembic-clean-db's 15 — full pytest run needs more headroom)
- **Insertion point:** lines 493-595 in `.github/workflows/ci.yml` (post-edit line numbers)

## e2e-test needs update

The `e2e-test` job at line ~641 previously had:

```yaml
    needs: [backend-lint, backend-test, frontend-lint, frontend-test, security-scan]
```

Now reads:

```yaml
    needs: [backend-lint, backend-test, pytest-parallel-isolation, frontend-lint, frontend-test, security-scan]
```

`pytest-parallel-isolation` placed between `backend-test` and `frontend-lint` — keeps the backend cluster together. `e2e-test` is currently `if: false` (disabled per comment block at lines 632-636 because the dockerized stack + browser fixtures push CI minutes past the free-tier budget) so this is forward-compatibility wiring; when e2e is re-enabled it will require the parallel gate as a required check.

## CI live-verification deferred

The `pytest-parallel-isolation` gate's actual effectiveness — does it correctly fire on a regression to Phase 1088's fixture-isolation work? — can only be confirmed on a real push to GitHub. This plan ships only the YAML wiring; live verification is deferred to Plan 1089-03's SUMMARY which will reference the first post-merge CI run with a `gh run watch <run_id>` command for the operator (instruction invariant #4). The local YAML lint (`python3 -c "import yaml; yaml.safe_load(...)"`) is the maximum offline validation possible.

## Sequential baseline preserved

Re-verified `failed == 0` immediately before commit:

```
=== 3047 passed, 38 skipped, 14 deselected, 18 warnings in 543.28s (0:09:03) ===
```

Matches Phase 1088 close-state (3047 passed, 0 failed, 38 skipped) and Plan 1089-01's two re-verifies (545.02s / 546.14s campaign baselines) exactly on pass count. Phase 1088's invariant is intact.

## Traceability note

REQUIREMENTS.md `| CI-01 |` row STAYS `Pending` in this plan's commit. The atomic traceability flip for CI-01 + CI-02 + PERF-01 is deferred to Plan 1089-03's TD-13 commit per:
- `~/.claude/agents/gsd-executor.md` `<requirements_traceability_flip>` rule (atomicity invariant)
- Phase 1089 instruction invariant #3 (no row flip until atomic close-out)
- TD-13 paper trail (single-commit traceability flip for all phase requirements)

Verified via `grep -E '^\| CI-01 .* Pending' .planning/REQUIREMENTS.md` — exactly one match found.

## Skip-overlay decision documented

Per CONTEXT.md "CI-01 shape (LOCKED)" decision: the enterprise overlay path is SKIPPED from the new job ("simpler is better; overlay-specific fixture races are tracked separately in Phase 1090 HYG-02 if they surface"). The `backend-test` job already exercises the overlay-installed path WITH coverage (the `OVERLAY_INSTALLED=1` branch at lines 422-425 includes lifecycle markers). The new `pytest-parallel-isolation` gate is a regression-pin for the fixture-isolation work, not a coverage gate, so the overlay path adds complexity without testable surface this gate cares about.

## Task Commits

Each task was committed atomically:

1. **Task 1: Resolve PERF-01 recommended default + write the new CI job** — no separate commit (atomic with Task 2 per Plan Task 2 step 3)
2. **Task 2: Re-verify sequential baseline + commit + write SUMMARY** — atomic 2-file commit of `.github/workflows/ci.yml` + this SUMMARY

**Plan metadata commit:** see git log immediately after this plan completes.

## Files Created/Modified

- `.github/workflows/ci.yml` — +100 lines (new `pytest-parallel-isolation` job at lines 493-595) / -1 line (e2e-test needs list extended at line ~641)
- `.planning/phases/1089-ci-gate-perf-parallel-default/1089-02-SUMMARY.md` — this file

## Decisions Made

1. **`-n 4` value consumed verbatim from PERF-01 audit** — both sources (audit Section 5 sentinel line + Plan 1089-01 SUMMARY) agreed exactly. No tie-breaker needed; no executor judgment exercised on the value.

2. **Insertion point: lines 493-595 (between alembic-clean-db and `# ---------- frontend ----------`)** — canonical sister-job placement per v1017 precedent. Keeps the backend-shaped CI cluster contiguous.

3. **Forward-compat needs-list wiring** — `e2e-test` `needs:` list extended now even though `e2e-test` is currently `if: false`. When e2e is re-enabled, the gate is automatically a required check. Cost: 0; benefit: 1 fewer file edit when e2e re-enables.

4. **Enterprise overlay SKIPPED from new job** — per CONTEXT.md decision; the `backend-test` job already covers the overlay path with coverage.

5. **REQUIREMENTS.md CI-01 flip deferred** — per TD-13 + instruction invariant #3; atomic flip for all three Phase 1089 reqs ships in Plan 1089-03.

## Deviations from Plan

None — plan executed exactly as written. Both Step 1 sources (audit + SUMMARY) agreed on `-n 4` so no HALT path was needed. The YAML inserted matches the plan's "Step 2 Edit" block verbatim with the `<PERF_N>` placeholder substituted to `4` in both the comment block and the `run:` command.

## Issues Encountered

None.

## User Setup Required

None. Plan 1089-03 will perform the atomic TD-13 traceability flip for CI-01 + CI-02 + PERF-01 + reference the first post-merge CI run for live-verification.

## Next Phase Readiness

- **Plan 1089-03 (CI-02 + traceability flip) ready:**
  - `-n 4` is locked in `.github/workflows/ci.yml` (live in the new job) AND in the audit Section 5 sentinel AND in Plan 1089-01's frontmatter `recommended_default` field. Plan 1089-03 has 3 grep-able sources for the value.
  - REQUIREMENTS.md `CI-01` row is still `Pending`, ready for atomic flip alongside CI-02 + PERF-01.
  - Sequential baseline preserved (3047/0/38) — Phase 1088 invariant intact.
- **No blockers.** No code changes; no schema changes; no dependency changes; no production code touched.

## Self-Check: PASSED

- FOUND: `.github/workflows/ci.yml` — `pytest-parallel-isolation:` job present at line ~499 (post-edit)
- FOUND: `uv run pytest -n 4 -v --tb=short -m 'not perf'` invocation in the new job's `Run tests with -n 4` step
- FOUND: `needs: [backend-lint, backend-test, pytest-parallel-isolation, frontend-lint, frontend-test, security-scan]` at the `e2e-test` job needs line
- FOUND: `timeout-minutes: 30` in the new job
- VERIFIED: YAML parses cleanly (`python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` exit 0)
- VERIFIED: Sequential pytest baseline `3047 passed, 0 failed, 38 skipped in 543.28s` re-verified pre-commit
- VERIFIED: REQUIREMENTS.md `| CI-01 |` row still `Pending` (atomic flip deferred to Plan 1089-03)
- VERIFIED: HEAD commit touches exactly 2 files (`.github/workflows/ci.yml` + this SUMMARY)
- VERIFIED: No production code, Makefile, pyproject.toml, conftest.py, or frontend changes

---
*Phase: 1089-ci-gate-perf-parallel-default*
*Plan: 02 (CI-01 pytest-parallel-isolation job)*
*Completed: 2026-05-22*
