---
phase: quick-260515-rdn
reviewed: 2026-05-15T00:00:00Z
depth: quick
files_reviewed: 4
files_reviewed_list:
  - frontend/src/components/builder/StackRow.tsx
  - frontend/src/components/builder/UnifiedStackPanel.tsx
  - frontend/src/components/builder/__tests__/StackRow.test.tsx
  - .claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md
findings:
  critical: 0
  warning: 0
  info: 1
  total: 1
status: clean
---

# Quick Task 260515-rdn: Code Review Report

**Reviewed:** 2026-05-15
**Depth:** quick (focused — deletion-heavy refactor)
**Files Reviewed:** 4
**Status:** clean (1 info note, no fix required)

## Summary

Clean execution. The per-row opacity slider was removed from `StackRow.tsx` exactly as scoped in RESEARCH.md, with all callsite cleanup done in `UnifiedStackPanel.tsx` and tests updated in lockstep. The sketch reference doc was updated with an explicit note about the change and a load-bearing caveat that group-row HTML examples intentionally retain their slider.

**All six prompt focus areas verified:**

1. **Callsite cleanup** — All 4 `onOpacityChange` references on `<StackRow>` / `SortableStackRow` paths in `UnifiedStackPanel.tsx` were dropped (lines 196, 932, 962, 1012 in the pre-diff). Researcher noted 2 SortableStackRow callsites; executor correctly also stripped the prop from the `SortableStackRowProps` interface (line 131) and destructure (line 155), plus the 2 SortableStackRow usage sites at lines 929 and 959 — none of which were enumerated in RESEARCH.md §1's main callsite table but were correctly inferred from the prop-removal type ripple. `rg "onOpacityChange"` over `StackRow.tsx` + `StackRow.test.tsx` returns zero. The prop continues to flow through `UnifiedStackPanelProps` (line 76), `FolderGroupRowWrapper`, and `BasemapGroupRowWrapper` as intended — load-bearing for group-level sliders.

2. **Grid template consistency** — `grid-cols-[16px_14px_22px_22px_1fr_22px]` applied at `StackRow.tsx:174`. Exactly 6 grid cells render in order: Cell 1 (Caret/Checkbox, lines 195–214), Cell 2 (Grip, 216–231), Cell 3 (Eye, 233–253), Cell 4 (Type icon, 255–258), Cell 5 (Name, 260–296), Cell 6 (Kebab, 298–375). Cell numbering in comments correctly renumbered from "Cell 7: Kebab" → "Cell 6: Kebab menu". `SublayerRow` in the same UnifiedStackPanel file (line 430) and the three OUT-OF-SCOPE sibling rows (`BasemapGroupRow`, `FolderGroupRow`, `BasemapGroupEditorScene`) correctly retain their 7-column `16px_14px_22px_22px_1fr_60px_22px` template.

3. **No collateral damage** — Diff in `StackRow.tsx` is exactly: 1 import line, 1 prop interface line, 1 destructure line, 1 `opacity` local, 1 grid template change, 23-line Cell 6 block, 1 comment renumber. Nothing else in the file moved. Multi-select props (Phase 1041), POL-15 `isFresh` entry animation (Phase 1042), SP-10 `aria-pressed`, SP-14 hover affordance, and the inline-delete `alertdialog` all survived intact. The `<Button>`, `<Checkbox>` imports remain used elsewhere in the file (delete confirm + multi-select checkbox).

4. **Tests** — `defaultProps()` factory (`StackRow.test.tsx:86–100`) correctly drops `onOpacityChange: vi.fn()`. The renamed test ("renders the five interactive cells…") matches the actual six DOM positions (caret hidden + 5 visible). The deleted `'opacity slider aria-label…'` block at the old line 282–288 is gone. `within` import at line 1 is still used at line 226 (Delete confirm). No orphaned `Slider` / `Opacity` references remain. Test count drops from 32 to 31 — matches RESEARCH.md §2 checkpoint #2.

5. **Sketch ref doc** — `layer-rows-and-groups.md` updated to match the new spec at every required touchpoint per RESEARCH.md §4: row anatomy diagram drops `[opacity]` (line 21–22), bullet list drops the `60px range slider` bullet, CSS `.row` template at line 89 → `16px 14px 22px 22px 1fr 22px`, CSS `.group-children .row` template at line 141 → same six-column template, HTML loose-row example (line 149–157) has no `<input class="opacity">`. **Critically, the group-row HTML example at line 161–170 retains `<input class="opacity" type="range">` as intended** — the note at line 34–41 explicitly explains why and cross-references that group/sublayer sliders survive. The "What to Avoid" section's "Numeric opacity inputs" bullet at the original line 182 was correctly kept (it advises against a different anti-pattern, not the slider itself).

6. **No debug/secret artifacts** — `rg` for `TODO|FIXME|XXX|HACK|console\.log|debugger|password|api_key|secret` over all four changed files returns zero. No commented-out code introduced.

**Validations that match RESEARCH.md checkpoints:**
- §1 i18n caveat respected: `stackRow.opacitySlider` locale key NOT removed (verified out of scope here; no i18n files in this diff).
- §2 e2e: no e2e changes (none required).
- §5 OUT-OF-SCOPE sibling files: untouched (verified by file list in diff — only the 4 expected files).
- §8 LOC estimate: actual delta is `−25 / −6 / −10` for code + tests (close to estimated `−25 / −4 / −10`), plus +331 for the sketch ref doc (committed as new file — see IN-01 below).

## Info

### IN-01: Sketch ref doc committed as `new file mode 100644`, not modified

**File:** `.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md` (new file)
**Issue:** The diff shows `new file mode 100644` and `+331` lines added — not a typical edit-in-place. Investigation: the entire `.claude/` directory is gitignored (`.gitignore:50`), and the `sketch-findings-geolens` skill was previously untracked (its 5 other files — `SKILL.md`, `empty-state.md`, `layer-editor-flyout.md`, `responsive.md`, `sidebar-structure.md`, plus the `sources/` subdir — remain untracked). The executor used `git add -f` to force-add only the one file they edited, which is consistent with project pattern feedback `[No blanket add in .planning/]` (do not sweep in untracked siblings). The pre-edit file content existed on disk since 2026-05-13; the executor's mutation is the 2026-05-15 note + diagram/bullet/CSS/HTML updates documented in the commit message of `dbf43ab5`.

The result is correct (the on-disk file matches what RESEARCH.md §4 prescribed), but it means there is no in-repo diff showing *what changed* relative to the pre-edit content — only the full final state. A reviewer cannot mechanically verify the line-by-line edits from `git diff` alone; the spec compliance has to be verified by reading the file against the spec (done — see Summary §5).

**Fix:** None required. This is a one-time hygiene observation about gitignored skill files becoming "new" on first force-add. Future edits to this file will diff normally. If the wider skill directory deserves to be tracked, that is a separate decision out of scope for this quick task.

---

_Reviewed: 2026-05-15_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: quick_
