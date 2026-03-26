---
phase: 260325-sos
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/quick/260325-sos-qa-pass-on-dataset-details-page-for-kiss/260325-sos-QA-REPORT.md
autonomous: true
requirements: [QA-AUDIT]

must_haves:
  truths:
    - "Every KISS, DRY, and best-practice violation in the dataset details page surface area is cataloged"
    - "Each finding has a severity, confidence level, affected files, and concrete remediation"
    - "Findings are prioritized so the most impactful fixes can be tackled first"
  artifacts:
    - path: ".planning/quick/260325-sos-qa-pass-on-dataset-details-page-for-kiss/260325-sos-QA-REPORT.md"
      provides: "Consolidated QA report with prioritized findings and recommendations"
      min_lines: 150
  key_links: []
---

<objective>
Deep QA audit of the dataset details page for KISS, DRY, and best-practice violations, producing a prioritized findings report.

Purpose: Identify all code quality issues across DatasetPage.tsx and its ~30 related components, tabs, and panels so follow-up refactoring work has a clear, prioritized backlog.
Output: A single QA report file with categorized, prioritized findings.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/quick/260325-sos-qa-pass-on-dataset-details-page-for-kiss/260325-sos-RESEARCH.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Deep audit of all dataset details page files</name>
  <files>
    frontend/src/pages/DatasetPage.tsx
    frontend/src/components/dataset/DatasetMap.tsx
    frontend/src/components/dataset/panels/VectorDetailPanel.tsx
    frontend/src/components/dataset/panels/RasterDetailPanel.tsx
    frontend/src/components/dataset/panels/VrtDetailPanel.tsx
    frontend/src/components/dataset/panels/CollectionDetailPanel.tsx
    frontend/src/components/dataset/tabs/OverviewTab.tsx
    frontend/src/components/dataset/tabs/MetadataTab.tsx
    frontend/src/components/dataset/tabs/AccessTab.tsx
    frontend/src/components/dataset/tabs/AccessSharingTab.tsx
    frontend/src/components/dataset/tabs/DataTab.tsx
    frontend/src/components/dataset/tabs/SourcesTab.tsx
    frontend/src/components/dataset/tabs/SourceQualityTab.tsx
    frontend/src/components/dataset/tabs/StructureTab.tsx
    frontend/src/components/dataset/DatasetHealthStrip.tsx
    frontend/src/components/dataset/PublishButton.tsx
    frontend/src/components/dataset/AddToMapButton.tsx
    frontend/src/components/dataset/ConnectDropdown.tsx
    frontend/src/components/dataset/DatasetDeleteDialog.tsx
    frontend/src/components/dataset/DatasetDetailHeader.tsx
    frontend/src/components/dataset/PendingEditsBar.tsx
    frontend/src/components/dataset/EditableFieldShell.tsx
    frontend/src/components/dataset/InlineEdit.tsx
    frontend/src/components/dataset/ExportButton.tsx
    frontend/src/components/dataset/RelatedRecordsPanel.tsx
    frontend/src/components/dataset/RelatedDatasets.tsx
    frontend/src/components/dataset/UsedInMaps.tsx
    frontend/src/components/dataset/AttributeTable.tsx
    frontend/src/components/dataset/AttributeMetadataTable.tsx
    frontend/src/components/dataset/DistributionsList.tsx
    frontend/src/components/dataset/QualityScoreCard.tsx
    frontend/src/components/dataset/ValidationStatus.tsx
    frontend/src/components/dataset/ValidationTroubleshootPanel.tsx
    frontend/src/components/dataset/SchemaEditor.tsx
    frontend/src/components/dataset/SchemaDiffView.tsx
    frontend/src/components/dataset/VersionHistory.tsx
    frontend/src/components/dataset/ChangeHistory.tsx
    frontend/src/components/dataset/ReuploadDialog.tsx
    frontend/src/components/dataset/ContactsEditor.tsx
    frontend/src/components/dataset/KeywordsEditor.tsx
    frontend/src/components/dataset/MetadataField.tsx
    frontend/src/components/dataset/RoleCapabilityHint.tsx
    frontend/src/components/dataset/SectionCapabilityHint.tsx
    frontend/src/components/dataset/AiAssistButton.tsx
    frontend/src/components/dataset/DatasetDetailSkeleton.tsx
    frontend/src/components/dataset/__tests__/DatasetMap.test.tsx
    frontend/src/components/dataset/__tests__/AddToMapButton.test.tsx
    frontend/src/components/dataset/__tests__/ConnectDropdown.test.tsx
    frontend/src/components/dataset/__tests__/DatasetDetailHeader.test.tsx
    frontend/src/components/dataset/__tests__/DatasetHealthStrip.test.tsx
    frontend/src/components/dataset/__tests__/EditableFieldShell.test.tsx
    frontend/src/components/dataset/__tests__/ExportButton.test.tsx
    frontend/src/components/dataset/__tests__/PendingEditsBar.test.tsx
    frontend/src/components/dataset/__tests__/QualityScoreCard.test.tsx
    frontend/src/components/dataset/__tests__/RelatedRecordsPanel.test.tsx
    frontend/src/components/dataset/__tests__/ReuploadDialog.test.tsx
    frontend/src/components/dataset/__tests__/SourcesTab.test.tsx
    frontend/src/components/dataset/__tests__/StructureTab.test.tsx
    frontend/src/components/dataset/__tests__/ValidationStatus.test.tsx
    frontend/src/components/dataset/__tests__/DatasetDetailSkeleton.test.tsx
    frontend/src/components/dataset/__tests__/DistributionsList.test.tsx
  </files>
  <action>
Read every file listed above. For each file, evaluate against these criteria:

**KISS violations:**
- Component too large (>300 lines with mixed concerns)
- Too many hooks in a single component (>5 useState, >3 useEffect)
- Inline JSX blocks >50 lines that should be extracted
- Complex branching that could be simplified
- State that could be derived instead of stored

**DRY violations:**
- Types or interfaces defined in multiple files
- Identical or near-identical code blocks across files
- Utility functions redefined locally when shared versions exist
- Same prop-drilling pattern repeated across siblings
- Copy-pasted JSX patterns (tabs, wrappers, dialogs)

**Best practice violations:**
- Dead code (components, imports, exports never consumed)
- Stale test mocks referencing deleted/renamed modules
- Hardcoded strings bypassing i18n
- Missing error boundaries or error handling
- Accessibility gaps (missing aria attributes, keyboard handling)
- Components re-created per render that should be module-scoped
- Redundant function calls (same pure function called twice with same args)

Use the RESEARCH.md findings (F1-F12) as a starting checklist, but look beyond them for anything the initial research may have missed. Verify each research finding against the actual code -- confirm, refine, or reject.

For each finding, record:
1. ID (F1, F2, ... continuing from research, or NEW-1, NEW-2 for new discoveries)
2. Category (KISS / DRY / BEST-PRACTICE / DEAD-CODE / TEST-HYGIENE / I18N)
3. Severity (HIGH / MEDIUM / LOW)
4. Confidence (HIGH / MEDIUM)
5. Affected files (exact paths)
6. Description (what the issue is, with line numbers where possible)
7. Recommended fix (specific, actionable)
8. Estimated effort (Low / Medium / High)
  </action>
  <verify>
All files listed above have been read and evaluated. Notes collected for every finding.
  </verify>
  <done>Complete audit notes exist covering every file in the dataset details surface area, with each finding categorized and described.</done>
</task>

<task type="auto">
  <name>Task 2: Write consolidated QA report</name>
  <files>.planning/quick/260325-sos-qa-pass-on-dataset-details-page-for-kiss/260325-sos-QA-REPORT.md</files>
  <action>
Compile all findings from Task 1 into a single structured QA report at the path above. The report structure:

```markdown
# QA Report: Dataset Details Page -- KISS, DRY, Best Practices

**Date:** 2026-03-25
**Scope:** DatasetPage.tsx + all dataset detail components, panels, tabs, and tests
**Files audited:** {count}

## Executive Summary
{2-3 sentence overview of the health of this surface area, key themes}

## Findings by Priority

### Priority 1 -- High Impact
{Findings that should be fixed first. For each:}
#### F{N}: {Title} [{CATEGORY}]
- **Severity:** HIGH
- **Confidence:** HIGH/MEDIUM
- **Files:** {paths}
- **Issue:** {description with line references}
- **Fix:** {specific remediation steps}
- **Effort:** Low/Medium/High

### Priority 2 -- Medium Impact
{Same format}

### Priority 3 -- Low Impact / Nice-to-Have
{Same format}

## Metrics Summary
| Metric | Value |
|--------|-------|
| Files audited | {N} |
| Total findings | {N} |
| HIGH severity | {N} |
| MEDIUM severity | {N} |
| LOW severity | {N} |
| Dead code files | {N} |
| DRY violations | {N} |
| KISS violations | {N} |
| Estimated total cleanup effort | {Low/Medium/High} |

## Recommended Refactoring Sequence
{Ordered list of what to tackle first, with dependency notes -- e.g., delete dead code before refactoring panels, since dead code removal simplifies the picture}
```

Ensure every finding from RESEARCH.md (F1-F12) is accounted for -- confirmed, refined, or rejected with explanation. Include any new findings discovered in Task 1.
  </action>
  <verify>
    <automated>test -f ".planning/quick/260325-sos-qa-pass-on-dataset-details-page-for-kiss/260325-sos-QA-REPORT.md" && wc -l ".planning/quick/260325-sos-qa-pass-on-dataset-details-page-for-kiss/260325-sos-QA-REPORT.md" | awk '{if ($1 >= 150) print "PASS: "$1" lines"; else print "FAIL: only "$1" lines"}'</automated>
  </verify>
  <done>QA report exists at the specified path with all findings categorized, prioritized, and actionable. Every research finding (F1-F12) is accounted for. Report has at least 150 lines.</done>
</task>

</tasks>

<verification>
- QA report file exists and is at least 150 lines
- All 12 research findings (F1-F12) are addressed (confirmed, refined, or rejected)
- Findings are grouped by priority with clear severity/effort ratings
- A recommended refactoring sequence is included
</verification>

<success_criteria>
- Comprehensive QA report covering the full dataset details surface area
- Every finding has severity, confidence, affected files, and concrete fix
- Prioritized ordering enables follow-up work to start from highest impact
- No code changes -- report only
</success_criteria>

<output>
After completion, create `.planning/quick/260325-sos-qa-pass-on-dataset-details-page-for-kiss/260325-sos-01-SUMMARY.md`
</output>
