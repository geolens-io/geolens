---
created: 2026-05-07
closed: 2026-05-07T21:38:28Z
status: closed
shipped_in: v13.13
title: e2e/dataset-detail.spec.ts L144 — replace conditional fixture with deterministic prelude
area: testing
resolves_phase: 278
files:
  - e2e/dataset-detail.spec.ts
parent_finding: H-33 (v13.12 test-audit)
target_milestone: v13.13 (TEST-10, Phase 278)
---

## Closure note (2026-05-07)

**Closed in v13.13 Phase 278 Plan 06 (TEST-10) — Path A (stabilize via API fixture).**

The L144 `test.skip(...)` in `e2e/dataset-detail.spec.ts` has been re-enabled. The
racy UI-driven fill-prelude (lines 152-181 in the prior shape) was replaced with a
deterministic API-seeded fixture that PATCHes `/api/datasets/{id}` with a
known-unique `summary` value before the UI assertions begin. The prelude no longer
contains conditional `if visible : noop : fill` branches, so the editable-field
state machine starts from a known-good baseline on every run.

**Path-A rationale (alternative-coverage check):** Path B (delete with rationale)
was viable — `frontend/src/pages/__tests__/DatasetPage.edit-affordances.test.tsx`
covers all three asserted behaviors at the vitest layer: (a) pending-edits-bar
appears on draft change → save mutates with correct payload + clears the bar;
(b) pending-edits-bar appears on draft change → cancel clears the bar; (c)
viewer-role users see `data-editable="false"` shell + click-to-reveal denial hint.
`PendingEditsBar.test.tsx` (4 tests) covers the bar component in isolation;
`EditableFieldShell.test.tsx` (3 tests) covers the role-denied hint flow. So the
behaviors are not exclusively tested by L144.

The plan's checkpoint guidance defaults to Path A when the test is stabilizable
("a perpetually-skipped test is worse than no test"); the API fixture path is
viable (PATCH route at `backend/.../router.py:262` accepts `DatasetMeta` body,
requires `edit_metadata`, the storage-state admin auth has all permissions), so
Path A was selected. The E2E test now serves as a real-network/real-DB
belt-and-suspenders complement to the vitest coverage.

**Consecutive-run verification: DEFERRED to reviewer.** No Playwright MCP browser
tools were available in the executor environment and the global `playwright`
binary is not on PATH at the executor's CWD level. The plan's Path A clause
explicitly permits a provisional merge in this case ("the executor MUST document
the deferred-verification command in SUMMARY for the human reviewer, and the work
merges as `provisional — needs reviewer Playwright run`"). The reviewer should
run, against a healthy local stack (api on :8001, frontend on :8080, db healthy):

```bash
# From repo root, with playwright/.auth/user.json in place:
for i in 1 2 3 4 5; do
  npx playwright test e2e/dataset-detail.spec.ts -g "editable markers" --project=chromium
done
```

5 consecutive green runs confirms the fixture stabilization. If any run fails,
investigate root cause — do NOT add `test.retry()` to mask flake; revert to Path B
(delete) instead.

**Acceptance from this todo (1-3 of original ## Acceptance):**
- [x] L144 test re-enabled (no `test.skip()`)
- [ ] Test passes 10+ consecutive runs locally — DEFERRED to reviewer Playwright run
- [x] No new flaky-test M-findings introduced (the API fixture removes the only
      named race; no new conditional waits added)

**Commit:** see Phase 278 Plan 06 SUMMARY (commit hash captured at plan close).

## Problem

Phase 269 H-33 closure deleted one obsolete `test.skip()` (L226 — UI never shipped, `edit-context-option-*` testIds don't exist anywhere) but left the L144 skip in place with a documented rationale. The L144 test depends on a conditional fill-prelude that races against the editable-field state machine: the test attempts to set up the dataset into a known editable state via UI interactions, but those interactions are racy under headless E2E execution and intermittently leave the state machine in the wrong context.

The pragmatic short-term fix in v13.12 was to keep the test skipped rather than commit a flaky test. The longer-term fix is to replace the conditional fill-prelude with a deterministic fixture (e.g., seed the dataset directly into editable-context state via API, then drive the test scenario from there).

## Solution

1. Replace the conditional `if (...) await page.fill(...)` prelude in `e2e/dataset-detail.spec.ts` around L144 with a deterministic fixture that:
   - Seeds the test dataset via API (`POST /datasets` or fixture loader) into the exact state the test asserts against
   - Sets the editable-context to the correct value via API or direct store write
   - Drops the UI-driven prelude entirely
2. Re-enable the test (remove the `test.skip()` wrapper)
3. Verify via local Playwright run that the test is deterministic across 10+ consecutive runs before merging
4. If the test surfaces a real editable-field/validation regression once enabled, file as a separate finding and either fix or document — do NOT commit a broken test

## Context

- Source finding: H-33 in `.planning/audits/v13.12/test-audit.md`
- Closing commit: `04fb3208` (Phase 269 FIX-TEST-01)
- Filed as a follow-up because v13.12 was a hardening milestone, not a test-suite-rewrite milestone
- Recommended target: next test-cleanup milestone (whenever that lands), or fold into a broader E2E-deflake initiative if scope expands

## Acceptance

- L144 test re-enabled (no `test.skip()`)
- Test passes 10+ consecutive runs locally
- No new flaky-test M-findings introduced
