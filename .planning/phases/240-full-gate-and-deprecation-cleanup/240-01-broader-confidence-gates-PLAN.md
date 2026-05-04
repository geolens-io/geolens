---
phase: 240-full-gate-and-deprecation-cleanup
plan: "01"
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/phases/240-full-gate-and-deprecation-cleanup/240-01-SUMMARY.md
  - docs-internal/audits/post-impl-20260504-v13-6.md
autonomous: true
requirements:
  - DEBT-01
must_haves:
  truths:
    - Broader backend confidence gates have exact recorded outcomes, including full backend pytest/coverage or the nearest locally runnable equivalent with any environmental blocker called out.
    - Frontend validation has exact recorded outcomes for build, lint, and test coverage, or an environmental blocker with the nearest equivalent evidence.
    - Playwright smoke/E2E coverage has an exact recorded outcome, or local prerequisite blockers are documented with enough detail to reproduce.
    - Any gate failure fixed during this plan is fixed forward with the smallest relevant patch, followed by rerunning the failed gate.
  artifacts:
    - path: .planning/phases/240-full-gate-and-deprecation-cleanup/240-01-SUMMARY.md
      provides: Broader backend/frontend/E2E gate evidence for DEBT-01
    - path: docs-internal/audits/post-impl-20260504-v13-6.md
      provides: Updated close-gate evidence showing broader gate outcomes or blockers
  key_links:
    - from: .planning/v13.6-MILESTONE-AUDIT.md
      to: .planning/phases/240-full-gate-and-deprecation-cleanup/240-01-SUMMARY.md
      via: TD-01 broader verification debt closure evidence
      pattern: "TD-01|DEBT-01"
    - from: backend/tests
      to: .planning/phases/240-full-gate-and-deprecation-cleanup/240-01-SUMMARY.md
      via: Full backend validation command output
      pattern: "pytest|test-cov|make test"
    - from: frontend
      to: .planning/phases/240-full-gate-and-deprecation-cleanup/240-01-SUMMARY.md
      via: Frontend build/lint/test validation command output
      pattern: "npm run build|npm run lint|npm run test:coverage"
    - from: e2e
      to: .planning/phases/240-full-gate-and-deprecation-cleanup/240-01-SUMMARY.md
      via: Playwright smoke or E2E command output
      pattern: "npm run e2e:smoke|npm run e2e"
---

<objective>
Close DEBT-01 by broadening the v13.6 close evidence beyond the focused maps/search backend suite.

Purpose: run the broader backend, frontend, and Playwright validation surface that the milestone audit identified as missing, fix only directly related gate failures, and record exact evidence or local prerequisite blockers.

Output: `240-01-SUMMARY.md` plus an update to `docs-internal/audits/post-impl-20260504-v13-6.md` summarizing broader gate outcomes.
</objective>

<execution_context>
@/Users/ishiland/.codex/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.codex/get-shit-done/templates/summary.md
@.agents/skills/geolens-test-audit/SKILL.md
@.agents/skills/geolens-smoke/SKILL.md
</execution_context>

<context>
@.planning/ROADMAP.md
@.planning/REQUIREMENTS.md
@.planning/STATE.md
@.planning/v13.6-MILESTONE-AUDIT.md
@docs-internal/audits/post-impl-20260504-v13-6.md

Phase 239 intentionally claimed only focused backend maps/search close-gate coverage. This plan closes the missing broader gate evidence from TD-01 / DEBT-01.

Known worktree constraint: unrelated user changes may exist outside the Phase 240 scope. Do not revert or commit unrelated frontend/docs edits.
</context>

<tasks>
<task type="auto">
  <name>Establish gate baseline</name>
  <files>.planning/phases/240-full-gate-and-deprecation-cleanup/240-01-SUMMARY.md</files>
  <action>Capture `git status --short --untracked-files=all` before running gates. Identify unrelated dirty files and exclude them from any commits unless a failing gate proves they are directly related to DEBT-01. Record whether Docker Compose DB, frontend dependencies, and Playwright browser dependencies are available.</action>
  <verify>
    <automated>git status --short --untracked-files=all</automated>
  </verify>
  <done>The summary records baseline worktree state and local gate prerequisites before validation commands run.</done>
</task>

<task type="auto">
  <name>Run backend confidence gates</name>
  <files>backend, .planning/phases/240-full-gate-and-deprecation-cleanup/240-01-SUMMARY.md</files>
  <action>Run the broadest practical backend gate from the repo's documented commands. Prefer `make test-cov`. If blocked by local prerequisites, run the nearest equivalent such as `make test`, `cd backend &amp;&amp; uv run ruff check .`, and `cd backend &amp;&amp; uv run ruff format --check .`; document the blocker. If a gate fails from a real v13.6 regression, fix forward in the smallest relevant backend file and rerun the failed command. Do not widen the maps/search decomposition scope.</action>
  <verify>
    <automated>make test-cov</automated>
    <automated>cd backend &amp;&amp; uv run ruff check .</automated>
    <automated>cd backend &amp;&amp; uv run ruff format --check .</automated>
  </verify>
  <done>Backend gate outcomes are recorded as pass/fail/blocker with rerun evidence for any fix-forward change.</done>
</task>

<task type="auto">
  <name>Run frontend confidence gates</name>
  <files>frontend, .planning/phases/240-full-gate-and-deprecation-cleanup/240-01-SUMMARY.md</files>
  <action>Run `cd frontend &amp;&amp; npm run build`, `cd frontend &amp;&amp; npm run lint`, and `cd frontend &amp;&amp; npm run test:coverage`. If dependencies are missing, run `cd frontend &amp;&amp; npm ci` first. If a gate is blocked by environment, document the exact blocker and nearest equivalent command evidence. Fix only gate failures directly attributable to current v13.6 work or Phase 240 cleanup; do not revert unrelated user changes.</action>
  <verify>
    <automated>cd frontend &amp;&amp; npm run build</automated>
    <automated>cd frontend &amp;&amp; npm run lint</automated>
    <automated>cd frontend &amp;&amp; npm run test:coverage</automated>
  </verify>
  <done>Frontend gate outcomes are recorded as pass/fail/blocker with rerun evidence for any fix-forward change.</done>
</task>

<task type="auto">
  <name>Run Playwright smoke or E2E gate</name>
  <files>e2e, .planning/phases/240-full-gate-and-deprecation-cleanup/240-01-SUMMARY.md</files>
  <action>Run the fastest meaningful browser gate, `npm run e2e:smoke`. If smoke is unavailable or blocked, document why and run the nearest local equivalent. Escalate to `npm run e2e` only if smoke is not representative and local prerequisites are already satisfied.</action>
  <verify>
    <automated>npm run e2e:smoke</automated>
  </verify>
  <done>Playwright smoke/E2E outcome is recorded as pass/fail/blocker with exact command evidence.</done>
</task>

<task type="auto">
  <name>Record broader gate evidence</name>
  <files>.planning/phases/240-full-gate-and-deprecation-cleanup/240-01-SUMMARY.md, docs-internal/audits/post-impl-20260504-v13-6.md</files>
  <action>Write `240-01-SUMMARY.md` with exact commands run, pass/fail/blocker status, fixes and rerun evidence, and residual risk. Update `docs-internal/audits/post-impl-20260504-v13-6.md` with a Phase 240 broader-gate evidence addendum for DEBT-01.</action>
  <verify>
    <automated>test -s .planning/phases/240-full-gate-and-deprecation-cleanup/240-01-SUMMARY.md</automated>
    <automated>rg -n "DEBT-01|broader|backend|frontend|Playwright|e2e" .planning/phases/240-full-gate-and-deprecation-cleanup/240-01-SUMMARY.md docs-internal/audits/post-impl-20260504-v13-6.md</automated>
  </verify>
  <done>The summary and close audit addendum contain enough evidence to disposition DEBT-01.</done>
</task>
</tasks>

<verification>

Required before summary completion:
- `test -s .planning/phases/240-full-gate-and-deprecation-cleanup/240-01-SUMMARY.md`
- `rg -n "DEBT-01|broader|backend|frontend|Playwright|e2e" .planning/phases/240-full-gate-and-deprecation-cleanup/240-01-SUMMARY.md docs-internal/audits/post-impl-20260504-v13-6.md`

</verification>
