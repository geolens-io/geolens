---
phase: 260325-sos
verified: 2026-03-25T00:00:00Z
status: gaps_found
score: 2/3 must-haves verified
gaps:
  - truth: "Every KISS, DRY, and best-practice violation in the dataset details page surface area is cataloged"
    status: failed
    reason: "QA report incorrectly REJECTED four research findings (F1, F3, F9, F11) that are confirmed by the actual code. It also dismissed F6 as 'well within acceptable limits' using fabricated line counts."
    artifacts:
      - path: ".planning/quick/260325-sos-qa-pass-on-dataset-details-page-for-kiss/260325-sos-QA-REPORT.md"
        issue: "F1 REJECTED but DatasetHealthStrip, AccessSharingTab, PublishButton have zero runtime imports — they are dead code. F3 REJECTED but panels/ directory with 4 panels exists and is actively used from DatasetPage.tsx. F9 REJECTED but statsLine (line 465) and Sep component (line 463) both exist in current DatasetPage.tsx. F11 REJECTED but parseDependentVrts IS called twice at lines 86 and 90 of DatasetDeleteDialog.tsx. DatasetPage.tsx reported as 497 lines but is actually 824 lines. DatasetMap.tsx reported as 1146 lines but is actually 975 lines. DatasetPage.tsx hook counts (16 useState, 9 useEffect, 10 useCallback) match the research warning, but report dismissed F6 as acceptable without acknowledging these counts. F10 says only edit-affordances.test.tsx has the stale mock, but DatasetPage.hero.test.tsx also mocks AccessSharingTab."
    missing:
      - "Reinstate F1: DatasetHealthStrip, AccessSharingTab, PublishButton are dead code with no runtime imports"
      - "Reinstate F3: panels/ directory exists with ~90% boilerplate duplication across 4 panel files"
      - "Reinstate F9: Sep component defined per-render inside DatasetPage (line 463), statsLine inline block exists (line 465)"
      - "Reinstate F11: parseDependentVrts double-call in DatasetDeleteDialog.tsx (lines 86, 90)"
      - "Correct F6: DatasetPage.tsx is 824 lines with 16 useState/9 useEffect/10 useCallback — research finding is valid"
      - "Correct F10: Both DatasetPage.edit-affordances.test.tsx AND DatasetPage.hero.test.tsx contain the stale AccessSharingTab mock"
      - "Correct line counts: DatasetPage.tsx=824, DatasetMap.tsx=975, SourceQualityTab.tsx=582, ReuploadDialog.tsx=741"
      - "Correct ConnectDropdown string name: report says 'Copy Feature URL' but actual string is 'Copy API URL'"
human_verification: []
---

# Phase 260325-sos: QA Audit Verification Report

**Phase Goal:** QA pass on dataset details page for KISS, DRY and best practices — research-only, no code changes.
**Verified:** 2026-03-25
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Every KISS, DRY, and best-practice violation in the dataset details page surface area is cataloged | ✗ FAILED | QA report incorrectly REJECTs four valid research findings (F1, F3, F9, F11) based on false premises |
| 2 | Each finding has a severity, confidence level, affected files, and concrete remediation | ✓ VERIFIED | All findings that appear in the report are formatted correctly with severity/confidence/files/fix |
| 3 | Findings are prioritized so the most impactful fixes can be tackled first | ✓ VERIFIED | Three-tier priority grouping with refactoring sequence present |

**Score:** 2/3 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `.planning/quick/260325-sos-qa-pass-on-dataset-details-page-for-kiss/260325-sos-QA-REPORT.md` | Consolidated QA report with prioritized findings, min 150 lines | ✓ VERIFIED | File exists, 207 lines, well-structured |

---

## Key Link Verification

No key links defined in PLAN frontmatter. Not applicable for a research-only task.

---

## Data-Flow Trace (Level 4)

Not applicable — this phase produces a document, not runnable code.

---

## Behavioral Spot-Checks

Step 7b: SKIPPED — research/documentation-only phase, no runnable entry points.

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| QA-AUDIT | 260325-sos-PLAN.md | Deep audit of dataset details page for KISS/DRY/best-practices | ✗ BLOCKED | Audit is partially complete — confirmed findings (F2-REVISED, F5, F7, F8, F10-REVISED, F12, NEW-1 through NEW-9) are valid, but four incorrectly rejected research findings and fabricated line counts undermine the catalog's completeness |

---

## Finding-by-Finding Disposition Check

All 12 original research findings (F1-F12) were checked against the actual codebase.

### Incorrectly Rejected / Miscalibrated Findings

**F1 — REJECTED in report, CONFIRMED by codebase**

The report claims "DatasetHealthStrip, AccessSharingTab, PublishButton are all actively imported and used." A full grep of all non-test `.tsx`/`.ts` source files finds zero runtime imports for any of the three:

- `DatasetHealthStrip`: only imported in `__tests__/DatasetHealthStrip.test.tsx`
- `AccessSharingTab`: only mocked in two page test files (never imported as a real dep)
- `PublishButton`: no imports anywhere outside its own file

F1 from the research was correct. These are dead code files.

**F3 — REJECTED in report, CONFIRMED by codebase**

The report claims "The 4 detail panels do not exist in the codebase; no `panels/` directory." This is factually wrong.

The directory `frontend/src/components/dataset/panels/` exists with:
- `VectorDetailPanel.tsx` (113 lines)
- `RasterDetailPanel.tsx` (66 lines)
- `VrtDetailPanel.tsx` (72 lines)
- `CollectionDetailPanel.tsx` (72 lines)

All four are imported in `DatasetPage.tsx` (lines 24-27). `PendingDraftField` and `DetailPanelProps` are exported from `VectorDetailPanel.tsx` and imported by the other three panels — the F3 pattern description is accurate.

**F6 — Dismissed in report, CONFIRMED by codebase**

The report says "DatasetPage.tsx is 497 lines with ~8 useState, ~3 useEffect, ~7 useCallback — well within acceptable limits."

Actual counts from `wc -l` and `grep -c`:
- Lines: **824** (not 497)
- `useState`: **16** (not 8)
- `useEffect`: **9** (accurate)
- `useCallback`: **10** (not 7)

The research finding of excessive state in DatasetPage.tsx is valid.

**F9 — REJECTED in report, CONFIRMED by codebase**

The report claims "The `statsLine` variable and inline `Sep` component do not exist in current DatasetPage.tsx." Both are confirmed present:
- `const Sep = () => <span ...>` at line 463
- `const statsLine = (` at line 465

F9 from the research is valid.

**F11 — REJECTED in report, CONFIRMED by codebase**

The report claims "`parseDependentVrts` does not appear in DatasetDeleteDialog.tsx." It appears at:
- Line 23: function definition
- Line 86: first call (condition check)
- Line 90: second call (data extraction, same error object, JSON.parse fires twice)

F11 from the research is valid.

### Findings With Minor Inaccuracies

**F10 — REFINED in report, but incomplete**

Report says "Only `DatasetPage.edit-affordances.test.tsx` still mocks AccessSharingTab." In fact, both `DatasetPage.edit-affordances.test.tsx` (line 74) and `DatasetPage.hero.test.tsx` (line 92) contain stale `vi.mock('@/components/dataset/tabs/AccessSharingTab', ...)`.

**NEW-1 (ConnectDropdown strings) — Minor label error**

Report identifies "Copy Feature URL" (line 80) as a hardcoded string, but the actual string at that position is "Copy API URL" (line 82). The other strings (Copy COG URL, Copy XYZ Tile URL, Copy S3 URI, Copy Tile URL, "Copied: ...") are correctly identified and genuinely hardcoded — the component imports `useTranslation('dataset')` but uses `t()` nowhere.

**Line count discrepancies across multiple files:**

| File | Report claims | Actual |
|------|--------------|--------|
| `DatasetPage.tsx` | 497 | 824 |
| `DatasetMap.tsx` | 1146 | 975 |
| `SourceQualityTab.tsx` | 529 | 582 |
| `ReuploadDialog.tsx` | 719 | 741 |

### Confirmed Findings (Accurate in Report)

The following findings were verified against actual code and are accurate:

- **F2-REVISED** (type overlap between `PendingDraftField` and `SourceQualityDraftField`): confirmed — 8 identical members, one unique to DatasetPage
- **F5** (`formatBytes` local copy in OverviewTab.tsx line 44 vs `@/lib/format.ts` line 53): confirmed
- **F7** (DatasetMap.tsx at 975 lines with 7 useState, 12 useEffect, 17 useCallback): confirmed, though line count in report (1146) is wrong
- **F8** (`isRaster` computed independently in DatasetPage line 419, ConnectDropdown line 29, OverviewTab line 113): confirmed
- **F12** (AddToMapButton hardcoded strings, no `useTranslation`): confirmed — "Add to Map", "Loading maps...", "No maps available", "+ New map" all hardcoded
- **NEW-1** (ConnectDropdown hardcoded strings): confirmed — actual strings are "Copy COG URL", "Copy XYZ Tile URL", "Copy S3 URI", "Copy Tile URL", "Copy API URL", toast "Copied: ..." — all bypass `t()`
- **NEW-2** (UsedInMaps.tsx "Used in Maps" hardcoded, no useTranslation): confirmed
- **NEW-5** (DatasetMap duplicate zoom calculation at lines 340-344 and 775-778): confirmed identical formula
- **NEW-7** (SchemaEditor.tsx `.map((t)` shadows translation `t` at line 204): confirmed
- **NEW-8** (DistributionsList.tsx `document.execCommand('copy')` fallback at line 83): confirmed
- **NEW-9** (SectionCapabilityHint.tsx hardcodes `reason="read_only_field"` at line 23): confirmed

---

## Anti-Patterns Found in QA Report

The QA report itself contains anti-patterns:

| Issue | Severity | Details |
|-------|----------|---------|
| Fabricated line counts | Blocker | DatasetPage.tsx claimed as 497 lines when it is 824; DatasetMap.tsx claimed 1146 when it is 975. These numbers form the basis for rejecting or downgrading findings. |
| Incorrect REJECTED dispositions (F1, F3, F9, F11) | Blocker | All four are confirmed by direct file inspection. The catalog is incomplete. |
| Incomplete F10 coverage | Warning | Second stale mock file omitted |
| Single string name wrong in NEW-1 | Info | "Copy Feature URL" should be "Copy API URL" |

---

## Human Verification Required

None. All verification was performed programmatically via file reads and grep.

---

## Gaps Summary

The QA report file exists, is well-formatted, and all findings it does contain are accurate and actionable. The report fails on completeness: it incorrectly dismissed four valid research findings (F1, F3, F9, F11) based on false codebase observations (claiming files/directories don't exist when they do), and it used fabricated line counts to downgrade F6. The practical impact is that a follow-up refactoring plan built from this report would miss: deleting three dead-code components, consolidating four near-identical detail panels (the highest-effort DRY fix in the surface area), the Sep/statsLine extraction, the parseDependentVrts cache fix, and would underestimate DatasetPage.tsx's complexity.

The confirmed findings (F2-REVISED, F5, F7, F8, F12, NEW-1 through NEW-9) are all accurate and represent real, actionable issues. The refactoring sequence is sound for the findings it covers.

---

_Verified: 2026-03-25_
_Verifier: Claude (gsd-verifier)_
