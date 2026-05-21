---
phase: 260318-qla
verified: 2026-03-18T23:55:00Z
status: gaps_found
score: 6/7 must-haves verified
gaps:
  - truth: "Primary actions (Add to Map, Download, Connect) are visible buttons; secondary actions (Publish, Re-upload, Create VRT, Delete) are in a kebab overflow menu"
    status: failed
    reason: "partitionActions promotes the two lowest-priority-number actions from the actions array to visible primary buttons (DESKTOP_PRIMARY_ACTION_LIMIT=2). Publish (priority 5) and Re-upload (priority 10) land in primary[] — rendered as visible buttons — rather than in overflow[]. This contradicts the success criterion that Publish/Unpublish is in the kebab, NOT a visible button."
    artifacts:
      - path: "frontend/src/components/dataset/DatasetDetailHeader.tsx"
        issue: "DESKTOP_PRIMARY_ACTION_LIMIT = 2 causes the two highest-priority actions to become visible buttons, not overflow items"
      - path: "frontend/src/pages/DatasetPage.tsx"
        issue: "Publish action has priority: 5 (lowest number, highest ranking) so it becomes a visible button alongside Re-upload (priority 10) for editor users"
    missing:
      - "Set DESKTOP_PRIMARY_ACTION_LIMIT and MOBILE_PRIMARY_ACTION_LIMIT to 0 in DatasetDetailHeader.tsx so ALL actions in the actions array go to overflow, OR move Publish/Re-upload/Create VRT/Delete to priorities > the limit and document the boundary clearly"
      - "Simplest fix: change DESKTOP_PRIMARY_ACTION_LIMIT to 0 — the plan intent is that all kebab actions live in overflow and primary visible buttons are only what is in leadingContent (AddToMapButton, Download COG, ConnectDropdown)"
---

# Quick Task 260318-qla: Detail Page UX Overhaul Verification Report

**Task Goal:** Detail page UX overhaul: header hierarchy, action bar rationalization, read-first metadata, dataset health redesign, VRT framing
**Verified:** 2026-03-18T23:55:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Detail page header shows RecordTypeBadge + type-specific key stats inline below title | VERIFIED | `DatasetPage.tsx:407-488` builds `statsLine` JSX with `RecordTypeBadge` + conditional type-specific stats (vector/raster/VRT). `DatasetDetailHeader.tsx:129-133` renders `statsLine` in a div below the `<h1>`. |
| 2 | Primary actions (Add to Map, Download, Connect) visible buttons; secondary actions (Publish, Re-upload, Create VRT, Delete) in kebab overflow | FAILED | `headerActions` array has Publish at priority 5, Re-upload at priority 10. With `DESKTOP_PRIMARY_ACTION_LIMIT=2`, `partitionActions()` puts Publish and Re-upload into `primary[]` (visible buttons). They are NOT in the overflow/kebab for an editor on desktop. |
| 3 | Contact form hidden behind "Add contact" button when no contacts exist | VERIFIED | `ContactsEditor.tsx:82-94` — `showContactForm = canEdit && (contacts.length > 0 \|\| showForm)`. When `contacts.length === 0 && !showForm`, an "Add contact" `<Button>` is shown. Form only appears after clicking it. `handleAdd` calls `setShowForm(false)` on success. |
| 4 | Empty metadata textareas show collapsed "Not set" placeholder with edit button | VERIFIED | `SourceQualityTab.tsx:100-134` — `renderReadFirstField` helper implemented. Applied to: lineage_summary, source_url, source_organization, quality_statement, usage_constraints, access_constraints. OverviewTab summary field uses same pattern via `summaryExpanded` state (lines 266-288). |
| 5 | DatasetHealthStrip removed from between map and tabs; compact health block appears inside OverviewTab | VERIFIED | `DatasetPage.tsx` has no `DatasetHealthStrip` import or render (only `PublishButton.tsx` and `DatasetHealthStrip.tsx` files exist with no page-level usage). `OverviewTab.tsx:134-159` renders compact health block with `AlertCircle`/`CheckCircle2` icons, issue counts, completion percentage, and "Review issues" button. |
| 6 | VRT overview shows derivation summary with source count, VRT type, generation status, last regenerated date | VERIFIED | `OverviewTab.tsx:310-383` — `isVrt && dataset.raster` guard renders "Derivation Summary" Card. Displays VRT type badge, source count, resolution strategy, generation status with semantic colors, and `lastGeneration?.started_at` formatted via `formatDate()` or "Never". `useVrtGenerations` hook called with `limit: 1`. |
| 7 | Band color "undefined" shows "Not specified"; dash "-" empty states replaced with "Not available" | VERIFIED | `OverviewTab.tsx:477` — `band.color_interp && band.color_interp !== 'undefined' ? band.color_interp : t('common:notSpecified', ...)`. `notAvailableLabel` used for `band_count`, `compression`, `size_bytes`, and `band.nodata` throughout. |

**Score:** 6/7 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/components/dataset/DatasetDetailHeader.tsx` | Stats line slot below title, restructured for new action flow | VERIFIED | `statsLine?: React.ReactNode` prop added (line 50), rendered at lines 129-133. `partitionActions` present. |
| `frontend/src/pages/DatasetPage.tsx` | Reorganized actions array, health strip removed | PARTIAL | `statsLine` built and passed. `headerActions` array with all 4 secondary actions present. Health strip removed. BUT: action partition logic causes Publish+Re-upload to surface as visible buttons, not overflow-only. |
| `frontend/src/components/dataset/tabs/OverviewTab.tsx` | Compact health block, VRT derivation summary, read-first summary, bug fixes | VERIFIED | All 5 features present and wired. `useValidation` + `useVrtGenerations` imported and called. |
| `frontend/src/components/dataset/tabs/SourceQualityTab.tsx` | Read-first empty state for 6 fields | VERIFIED | `renderReadFirstField` helper at line 111 applied to lineage_summary, source_url, source_organization, quality_statement, usage_constraints, access_constraints. `expandedFields` Set state controls expansion. |
| `frontend/src/components/dataset/ContactsEditor.tsx` | Collapsible contact form | VERIFIED | `showForm` state at line 41. Guard at line 90 hides form behind button. `setShowForm(false)` on successful add at line 57. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `DatasetPage.tsx` | `DatasetDetailHeader.tsx` | `statsLine` prop with RecordTypeBadge | VERIFIED | `statsLine={statsLine}` at line 536. `statsLine` includes `<RecordTypeBadge recordType={dataset.record_type} />`. |
| `OverviewTab.tsx` | `use-vrt.ts` | `useVrtGenerations` for last regenerated date | VERIFIED | `import { useVrtGenerations } from '@/hooks/use-vrt'` at line 35. Called at line 129 with `isVrt ? dataset.id : ''`. |
| `OverviewTab.tsx` | `use-dataset.ts` | `useValidation` for compact health block | VERIFIED | `import { useValidation } from '@/hooks/use-dataset'` at line 34. Called at line 120 with `resolvedDatasetId`. |

### Requirements Coverage

Requirements DPX-01 through DPX-05 declared in plan. No REQUIREMENTS.md file present for this quick task format — requirements are embedded in the plan's success_criteria.

| Requirement | Description | Status |
|-------------|-------------|--------|
| DPX-01 | Header hierarchy — RecordTypeBadge + type stats | SATISFIED |
| DPX-02 | Action bar rationalization — primary/secondary separation with kebab | PARTIALLY SATISFIED — kebab exists but Publish/Re-upload surface as visible primary buttons due to partition limit |
| DPX-03 | Read-first metadata — contacts collapsed, empty textareas collapsed | SATISFIED |
| DPX-04 | Dataset health as compact QA block inside OverviewTab | SATISFIED |
| DPX-05 | VRT framing — derivation summary | SATISFIED |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `DatasetDetailHeader.tsx` | 54-55 | `DESKTOP_PRIMARY_ACTION_LIMIT = 2` causes Publish to appear as a visible button | BLOCKER | Contradicts the primary design goal — Publish/Unpublish must be in the kebab. |
| `CollectionDetailPanel.tsx` | 61-63 | `collection.membersPlaceholder` renders "Collection member listing coming soon." | INFO | Pre-existing placeholder, unrelated to this task. |

### Human Verification Required

#### 1. Stats line visual hierarchy

**Test:** Visit a vector dataset detail page on a normal-width browser window.
**Expected:** Below the dataset title, see RecordTypeBadge badge + geometry type + feature count + EPSG code in a single line with `·` separators, then a second line showing record status + relative "Updated X ago" text.
**Why human:** Can't verify visual rendering or font sizing programmatically.

#### 2. Action bar layout

**Test:** As an editor, visit a dataset detail page. Check the header action area.
**Expected (per plan):** Only Add to Map, Download COG (raster), and Connect visible as buttons. Kebab (three-dots) shows Publish, Re-upload, Create VRT, Delete.
**Why human:** Confirms the gap — current code will show Publish + Re-upload as visible buttons due to the partition limit issue.

#### 3. Collapsible contacts UX

**Test:** Navigate to a dataset with no contacts as an editor.
**Expected:** "No contacts" message + single "Add contact" button. Clicking reveals the form. Submitting a contact hides the form and shows the contact row.
**Why human:** Requires interaction to verify state transition.

#### 4. Read-first metadata fields

**Test:** Navigate to SourceQualityTab of a dataset where lineage, source URL, source org, quality statement, usage/access constraints are all empty.
**Expected:** Each shows an italicized "Add [field]..." ghost button. Clicking any one expands just that field to its InlineEdit. Other fields remain collapsed.
**Why human:** Requires interaction and visual inspection.

### Gaps Summary

One gap blocks the action bar rationalization goal. The `partitionActions` function in `DatasetDetailHeader.tsx` uses `DESKTOP_PRIMARY_ACTION_LIMIT = 2`, which promotes the two highest-priority actions from `headerActions` into visible primary buttons. Since Publish has priority 5 (lowest number = first in sort order), it becomes a visible button for any editor user — directly contradicting the success criterion that "Publish/Unpublish is in the kebab, NOT a visible button."

The fix is straightforward: set `DESKTOP_PRIMARY_ACTION_LIMIT` and `MOBILE_PRIMARY_ACTION_LIMIT` to `0` in `DatasetDetailHeader.tsx`. The intent is that all visible primary buttons are supplied via `leadingContent` (AddToMapButton, Download COG, ConnectDropdown) — those three are not affected by `partitionActions` at all. The `actions` array is exclusively for overflow/kebab items.

All other 6 truths are fully verified. TypeScript compiles without errors.

---

_Verified: 2026-03-18T23:55:00Z_
_Verifier: Claude (gsd-verifier)_
