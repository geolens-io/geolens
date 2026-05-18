---
phase: 1051-map-builder-polish-bug-sweep
plan: 04
subsystem: ui
tags: [builder, ux, touch-target, caret, lucide, a11y, basemap-group, folder-group]

# Dependency graph
requires:
  - phase: 1051
    provides: BUG-01 adapter visibility-on-add (Wave 1, 8c6de63), BUG-02 handleRemove optimistic update + rollback (Wave 2, eeeb8be8), and BUG-03 rAF-deferred focus (Wave 3, 80bddc14) — Wave 4 builds on the same group-row surfaces (BasemapGroupRow + FolderGroupRow) without disturbing the prior fixes
provides:
  - UX-01 closed — expand caret on group rows is a 24×24 px hit target with a 16px Lucide ChevronRight glyph
  - Caret-glyph swap pattern: Unicode `▸` → `<ChevronRight />` in the same hit-target wrapper, preserving rotate-90 + aria-expanded animation
  - 4 className-based regression tests in BasemapGroupRow.test.tsx (Test 13-16) covering hit-target dimensions, Lucide SVG presence, rotate animation, and aria-expanded reflection
affects: [phase-1051-plan-05, phase-1051-plan-06, phase-1051-plan-13]

# Tech tracking
tech-stack:
  added: []  # no new dependencies; ChevronRight is already in lucide-react and used elsewhere in the builder
  patterns:
    - "Negative margin (`-mx-1`) hit-target expansion within a locked grid column — keeps the 16px caret column intact while extending the visual button box 4px past each side (sketch 002 A 'A-strict')"
    - "Lucide icon swap for text-glyph carets — `<ChevronRight className=\"h-4 w-4\" />` with `transition-transform duration-[--motion-fast]` + `isExpanded && 'rotate-90'` mirrors the SettingsEditorScene + BasemapSublayerEditorScene pattern"
    - "className-token assertion as a substitute for getBoundingClientRect in jsdom (per critical_planning_directive #10) — actual rendered geometry verified by Playwright MCP, not vitest"

key-files:
  created: []
  modified:
    - frontend/src/components/builder/BasemapGroupRow.tsx
    - frontend/src/components/builder/FolderGroupRow.tsx
    - frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx

key-decisions:
  - "Applied the locked 'A-strict' decision from sketch 002 A: the caret grid column (`grid-cols-[16px_...]` in StackRow.tsx:174) stays at 16px. Hit-target expansion uses negative horizontal margin (`-mx-1`) on the button so the visual 24×24 hit box extends 4px past each side of the column WITHOUT altering layout for non-group rows."
  - "Symmetric fix on both BasemapGroupRow and FolderGroupRow even though only BasemapGroupRow has a dedicated test file — FolderGroupRow's existing caret tests (rotate-90, aria-expanded, aria-controls) all continued to pass without modification because the contract change is class-token level, not behavior level."
  - "Lucide ChevronRight chosen as the icon (not ChevronDown + dynamic switch) — the rotate-90 animation is the standard pattern from SettingsEditorScene.tsx:152-156 + BasemapSublayerEditorScene.tsx, and it preserves the existing animation contract."
  - "Live Playwright MCP measurement of getBoundingClientRect deferred to orchestrator per phase 1051 pattern (MCP is orchestrator-scoped). Tasks 1 (pre-fix measurement) and 3 (post-fix measurement + commit-verify) are orchestrator gates. Vitest className assertions catch the contract change at the unit-test level; MCP confirms the actual rendered pixel geometry."
  - "Cell 4 (type-icon amber `▸` glyph) in FolderGroupRow:238 explicitly NOT changed — that is a decorative folder type-icon, not a caret. FolderGroupRow.test.tsx Test 1 asserts that glyph's presence as part of the type-icon contract, and it is out of scope for UX-01."

patterns-established:
  - "Pattern: Hit-target expansion inside a locked grid column via `flex items-center justify-center h-6 w-6 -mx-1` — preserves the parent grid template while expanding the visual click area. Apply wherever a sub-24px decorative glyph lives inside a constrained grid column."
  - "Pattern: Lucide icon swap for legacy Unicode text glyphs in interactive controls. The icon wraps in a 24×24 (h-6 w-6) button; the icon itself is 16×16 (h-4 w-4); rotate-90 + duration-[--motion-fast] preserves the expand/collapse animation."

requirements-completed: [UX-01]

# Metrics
duration: ~6min
completed: 2026-05-18
---

# Phase 1051 Plan 04: UX-01 Group-Expand Caret Touch Target Summary

**Group expand carets (BasemapGroupRow + FolderGroupRow) now meet the 24×24 px touch-target contract via h-6 w-6 + -mx-1, with a Lucide ChevronRight glyph replacing the Unicode `▸` text character.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-05-18T01:00:36Z (Plan 03 close)
- **Completed:** 2026-05-18T01:06:51Z
- **Tasks:** 1 production task (Task 2 — Tasks 1 and 3 are orchestrator Playwright MCP checkpoints, deferred per phase 1051 pattern)
- **Files modified:** 3 (2 production, 1 test)

## Accomplishments

### UX-01 closed

The expand caret on both group-row variants is now a 24×24 px hit target with a 16 px visible Lucide glyph:

**`frontend/src/components/builder/BasemapGroupRow.tsx`**
- Added `ChevronRight` to the lucide-react named-import list (line 4).
- Replaced the caret button (lines 88-110) — the className now contains `flex items-center justify-center h-6 w-6 -mx-1 rounded text-muted-foreground transition-transform duration-[--motion-fast] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring` with the existing `isExpanded && 'rotate-90'` token, and the child is `<ChevronRight className="h-4 w-4" aria-hidden="true" />` instead of the Unicode `▸`.
- Preserved `aria-expanded`, `aria-controls`, `aria-label`, and the `onClick` stopPropagation + onToggleExpand call.

**`frontend/src/components/builder/FolderGroupRow.tsx`**
- Added `ChevronRight` to the lucide-react named-import list (line 4).
- Replaced the caret button (lines 170-192) — same className shape, same icon swap. The button only renders in the non-multi-select branch of the ternary (`isMultiSelectionActive ? <Checkbox /> : <button>...`).
- Cell 4 (type-icon amber `▸` glyph at line 238) is explicitly preserved — that is the decorative folder type-icon, not the caret, and is asserted by FolderGroupRow.test.tsx Test 1.

**`frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx`**
- Added a new `describe('UX-01: caret hit-target & icon')` block with 4 regression tests:
  - **Test 13:** caret button className contains `h-6`, `w-6`, `-mx-1`, `flex`, `items-center`, `justify-center` (the hit-target contract).
  - **Test 14:** caret button child is an `<svg>` with class matching `/lucide-chevron-right/` and `h-4 w-4` (16px visible glyph); the button textContent does not contain `▸`.
  - **Test 15:** caret rotates 90deg when `isExpanded=true` (animation preserved).
  - **Test 16:** caret `aria-expanded` reflects `isExpanded` state (a11y contract preserved).

### Verification

- `cd frontend && npx vitest run src/components/builder/__tests__/BasemapGroupRow.test.tsx src/components/builder/__tests__/FolderGroupRow.test.tsx` → **44/44 PASS** (15 new in BasemapGroupRow + 16 existing FolderGroupRow + cross-suite preserves).
- `cd frontend && npx vitest run src/components/builder` → **943/943 PASS** across 73 test files (no regressions to peer surfaces — BulkActionBar, LayerEditorPanel, map-sync, etc.).
- `cd frontend && npx tsc --noEmit` → 0 errors.
- Grep acceptance:
  - `▸` removed from caret JSX — only remaining occurrences in modified files are inside `/* ... */` and `// ...` documentation comments (BasemapGroupRow:92, FolderGroupRow:174) plus the unchanged Cell 4 type-icon glyph at FolderGroupRow:238.
  - `ChevronRight` imported + rendered in both files.
  - `h-6 w-6` present in both caret className strings.
  - StackRow.tsx:174 grid template `grid-cols-[16px_14px_22px_22px_1fr_22px]` unchanged (not in the diff).

## RED → GREEN

- **RED gate** (before fix): Tests 13 & 14 failed as expected — Test 13 saw `text-xs text-muted-foreground transition-transform ...` (no `h-6`); Test 14 saw `null` when querying for `<svg>` inside the caret button (still rendering the `▸` text glyph). Tests 15 & 16 passed since rotate-90 + aria-expanded contracts were already in place.
- **GREEN gate** (after fix): all 4 new tests pass; 44/44 across both group-row test files; 943/943 across the entire builder test suite.

## Pre/Post Hit-Target Measurements

**Deferred to orchestrator.** Tasks 1 (pre-fix Playwright MCP measurement) and Task 3 (post-fix Playwright MCP measurement on live `localhost:8080`) are `checkpoint:orchestrator` per phase 1051's `checkpoint:orchestrator` pattern — Playwright MCP is orchestrator-scoped, not executor-spawnable. The vitest className assertions verify the contract; orchestrator MCP confirms the actual rendered pixel geometry (≥24×24 hit-target via `getBoundingClientRect()` at any viewport ≥800px).

## Deviations from Plan

None — plan executed exactly as written. Acceptance criteria all satisfied:
- ✅ `grep '▸'` returns 0 matches in caret JSX (only in unchanged Cell 4 type-icon and documentation comments)
- ✅ `grep 'ChevronRight'` returns ≥1 match in BasemapGroupRow.tsx (import + JSX)
- ✅ `grep 'h-6 w-6'` returns ≥2 matches across both files (one per caret)
- ✅ Vitest regression assertions pass (44/44 across both group-row test files)
- ✅ StackRow.tsx:174 grid template unchanged
- ✅ `npx tsc --noEmit` returns 0 errors

## Commits

| Hash       | Subject                                                                |
| ---------- | ---------------------------------------------------------------------- |
| `278e8933` | fix(builder): group-row expand caret meets 24px touch target (UX-01)   |

## Self-Check: PASSED

**Files exist (modified):**
- ✅ `frontend/src/components/builder/BasemapGroupRow.tsx` (line 4 import, lines 88-110 caret)
- ✅ `frontend/src/components/builder/FolderGroupRow.tsx` (line 4 import, lines 170-192 caret)
- ✅ `frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx` (new `describe('UX-01: ...')` block)

**Commit exists:**
- ✅ `278e8933` — `fix(builder): group-row expand caret meets 24px touch target (UX-01)` (verified via `git log --oneline | grep 278e8933`)
