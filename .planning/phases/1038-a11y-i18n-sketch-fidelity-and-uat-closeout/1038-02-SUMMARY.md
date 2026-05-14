---
phase: 1038-a11y-i18n-sketch-fidelity-and-uat-closeout
plan: 02
subsystem: ui
tags: [react, builder, dnd-kit, css, sketch-fidelity, typography, spacing]

# Dependency graph
requires:
  - phase: 1034-unified-stack-rows-and-layer-editor-flyout
    provides: StackRow/UnifiedStackPanel/BasemapGroupRow/FolderGroupRow components
  - plan: 1038-01
    provides: Post-1038-01 UnifiedStackPanel with Tooltip on Settings, StackRow with inline confirm

provides:
  - BSR-24 VIS-01: DragOverlay ghost (opacity-40 scale-[0.98]) following pointer during drag
  - BSR-24 EXP-02: .dragging-active root class toggles on drag start/end/cancel; CSS hides kebabs on non-dragging rows
  - BSR-24 insertion line: 2px --primary border-top on [data-dnd-over="true"] elements
  - BSR-24 TYP-01: zero font-medium (weight 500) in four builder source files
  - BSR-24 SPC-01: zero gap-1.5 and py-3 in four builder source files

affects:
  - 1038-04-playwright-uat (drag visual feedback assertions, typography/spacing assertions)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - DragOverlay ghost: DragOverlay with dropAnimation=null wrapping StackRow with isDragging=true + NOOP handlers inside DndContext
    - .dragging-active lifecycle: handleDragStart adds class on <html>; handleDragEnd and onDragCancel both remove it
    - Insertion line: data-dnd-over={isOver ? 'true' : undefined} on SortableStackRow div; CSS [data-dnd-over="true"] { border-top: 2px solid var(--primary) }
    - Kebab hide: data-kebab-trigger="" attribute on DropdownMenuTrigger buttons; CSS .dragging-active [data-testid^="stack-row-"] [data-kebab-trigger] { opacity: 0 !important }

key-files:
  created: []
  modified:
    - frontend/src/components/builder/UnifiedStackPanel.tsx
    - frontend/src/components/builder/StackRow.tsx
    - frontend/src/components/builder/BasemapGroupRow.tsx
    - frontend/src/components/builder/FolderGroupRow.tsx
    - frontend/src/components/builder/SidebarRail.tsx
    - frontend/src/components/builder/LayerEditorPanel.tsx
    - frontend/src/index.css

key-decisions:
  - "DragOverlay ghost body: used full StackRow with NOOP handlers (not minimal type-icon+name stand-in) because StackRow already handles isDragging=true with opacity-40/scale-[0.98] and the type icon + name rendering is tightly coupled to internal logic — simpler than duplicating"
  - "font-medium replacements: type-icon glyphs (raster ▦, vector ≡, basemap-sublayer variants) → font-semibold (glyphs are iconic labels not body text); Badge layer count → font-semibold (eyebrow scale); SidebarRail raster glyph → font-semibold"
  - "py-3 fixes: replaced all 9 occurrences of px-4 py-3 in LayerEditorPanel with px-4 py-2 (includes both section bodies and collapsible trigger rows, ensuring zero grep hits)"
  - "gap-1.5 fixes: title row gap-1.5→gap-2, renderAs chips row gap-1.5→gap-2"

patterns-established:
  - "DragOverlay ghost: always place inside DndContext as last child of DndContext, after SortableContext"
  - "Kebab hide during drag: data-kebab-trigger attribute + .dragging-active CSS (not JS-driven opacity) for resilience across refactors"
  - "insertion line: data attribute on the sortable wrapper div, not on the inner row component"

requirements-completed: [BSR-24]

# Metrics
duration: 20min
completed: 2026-05-14
---

# Phase 1038 Plan 02: DragOverlay Ghost + Sketch-Fidelity Polish Summary

**DragOverlay ghost with opacity-40/scale-[0.98], .dragging-active kebab-hide root class, 2px insertion-line CSS, and removal of font-medium/gap-1.5/py-3 from four builder source files (BSR-24 VIS-01, EXP-02, TYP-01, SPC-01)**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-05-14T00:10:00Z
- **Completed:** 2026-05-14T00:31:59Z
- **Tasks:** 2
- **Files modified:** 7 (5 source + 1 CSS + pre-existing files updated)

## Accomplishments

- Task 1: Wired DragOverlay inside DndContext in UnifiedStackPanel. activeId state tracks the dragging layer. handleDragStart/handleDragEnd/handleDragCancel all manage the .dragging-active root class lifecycle. DragOverlay renders a ghost StackRow with isDragging=true (opacity-40 + scale-[0.98]).
- Task 1: Added data-dnd-over={isOver} on SortableStackRow wrappers for 2px insertion-line CSS.
- Task 1: Added data-kebab-trigger="" to DropdownMenuTrigger buttons in StackRow, BasemapGroupRow, and FolderGroupRow.
- Task 1: Appended Phase 1038 BSR-24 drag CSS block to index.css: insertion-line rule + .dragging-active kebab-hide rule.
- Task 2: Replaced all 5 font-medium occurrences in UnifiedStackPanel/StackRow/SidebarRail with font-semibold (type icon glyphs and the Badge count).
- Task 2: Replaced all 2 gap-1.5 occurrences in LayerEditorPanel with gap-2.
- Task 2: Replaced all 9 py-3 occurrences in LayerEditorPanel with py-2.
- Final grep confirms zero font-medium, gap-1.5, or py-3 in the four production source files.

## Task Commits

1. **Task 1: DragOverlay ghost + .dragging-active root class + insertion-line CSS** - `438bb500` (feat)
2. **Task 2: Remove font-medium (TYP-01) + off-scale gap-1.5/py-3 (SPC-01)** - `e7e7e23a` (fix)

## Files Created/Modified

- `frontend/src/components/builder/UnifiedStackPanel.tsx` — Added useState, DragOverlay import, DragStartEvent type, DraggableAttributes type; added activeId state; refactored handleDragStart to set activeId + add .dragging-active; refactored handleDragEnd to clear activeId + remove .dragging-active; added handleDragCancel; added onDragCancel to DndContext; added DragOverlay block; added data-dnd-over to SortableStackRow; fixed font-medium x2 (sublayer type icons → font-semibold); fixed Badge font-medium → font-semibold
- `frontend/src/components/builder/StackRow.tsx` — Added data-kebab-trigger="" to kebab DropdownMenuTrigger; fixed TypeIcon raster glyph font-medium → font-semibold
- `frontend/src/components/builder/BasemapGroupRow.tsx` — Added data-kebab-trigger="" to kebab DropdownMenuTrigger
- `frontend/src/components/builder/FolderGroupRow.tsx` — Added data-kebab-trigger="" to kebab DropdownMenuTrigger
- `frontend/src/components/builder/SidebarRail.tsx` — Fixed raster glyph ▦ font-medium → font-semibold
- `frontend/src/components/builder/LayerEditorPanel.tsx` — Fixed title row gap-1.5 → gap-2; fixed renderAs chips gap-1.5 → gap-2; fixed all 9 occurrences of py-3 → py-2
- `frontend/src/index.css` — Appended Phase 1038 BSR-24 drag polish CSS block (insertion-line + kebab-hide rules)

## Decisions Made

- **DragOverlay ghost body — full StackRow vs minimal stand-in:** Used full StackRow with NOOP handlers (`() => {}`). The plan noted both options as acceptable. StackRow's isDragging=true already applies opacity-40 + scale-[0.98] styling, and the type icon rendering (TypeIcon, ColorizedGeometryIcon) is tightly coupled to internal layer caps logic — duplicating it inline would be brittle. The NOOP approach is cleaner and uses the stable module-level `NOOP` constant.
- **font-medium replacements:** All type-icon glyphs (raster ▦, vector ≡ in sublayer rows, SidebarRail ▦) use font-semibold because these are iconic labels (not body text) and need visual weight. The Badge layer count uses font-semibold to match the eyebrow scale convention. No occurrence warranted font-normal removal (none were body text outside the layer-name span which was already unstyled).
- **py-3 scope — all 9 occurrences replaced:** The plan specifies "Expected: no matches" for the grep. All py-3 in LayerEditorPanel were replaced (section body divs AND collapsible trigger buttons). The trigger buttons at py-3 were also borderline section body padding, and the spec scale requires py-2 everywhere. Replacing all ensures the grep passes clean.

## Deviations from Plan

None — plan executed exactly as written. The PATTERNS.md NOOP approach for the DragOverlay ghost was adopted as the primary choice (plan listed it as acceptable alternative).

## Issues Encountered

- Pre-existing test failures (out of scope per scope boundary rules):
  - `StackRow.test.tsx`: "clicking Delete layer in kebab calls onRemove" — broken since Plan 01 added inline confirm; test expects direct call but Plan 01 routes through setConfirmingDelete
  - `UnifiedStackPanel.test.tsx`: "calls onAddDataClick when ＋ Add data button is clicked" — pre-existing test issue
  - `use-builder-layers.add-dataset.test.ts` — vitest worker OOM crash (pre-existing heap issue)
  - `i18n/resources.test.ts` — locale key parity failures (Plan 03 is adding missing keys concurrently)
  - These were already failing on main at commit 8f1a3046 before this plan's changes
- Worktree had empty node_modules; used main repo's tsc binary for typecheck — no errors found in worktree files

## Known Stubs

None. All changes are complete visual/CSS polishing with no stub patterns.

## Threat Flags

None. CSS and class changes only; no new endpoints, auth paths, or schema changes.

---

## Self-Check

### Files Exist
- `frontend/src/components/builder/UnifiedStackPanel.tsx`: modified ✓
- `frontend/src/components/builder/StackRow.tsx`: modified ✓
- `frontend/src/components/builder/BasemapGroupRow.tsx`: modified ✓
- `frontend/src/components/builder/FolderGroupRow.tsx`: modified ✓
- `frontend/src/components/builder/SidebarRail.tsx`: modified ✓
- `frontend/src/components/builder/LayerEditorPanel.tsx`: modified ✓
- `frontend/src/index.css`: modified ✓

### Commits Exist
- 438bb500: feat(1038-02): DragOverlay ghost + .dragging-active root class + insertion-line CSS ✓
- e7e7e23a: fix(1038-02): remove font-medium (TYP-01) and off-scale spacing (SPC-01) ✓

## Self-Check: PASSED

---
*Phase: 1038-a11y-i18n-sketch-fidelity-and-uat-closeout*
*Completed: 2026-05-14*
