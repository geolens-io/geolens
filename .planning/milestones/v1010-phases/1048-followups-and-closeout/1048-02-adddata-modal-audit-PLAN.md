---
phase: 1048-followups-and-closeout
plan: 02
type: execute
wave: 2
depends_on:
  - 1048-01
files_modified:
  - .planning/phases/1048-followups-and-closeout/1048-ADDDATA-MODAL-AUDIT.md
autonomous: true
requirements:
  - FOLLOWUP-02
must_haves:
  truths:
    - "An audit document exists at the prescribed path covering BuilderDialogs.tsx (Add Data section), DatasetSearchPanel.tsx, and any AddData-specific helpers."
    - "Every finding is tagged P0 / P1 / P2 with file:line + recommended fix + Phase 1048-or-defer disposition."
    - "The audit explicitly verifies alignment with the v1008 unified-stack model — no leftover six-section assumptions remain in audited code."
    - "Any P0 finding that costs ≤1 hour is shipped inline in this plan; P0+ items over budget are flagged for a targeted follow-on plan with rationale; P1+P2 default to defer with rationale."
  artifacts:
    - path: .planning/phases/1048-followups-and-closeout/1048-ADDDATA-MODAL-AUDIT.md
      provides: "Classified findings (P0/P1/P2) + dispositions + six-section verification statement + v1008 alignment statement"
      contains: "P0|P1|P2|six-section|unified-stack"
  key_links:
    - from: 1048-ADDDATA-MODAL-AUDIT.md
      to: BuilderDialogs.tsx AddData section + DatasetSearchPanel.tsx
      via: "file:line citations in each finding"
      pattern: "BuilderDialogs\\.tsx:\\d+|DatasetSearchPanel\\.tsx:\\d+"
---

<objective>
Produce `1048-ADDDATA-MODAL-AUDIT.md` — a structured P0/P1/P2 finding document for the Add Data modal surface, mirroring Phase 1046's `BUILDER-CODE-AUDIT.md` pattern. Verify alignment with the v1008 unified-stack model (no leftover six-section assumptions from the pre-v1008 sidebar redesign). Ship any P0 inline if effort is ≤1 hour each; otherwise defer-with-rationale.

Purpose: FOLLOWUP-02 closes a known carry-over. The Add Data modal has not been audited since v1008 unified-stack landed, and there is no record document showing whether the modal still carries pre-v1008 structural assumptions (the legacy "six-section" sidebar shape). The audit becomes the disposition record for any future Add Data work and closes the followup gate.

Output: One audit document at `.planning/phases/1048-followups-and-closeout/1048-ADDDATA-MODAL-AUDIT.md`. Inline P0 fixes (if any, ≤1 hour each) committed in the same plan. Deferred items have written rationale in the document.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/REQUIREMENTS.md
@.planning/phases/1048-followups-and-closeout/1048-CONTEXT.md
@.planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md
@.planning/phases/1047-perf-and-code-quality-fixes/1047-06-AUDIT-CLOSEOUT.md

<interfaces>
<!-- Files in scope of the audit + their entry points. Extracted from codebase. -->

Scope (audit ALL of these):
- frontend/src/components/builder/BuilderDialogs.tsx (193 LOC)
  - exports `BuilderDialogs(props: BuilderDialogsProps)` — renders 4 dialogs; the Add Data dialog is lines 86–109 wrapping a `<Suspense fallback={<SceneSpinnerFallback />}><DatasetSearchPanel .../></Suspense>`
  - props relevant to Add Data: `showAddData, onShowAddDataChange, onAddDataset, onDuplicateRendering, layers, isAdding, basemapStyle, showBasemapLabels, basemapConfig, onBasemapChange, onBasemapLabelsChange, onBasemapConfigChange, addDataInitialQuery`
- frontend/src/components/builder/DatasetSearchPanel.tsx (744 LOC) — the actual modal body content. Exports `DatasetSearchPanel({...})` at line 385.
- Any helpers DatasetSearchPanel imports from `@/components/builder/` (e.g., column-info pickers, dataset-card renderers — surface as you read).

v1008 unified-stack reference (what to compare against):
- Pre-v1008 Map Builder sidebar had a "six-section" structure (basemap / DEM / catalog / layers / settings / share OR similar). v1008 collapsed everything into the unified layer stack with basemap-as-group and DEM-as-raster-layer.
- The Add Data modal is a separate surface (not the sidebar). Audit must verify the modal does NOT iterate, key off, or render based on the legacy six-section model.

Audit-template reference (Phase 1046):
- `.planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md` is the format model: findings keyed `CA-NN`/`CB-NN`/`CC-NN`/`CD-NN`/`CE-NN` by dimension; each has Severity / File / Line / Description / Recommended fix / Status.
- For this audit, key findings as `ADM-NN` (Add Data Modal) to avoid namespace collision.
- Use the same dimensions: Duplication / File size / Dead code / Complexity / Test coverage / Accessibility / Performance (add Accessibility + Performance because they're particularly relevant to a modal surface).
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Read audited files + classify findings</name>
  <files>
    .planning/phases/1048-followups-and-closeout/1048-ADDDATA-MODAL-AUDIT.md
  </files>
  <read_first>
    - frontend/src/components/builder/BuilderDialogs.tsx (full file — 193 LOC, read in one pass)
    - frontend/src/components/builder/DatasetSearchPanel.tsx (full file — 744 LOC, read in one pass; if too large, split into 1–400 then 400–744)
    - .planning/phases/1046-builder-perf-and-code-audit/1046-BUILDER-CODE-AUDIT.md (read in full — this is the format template)
    - .planning/phases/1047-perf-and-code-quality-fixes/1047-06-AUDIT-CLOSEOUT.md (read in full — this is the disposition-matrix template)
  </read_first>
  <acceptance_criteria>
    - The audit document exists with frontmatter (phase, plan, artifact, generated, total_findings, p0, p1, p2).
    - Every finding cites file:line.
    - Every finding has a recommended fix sentence.
    - Every finding has a disposition: `shipped` (with task reference inside this plan), `defer` (with rationale), or `resolved (not reproducible)`.
    - At least one finding (positive or negative) addresses the v1008 unified-stack alignment / six-section question. If no leftover assumptions are found, the document MUST state that explicitly in a `## v1008 Unified-Stack Alignment` section: "Audit found no references to a six-section or pre-v1008 sidebar model. DatasetSearchPanel iterates [N] sections derived from [source]; these are content-organizational sections, not structural sidebar sections."
    - The audit document includes a summary table similar to Phase 1047's closeout: `| Status | Count |` rows for `shipped`, `deferred`, `resolved (not reproducible)`, `Total`.
    - If ANY P0 is identified AND its inline fix is estimated ≤1 hour, ship it in Task 2 (below) and mark `shipped` with `1048-02 T2` in the disposition column.
    - If a P0 exceeds the 1-hour budget, mark it `defer` with rationale "Exceeds Phase 1048 inline budget — recommend follow-on plan." (Do NOT silently ship a partial fix.)
  </acceptance_criteria>
  <action>
    Step 1 — Read all four audited files in one pass each (no re-reads). While reading, jot findings inline as you encounter them. Capture file:line for every finding.

    Step 2 — Classify findings by dimension:
    - **Duplication (ADM-A-NN):** Repeated logic that could be extracted (e.g., dataset-card render branches, repeated geometry-type checks, repeated filter chips).
    - **File size (ADM-B-NN):** DatasetSearchPanel is 744 LOC — likely already over a per-file threshold. Reference Phase 1046's threshold (typically 500 or 800 LOC for component files). State the threshold the audit uses.
    - **Dead code (ADM-C-NN):** Unused imports, unused state, unreachable branches, props that are passed-through but never consumed.
    - **Complexity (ADM-D-NN):** Deeply nested ternaries, switch-on-string render dispatch, useEffect chains.
    - **Test coverage (ADM-E-NN):** Missing test files, untested branches in DatasetSearchPanel (search the codebase for `DatasetSearchPanel.test` or sibling `__tests__/` to confirm).
    - **Accessibility (ADM-F-NN):** Modal focus trap, ESC handling, aria-modal / aria-labelledby, keyboard nav for the dataset list. Compare against the Dialog from `@/components/ui/dialog` which already provides some primitives.
    - **Performance (ADM-G-NN):** Render cost on opening (the modal is now lazy-loaded per Phase 1047 Plan 02, but its first render after lazy load still matters). Search re-render cost as user types. Memoization of expensive derivations.

    Step 3 — Severity rubric (match Phase 1046):
    - **P0**: Blocking bug, security issue, broken behavior, or pre-v1008 six-section assumption that affects functionality.
    - **P1**: Significant code-quality issue (duplication, file size offender, dead code present today) but not user-facing-broken.
    - **P2**: Nice-to-have, would improve maintainability but no quality regression risk.

    Step 4 — v1008 alignment check: grep for `'section'`, `sections`, `six`, `SECTION_` inside DatasetSearchPanel.tsx + BuilderDialogs.tsx. Inspect any hits. If a hardcoded six-element list, switch on a `SECTION` enum, or section-id mapping exists, classify it as P0 (alignment with the unified-stack model). If no such pattern, record the finding explicitly under `## v1008 Unified-Stack Alignment` as a negative result with grep evidence.

    Step 5 — Write the audit document at `.planning/phases/1048-followups-and-closeout/1048-ADDDATA-MODAL-AUDIT.md` with this skeleton:

    ```
    ---
    phase: 1048
    plan: 02
    artifact: adddata-modal-audit
    generated: 2026-05-16
    total_findings: <N>
    p0: <count>
    p1: <count>
    p2: <count>
    ---

    # Add Data Modal Audit (Phase 1048 FOLLOWUP-02)

    ## Scope
    <files audited, LOC counts>

    ## Threshold
    <LOC threshold used + source>

    ## Findings
    ### Duplication
    | ID | Sev | File | Line | Description | Recommended fix | Disposition |
    |----|-----|------|------|-------------|-----------------|-------------|
    | ADM-A-01 | P? | ... | ... | ... | ... | ship 1048-02 T2 / defer (rationale) |

    ### File size
    <same table>
    ### Dead code
    <same table>
    ### Complexity
    <same table>
    ### Test coverage
    <same table>
    ### Accessibility
    <same table>
    ### Performance
    <same table>

    ## v1008 Unified-Stack Alignment
    <verdict: aligned / not-aligned + grep evidence>

    ## Disposition Summary
    | Status | Count |
    |--------|-------|
    | shipped (1048-02 T2) | <N> |
    | deferred (rationale present) | <N> |
    | resolved (not reproducible) | <N> |
    | **Total** | <N> |

    ## Inline-Ship Budget
    Phase 1048 budget: P0 inline if ≤1 hour each. List shipped P0s with their estimated effort.
    ```

    Be deliberate. The audit's value is the file:line citations + dispositions, not raw volume. 8–20 findings is normal for a 744-LOC component; <5 is suspicious (under-audited); >40 suggests the audit is conflating P2 nitpicks with real findings.
  </action>
  <verify>
    <automated>test -f .planning/phases/1048-followups-and-closeout/1048-ADDDATA-MODAL-AUDIT.md &amp;&amp; grep -c 'P[012]' .planning/phases/1048-followups-and-closeout/1048-ADDDATA-MODAL-AUDIT.md | awk '$1 &gt; 0 {exit 0} {exit 1}' &amp;&amp; grep -q 'v1008 Unified-Stack Alignment' .planning/phases/1048-followups-and-closeout/1048-ADDDATA-MODAL-AUDIT.md &amp;&amp; grep -q 'Disposition Summary' .planning/phases/1048-followups-and-closeout/1048-ADDDATA-MODAL-AUDIT.md</automated>
  </verify>
  <done>
    - Audit document at the prescribed path with all required sections
    - Every finding has file:line + recommended fix + disposition
    - v1008 Unified-Stack Alignment section is present with explicit verdict
    - Disposition Summary table sums to total_findings
  </done>
</task>

<task type="auto">
  <name>Task 2: Inline-ship any P0 findings under 1-hour budget; flag larger fixes</name>
  <files>
    .planning/phases/1048-followups-and-closeout/1048-ADDDATA-MODAL-AUDIT.md
  </files>
  <read_first>
    - .planning/phases/1048-followups-and-closeout/1048-ADDDATA-MODAL-AUDIT.md (the document just produced)
    - Any source files referenced by P0 findings (read each ONCE)
  </read_first>
  <acceptance_criteria>
    - For each P0 with estimated effort ≤1 hour: the fix is shipped in this task, and the audit document marks the finding `shipped 1048-02 T2` with a commit-reference placeholder (filled by the executor's git workflow).
    - For each P0 with estimated effort >1 hour: the audit document marks it `defer — exceeds Phase 1048 inline budget (X estimated effort). Recommend follow-on plan.`
    - If NO P0 findings exist: this task is a no-op; the audit document records "Inline-ship budget: 0 P0 findings — no inline work."
    - Where P0 fixes are shipped, regression tests are added if applicable (e.g., a P0 dead-code removal that touches a render branch needs a vitest case demonstrating the branch is unreachable / the remaining code path renders correctly).
    - `cd frontend && npx tsc -b --noEmit` must remain clean after any inline P0 fix.
    - The existing vitest suite must remain green after any inline P0 fix.
  </acceptance_criteria>
  <action>
    Iterate through each P0 finding in the audit document. For each:

    1. Re-read the cited file(s) (one Read per file).
    2. Estimate effort honestly: P0 inline fix is ≤1 hour if it's a localized edit (single function, single component, single import cleanup) AND requires no new abstractions AND has clear test coverage. If the fix requires a new helper, a new file, a new test file, or touches >2 files, it exceeds the budget — DEFER it.
    3. If shipping inline:
       - Apply the edit using the Edit tool.
       - Run `cd frontend && npx vitest run <affected test file or related test directory>` to confirm no regression.
       - Update the audit document row: change disposition from `(pending)` to `shipped 1048-02 T2`.
    4. If deferring:
       - Update the audit document row to `defer — <rationale: time / scope / risk>`.

    After all P0 findings are dispositioned:
    - Run `cd frontend && npx tsc -b --noEmit` to verify type-correctness.
    - Run `cd frontend && npm test` and confirm no NEW failures vs the Phase 1047 baseline of 1875/1875.

    Update the audit document's frontmatter and Disposition Summary table to reflect final counts after this task.

    If Task 1 found zero P0 findings, write that explicitly in the audit document's "Inline-Ship Budget" section and exit cleanly. Do NOT manufacture findings to satisfy a perceived task obligation.
  </action>
  <verify>
    <automated>cd frontend &amp;&amp; npx tsc -b --noEmit &amp;&amp; npm test</automated>
  </verify>
  <done>
    - Every P0 finding has a final disposition (`shipped` or `defer` with rationale)
    - Inline-shipped P0 fixes: typecheck clean, vitest suite still green
    - If zero P0 findings: audit document records that explicitly
    - Frontmatter and Disposition Summary table reflect final counts
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries
| Boundary | Description |
|----------|-------------|
| n/a (audit-only plan) | This plan produces an audit document + small inline fixes; no new trust boundaries introduced |

## STRIDE Threat Register
| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1048-02-01 | Information disclosure | Audit document may surface internal implementation details | accept | Document lives under `.planning/` which is gitignored per project convention; not user-facing |
</threat_model>

<verification>
- `test -f .planning/phases/1048-followups-and-closeout/1048-ADDDATA-MODAL-AUDIT.md` — file exists
- Audit document covers all of: BuilderDialogs.tsx Add Data section, DatasetSearchPanel.tsx, and references to v1008 alignment
- All P0 findings have final dispositions
- `cd frontend && npx tsc -b --noEmit` clean after Task 2
- `cd frontend && npm test` no new failures
</verification>

<success_criteria>
- FOLLOWUP-02 is implementation-complete: audit document exists; P0 findings are dispositioned (shipped or deferred-with-rationale); v1008 unified-stack alignment is verified or any leftover assumptions are flagged as P0.
</success_criteria>

<output>
Create `.planning/phases/1048-followups-and-closeout/1048-02-SUMMARY.md` when done. Record:
- Total findings + P0/P1/P2 counts
- Number of P0 findings shipped inline (with brief description of each)
- Number of P0 findings deferred (with rationale per defer)
- v1008 unified-stack alignment verdict (aligned / not-aligned)
- FOLLOWUP-02 status: complete
</output>
