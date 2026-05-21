---
phase: quick-260322-ljk
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/STATE.md
autonomous: true
requirements:
  - AUDIT-VERIFY

must_haves:
  truths:
    - "Playwright e2e suite runs against live dev environment without selector failures"
    - "260322 vector detail map audit status is updated to Verified"
    - "260319-qu1 detail data page map audit status is updated to Verified"
  artifacts:
    - path: ".planning/STATE.md"
      provides: "Updated audit statuses"
      contains: "Verified"
  key_links:
    - from: "e2e/dataset-detail.spec.ts"
      to: "http://localhost:8080"
      via: "Playwright test runner"
      pattern: "openAdminCountriesDataset"
---

<objective>
Run the Playwright e2e suite to confirm both outstanding audit gaps (260322 vector detail map, 260319-qu1 detail data page map) are resolved, then update their statuses in STATE.md.

Purpose: Close out the two remaining non-Verified audits from the v12.3 follow-up series.
Output: Passing e2e results, updated STATE.md with Verified statuses.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/260322-ljk-resolve-outstanding-audit-gaps-260322-ve/260322-ljk-RESEARCH.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Run Playwright e2e suite and verify both audits pass</name>
  <files>e2e/dataset-detail.spec.ts, e2e/search.spec.ts</files>
  <action>
Run the Playwright e2e suite against the live Docker dev environment (localhost:8080). Focus on the specs most relevant to the two audits:

1. Delete `playwright/.auth/` if it exists to avoid stale JWT tokens.

2. Run the core dataset-detail and search specs first:
   ```
   npx playwright test e2e/dataset-detail.spec.ts e2e/search.spec.ts --project=chromium
   ```
   These cover the 260322 gaps (selector fixes, dataset navigation) and 260319-qu1 items 1 and 5 (vector rendering, edit geometry).

3. If those pass, run the full suite (excluding record-detail-ux-audit.spec.ts which depends on qa-targets.json with potentially stale UUIDs):
   ```
   npx playwright test --project=chromium --ignore-pattern="record-detail-ux-audit"
   ```

4. If any tests fail due to issues OTHER than the two audited gaps, note them but do not block the audit closure -- those are separate concerns.

5. Capture the test results summary (pass/fail counts) for the SUMMARY.

Per research: selectors were already fixed by 260320-m42. Multi-part geometry fix is in place with unit tests. This task is verification, not implementation.
  </action>
  <verify>
    <automated>npx playwright test e2e/dataset-detail.spec.ts --project=chromium 2>&1 | tail -5</automated>
  </verify>
  <done>dataset-detail.spec.ts passes all non-skipped tests (2 of 3, test 3 is intentionally skipped). Search spec passes. Full suite results captured.</done>
</task>

<task type="auto">
  <name>Task 2: Update audit statuses in STATE.md</name>
  <files>.planning/STATE.md</files>
  <action>
Update the Quick Tasks Completed table in STATE.md to change the status of two audits:

1. Find the row for `260322` (vector detail page map, currently "Gaps") and change status to "Verified".
2. Find the row for `260319-qu1` (detail data page map, currently "Needs Review") and change status to "Verified".

Only update these two rows. Do not modify any other content in STATE.md.

If Task 1 revealed any failing tests unrelated to these audits, add a note to the Blockers/Concerns section documenting which tests failed and why (as a future investigation item).
  </action>
  <verify>
    <automated>grep -E "260322.*Verified|260319-qu1.*Verified" .planning/STATE.md | wc -l | tr -d ' '</automated>
  </verify>
  <done>Both audit rows show "Verified" status. grep returns count of 2.</done>
</task>

</tasks>

<verification>
- Playwright dataset-detail spec passes 2/3 tests (1 intentionally skipped)
- STATE.md shows "Verified" for both 260322 and 260319-qu1 audits
- No regressions introduced (no code changes, only status updates)
</verification>

<success_criteria>
- E2e suite confirms selectors work and dataset detail tests pass
- Both audit statuses updated from Gaps/Needs Review to Verified in STATE.md
</success_criteria>

<output>
After completion, create `.planning/quick/260322-ljk-resolve-outstanding-audit-gaps-260322-ve/260322-ljk-SUMMARY.md`
</output>
