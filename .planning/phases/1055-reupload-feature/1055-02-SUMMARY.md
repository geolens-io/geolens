---
phase: 1055-reupload-feature
plan: "02"
subsystem: ui
tags: [i18n, accessibility, playwright, vitest, dataset-detail, overflow-menu]

requires:
  - phase: 1055-01
    provides: ReuploadDialog component and backend reupload endpoint already shipped

provides:
  - Visible "More" label on overflow trigger (desktop, hidden on mobile) + aria-label retained
  - HTML title tooltips on all overflow menu items (reupload, create-vrt, delete)
  - tooltip field on DatasetDetailHeaderAction interface
  - 4-locale i18n parity: header.more + 3 *Tooltip keys (en/de/es/fr)
  - IMPORT-04 M001 audit replay e2e regression test in dataset-detail.spec.ts

affects: [dataset-detail, DatasetDetailHeader, DatasetPage, i18n-parity]

tech-stack:
  added: []
  patterns:
    - "Audit-discoverable overflow: visible text label on kebab trigger + title attribute on each DropdownMenuItem so DOM snapshots surface actions without clicking"
    - "optional tooltip field on action interface flows from page-level i18n call through header component to HTML title attribute"

key-files:
  created: []
  modified:
    - frontend/src/components/dataset/DatasetDetailHeader.tsx
    - frontend/src/components/dataset/__tests__/DatasetDetailHeader.test.tsx
    - frontend/src/pages/DatasetPage.tsx
    - frontend/src/i18n/locales/en/dataset.json
    - frontend/src/i18n/locales/de/dataset.json
    - frontend/src/i18n/locales/es/dataset.json
    - frontend/src/i18n/locales/fr/dataset.json
    - e2e/dataset-detail.spec.ts

key-decisions:
  - "Reupload stays in overflow (CONTEXT.md locked: deliberate rare action, not promoted to primary)"
  - "Visible More label uses hidden sm:inline Tailwind pattern — mobile remains icon-only, desktop shows word More"
  - "title attribute chosen for tooltip transport because axe/RTL accessibleName falls back to title, surfacing the action to audit-style DOM snapshots without requiring menu expansion"
  - "tooltip field is optional on DatasetDetailHeaderAction — publish/unpublish is not given a tooltip since it's primary not overflow"

patterns-established:
  - "Audit-discoverable overflow pattern: trigger gets visible text label (not just aria-label) + each overflow item gets HTML title attribute carrying action description"

requirements-completed:
  - IMPORT-04

duration: 10min
completed: 2026-05-19
---

# Phase 1055 Plan 02: Frontend Discoverability Hardening Summary

**Overflow trigger gets visible "More" label + HTML title tooltips on all 3 overflow items, closing the M001 audit's missed-kebab finding; pinned by a new M001-replay e2e regression test**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-05-19T22:10:00Z
- **Completed:** 2026-05-19T22:20:35Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments

- DatasetDetailHeader overflow trigger now renders a visible "More" text label next to the MoreHorizontal icon on desktop (`hidden sm:inline`), keeping the icon-only mobile treatment; `aria-label="More actions"` retained for screen readers
- Each DropdownMenuItem in the overflow carries a `title` HTML attribute from the action's new optional `tooltip` field — axe/RTL's `accessibleName` falls back to `title`, so a Playwright DOM snapshot surfaces "Replace this dataset's source file" even without expanding the menu
- DatasetPage.tsx populates `tooltip` on reupload, create-vrt, and delete actions via i18n; publish/unpublish left without tooltip since they are primary buttons (not overflow)
- 4 new i18n keys added with full parity across en/de/es/fr: `header.more`, `actions.reuploadTooltip`, `actions.createVrtTooltip`, `actions.deleteTooltip`
- New e2e regression test `IMPORT-04: M001 audit replay` in `dataset-detail.spec.ts` — mirrors the auditor's path (scan for button whose name matches Re-Upload|Replace|Reupload|More, click, assert dialog opens), accepts either overflow or future primary placement so UX iteration doesn't break it

## Task Commits

Each task was committed atomically following TDD RED → GREEN:

1. **Task 1 RED: Failing tests** - `90037a70` (test)
2. **Task 1 GREEN: DatasetDetailHeader + i18n + DatasetPage** - `f4b7242a` (feat)
3. **Task 2: M001 audit replay e2e test** - `d944407b` (test)

## Files Created/Modified

- `frontend/src/components/dataset/DatasetDetailHeader.tsx` - Added optional `tooltip` field to `DatasetDetailHeaderAction` interface; rendered visible "More" span in trigger button; passed `title={action.tooltip}` to each DropdownMenuItem
- `frontend/src/components/dataset/__tests__/DatasetDetailHeader.test.tsx` - Added 2 new tests: overflow trigger has visible "More" text + aria-label, overflow items have title attributes
- `frontend/src/pages/DatasetPage.tsx` - Populated `tooltip` field on reupload/createVrt/delete headerActions using i18n keys
- `frontend/src/i18n/locales/en/dataset.json` - Added `header.more`, `actions.reuploadTooltip`, `actions.createVrtTooltip`, `actions.deleteTooltip`
- `frontend/src/i18n/locales/de/dataset.json` - German translations for same 4 keys
- `frontend/src/i18n/locales/es/dataset.json` - Spanish translations for same 4 keys
- `frontend/src/i18n/locales/fr/dataset.json` - French translations for same 4 keys
- `e2e/dataset-detail.spec.ts` - Added `IMPORT-04: M001 audit replay` test

## Decisions Made

**Why reupload is NOT promoted to primary:** CONTEXT.md locked decision — "Use existing action-menu styling, not a primary button — reupload is a deliberate, rare action." Promoting it would clutter the header for every dataset page view with an action most users never invoke.

**Why `title` attribute for tooltips:** The HTML `title` attribute is read by axe's `accessibleName` computation and by RTL's `getByTitle` / `getAttribute('title')`. A Playwright `.getAttribute('title')` or `getByTitle()` query reaches the attribute without expanding the dropdown, exactly mirroring an audit-style DOM snapshot.

**Why `hidden sm:inline` for the More label:** Matches the existing Tailwind pattern used throughout the builder sidebar for responsive icon+label buttons. Mobile keeps the compact icon-only form; desktop (sm breakpoint and up) reveals the word "More" next to the icon.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Known Stubs

None — the reupload dialog is fully wired (shipped in Plan 01). This plan only adds discoverability, not new functionality.

## Self-Check: PASSED

- `frontend/src/components/dataset/__tests__/DatasetDetailHeader.test.tsx` — 10/10 tests pass (8 existing + 2 new)
- `src/i18n/resources.test.ts` — 2/2 parity tests pass (all 4 locales have all keys)
- `e2e/dataset-detail.spec.ts` — 2/2 e2e tests pass against live stack (existing + new M001 replay)
- All 4 commits verified in git log: `90037a70`, `f4b7242a`, `d944407b`, plus this metadata commit

## Next Phase Readiness

- IMPORT-04 discoverability hardening complete — the audit-style selector path now resolves to the overflow trigger by text "More", the reupload dialog opens, and the regression test pins that behavior
- Phase 1055 can close after Plan 03 (if any) or the v1055 tagging step

---
*Phase: 1055-reupload-feature*
*Completed: 2026-05-19*
