---
phase: 1051
plan: 12
type: execute
wave: 12
depends_on: ["1051-11"]
files_modified:
  - .planning/phases/1051-map-builder-polish-bug-sweep/FINDINGS.md
autonomous: false
requirements: [EMRG-01]
tags: [builder, triage, emergent-findings, hygiene]

must_haves:
  truths:
    - "FINDINGS.md exists at .planning/phases/1051-map-builder-polish-bug-sweep/FINDINGS.md"
    - "Every emergent finding surfaced during Plans 01-11 Playwright MCP passes has a per-finding entry (id, title, severity, scope, fix-now-vs-defer decision, rationale, follow-up disposition)"
    - "Every FIX-NOW finding has a referenced commit hash"
    - "Every DEFER finding has a referenced PROJECT.md tech-debt entry OR a pending todo at .planning/todos/pending/"
    - "If zero emergent findings, FINDINGS.md still exists with an explicit '0 emergent findings' note + timestamp + 'verified during Plan 01-11 Playwright MCP passes' rationale"
  artifacts:
    - path: ".planning/phases/1051-map-builder-polish-bug-sweep/FINDINGS.md"
      provides: "Per-finding triage matrix following v1009.1 FINDINGS.md shape"
      contains: "EMRG-FN-"
  key_links:
    - from: "Plans 01-11 Playwright MCP scratch list"
      to: "FINDINGS.md per-finding entries"
      via: "Orchestrator aggregates findings during execution; Plan 12 formalizes the matrix"
      pattern: "EMRG-FN-"
---

<objective>
Fix EMRG-01: Triage any additional Map Builder issues surfaced during Playwright MCP inspection of Plans 01-11. Per ROADMAP Plan 12 + critical_planning_directive #8 + PATTERNS.md Plan 12 reference shape (v1009.1 `.planning/quick/260515-cej-docker-rebuild-builder-smoke/FINDINGS.md`):

This is a POLICY-ONLY plan from the planner's POV — the planner authors the FINDINGS.md placeholder + triage protocol. The orchestrator maintains a running scratch list of emergent findings during Plans 01-11 (each plan's Playwright MCP step surfaces unrelated issues to scratch). When Plan 12 runs, the orchestrator dumps the scratch list into FINDINGS.md following the matrix described in <interfaces>.

Known seed findings (pre-planning notes that should appear if not already addressed):
- Plan 11 INV-01 SUMMARY references sibling no-op callbacks in `MapBuilderPage.tsx:801-810` (`onStrokeColorChange`, `onStrokeWidthChange`, `onCasingColorChange`, `onCasingWidthChange`, `onZoomChange`) — all share the same "Phase 1038 TODO" comment. These are confirmed dead wiring NOT covered by INV-01's scope. Triage candidate: DEFER (out of v1011 scope per REQUIREMENTS.md Out-of-Scope row 1) → file a pending todo or PROJECT.md tech-debt entry.

If zero additional findings surface, the FINDINGS.md still exists with the explicit "0 emergent" note per ROADMAP success criterion #5.

Purpose: Make emergent triage decisions explicit and traceable; prevent quiet defer or quiet fix without paper trail.
Output: FINDINGS.md authored with the canonical per-finding matrix; cross-links to fix-now commits or defer tracking entries.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/1051-map-builder-polish-bug-sweep/1051-CONTEXT.md
@.planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md

<interfaces>
<!-- FINDINGS.md document template — all markdown shapes the executor must produce. -->

Top of file (header structure):

```markdown
# Phase 1051 — Emergent Findings (EMRG-01)

**Authored:** <YYYY-MM-DD>
**Plan:** 1051-12
**Reviewed against:** Plans 01-11 Playwright MCP scratch list + per-plan SUMMARY entries

## Summary

- Total emergent findings: <N>
- Fix-now: <X>
- Defer: <Y>

## Findings

(one EMRG-FN-NN entry per finding using the template below)
```

Per-finding entry template (from PATTERNS.md Plan 12 reference shape):

```markdown
## EMRG-FN-NN: <Title>

- **Severity:** P0 / P1 / P2
- **Scope:** <surface + flow — e.g., "BasemapSublayerEditorScene onStrokeColorChange (MapBuilderPage.tsx:802-810)">
- **Disposition:** fix-now / defer
- **Rationale:** <one-paragraph reasoning>
- **Follow-up:** <commit hash if fix-now; target file path or todo path if defer>
- **Discovered during:** <Plan NN Playwright MCP step>
```

Seed entry (if orchestrator confirmed it surfaced during Plan 11):

```markdown
## EMRG-FN-01: BasemapSublayerEditorScene no-op style callbacks (Phase 1038 TODO)

- **Severity:** P2 (parallel-shaped issue to INV-01 but covers stroke/casing/zoom rather than detail-level)
- **Scope:** MapBuilderPage.tsx:801-830 — onStrokeColorChange, onStrokeWidthChange, onCasingColorChange, onCasingWidthChange, onZoomChange all carry the same `TODO(Phase 1038): markDirty() once sublayer styling is persisted` comment; all are no-op stubs.
- **Disposition:** defer
- **Rationale:** Same shape as INV-01 (dead wiring). REMOVE OR FIX requires either deletion of the entire BasemapSublayerEditorScene OR implementation of sublayer style persistence (Phase 1038 work, 3-5 days). Out of v1011 hygiene scope per REQUIREMENTS.md Out-of-Scope row 1.
- **Follow-up:** Add a tech-debt entry to PROJECT.md "Known Limitations" or a pending todo at `.planning/todos/pending/basemap-sublayer-style-persistence.md` citing v1011 INV-01 as the related finding.
- **Discovered during:** Plan 11 Task 1 grep enumeration
```

Zero-findings shape (use INSTEAD of per-finding entries when no emergent findings surfaced):

```markdown
## 0 emergent findings

Playwright MCP inspection passes for plans 01-11 surfaced no unrelated regressions.
Verified <date> on <commit hash> against the v1010.2 baseline.
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Aggregate scratch findings + author FINDINGS.md</name>
  <files>.planning/phases/1051-map-builder-polish-bug-sweep/FINDINGS.md</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 12 reference shape)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-11-SUMMARY.md (the INV-01 summary; check for the flagged sibling no-op callbacks finding)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-01-SUMMARY.md through 1051-10-SUMMARY.md (check each for incidental observations the orchestrator added to scratch during MCP passes)
    - .planning/quick/260515-cej-docker-rebuild-builder-smoke/FINDINGS.md (v1009.1 reference shape — confirm before authoring)
    - PROJECT.md Out-of-Scope section (for defer destination if applicable)
  </read_first>
  <action>
    Author `.planning/phases/1051-map-builder-polish-bug-sweep/FINDINGS.md` using the document templates supplied in `<interfaces>`. Steps:

    (1) Write the top-of-file header per the "Top of file" template in `<interfaces>` — substitute today's date and the counts for N/X/Y after Step 2.

    (2) For EACH finding aggregated from the orchestrator's running scratch list (built up during Plans 01-11 MCP passes), write a per-finding entry using the "Per-finding entry" template in `<interfaces>`. Assign sequential ids EMRG-FN-01, EMRG-FN-02, etc.

    (3) Apply severity assignment rules:
    - P0: blocks shipping (user-facing functional break — must fix-now)
    - P1: degraded UX or maintainability (fix-now preferred; defer with justification acceptable)
    - P2: polish/cleanup (defer is fine; tracked for future milestone)

    (4) Apply disposition rules:
    - P0 → ALWAYS fix-now (before CTRL-01 gate); reference its inline commit hash in the entry
    - P1 → default fix-now; orchestrator may defer with rationale if scope/time-bound; defer requires a tracking artifact (todo OR PROJECT.md)
    - P2 → default defer; track via pending todo OR PROJECT.md tech-debt entry

    (5) The Plan 11 SUMMARY may have flagged the sibling no-op callbacks (`onStrokeColorChange` etc.) for triage. If recorded, include them as EMRG-FN-01 using the "Seed entry" template in `<interfaces>` (severity P2, disposition defer, rationale referencing INV-01's REMOVE precedent, follow-up creating either a PROJECT.md tech-debt entry OR a pending todo). If Plan 11 did NOT surface this finding (orchestrator decision), do not synthesize it from this plan.

    (6) For each DEFER entry, also create the referenced tracking artifact in the same task:
    - Append a tech-debt bullet to PROJECT.md under "Known Limitations" / "Out-of-Scope" / "Future Tasks" (choose the section that fits scope), OR
    - Create a pending todo at `.planning/todos/pending/<finding-slug>.md` with the v1011 source citation.

    (7) If the orchestrator's scratch list is EMPTY (zero emergent findings), use the "Zero-findings shape" template in `<interfaces>` INSTEAD of per-finding entries — substitute today's date and the current commit hash.

    NOTE: This task only AGGREGATES + WRITES the matrix. Fix-now COMMITS are made during Plans 01-11 execution by the orchestrator — Plan 12 only references their hashes.
  </action>
  <verify>
    <automated>test -f .planning/phases/1051-map-builder-polish-bug-sweep/FINDINGS.md && grep -cE 'EMRG-FN-|0 emergent' .planning/phases/1051-map-builder-polish-bug-sweep/FINDINGS.md</automated>
  </verify>
  <acceptance_criteria>
    - FINDINGS.md exists at the canonical path
    - File contains either ≥1 EMRG-FN-NN entry OR the explicit "0 emergent findings" note with timestamp
    - Every fix-now finding (if any) references a commit hash in its "Follow-up" line
    - Every defer finding references either a PROJECT.md update OR a pending todo file in its "Follow-up" line
    - Severity assignment present on each entry
    - Summary counts (N total / X fix-now / Y defer) match the actual per-entry dispositions
  </acceptance_criteria>
  <done>FINDINGS.md authored; per-finding triage complete.</done>
</task>

<task type="auto">
  <name>Task 2: Atomic summary commit (FINDINGS.md + any defer tracking artifacts)</name>
  <files>(commit only — stages files modified in Task 1 + any defer tracking artifacts authored)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/FINDINGS.md (the file just authored)
    - PROJECT.md (if updated for defer tracking)
    - .planning/todos/pending/ (if any new todo files created)
  </read_first>
  <action>
    Stage `.planning/phases/1051-map-builder-polish-bug-sweep/FINDINGS.md` and any defer-tracking files authored during Task 1 (PROJECT.md updates, pending todos). Per `feedback_no_blanket_add_planning.md`: do NOT use `git add -fA .planning/`; stage specific files by name. Use `git add -f` for the FINDINGS.md since `.planning/` is gitignored. Create the atomic commit with subject `chore(1051): EMRG-01 emergent-findings triage (<X> fix-now, <Y> defer)` (or `chore(1051): EMRG-01 emergent-findings triage (0 emergent)` for the zero-findings case). FIX-NOW commits are separate per-finding commits created during Plans 01-11; this commit is for FINDINGS.md + defer tracking only.
  </action>
  <verify>
    <automated>git log --oneline -1 && git show --stat HEAD</automated>
  </verify>
  <acceptance_criteria>
    - Commit exists with subject matching `chore(1051): EMRG-01 emergent-findings triage \(.*\)`
    - `git diff HEAD~1 HEAD --stat` shows ONLY FINDINGS.md + (optionally) PROJECT.md + (optionally) .planning/todos/pending/<file>.md
    - No source files modified in this commit
    - `git add -fA` was NOT used (only specific paths)
  </acceptance_criteria>
  <done>Triage committed atomically.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| docs-only | This plan modifies only documentation/triage files; no code or API changes |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1051-12 | (n/a) | FINDINGS.md | accept | No security surface; pure documentation |
</threat_model>

<verification>
- FINDINGS.md exists with per-finding entries or explicit 0-emergent note
- Defer-tracking artifacts exist for every defer entry
- Atomic commit subject matches the (X, Y) count
</verification>

<success_criteria>
- FINDINGS.md exists at canonical path
- Every finding has severity, scope, disposition, rationale, follow-up
- Every fix-now finding cites a commit hash (created during Plans 01-11)
- Every defer finding cites a tracking artifact (PROJECT.md or pending todo)
- If zero findings, the explicit 0-emergent note is present with timestamp
- Atomic commit on main with subject `chore(1051): EMRG-01 emergent-findings triage (<X> fix-now, <Y> defer)`
</success_criteria>

<output>
Create `.planning/phases/1051-map-builder-polish-bug-sweep/1051-12-SUMMARY.md` with: total finding count, severity breakdown, fix-now vs defer split, list of fix-now commit hashes, list of defer tracking artifacts.
</output>
