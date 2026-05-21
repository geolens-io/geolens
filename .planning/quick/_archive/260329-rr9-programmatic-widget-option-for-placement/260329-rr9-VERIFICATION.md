---
phase: 260329-rr9
verified: 2026-03-29T20:12:00Z
status: gaps_found
score: 5/6 must-haves verified
gaps:
  - truth: "Existing measurement and legend widgets still work correctly"
    status: failed
    reason: "WidgetHost.test.tsx registers test widgets with the old `slot:` field (e.g. slot: 'top-left'). At runtime, w.placement is undefined, so w.placement.mode throws TypeError. 6 of 12 widget tests crash with 'Cannot read properties of undefined (reading mode)'. The SUMMARY claims 817 tests pass — this is false for the widget test file."
    artifacts:
      - path: "frontend/src/components/map-widgets/__tests__/WidgetHost.test.tsx"
        issue: "Lines 40-42: test widget registrations still use `slot: 'top-left'` / `slot: 'top-right'` / `slot: 'bottom-left'` — the old API. WidgetDefinition no longer has a slot field; it requires placement: WidgetPlacement. These stale registrations pass TypeScript (vitest bypasses strict type-checking at test-run time) but crash at runtime inside WidgetHost when it accesses w.placement.mode."
    missing:
      - "Update test widget registrations in WidgetHost.test.tsx: replace `slot: 'top-left'` with `placement: { mode: 'floating', anchor: 'top-left' }`, same for top-right and bottom-left."
---

# Quick Task 260329-rr9: Programmatic Widget Placement Verification Report

**Task Goal:** Programmatic widget option for placement (floating w/anchor or sidebar)
**Verified:** 2026-03-29T20:12:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Floating widgets render in their anchored map corner exactly as before | VERIFIED | WidgetHost.tsx:85-116 groups floating widgets by `w.placement.anchor`, uses `ANCHOR_POSITIONS` Record with all 4 corners, renders via WidgetPanel. Logic is structurally identical to the old slot-based grouping. |
| 2 | Sidebar widgets render in a slide-over panel overlaying the map on the specified side | VERIFIED | WidgetSidebar.tsx exists with `absolute top-0 bottom-0 z-20 w-72`, correct side positioning (`right-0` or `left-0`), renders each widget in WidgetPanel + WidgetErrorBoundary. WidgetHost.tsx:117-132 renders WidgetSidebar for both sides. |
| 3 | Sidebar panel auto-collapses (slides out) when all sidebar widgets within it are closed | VERIFIED | WidgetSidebar.tsx:23 — `const hasActive = widgets.length > 0`. When false: `translate-x-full` (right) or `-translate-x-full` (left) + `pointer-events-none`. Panel translates off-screen without unmounting. |
| 4 | Sidebar panel slides in with smooth animation when a sidebar widget is opened | VERIFIED | WidgetSidebar.tsx:29 — `transition-transform duration-200 ease-out`. When `hasActive` is true: `translate-x-0`. Always-render container pattern (mounted when allSidebarWidgets.length > 0) ensures CSS transition fires correctly on state change. |
| 5 | Multiple sidebar widgets stack vertically inside the panel | VERIFIED | WidgetSidebar.tsx:41-53 — `<div className="flex-1 overflow-y-auto p-2 space-y-2">` maps over all active sidebar widgets rendering each as a WidgetPanel. `space-y-2` produces vertical stacking. |
| 6 | Existing measurement and legend widgets still work correctly | FAILED | register-widgets.ts correctly migrated to `placement: { mode: 'floating', ... }`. But WidgetHost.test.tsx test registrations still use the old `slot:` field. Running `npx vitest run src/components/map-widgets/__tests__/` shows 6 test failures with `TypeError: Cannot read properties of undefined (reading 'mode')` at WidgetHost.tsx:68. |

**Score:** 5/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/components/map-widgets/types.ts` | WidgetAnchor, WidgetPlacement, updated WidgetDefinition with placement field | VERIFIED | Exports `WidgetAnchor`, `WidgetPlacement` discriminated union (`mode: 'floating'` or `mode: 'sidebar'`), `WidgetDefinition` uses `placement: WidgetPlacement`. `WidgetSlot` fully removed. |
| `frontend/src/components/map-widgets/WidgetSidebar.tsx` | Sidebar panel component with slide animation | VERIFIED | 57 lines, exports `WidgetSidebar`, CSS translate animation, correct side positioning, renders WidgetPanel + WidgetErrorBoundary per widget. |
| `frontend/src/components/map-widgets/WidgetHost.tsx` | Partitions widgets by placement mode, renders floating + sidebar | VERIFIED | `w.placement.mode === 'floating'` and sidebar partitions at lines 68-81. Renders `<WidgetSidebar>` for left and right at lines 117-132. |
| `frontend/src/components/map-widgets/register-widgets.ts` | Migrated registrations using new placement format | VERIFIED | Both widgets use `placement: { mode: 'floating', anchor: '...' }`. No `slot:` references remain. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `WidgetHost.tsx` | `WidgetSidebar.tsx` | passes sidebar widgets + ctx to WidgetSidebar | WIRED | Lines 117-132: `<WidgetSidebar side="left" widgets={sidebarLeft} allSidebarWidgets={allSidebarLeft} ctx={ctx} />` and same for right. Import at line 7. |
| `register-widgets.ts` | `types.ts` | uses WidgetPlacement type in registration | WIRED | Both registrations use `placement: { mode: 'floating', anchor: '...' }` matching the `WidgetPlacement` type. No implicit `any`. |

### Data-Flow Trace (Level 4)

Not applicable — this task adds a structural placement API and UI rendering architecture. No external data sources involved.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| TypeScript compiles with zero errors | `cd frontend && npx tsc --noEmit` | No output (clean) | PASS |
| WidgetSlot fully removed from codebase | `grep -r WidgetSlot src/` | No matches | PASS |
| Widget tests pass | `npx vitest run src/components/map-widgets/__tests__/` | 6 FAILED — TypeError: Cannot read properties of undefined (reading 'mode') at WidgetHost.tsx:68 | FAIL |

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| WIDGET-PLACEMENT | Add structured placement API (floating w/anchor or sidebar) to widget registration | SATISFIED (code) / PARTIAL (tests) | WidgetPlacement discriminated union implemented, WidgetSidebar created, WidgetHost partitions rendering by mode. Test suite broken for existing widget tests. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `frontend/src/components/map-widgets/__tests__/WidgetHost.test.tsx` | 40-42 | `slot: 'top-left'` / `slot: 'top-right'` / `slot: 'bottom-left'` — old API in test registrations | Blocker | 6 of 12 widget tests crash at runtime. SUMMARY claim of "817 tests pass" is inaccurate for this file. |

### Human Verification Required

#### 1. Sidebar Slide Animation Feel

**Test:** Open map builder, register a widget with `placement: { mode: 'sidebar', side: 'right' }`, toggle it on and off.
**Expected:** Panel slides in smoothly from the right (200ms ease-out), then slides back off-screen when closed. No layout shift on the map itself.
**Why human:** CSS transition behavior cannot be verified by static analysis or unit tests.

#### 2. Floating Widgets Render in Original Positions

**Test:** Open map builder with measurement and legend widgets active.
**Expected:** Measurement appears top-left, legend appears bottom-left, both in the same positions as before the refactor.
**Why human:** Pixel-accurate position comparison requires a running browser.

### Gaps Summary

One gap blocks the "existing widgets still work correctly" truth: the test file `WidgetHost.test.tsx` was not updated as part of the migration. It registers three test-only widgets using the old `slot:` field (`slot: 'top-left'`, `slot: 'top-right'`, `slot: 'bottom-left'`). Since `WidgetDefinition` no longer has a `slot` field, TypeScript would catch this — but vitest's jsdom runner doesn't enforce the type at registration time. The crash happens at render time inside `WidgetHost` when it evaluates `w.placement.mode` and `w.placement` is `undefined`.

The fix is a one-line-per-registration change: replace each `slot:` with `placement: { mode: 'floating', anchor: '...' }`.

The production code (register-widgets.ts, WidgetHost.tsx, WidgetSidebar.tsx, types.ts, index.ts) is fully correct. This is a test maintenance gap only.

---

_Verified: 2026-03-29T20:12:00Z_
_Verifier: Claude (gsd-verifier)_
