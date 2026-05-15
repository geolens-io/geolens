---
phase: 1043-error-empty-states-and-ia-cleanup
plan: "03"
subsystem: ui
tags: [react, builder, sidebar-rail, layer-editor, i18n, lucide-react, a11y]

# Dependency graph
requires:
  - phase: 1043-02
    provides: AUD-22 EmptyStackState, AUD-14 secondary CTA, AUD-11 retry button, POL-17 Source/Filter/Labels empty states
provides:
  - AUD-20: SidebarRail basemap-group rail button (LayoutGrid icon, h-[18px] w-[18px])
  - AUD-18: BasemapGroupEditorFooter Remove basemap styled text-destructive
  - POL-18: LayerEditorPanel scroll + keyboard focus preservation across scene transitions
  - basemapGroup.railLabel i18n key added to en/builder.json
affects:
  - 1043-04
  - phase-1044

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SidebarRail basemapGroup?: { id: string } | null prop pattern for optional non-layer rail entries"
    - "useRef cleanup capture: assign bodyRef.current to local variable before cleanup fn runs"
    - "prevSceneRef pattern for tracking previous scene value without causing re-renders"

key-files:
  created: []
  modified:
    - frontend/src/components/builder/SidebarRail.tsx
    - frontend/src/pages/MapBuilderPage.tsx
    - frontend/src/components/builder/BasemapGroupEditorScene.tsx
    - frontend/src/components/builder/LayerEditorPanel.tsx
    - frontend/src/i18n/locales/en/builder.json

key-decisions:
  - "AUD-20: basemapGroup prop uses { id: string } | null minimal shape; MapBuilderPage passes literal id 'basemap-group'"
  - "AUD-20: Divider now guards on (layers.length > 0 || basemapGroup) so it renders above basemap button even when overlay list is empty"
  - "AUD-18: No confirmation dialog added to Remove basemap (per UI-SPEC discretion — local state reset, not a backend mutation)"
  - "POL-18: savedScrollTopRef cleanup captures bodyRef.current into local var to satisfy react-hooks/exhaustive-deps"
  - "POL-18: tabIndex={-1} added to layer-editor-header to enable programmatic focus without adding to tab order"
  - "POL-18: Section ordering verified correct (Render as → Appearance → Visibility → Filter → Labels → Source) — no reordering work needed"

patterns-established:
  - "Destructive ghost button: variant='ghost' className='flex-1 text-destructive hover:bg-[oklch(0.97_0.02_27)] hover:text-destructive'"
  - "SidebarRail basemap button selected state: bg-[var(--primary-50,oklch(0.97_0.02_250))] shadow-[inset_2px_0_0_var(--primary)]"

requirements-completed:
  - POL-17
  - POL-18

# Metrics
duration: 22min
completed: 2026-05-14
---

# Phase 1043 Plan 03: SidebarRail basemap button + AUD-18 destructive footer + POL-18 scroll/focus preservation

**SidebarRail gains a LayoutGrid basemap-group rail button with proper selected/hover state; Remove basemap footer styled destructive; LayerEditorPanel preserves scroll position and keyboard focus across scene transitions.**

## Performance

- **Duration:** ~22 min
- **Started:** 2026-05-14T21:35:00Z
- **Completed:** 2026-05-14T21:57:00Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- AUD-20 closed: SidebarRail renders a basemap-group button (LayoutGrid, h-[18px] w-[18px]) below the divider when basemapGroup prop is present; divider guard fixed to prevent dangling when overlay list is empty but basemap is configured
- AUD-18 closed: BasemapGroupEditorFooter Remove basemap button styled text-destructive + oklch destructive-hover background; Reset appearance remains benign ghost
- POL-18 closed: LayerEditorPanel bodyRef + savedScrollTopRef + headerRef + prevSceneRef added; scroll position preserved across editorScene transitions; keyboard focus restores to panel header on basemap-sublayer → basemap-group back navigation
- Section ordering verified correct per UI-SPEC (no reordering work needed)

## Task Commits

Each task was committed atomically:

1. **Task 1: SidebarRail basemap-group button + divider relocation (AUD-20 P1)** - `b78fdad3` (feat)
2. **Task 2: BasemapGroupEditorFooter destructive Remove styling (AUD-18 P1)** - `a5c9c713` (feat)
3. **Task 3: LayerEditorPanel scene-transition scroll + focus preservation (POL-18)** - `b0f2150a` (feat)

## Files Created/Modified

- `frontend/src/components/builder/SidebarRail.tsx` - Added basemapGroup prop, LayoutGrid import, basemap rail button, fixed divider guard
- `frontend/src/pages/MapBuilderPage.tsx` - Wired basemapGroup={layers.localBasemap ? { id: 'basemap-group' } : null} to SidebarRail
- `frontend/src/components/builder/BasemapGroupEditorScene.tsx` - Remove basemap button styled text-destructive
- `frontend/src/components/builder/LayerEditorPanel.tsx` - Added 4 refs (bodyRef, savedScrollTopRef, prevSceneRef, headerRef), 3 useEffects for scroll/focus preservation, tabIndex={-1} on header
- `frontend/src/i18n/locales/en/builder.json` - Added basemapGroup.railLabel = "Basemap group"

## Decisions Made

- Used `{ id: string } | null` as the minimal surface for the basemapGroup prop rather than passing the full basemap group object; callers only need to know the id for selection matching
- No confirmation dialog added to Remove basemap per UI-SPEC discretion (it's a local state reset, not a destructive backend mutation)
- `tabIndex={-1}` on the header element allows programmatic focus without disrupting the tab order for keyboard users
- Captured `bodyRef.current` into a local variable in the cleanup function to satisfy react-hooks/exhaustive-deps lint rule correctly

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed react-hooks/exhaustive-deps warning in bodyRef cleanup**
- **Found during:** Task 3 (POL-18 implementation)
- **Issue:** `useEffect` cleanup directly accessed `bodyRef.current` — ESLint warns this ref value may have changed by the time the cleanup runs
- **Fix:** Captured `const bodyEl = bodyRef.current` inside the effect body, then used `bodyEl` in the cleanup fn
- **Files modified:** frontend/src/components/builder/LayerEditorPanel.tsx
- **Verification:** `npx eslint src/components/builder/LayerEditorPanel.tsx` — clean (no warnings)
- **Committed in:** b0f2150a (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — lint correctness)
**Impact on plan:** Minimal fix for correct ESLint-compliant ref cleanup. No scope creep.

## Issues Encountered

- Pre-existing TS error at LayerEditorPanel.tsx:94 (`caps.kind === 'basemap'` comparison — `LayerKind` type doesn't include `'basemap'`). Confirmed pre-existing before this plan's changes; out of scope per deviation rules. Logged here for awareness.
- Pre-existing ESLint error at MapBuilderPage.tsx:106 (irregular whitespace) and 9 warnings (missing useCallback dependencies). All pre-existing. Out of scope.
- Pre-existing test failure in `DatasetSearchPanel.test.tsx` (cursor-grab test). Confirmed pre-existing. Out of scope.

## Next Phase Readiness

- All three AUD-18, AUD-20, POL-18 findings closed
- Phase 1043 complete: AUD-09/11/14/18/20/22 + POL-16/17/18 all addressed across Plans 01-03
- Phase 1044 can proceed with Playwright UAT spec and de/es/fr locale fill

## Self-Check: PASSED

- `b78fdad3` exists in git log
- `a5c9c713` exists in git log
- `b0f2150a` exists in git log
- frontend/src/components/builder/SidebarRail.tsx — modified with basemapGroup prop + LayoutGrid button
- frontend/src/components/builder/BasemapGroupEditorScene.tsx — Remove basemap has text-destructive
- frontend/src/components/builder/LayerEditorPanel.tsx — 4 refs + 3 useEffects added
- frontend/src/i18n/locales/en/builder.json — railLabel key present

---
*Phase: 1043-error-empty-states-and-ia-cleanup*
*Completed: 2026-05-14*
