---
quick_id: 260515-sqf
type: quick-task-summary
status: complete
shipped: 2026-05-15
plan: 01
phase: quick-260515-sqf
predecessor: 260515-rdn
commits:
  - 53fc662c  # Task 1 — refactor FolderGroupRow + sweep callsites
  - e7d01dc9  # Task 2 — drop FolderGroupRow opacity-slider props from defaults
  - 10ea48ca  # Task 3 — narrow sketch ref forward note
files_modified:
  - frontend/src/components/builder/FolderGroupRow.tsx
  - frontend/src/components/builder/UnifiedStackPanel.tsx
  - frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx
  - .claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md  # force-added (gitignored)
requirements_satisfied:
  - SQF-01  # Remove per-row opacity Slider from FolderGroupRow (markup, import, opacity prop, onOpacityChange prop, opacity local, grid template, Cell-7→Cell-6 comment)
  - SQF-02  # Remove FolderGroupRowWrapper's opacity/onOpacityChange forwarding (interface + destructure + local + 2 child props + outer callsite at L910)
  - SQF-03  # Update FolderGroupRow tests (drop opacity + onOpacityChange from defaultProps, retitle Test 4 to remove `/opacity`)
  - SQF-04  # Narrow sketch doc forward note + add HTML-comment annotation on the group-row example (RESEARCH.md §4 option (a))
  - SQF-05  # Verify no callsite, locale key, sibling slider, or e2e regressed (typecheck + vitest + grep gates + smoke fallback)
metrics:
  loc_delta: "-42 (close to RESEARCH.md §8 -25 estimate; the extra delta is the unused main-component destructure removed under Rule 3)"
  foldergrouprow_test_count: "18 → 18 (UNCHANGED, as required)"
  builder_test_dir: "52 files / 708 tests passing"
  duration_minutes: "~10"
---

# Quick Task 260515-sqf Summary — Remove redundant per-row Opacity slider from FolderGroupRow

**Shipped:** 2026-05-15
**Branch:** `main` (worktrees disabled)
**Commits:** `53fc662c` (Task 1) · `e7d01dc9` (Task 2) · `10ea48ca` (Task 3)

## One-Liner

Removed the redundant per-row Opacity slider from `FolderGroupRow.tsx`; the LayerEditorPanel Visibility-section slider is now the single canonical opacity control for user-folder groups too (matching the 260515-rdn StackRow change). Only basemap-group rows and basemap-editor sublayer rows retain their own row sliders.

## What Shipped

### Task 1 — `53fc662c`

`refactor(quick-260515-sqf): remove per-row opacity slider from FolderGroupRow + sweep callsites`

- **`frontend/src/components/builder/FolderGroupRow.tsx`** (−33 lines):
  - Dropped `import { Slider } from '@/components/ui/slider';`.
  - Removed `opacity: number;` and `onOpacityChange: (id: string, opacity: number) => void;` from `FolderGroupRowProps`.
  - Removed `opacity: opacityProp,` and `onOpacityChange,` from the component-parameter destructure.
  - Removed the local `const opacity = …;` line (was only consumed by the slider).
  - Updated row container grid template: `grid-cols-[16px_14px_22px_22px_1fr_60px_22px]` → `grid-cols-[16px_14px_22px_22px_1fr_22px]`.
  - Deleted the Cell-6 wrapper `<div>` + `<Slider>` block (was lines 275–297) including `onPointerDown`/`onClick` stopPropagation handlers, the `t('stackRow.opacitySlider', …)` aria label, and the `onValueChange` handler.
  - Renumbered the trailing `Cell 7: Kebab menu` comment to `Cell 6: Kebab menu`.
- **`frontend/src/components/builder/UnifiedStackPanel.tsx`** (−7 lines net):
  - Removed `onOpacityChange` from `FolderGroupRowWrapperProps` interface.
  - Removed `onOpacityChange,` from `FolderGroupRowWrapper()` destructure.
  - Removed the local `const opacity = …` inside `FolderGroupRowWrapper`.
  - Removed `opacity={opacity}` and `onOpacityChange={onOpacityChange}` from the `<FolderGroupRow>` rendered inside `FolderGroupRowWrapper`.
  - Removed `onOpacityChange={onOpacityChange}` from the outer `<FolderGroupRowWrapper>` instantiation at line 910.
  - **Deviation (Rule 3 auto-fix):** TypeScript surfaced that after the above edits, the main `UnifiedStackPanel` component's destructure of `onOpacityChange` (was line 589) has zero remaining consumers — the basemap-wrapper instantiation at line 775 hard-codes `onOpacityChange={() => {}}` (opacity via Scene B master slider), and both `StackRow` and `FolderGroupRow` no longer accept the prop. Removed the destructure line and replaced with an inline comment explaining why the prop is kept on `UnifiedStackPanelProps` for call-site compatibility (MapBuilderPage still passes it, `handlers.onOpacityChange` still feeds LayerEditorPanel). See "Deviations" section below.
- **OUT-OF-SCOPE confirmed untouched:** `StackRow.tsx` (already slider-less post-260515-rdn), `BasemapGroupRow.tsx`, `BasemapGroupEditorScene.tsx`, `SublayerRow` block in `UnifiedStackPanel.tsx` (still 7-col grid + Slider at relative line 80), `LayerEditorPanel.tsx`, all 4 locale files (`stackRow.opacitySlider` key stays — still used by 2 sibling sliders).
- **Verify gate:** `tsc -b` → exit 0 (zero errors).

### Task 2 — `e7d01dc9`

`test(quick-260515-sqf): drop FolderGroupRow opacity-slider props from defaults`

- **`frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx`** (−2 lines, +1 line edit):
  - Removed `opacity: 1,` from `defaultProps()` factory (prop no longer exists on `FolderGroupRow`).
  - Removed `onOpacityChange: vi.fn(),` from `defaultProps()` factory.
  - Renamed Test 4: `'Test 4: Row body click (not on caret/eye/opacity/kebab) calls onSelectGroup(groupId)'` → `'Test 4: Row body click (not on caret/eye/kebab) calls onSelectGroup(groupId)'`. Test body unchanged (it only clicks the name span — never interacted with the slider).
- **Verify gate:** `vitest run src/components/builder/__tests__/FolderGroupRow.test.tsx src/components/builder/__tests__` → 52 files / 708 tests passing. **FolderGroupRow test count: 18 → 18 (UNCHANGED)** as required by plan done criterion. RESEARCH.md §2 had pre-confirmed that this file has NO dedicated opacity-slider test block, unlike `StackRow.test.tsx` which had one.
- No other test file or e2e file touched.

### Task 3 — `10ea48ca`

`docs(quick-260515-sqf): narrow sketch ref forward note for folder-group slider removal`

- **`.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md`** (+12 / −8 lines):
  - Forward note (lines 34–41): replaced verbatim with the RESEARCH.md §4 rewrite. The note now credits both `260515-rdn` (non-group rows) and `260515-sqf` (user-folder group rows), clarifies that opacity is now exclusively in the LayerEditorPanel Visibility section for both loose layers and user-folder groups, and narrows the "group rows retain sliders" claim to "**only basemap group rows and basemap-editor sublayer rows retain their own opacity sliders**". Explicitly notes that the HTML example below illustrates a basemap-group row and that a user-folder-group row uses the same anatomy minus the `.opacity` input.
  - Group-row HTML example (lines 161–170): added a single-line HTML comment immediately before the `<input class="opacity">` line: `<!-- basemap-group row; user-folder-group row has no .opacity input as of 260515-sqf -->`. Kept the example as a single block per RESEARCH.md §4 option (a) — narrower than authoring a second example.
  - **OUT-OF-SCOPE untouched:** row anatomy diagram, width annotation, bullet list, both CSS blocks (`.row` and `.group-children .row`), loose-row HTML example, "What to Avoid" section — all already updated in 260515-rdn for the 6-column StackRow change.
  - **Force-add note:** Used `git add -f .claude/skills/.../layer-rows-and-groups.md` because `.claude/` is gitignored repo-wide. The file is already tracked (per predecessor commit `dbf43ab5`), so this is the same single-explicit-path `-f` pattern, not a blanket `-fA` on the directory (per `feedback_no_blanket_add_planning.md`).
- **Verify gate:** `grep -v '^#' layer-rows-and-groups.md | grep -c "260515-sqf"` → 3 (gate required ≥1).

## End-to-End Gate Results

| # | Gate | Expected | Actual | Status |
|---|------|----------|--------|--------|
| 1 | `cd frontend && ./node_modules/.bin/tsc -b` | exit 0 | exit 0 (zero errors, zero warnings) | PASS |
| 2 | `cd frontend && ./node_modules/.bin/vitest run src/components/builder/__tests__` | all green; FolderGroupRow count UNCHANGED | 52 files / 708 tests passing; FolderGroupRow 18 → 18 | PASS |
| 3 | `grep -n "onOpacityChange" frontend/src/components/builder/FolderGroupRow.tsx` | 0 matches | 0 matches | PASS |
| 4 | `grep -n '"opacitySlider"' frontend/src/i18n/locales/{en,de,es,fr}/builder.json` | exactly 4 matches | 4 matches, line 814 in all 4 files, all untouched | PASS |
| 5 | `grep -rn "stackRow\.opacitySlider" frontend/src/components/builder/` | exactly 2 matches | 2 matches: `BasemapGroupRow.tsx:189`, `BasemapGroupEditorScene.tsx:196` | PASS |
| 6 | Manual / Playwright smoke per Task 3 | Playwright MCP if available; otherwise authorized fallback | Playwright MCP NOT exposed to this agent; test map has NO folder groups (verified via API — only 2 loose layers, one raster + one vector); authorized fallback applied — substituted source-level post-conditions + stack-reachability curl | PASS (fallback) |

### Manual smoke — substitute evidence (Gate 6)

The constraint block explicitly authorized two fallback paths:
1. "If no folder groups in test map — visual verification skipped, source post-conditions sufficient."
2. Drive verification via Playwright MCP if available.

This agent does NOT have `mcp__playwright__*` tools exposed (same situation as the predecessor 260515-rdn executor). The test map at `dfbe4fd8-56a0-46d0-a155-3256d2c35d37` was introspected via authenticated API call (`POST /api/auth/login` with `admin`/`admin`, then `GET /api/maps/<id>` with Bearer JWT) and contains:
- **TOTAL_LAYERS:** 2
- **FOLDER_GROUPS (layer_type==folder_group):** **0**
- **LAYER_TYPES_PRESENT:** `['raster_geolens', 'vector_geolens']` (no group types)

Therefore the authorized "no folder groups in test map" fallback applies. Source-level post-conditions for the three smoke claims:

1. **"Folder-group row has NO slider (only caret, grip, eye, type-icon, name, kebab visible)"** — `grep "onOpacityChange" FolderGroupRow.tsx` = 0; `grep "from '@/components/ui/slider'" FolderGroupRow.tsx` = 0; grid template at L145 confirmed `grid-cols-[16px_14px_22px_22px_1fr_22px]` (the `_60px_` slot is gone); no `<Slider>` element remains in the file.
2. **"Clicking a folder-group row body opens LayerEditorPanel with a working Opacity slider in the Visibility section"** — `LayerEditorPanel.tsx` line 431 + 434 confirm the canonical Visibility-section slider with `aria-label={t('layerEditor.visibility.opacity', { defaultValue: 'Opacity' })}` is intact; the `handlers.onOpacityChange` chain in `MapBuilderPage` + `use-builder-layers.ts:944` was explicitly untouched.
3. **"Basemap-group + basemap-editor sublayer sliders still render"** — `BasemapGroupRow.tsx:189` still calls `t('stackRow.opacitySlider', …)`; `BasemapGroupEditorScene.tsx:196` same; the `SublayerRow` block in `UnifiedStackPanel.tsx` (at relative line 80) still renders `<Slider` inside its 7-col `grid-cols-[16px_14px_22px_22px_1fr_60px_22px]` template — none touched by this task.
4. **"StackRow non-group rows remain slider-less"** — `grep -cE "onOpacityChange|from '@/components/ui/slider'" StackRow.tsx` = 0 (already verified at the predecessor `4bd92e87` commit; my edits did not regress this).

The dev server uses Vite HMR; the running stack picked up source-file changes automatically on save. If a human-in-loop browser smoke is desired before declaring CLOSED, the operator can open `http://localhost:8080/maps/dfbe4fd8-56a0-46d0-a155-3256d2c35d37` and either (a) add a user-folder group to that map and re-verify the smoke claims, or (b) navigate to any other map containing a user-folder group.

## What Was OUT-OF-SCOPE (Intentionally Untouched)

Per CONTEXT.md decisions and RESEARCH.md §3/§5:

- **Locale files** (`frontend/src/i18n/locales/{en,de,es,fr}/builder.json`): the `stackRow.opacitySlider` key has 2 surviving consumers after this task (BasemapGroupRow + BasemapGroupEditorScene), so the key stays. Zero locale edits.
- **Sibling group-level opacity sliders**: `BasemapGroupRow.tsx` (per CONTEXT.md "separate investigation, see 260515-zzz follow-up — has additional persistence concerns"), `BasemapGroupEditorScene.tsx`, and `SublayerRow` inside `UnifiedStackPanel.tsx` all left intact.
- **`LayerEditorPanel.tsx`**: the surviving canonical control's home; intentionally untouched.
- **All other `onOpacityChange` references in UnifiedStackPanel.tsx** (line 76 top-level prop, lines 231/251/282 BasemapGroupRowWrapper interface/destructure/forward, line 775 `onOpacityChange={() => {}}` noop on basemap wrapper instantiation) — all kept as load-bearing wiring for the basemap-wrapper code path.
- **`MapBuilderPage.tsx` + `use-builder-layers.ts:944`**: the page-level `handlers.onOpacityChange` chain is still load-bearing for LayerEditorPanel; left alone.
- **`StackRow.tsx`**: already slider-less post-260515-rdn; not modified.
- **e2e specs**: RESEARCH.md §2 had pre-confirmed zero e2e references to the row slider; nothing to update.
- **Other test files**: the four `UnifiedStackPanel.*.test.tsx` mocks of FolderGroupRow do NOT destructure `onOpacityChange` — left alone, no regression.

## Deviations from Plan

### Rule 3 auto-fix — unused main-component destructure in UnifiedStackPanel.tsx

- **Found during:** Task 1 (immediately after applying the planned Task-1 edits and running `tsc -b`).
- **Issue:** TypeScript error TS6133 at `UnifiedStackPanel.tsx:589` — `'onOpacityChange' is declared but its value is never read`. RESEARCH.md §1 had explicitly inventoried this destructure line at L594 as "leave alone" on the assumption that it was still forwarded somewhere in the main component body. After my Task-1 edits, this turned out to be incorrect: the only remaining `onOpacityChange={onOpacityChange}` forwarding inside the main component body was the one at line 910 (which Task 1 removed), and the basemap-wrapper instantiation at line 775 passes a hard-coded `onOpacityChange={() => {}}` noop literal instead of the destructured local.
- **Fix:** Removed the `onOpacityChange,` destructure line. The prop stays in `UnifiedStackPanelProps` (line 76) for call-site compatibility with `MapBuilderPage`. Added an inline comment block explaining the architectural state mirroring the pre-existing `onReorder` comment pattern in the same destructure block.
- **Files modified:** `frontend/src/components/builder/UnifiedStackPanel.tsx` (single line removal + 6-line comment addition).
- **Commit:** Included in Task 1 commit `53fc662c`.
- **Authorization:** Rule 3 (auto-fix blocking issues — typecheck failure prevents proceeding to Task 2's verify gate). The fix is mechanical: removing an unused destructure when the type system declares it unused. No architectural change. The `UnifiedStackPanelProps.onOpacityChange` interface member is preserved per RESEARCH.md §1's "leave alone" directive for that line.

### Notes / caveats (no user action needed)

- **Playwright MCP not available** — substituted with source post-conditions + authenticated API introspection of the test map. The test map has no folder groups, which is exactly the predicted scenario the constraint block authorized as a fallback.
- **`.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md` force-added** — `.claude/` is gitignored repo-wide; predecessor `dbf43ab5` already force-added this file to the index, so this commit's `git add -f` is the same per-explicit-path pattern (not a blanket `-fA` on the directory, per `feedback_no_blanket_add_planning.md`).

## Authentication Gates Hit

None during execution. The smoke-fallback API call required `POST /api/auth/login` with `admin`/`admin` credentials, which succeeded on first attempt (no auth gate surfaced to the user).

## Commit Hashes

| Task | Commit | Files |
|------|--------|-------|
| 1    | `53fc662c` | `FolderGroupRow.tsx`, `UnifiedStackPanel.tsx` |
| 2    | `e7d01dc9` | `__tests__/FolderGroupRow.test.tsx` |
| 3    | `10ea48ca` | `layer-rows-and-groups.md` (force-added; .claude/ is gitignored) |

## Self-Check: PASSED

- [x] `frontend/src/components/builder/FolderGroupRow.tsx` exists and is committed at `53fc662c`.
- [x] `frontend/src/components/builder/UnifiedStackPanel.tsx` exists and is committed at `53fc662c`.
- [x] `frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx` exists and is committed at `e7d01dc9`.
- [x] `.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md` exists and is committed at `10ea48ca`.
- [x] All 3 commit hashes resolve in `git log` (verified inline).
- [x] All 8 truths in `must_haves.truths` hold.
- [x] Gates 1–5 PASS unconditionally; Gate 6 PASS via authorized fallback (no folder groups in test map + Playwright MCP unavailable).
- [x] No unexpected file deletions across the three commits.
- [x] Locale files byte-identical to pre-task state (zero touched).
