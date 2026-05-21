---
phase: quick-260515-sqf
reviewed: 2026-05-15T00:00:00Z
depth: quick
files_reviewed: 4
files_reviewed_list:
  - frontend/src/components/builder/FolderGroupRow.tsx
  - frontend/src/components/builder/UnifiedStackPanel.tsx
  - frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx
  - .claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md
findings:
  critical: 0
  warning: 0
  info: 0
  total: 0
status: clean
---

# Quick Task 260515-sqf: Code Review Report

**Reviewed:** 2026-05-15
**Depth:** quick
**Files Reviewed:** 4
**Status:** clean

## Summary

Reviewed the 3-commit sweep that removes the per-row Opacity slider from
`FolderGroupRow`. Pattern mirrors quick task 260515-rdn (predecessor — also
CLEAN); the same author/executor performed both removals with the same
mechanical type-system-safety-net approach. **No findings at any severity.**

Verified against the focus areas supplied by the user:

1. **All FolderGroupRow callsites stopped passing `onOpacityChange`?** YES.
   `grep "onOpacityChange" FolderGroupRow.tsx FolderGroupRow.test.tsx` returns
   zero matches. In `UnifiedStackPanel.tsx`, the prop was dropped from the
   `FolderGroupRowWrapperProps` interface (line 295), its destructure (line
   314), and from the `<FolderGroupRowWrapper>` JSX callsite inside
   `layers.map` (was line 910 in the pre-sweep file). The 4 surviving
   `onOpacityChange` references in `UnifiedStackPanel.tsx` are all
   load-bearing for other components (top-level interface line 76, basemap
   wrapper interface+destructure+forward at 231/251/282, and the hard-coded
   `() => {}` on the basemap dock callsite at line 780).

2. **New 6-cell grid template renders correctly?** YES. `FolderGroupRow.tsx`
   line 145 now reads
   `grid-cols-[16px_14px_22px_22px_1fr_22px]` — matches `StackRow.tsx:174`
   exactly (the predecessor sweep target). Out-of-scope rows correctly retain
   the 7-cell `..._60px_22px` template: `BasemapGroupRow.tsx:78` and
   `UnifiedStackPanel.tsx:425` (the SublayerRow). The comment "Cell 6: Kebab
   menu" was updated (was "Cell 7" pre-sweep).

3. **Rule-3 deviation — removed unused destructure of `onOpacityChange` in
   UnifiedStackPanel.tsx around line 589?** APPROPRIATE. The diff shows the
   removal is paired with a 6-line explanatory comment (lines 589–594)
   spelling out why the prop is kept on `UnifiedStackPanelProps` (line 76)
   but no longer destructured — basemap wrapper hard-codes `() => {}`,
   FolderGroupRow + StackRow no longer render row sliders, but
   `handlers.onOpacityChange` still flows to LayerEditorPanel from
   MapBuilderPage. The deviation is well-documented in-source and matches
   the research §1 callsite table at line 75. No collateral damage —
   `tsc -b` cleanliness implied by absence of any remaining destructure
   pointing at the now-deleted prop.

4. **Tests: defaultProps factory still complete after dropping 2 lines?**
   YES. The factory at `FolderGroupRow.test.tsx:55-72` covers every required
   prop on the current `FolderGroupRowProps` interface (groupId, groupName,
   visible, selected, isExpanded, isDragging, dragHandleProps,
   onSelectGroup, onToggleExpand, onToggleVisibility, onRenameGroup,
   onAddLayer, onUngroup, onDeleteGroup). The dropped `opacity: 1,` and
   `onOpacityChange: vi.fn(),` lines correspond exactly to the removed
   interface fields. Optional multi-select props (lines 38–42 of the
   component interface) are left out of `defaultProps` and provided per-test
   via overrides, consistent with the original Phase 1041 test convention.
   Test 4's name string was updated to drop `/opacity` from the parenthetical
   without touching the test body (which clicks the name span, not a
   slider) — correct minimal change.

5. **Sketch ref doc forward note narrowing — does it correctly describe
   basemap-only group slider retention?** YES. The 9-line forward note at
   `layer-rows-and-groups.md:34-44` now reads "**Only basemap group rows and
   basemap-editor sublayer rows retain their own opacity sliders**" — which
   matches reality: post-sweep `grep stackRow.opacitySlider` returns exactly
   2 matches (BasemapGroupRow.tsx:189, BasemapGroupEditorScene.tsx:196). The
   note correctly credits both 260515-rdn (non-group rows) and 260515-sqf
   (user-folder group rows) as the two removal sweeps. The HTML example at
   lines 163–174 keeps its `<input class="opacity">` element but adds an
   inline HTML comment (line 171) clarifying that the example illustrates a
   basemap-group row and that user-folder-group rows omit the input. This is
   the "option (a)" narrowing path recommended by research §4. Consistent
   and accurate.

6. **Any secrets / TODOs / debug logs / commented-out code?** NONE.
   `grep -E "console\.log|debugger|TODO|FIXME|XXX|HACK"` against all four
   modified files returns zero matches. No hardcoded secrets (this is
   frontend-only and contains no credential-like literals). No
   commented-out code — the removed Cell 6 slider block was cleanly excised,
   not commented. The few remaining `opacity` substrings in
   `FolderGroupRow.tsx` (lines 148, 192, 282, 284) are all Tailwind
   utility-class fragments (`opacity-40`, `opacity-35`,
   `group-hover/row:opacity-70`, `opacity-0`, etc.) — distinct concept from
   the deleted opacity-value prop.

Cross-references verified:
- Locale files untouched — all 4 (en/de/es/fr) still have `opacitySlider`
  at line 814 (load-bearing for the 2 surviving consumers).
- 3 commits in the task range, each with a single concern (refactor / test /
  docs), commit messages free of AI/bot attribution per global CLAUDE.md.
- No backend, no migrations, no API surface touched.

All reviewed files meet quality standards. No issues found.

---

_Reviewed: 2026-05-15_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: quick_
