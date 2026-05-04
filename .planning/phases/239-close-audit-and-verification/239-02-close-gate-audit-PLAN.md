---
phase: 239-close-audit-and-verification
plan: "02"
type: execute
wave: 2
depends_on:
  - 239-01
files_modified:
  - docs-internal/audits/post-impl-20260504-v13-6.md
  - .planning/phases/239-close-audit-and-verification/239-VERIFICATION.md
  - .planning/phases/239-close-audit-and-verification/239-02-SUMMARY.md
autonomous: true
requirements:
  - QUAL-03
must_haves:
  truths:
    - The dated v13.6 close-gate audit records decomposition results for Phases 236, 237, and 238 plus the focused verification results from Plan 01.
    - The audit includes requirement coverage for all v13.6 requirements, with QUAL-01, QUAL-02, and QUAL-03 explicitly dispositioned.
    - The audit records residual risks and confirms no unresolved P0 or P1 findings remain before marking v13.6 closed.
    - GSD workflow state transitions remain owned by the execute-phase orchestrator after phase verification passes.
  artifacts:
    - path: docs-internal/audits/post-impl-20260504-v13-6.md
      provides: Dated v13.6 close-gate audit report
    - path: .planning/phases/239-close-audit-and-verification/239-VERIFICATION.md
      provides: Phase 239 verification record with QUAL-01, QUAL-02, and QUAL-03 results
    - path: .planning/phases/239-close-audit-and-verification/239-02-SUMMARY.md
      provides: Plan execution summary for close-gate and traceability updates
  key_links:
    - from: .planning/phases/236-maps-service-decomposition/236-VERIFICATION.md
      to: docs-internal/audits/post-impl-20260504-v13-6.md
      via: Maps decomposition evidence and MAPS-01..06 coverage
      pattern: "MAPS-0[1-6]"
    - from: .planning/phases/237-search-service-decomposition/237-VERIFICATION.md
      to: docs-internal/audits/post-impl-20260504-v13-6.md
      via: Search decomposition evidence and SRCH-01..06 coverage
      pattern: "SRCH-0[1-6]"
    - from: .planning/phases/238-boundary-guards-and-contract-stabilization/238-VERIFICATION.md
      to: docs-internal/audits/post-impl-20260504-v13-6.md
      via: Boundary guard evidence and BOUND-01..04 coverage
      pattern: "BOUND-0[1-4]"
    - from: .planning/phases/239-close-audit-and-verification/239-01-SUMMARY.md
      to: docs-internal/audits/post-impl-20260504-v13-6.md
      via: Focused pytest and ruff/format verification evidence for QUAL-01 and QUAL-02
      pattern: "QUAL-0[12]|ruff|test_maps.py|test_search.py"
    - from: docs-internal/audits/post-impl-20260504-v13-6.md
      to: .planning/phases/239-close-audit-and-verification/239-VERIFICATION.md
      via: Close status, residual risks, and P0/P1 disposition
      pattern: "QUAL-03|no unresolved P0/P1"
---

<objective>
Create the v13.6 close-gate audit after focused verification passes.

Purpose: record the decomposition results, requirement coverage, residual risks, and final close decision for v13.6 without losing the evidence from Phases 236-239.
Output: a dated close audit, Phase 239 verification record, and plan summary. The execute-phase workflow performs roadmap, requirements, and state transitions after verification passes.
</objective>

<execution_context>
@/Users/ishiland/.codex/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.codex/get-shit-done/templates/summary.md
@.agents/skills/geolens-post-impl/SKILL.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/REQUIREMENTS.md
@.planning/STATE.md
@.planning/phases/236-maps-service-decomposition/236-VERIFICATION.md
@.planning/phases/237-search-service-decomposition/237-VERIFICATION.md
@.planning/phases/238-boundary-guards-and-contract-stabilization/238-VERIFICATION.md
@.planning/phases/239-close-audit-and-verification/239-01-SUMMARY.md
@docs-internal/audits/post-impl-20260503-v13-4.md
@docs-internal/audits/post-impl-20260503-v13-5.md

<close_gate_rules>
Use the Phase 235 close-gate pattern, adapted to v13.6:
- Scope is v13.6 implementation surface from Phases 236, 237, 238, and the focused Phase 239 verification plan.
- The close audit must not mark the milestone verified unless Plan 01 gates passed or any blockers are explicitly resolved and rerun.
- Every P0/P1 finding must be fixed inline or deferred with a named backlog entry and rationale. An unresolved P0/P1 blocks close.
- Roadmap, requirements, and state updates are left to the execute-phase workflow after phase verification passes.
- Do not edit source code in this plan. If source changes are needed, mark this plan blocked and send execution back to a focused fix-forward plan.
</close_gate_rules>
</context>

<tasks>
<task type="auto">
  <name>Write the dated v13.6 close-gate audit</name>
  <files>docs-internal/audits/post-impl-20260504-v13-6.md</files>
  <action>Read the Phase 236, 237, and 238 verification records plus `239-01-SUMMARY.md`. Write a findings-first close audit at `docs-internal/audits/post-impl-20260504-v13-6.md` in the style of the v13.4/v13.5 post-impl close audits. Required sections: scope and close status; worktree/evidence baseline; maps decomposition result; search decomposition result; boundary guard result; focused verification result; requirement coverage table for MAPS-01..06, SRCH-01..06, BOUND-01..04, and QUAL-01..03; findings with severity, area, evidence, and disposition; residual risks; verification commands; milestone close status. The audit must explicitly state whether unresolved P0/P1 findings exist. If Plan 01 is missing or blocked, write the audit as blocked and do not proceed to planning status updates.</action>
  <verify>
    <automated>test -s docs-internal/audits/post-impl-20260504-v13-6.md</automated>
    <automated>rg -n "MAPS-01|MAPS-06|SRCH-01|SRCH-06|BOUND-01|BOUND-04|QUAL-01|QUAL-02|QUAL-03" docs-internal/audits/post-impl-20260504-v13-6.md</automated>
    <automated>rg -n "no unresolved P0/P1|No unresolved P0 or P1|MILESTONE CLOSE VERIFIED|MILESTONE CLOSE BLOCKED" docs-internal/audits/post-impl-20260504-v13-6.md</automated>
  </verify>
  <done>The dated audit exists, covers decomposition results and all v13.6 requirement IDs, records residual risks, and clearly states pass or blocked close status based on P0/P1 disposition.</done>
</task>

<task type="auto">
  <name>Create Phase 239 verification record</name>
  <files>.planning/phases/239-close-audit-and-verification/239-VERIFICATION.md</files>
  <action>If the close audit is verified and has no unresolved P0/P1 findings, create `239-VERIFICATION.md` with passed status, requirement-by-requirement results for QUAL-01 through QUAL-03, exact commands from Plan 01, audit path, findings, residual risks, and any blocked or limited checks. If the audit is blocked, create a blocked `239-VERIFICATION.md` and name the unresolved close blocker. Do not edit `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, or `.planning/STATE.md`; the execute-phase workflow owns those transitions after phase verification passes.</action>
  <verify>
    <automated>test -s .planning/phases/239-close-audit-and-verification/239-VERIFICATION.md</automated>
    <automated>rg -n "QUAL-01: passed|QUAL-02: passed|QUAL-03: passed|docs-internal/audits/post-impl-20260504-v13-6.md" .planning/phases/239-close-audit-and-verification/239-VERIFICATION.md</automated>
  </verify>
  <done>Phase 239 verification records QUAL-01 through QUAL-03 and either passes based on the audit evidence or names the unresolved close blocker.</done>
</task>

<task type="auto">
  <name>Write close-gate execution summary</name>
  <files>.planning/phases/239-close-audit-and-verification/239-02-SUMMARY.md</files>
  <action>Create `239-02-SUMMARY.md` using the GSD summary template. Include the audit path, final close status, P0/P1 disposition, QUAL-03 result, verification file updated, and any residual risks. Mention explicitly that roadmap, requirements, and state transitions are left to the execute-phase workflow after phase verification.</action>
  <verify>
    <automated>test -s .planning/phases/239-close-audit-and-verification/239-02-SUMMARY.md</automated>
    <automated>rg -n "post-impl-20260504-v13-6.md|QUAL-03|P0/P1|execute-phase workflow|239-VERIFICATION.md" .planning/phases/239-close-audit-and-verification/239-02-SUMMARY.md</automated>
    <automated>node /Users/ishiland/.codex/get-shit-done/bin/gsd-tools.cjs verify plan-structure .planning/phases/239-close-audit-and-verification/239-02-close-gate-audit-PLAN.md</automated>
  </verify>
  <done>`239-02-SUMMARY.md` gives execute-phase enough evidence to close or route the phase based on the close-gate result.</done>
</task>
</tasks>

<verification>
- `test -s docs-internal/audits/post-impl-20260504-v13-6.md`
- `rg -n "MAPS-01|MAPS-06|SRCH-01|SRCH-06|BOUND-01|BOUND-04|QUAL-01|QUAL-02|QUAL-03" docs-internal/audits/post-impl-20260504-v13-6.md`
- `rg -n "no unresolved P0/P1|No unresolved P0 or P1|MILESTONE CLOSE VERIFIED|MILESTONE CLOSE BLOCKED" docs-internal/audits/post-impl-20260504-v13-6.md`
- `test -s .planning/phases/239-close-audit-and-verification/239-VERIFICATION.md`
- `test -s .planning/phases/239-close-audit-and-verification/239-02-SUMMARY.md`
- `node /Users/ishiland/.codex/get-shit-done/bin/gsd-tools.cjs verify plan-structure .planning/phases/239-close-audit-and-verification/239-02-close-gate-audit-PLAN.md`
</verification>

<success_criteria>
- QUAL-03 is satisfied by a dated v13.6 close-gate audit that records decomposition results, requirement coverage, residual risks, and no unresolved P0/P1 findings.
- Phase 239 verification records QUAL-01, QUAL-02, and QUAL-03 results using Plan 01 evidence and the close audit.
- `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, and `.planning/STATE.md` are left to the execute-phase workflow after verification passes.
</success_criteria>

<output>
After completion, create `.planning/phases/239-close-audit-and-verification/239-02-SUMMARY.md`.
</output>
