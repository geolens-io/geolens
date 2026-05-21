---
phase: quick-260319-r4t
plan: 01
subsystem: testing
tags: [audit, coverage, testing, vitest, pytest, playwright]
dependency_graph:
  requires: []
  provides: [TEST-COVERAGE-REPORT]
  affects: []
tech_stack:
  added: []
  patterns: []
key_files:
  created:
    - .planning/quick/260319-r4t-review-test-coverage-and-create-a-plan-t/TEST-COVERAGE-REPORT.md
  modified: []
decisions:
  - "No coverage thresholds currently enforced in CI"
  - "Frontend at 22% statement coverage, backend has 90 test files for 189 modules"
  - "Phase 1 quick wins (thresholds + fix failing tests) estimated at 1-2 hours"
metrics:
  duration: 3min
  completed: 2026-03-19
---

# Quick Task 260319-r4t: Test Coverage Audit Summary

Full test coverage audit across backend pytest, frontend vitest, and Playwright e2e with prioritized 4-phase improvement plan.

## What Was Done

### Task 1: Run coverage collectors and audit test inventory

- Ran `vitest run --coverage` to collect actual v8 coverage numbers
- Audited all frontend directories for test file presence vs source file counts
- Catalogued 90 backend test files against 189 source modules
- Inventoried 10 e2e Playwright specs and identified missing flows
- Produced 342-line TEST-COVERAGE-REPORT.md with all 7 required sections

**Commit:** `0daff224`

## Key Findings

1. **Frontend overall:** 22.12% statements, 22.63% branches, 18.86% functions, 22.76% lines
2. **Well-tested areas:** stores (75%), layout (71%), lib (63%), auth components (58%)
3. **Major gaps:** API modules (12%), hooks (18%), pages (18%), admin (3%), collections (4%)
4. **16 of 17 API modules** have zero test coverage (only client.ts tested)
5. **22 of 27 hooks** are untested
6. **2 pre-existing test failures:** i18n parity (missing nav.importData key) and PageShell (py-6 changed to py-4)
7. **No coverage thresholds** enforced in CI

## Deviations from Plan

None -- plan executed exactly as written.

## Self-Check: PASSED

- [x] TEST-COVERAGE-REPORT.md exists (342 lines)
- [x] Commit 0daff224 verified
