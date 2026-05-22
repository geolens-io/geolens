---
phase: 1090-skip-audit-flake-hunt-close-gate
plan: 01
subsystem: test-infrastructure
tags: [hygiene, flake-hunt, paper-trail, close-gate-prep, v1020]
requirements_in_progress: [HYG-01, HYG-02, HYG-03]  # final flip in Plan 1090-02 atomic close
status: complete
date: 2026-05-22
head_sha: 78f8bf6593740d3de7cbabf8e88a23c4d09a0138
---

# Phase 1090 Plan 1090-01: HYG Measurements + Close-Gate Working Draft Summary

Hygiene measurements only — no REQUIREMENTS.md flip, no ROADMAP.md flip, no CHANGELOG.md
edit (Plan 1090-02 owns the atomic close commit + tag cuts).

## One-Liner

Plan 1090-01 produced `1090-01-CLOSE-GATE.md` with HYG-01 38-skip audit + HYG-02 6-run flake hunt + HYG-03 WR-01 paper-trail draft, all sequential baselines clean (3047/0/38).

## What Shipped

### HYG-01 — Sequential skip audit

- **38 sequential-mode skips dispositioned** in `1090-01-CLOSE-GATE.md` Section HYG-01.
- **Disposition split:** 38 KEEP · 0 FIX · 0 REMOVE.
- **Taxonomy:**
  - 11 × `ogr2ogr binary not available` (host env without GDAL) → KEEP, runs in backend Docker image + CI
  - 16 × `geolens_enterprise package is not installed` (SAML overlay enterprise-only) → KEEP
  - 4 × lifecycle SAML enterprise (same `geolens_enterprise` skip) → KEEP
  - 3 × `Set SEC_AUDIT_PUBLIC_DATASET_ID` (opt-in security audit, env-gated) → KEEP
  - 2 × `Titiler not reachable` (raster tile service, docker-stack-only) → KEEP
  - 1 × `geolens_cli imports failed` (Backend Tests CI doesn't install CLI deps) → KEEP
  - 1 × `No test DB available` (defensive guard, static-source assertions cover) → KEEP
- All 38 skips are intentional environment/edition gates. None represent dead code.

### HYG-02 — Flake hunt (6 measurement runs)

- **3× `pytest -n auto` (16-worker stress test):**
  - auto-1: 66 failed / 24 errors / 405.27s / 351 cascade raw-lines / 89 unique failing+error
  - auto-2: 51 failed / 18 errors / 415.01s / 277 cascade raw-lines / 69 unique failing+error
  - auto-3: 52 failed / 11 errors / 419.78s / 235 cascade raw-lines / 62 unique failing+error

- **3× `pytest -n 4` (PERF-01 CI default validation):**
  - n4-1: 0 failed / 0 errors / 332.57s / 0 cascade raw-lines / 0 unique failing+error
  - n4-2: 0 failed / 0 errors / 331.38s / 0 cascade raw-lines / 0 unique failing+error
  - n4-3: 0 failed / 0 errors / 330.43s / 0 cascade raw-lines / 0 unique failing+error

- **Cross-run determinism:**
  - `-n auto`: 6 deterministic flake-class (fail every run) + 173 non-deterministic
    (fail 1-2 of 3 runs)
  - `-n 4`: 0 common + 0 non-deterministic → **PERF-01 `-n 4` validated**

- **Phase 1088 4.3 residual disposition:** Confirmed flake-class deterministic; **defer to v1021 engine-level retry** per Phase 1088-04 architectural escalation. The `-n 4` CI gate handles operational defense (0 failures in 3 consecutive runs).

### HYG-03 — WR-01 paper-trail draft

- **Text drafted** in `1090-01-CLOSE-GATE.md` Section HYG-03 for Plan 1090-02 CHANGELOG `[1.5.5]` incorporation.
- **Grep-verified citations:**
  - `frontend/package.json:23` `"lint:sec-fu-03-no-false-positive"` present at HEAD
  - `frontend/package.json:22` companion `"lint:sec-fu-03-regression"` present at HEAD
- **NOT YET COMMITTED to CHANGELOG.md** — Plan 1090-02 owns the atomic close commit.

## Hard Invariants Preserved

- ✅ Sequential pytest baseline `failed == 0` re-verified at **Task 1 start** (3047/0/38, 542.39s).
- ✅ Sequential pytest baseline `failed == 0` re-verified at **Task 2 end** (post-HYG-02 mid-check).
- ✅ NO REQUIREMENTS.md / ROADMAP.md / CHANGELOG.md edit (Plan 1090-02 owns the TD-13 atomic flip).
- ✅ NO production code change outside `.planning/`.

## Measurement Artifacts (all at `/tmp/v1090-*`)

- `/tmp/v1090-seq-pre.log` — sequential baseline pre-HYG-02 (Task 1 hard gate; 3047/0/38)
- `/tmp/v1090-seq-skip-collect.log` — `pytest -v` SKIPPED line capture (Task 1 Step 2)
- `/tmp/v1090-collect-only.log` — collection-only listing (correlation for collection-time skip)
- `/tmp/v1090-skip-reasons.log` — `pytest --co -rs` for collection-time skip reason
- `/tmp/v1020-skip-lines.log` — extracted `SKIPPED` lines for HYG-01 grep gate
- `/tmp/v1090-hyg02-{auto,n4}-{1,2,3}.log` — HYG-02 6 measurement logs
- `/tmp/v1090-{auto-1,auto-2,auto-3,n4-1,n4-2,n4-3}-{failures,errors,all}.txt` — per-run extracts
- `/tmp/v1090-{auto,n4}-{common,union,nondeterministic}.txt` — cross-run determinism analysis
- `/tmp/v1090-seq-post.log` — sequential baseline post-HYG-02 (Task 2 Step 8 mid-check)

## NEGATIVE-shape gate result

`git diff --name-only HEAD` shows only:
- `.planning/phases/1090-skip-audit-flake-hunt-close-gate/1090-01-CLOSE-GATE.md`
- `.planning/phases/1090-skip-audit-flake-hunt-close-gate/1090-01-SUMMARY.md`

No REQUIREMENTS.md / ROADMAP.md / CHANGELOG.md / production-code files touched.

## Plan 1090-02 Handoff

Plan 1090-02 consumes `1090-01-CLOSE-GATE.md` as the working draft and:

1. **Full close-gate matrix run** (~30 min):
   - Sequential pytest (target: 3047/0/38)
   - Parallel pytest `-n 4` (target: 0 failures, validated 3 consecutive runs in HYG-02)
   - Frontend typecheck (target: exit 0)
   - Vitest (target: matches v1019 baseline)
   - e2e:smoke:builder (target: 25/0/1 matching v1019)
   - Playwright MCP 5/5 surfaces driven by orchestrator per `--use-playwright-mcp` flag

2. **TD-13 SAME-commit atomic close** (4-file commit):
   - `.planning/REQUIREMENTS.md` — flip HYG-01 + HYG-02 + HYG-03 checkboxes + traceability rows
   - `.planning/ROADMAP.md` — flip Phase 1090 ✅ + Plans `2/2 plans complete` + v1020 milestone ✅
   - `.planning/phases/1090-skip-audit-flake-hunt-close-gate/1090-SUMMARY.md` — phase close summary
   - `CHANGELOG.md` — `[Unreleased]` → `[1.5.5] - 2026-05-22` with full v1020 block including HYG-03 paper-trail line

3. **Tag cuts** at close SHA:
   - `git tag v1020 -m "v1020 Fixture Isolation milestone close"`
   - `git tag v1.5.5 -m "v1.5.5 - Fixture Isolation hygiene (no user-facing features)"`
   - Verify both at same SHA: `test "$(git rev-parse v1020)" = "$(git rev-parse v1.5.5)"`

4. **STATE.md advance** as a separate commit AFTER tag cuts.

## Atomic two-file commit

Files committed by Plan 1090-01:
- `.planning/phases/1090-skip-audit-flake-hunt-close-gate/1090-01-CLOSE-GATE.md`
- `.planning/phases/1090-skip-audit-flake-hunt-close-gate/1090-01-SUMMARY.md`

Commit message: `docs(1090-01): HYG-01 38-skip audit + HYG-02 6-run flake hunt + HYG-03 WR-01 paper-trail draft`

## Self-Check: PASSED

All claims in this SUMMARY verifiable from `1090-01-CLOSE-GATE.md` row counts + measurement artifacts at `/tmp/v1090-*`. Grep gates verified inline during execution:

- **HYG-01 (section-aware count):** `awk '/^## HYG-02/{exit} /^\| tests\//{count++} END{print count}' close-gate.md` = 38 ✅ matches the 38 collected skips (37 from `pytest -v` + 1 from `pytest --co -rs` collection-time skip).
- **HYG-01 (literal grep from PLAN.md verify):** `grep -cE "^\| tests/" close-gate.md` = 44 (includes 6 deterministic-flake-class rows in HYG-02 table). The literal grep gate as written in PLAN.md `<grep_gates>` 1 over-counts because HYG-02 was not anticipated to introduce additional `| tests/` table rows. The semantic gate (every collected skip has a row) is satisfied — see section-aware count above. Documented for Plan 1090-02 to fold into the close-gate matrix verify pattern.
- **HYG-02 grep gate:** `grep -cE "^\| (auto|n4)-[1-3] \|" close-gate.md` = 6 ✅ (3 auto + 3 n4).
- **HYG-03 grep gate:** Both `lint:sec-fu-03-no-false-positive` and `frontend/package.json:23` substrings present ✅.
- **NEGATIVE-shape gate:** `git diff --cached --name-only` returns only `.planning/phases/1090-...` files (no REQUIREMENTS.md / ROADMAP.md / CHANGELOG.md / production-code touched) ✅.
- **Sequential baseline at start:** 3047 passed / 0 failed / 38 skipped in 542.39s ✅
- **Sequential baseline at end (post-HYG-02):** 3047 passed / 0 failed / 38 skipped in 544.75s ✅
