---
quick_id: 260515-sqf
type: quick-task-research
status: ready-for-planning
researched: 2026-05-15
mode: blast-radius
predecessor: 260515-rdn
---

# Quick Task 260515-sqf: Remove FolderGroupRow per-row Opacity slider — Blast-Radius Research

**Researched:** 2026-05-15
**Confidence:** HIGH (every touchpoint located via rg with verbatim line numbers; sibling-row scoping confirmed by reading each consuming file)
**Approach:** Decision is locked (CONTEXT.md). This document is a categorized inventory of touchpoints, mirroring the §1–§8 shape of `260515-rdn-RESEARCH.md`. Not a domain survey.

## User Constraints (from CONTEXT.md)

### Locked Decisions
- Remove the per-row Opacity slider entirely from `FolderGroupRow.tsx` (lines 275–297 — see §1 for exact span).
- LayerEditorPanel Visibility-section slider becomes the single canonical opacity control for folder groups too (already canonical for non-group layers post-260515-rdn).
- Collapse the freed 60px column. Grid becomes `16px 14px 22px 22px 1fr 22px`.
- Remove the `onOpacityChange` prop from `FolderGroupRowProps` AND from any callsite that passes it (the type system catches the callsite).
- Tests in `FolderGroupRow.test.tsx` that assert the row slider must be removed or updated.
- `stackRow.opacitySlider` i18n key STAYS in all 4 locales — still used by 2 sibling sliders after this task. **DO NOT touch any locale file.**
- Update `.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md` to narrow the 260515-rdn forward note's "group rows retain opacity slider" claim to "*basemap* group rows retain their slider".

### Claude's Discretion
- Whether to grep for storybook/fixtures/e2e selectors (done — see §2 and §6).
- Whether to drop the upstream `handlers.onOpacityChange` chain in `MapBuilderPage` / `use-builder-layers.ts` (recommended NO — still load-bearing for LayerEditorPanel + BasemapGroupRow + BasemapGroupEditorScene/SublayerRow).
- Sketch-doc forward-note narrowing wording (Claude's choice — proposed in §4).

### Deferred Ideas (OUT OF SCOPE)
- LayerEditorPanel opacity slider behavior (untouched).
- BasemapGroupRow row slider — separate investigation per CONTEXT.md (`260515-zzz` follow-up, has additional persistence concerns).
- BasemapGroupEditorScene's master-opacity or per-sublayer sliders.
- SublayerRow inside `UnifiedStackPanel.tsx` (basemap-editor sublayer slider).
- Other FolderGroupRow controls (eye, kebab, drag handle, type icon, name, expand caret).

---

## 1. Source code touchpoints

### `frontend/src/components/builder/FolderGroupRow.tsx`

| Line(s) | What's there | Action |
|---------|-------------|--------|
| 6 | `import { Slider } from '@/components/ui/slider';` | **Remove import** (only consumer in this file is the row slider being deleted) |
| 27 | `opacity: number;` in `FolderGroupRowProps` interface | **CAUTION — see decision note below.** Strictly the field can be removed; safest minimal change is to remove it because nothing else in the component will reference `opacity` after the slider is gone. |
| 35 | `onOpacityChange: (id: string, opacity: number) => void;` in `FolderGroupRowProps` interface | **Remove prop** |
| 52 | `opacity: opacityProp,` destructure in component params (rename pattern: `opacity` as `opacityProp`) | **Remove** (only the slider consumes it) |
| 60 | `onOpacityChange,` destructure in component params | **Remove** |
| 79 | `const opacity = typeof opacityProp === 'number' && Number.isFinite(opacityProp) ? opacityProp : 1;` local | **Remove** (only the slider consumes it) |
| 152 | Grid template `'group/row grid grid-cols-[16px_14px_22px_22px_1fr_60px_22px] gap-2 items-center ...'` | **Update** → `grid-cols-[16px_14px_22px_22px_1fr_22px]` (collapse 60px slot — identical change to 260515-rdn's StackRow change) |
| 275–297 | `{/* Cell 6: Opacity slider */}` wrapper `<div>` with `onPointerDown` / `onClick` stopPropagation handlers + child `<Slider>` element including `t('stackRow.opacitySlider', ...)` aria-label and `onValueChange={([value]) => onOpacityChange(groupId, ...)}` | **Remove entire block** (Cell 6 disappears; Cell 7 kebab becomes Cell 6) |
| 299 | Comment `Cell 7: Kebab menu` | **Update** to `Cell 6: Kebab menu` |

**Decision note on the `opacity` prop (line 27):** In `260515-rdn`, the `StackRow` component received `layer` as a single prop (with `layer.opacity` read internally), so dropping the slider freed the local read but no separate prop. `FolderGroupRow` is structured differently — it receives `opacity` as a top-level prop name-aliased to `opacityProp`. After the slider is removed, the prop has zero remaining consumers in the component. Recommend removing it. The wrapper callsite (§ below) passes `opacity={opacity}` — that line also goes.

### `frontend/src/components/builder/UnifiedStackPanel.tsx`

#### `FolderGroupRowWrapper` interface + implementation

| Line | What's there | Action |
|------|-------------|--------|
| 302 | `onOpacityChange: (id: string, opacity: number) => void;` in `FolderGroupRowWrapperProps` interface | **Remove** (this wrapper exists only to render a `<FolderGroupRow>` — when the child no longer accepts the prop, the wrapper no longer needs to declare it) |
| 322 | `onOpacityChange,` destructure in `FolderGroupRowWrapper()` parameter list | **Remove** |
| 362 | `const opacity = typeof layer.opacity === 'number' && Number.isFinite(layer.opacity) ? layer.opacity : 1;` local (computed for the `opacity` prop passed to `<FolderGroupRow>`) | **Remove** (only consumer was the `opacity={opacity}` prop on `<FolderGroupRow>` at line 375; if removing the `opacity` prop per the §1 decision note above) |
| 375 | `opacity={opacity}` prop passed to `<FolderGroupRow>` | **Remove** (tracks the `opacity` prop removal in §1 line 27) |
| 383 | `onOpacityChange={onOpacityChange}` prop passed to `<FolderGroupRow>` | **Remove** |

#### Callsite passing `onOpacityChange` to `<FolderGroupRowWrapper>`

| Line | What's there | Action |
|------|-------------|--------|
| 903–920 | `<FolderGroupRowWrapper ... onOpacityChange={onOpacityChange} ... />` inside the `layers.map` render — `onOpacityChange` is on line 910 | **Remove the `onOpacityChange={onOpacityChange}` prop on line 910** |

#### Files / lines that pass `onOpacityChange` *through* but do NOT need the prop removed

After the prop is gone from `FolderGroupRow` + `FolderGroupRowWrapper`, the layer-opacity callback chain still needs to exist for the LayerEditorPanel and the sibling group/sublayer rows. **Do not chase these out — they are load-bearing for the surviving controls.**

- `frontend/src/components/builder/UnifiedStackPanel.tsx:76` — top-level `UnifiedStackPanelProps.onOpacityChange`. Still needed by BasemapGroupRowWrapper + LayerEditorPanel handler chain. **Leave alone.**
- `frontend/src/components/builder/UnifiedStackPanel.tsx:231, 251, 282` — `BasemapGroupRowWrapper` interface + destructure + forwarding to `<BasemapGroupRow>`. Out-of-scope. **Leave alone.**
- `frontend/src/components/builder/UnifiedStackPanel.tsx:594` — destructure on the main `UnifiedStackPanel` component. **Leave alone** (still forwarded to BasemapGroupRowWrapper).
- `frontend/src/components/builder/UnifiedStackPanel.tsx:780` — `onOpacityChange={() => {}}` on a basemap-related wrapper (comment: "opacity via master slider in Scene B editor"). **Leave alone.**
- `frontend/src/pages/MapBuilderPage.tsx` — `handlers.onOpacityChange = layers.handleOpacityChange` is passed to `<UnifiedStackPanel>` and `<LayerEditorPanel>`. Still load-bearing. **Leave alone.**
- `frontend/src/components/builder/hooks/use-builder-layers.ts:944` — `onOpacityChange: handleOpacityChange,` on the `handlers` object. Still load-bearing. **Leave alone.**

### Files that stay untouched and why
- `LayerEditorPanel.tsx` — surviving canonical control. CONTEXT.md says do not touch.
- `LayerStyleEditor.tsx`, `RasterLayerControls.tsx`, `BasemapSublayerEditorScene.tsx`, `DEMEditorScene.tsx` — all live in the LayerEditorPanel scene tree, not the row.
- `BasemapGroupRow.tsx`, `BasemapGroupEditorScene.tsx` — out-of-scope sibling sliders per CONTEXT.md.
- `StackRow.tsx` — already had its slider removed in 260515-rdn.

---

## 2. Test touchpoints

### `frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx`

| Line(s) | What's there | Action |
|---------|-------------|--------|
| 60 | `opacity: 1,` in `defaultProps()` factory | **Remove** (tracks the `opacity` prop removal in §1) |
| 68 | `onOpacityChange: vi.fn(),` in `defaultProps()` factory | **Remove** (prop no longer exists on FolderGroupRow) |
| 120 | Test name string: `'Test 4: Row body click (not on caret/eye/opacity/kebab) calls onSelectGroup(groupId)'` | **Update wording** (drop `/opacity`): e.g. `'Test 4: Row body click (not on caret/eye/kebab) calls onSelectGroup(groupId)'`. The test BODY does not interact with any slider — it clicks the name span — so no assertion changes are needed. |

**That is the entire test impact.** Unlike `260515-rdn` (which had a dedicated `'opacity slider aria-label reads "Opacity for {layer name}"'` test block at StackRow.test.tsx:282), **`FolderGroupRow.test.tsx` has NO dedicated opacity-slider test block.** Verified by `grep -n "opacity\|Opacity\|slider\|Slider" frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx` — only three hits: the defaultProps fields (lines 60, 68) and the Test 4 name string (line 120). No `getByRole('slider')`, no `Opacity for`, no `aria-label` assertion against the row slider.

**Implication:** test count does NOT change after this task — only props in `defaultProps()` shrink and one test name updates. All 18 tests in the file continue to pass (they assert non-opacity behavior: caret, name editing, kebab menu, alertdialog, focus return).

### Other test files — checked, no FolderGroupRow row-slider assertions

| File | Status |
|------|--------|
| `frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx:84–113` | Mocks `FolderGroupRow` as a stub that destructures only `{ groupId, groupName, isExpanded, onToggleExpand, onSelectGroup }` — does NOT destructure `onOpacityChange`. Extra props passed by the wrapper are ignored by the JSX stub. **Leave alone.** (Mock is structurally tolerant of the prop being removed.) |
| `frontend/src/components/builder/__tests__/UnifiedStackPanel.a11y.test.tsx:101–144` | Same shape — stub destructures `{ groupId, groupName, isExpanded, onToggleExpand, onSelectGroup, isMultiSelected, isMultiSelectionActive, onCmdClick, onShiftClick, onCheckboxClick }`. Does NOT destructure `onOpacityChange`. **Leave alone.** |
| `frontend/src/components/builder/__tests__/UnifiedStackPanel.multi-select.test.tsx:95–127` | Same shape, same prop set as a11y. **Leave alone.** |
| `frontend/src/components/builder/__tests__/UnifiedStackPanel.empty-state.test.tsx:71–85` | Stub destructures only `{ groupId, groupName }`. **Leave alone.** |
| `frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx:170` | Has its own `'Test 9: opacity slider calls onOpacityChange(groupId, value)'` — this is the **basemap** group slider, OUT-OF-SCOPE per CONTEXT.md. **Leave alone.** |
| `frontend/src/components/builder/__tests__/StackRow.test.tsx` | Already updated in 260515-rdn. **Leave alone.** |
| `frontend/src/components/builder/__tests__/LayerEditorPanel.test.tsx`, `LayerStyleEditor.test.tsx`, `RasterLayerControls.test.tsx`, `DEMEditorScene.test.tsx`, `BasemapSublayerEditorScene.test.tsx` | Test in-flyout / sublayer-editor controls. **Leave alone.** |
| `frontend/src/components/builder/__tests__/ChatPanel.test.tsx` | Tests semantic chat dispatch to `onOpacityChange`. **Leave alone.** |

### E2E touchpoints — **NONE**

Searched `e2e/` for `FolderGroupRow`, `onOpacityChange`, `folder-group`, `opacitySlider`, `Opacity for` — zero matches. Same conclusion as 260515-rdn. The 260515-rdn task did not need any e2e edit; this task will not either.

**Conclusion: no e2e updates required.**

---

## 3. i18n touchpoints — **CRITICAL CAVEAT (PROACTIVELY PRESERVED IN CONTEXT.md)**

CONTEXT.md already encodes the right decision after the 260515-rdn precedent: **DO NOT delete the `stackRow.opacitySlider` i18n key.** This research confirms the consumer count is now 3 → 2 (not 3 → 0).

### Current consumers of `t('stackRow.opacitySlider', ...)`

`grep -rn "stackRow\.opacitySlider" frontend/src/components/builder/` returns 3 matches **today**:

| Consumer | File:Line | Status after this task |
|----------|-----------|------------------------|
| Folder-group row slider (this task removes it) | `FolderGroupRow.tsx:283` | **Removed** |
| Basemap-group row slider (OUT-OF-SCOPE) | `BasemapGroupRow.tsx:189` | **Still uses the key** |
| Basemap-editor sublayer slider (OUT-OF-SCOPE) | `BasemapGroupEditorScene.tsx:196` | **Still uses the key** |

After this task: `grep -rn "stackRow\.opacitySlider" frontend/src/components/builder/` MUST return exactly **2** matches. (Was 4 before 260515-rdn, 3 today, will be 2 after.)

### Locale files — DO NOT TOUCH

| File | Line | Content |
|------|------|---------|
| `frontend/src/i18n/locales/en/builder.json` | 814 | `"opacitySlider": "Opacity for {{name}}",` |
| `frontend/src/i18n/locales/de/builder.json` | 814 | `"opacitySlider": "Deckkraft für {{name}}",` |
| `frontend/src/i18n/locales/es/builder.json` | 814 | `"opacitySlider": "Opacidad para {{name}}",` |
| `frontend/src/i18n/locales/fr/builder.json` | 814 | `"opacitySlider": "Opacité pour {{name}}",` |

All four files stay byte-identical. The key remains in active use by `BasemapGroupRow.tsx` and `BasemapGroupEditorScene.tsx`.

### Why this is still flagged as "CRITICAL" even though CONTEXT.md got it right

In 260515-rdn, CONTEXT.md said "delete the key" and research had to correct it. In 260515-sqf, CONTEXT.md learned from that and pre-emptively says "DO NOT delete." Research's job here is to **verify the precondition has not drifted** since 260515-rdn shipped. It has not: 3 consumers exist today (one of which this task removes). The planner must hold the line — *do not* let an executor "tidy up" the key on the grounds that "FolderGroupRow no longer uses it" or that "it's only used by two siblings now."

---

## 4. Sketch / planning doc touchpoints

### `.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md`

The 260515-rdn task already (a) updated the row anatomy to 6 columns, (b) updated both `.row` and `.group-children .row` grid templates, (c) updated the loose-row HTML example, and (d) added a forward note (lines 34–41) crediting 260515-rdn. **This task narrows that note** and clarifies which group rows retain a slider.

| Line(s) | What's there now (post-260515-rdn) | Action |
|---------|-------------------------------------|--------|
| 34–41 | Forward note paragraph: `**Group rows (basemap, user folder) and basemap-editor sublayer rows still render their own opacity sliders** — the HTML example for the group row below intentionally retains its `.opacity` range input.` | **Narrow the parenthetical** — change `(basemap, user folder)` to `(basemap only — user/folder group sliders were removed in quick task 260515-sqf)`. Also append a second sentence noting the second sweep. Proposed wording in callout below. |
| 161–170 | HTML example "A group row (basemap or user folder)" with `<input class="opacity">` on line 168 | **AMBIGUOUS — Claude's discretion required.** After this task, only the basemap group keeps a slider. The user-folder group does NOT. The doc's group-row HTML example currently conflates the two. Two options: **(a)** Leave example as-is, treat it as illustrating "basemap group row only" and rely on the forward note + section title to disambiguate. **(b)** Add a sibling example or annotation showing the user-folder-group row WITHOUT the `.opacity` input. **Recommended: (a)** — keeping diff small and letting the forward note carry the narrowing. Add a single-line comment inside the HTML example: `<!-- basemap-group row; user-folder-group row has no .opacity input as of 260515-sqf -->`. |
| (none) | "What to Avoid" section | **No changes needed** — the 260515-rdn task already removed the "Numeric opacity inputs on the row" bullet. |

### Proposed forward-note rewrite (replaces current lines 34–41)

```
> **Note (2026-05-15, quick tasks 260515-rdn + 260515-sqf):** The per-row
> opacity slider was removed in two sweeps — first from non-group rows
> (260515-rdn), then from user-folder group rows (260515-sqf). Opacity is
> now edited exclusively in the LayerEditorPanel Visibility section (see
> `layer-editor-flyout.md`) for both loose layers and user-folder groups.
> The dedicated 60px slider column was collapsed; the row template is six
> columns: `16px 14px 22px 22px 1fr 22px`. **Only basemap group rows and
> basemap-editor sublayer rows retain their own opacity sliders** — the
> HTML example for the group row below illustrates a basemap-group row;
> a user-folder-group row uses the same anatomy but without the `.opacity`
> range input.
```

### `.claude/skills/sketch-findings-geolens/references/layer-editor-flyout.md`

- **Not changed** — this is the surviving canonical control's spec.

---

## 5. Sibling-row touchpoints — IN-SCOPE / OUT-OF-SCOPE call-out

### **OUT-OF-SCOPE — DO NOT TOUCH** (per CONTEXT.md "Out of scope")

These files render their OWN per-row Slider with the *same* `stackRow.opacitySlider` i18n key. They do **not** delegate to `FolderGroupRow` — each is an independent component:

| File | Line | Render type | Reason out-of-scope |
|------|------|-------------|---------------------|
| `frontend/src/components/builder/BasemapGroupRow.tsx` | 188–202 (approx; key at line 189) | Own `<Slider>` + own `onOpacityChange(groupId, ...)` callback | Per CONTEXT.md: "BasemapGroupRow row slider — separate investigation, see 260515-zzz follow-up — has additional persistence concerns" |
| `frontend/src/components/builder/BasemapGroupEditorScene.tsx` | 195–209 (approx; key at line 196) | Own `<Slider>` per sublayer + own `onSublayerOpacityChange(...)` callback | Lives inside the LayerEditorPanel scene tree (Scene B), not the main stack rows |
| `frontend/src/components/builder/UnifiedStackPanel.tsx` (SublayerRow) | 497–516 (slider block; grid template at line 430) | Own `<Slider>` per sublayer + `onSublayerOpacityChange` | Basemap sublayer row — sublayer-level, inside basemap-group expansion |
| `frontend/src/components/builder/BulkActionBar.tsx` | 249 (`onBulkOpacity(selectedIds, v[0] / 100)`) | Own slider for bulk-edit operations | Bulk-action UI, independent feature, does not use `stackRow.opacitySlider` i18n key (has its own labeling) |

**Confirmed by reading each file:** None of these four render `<FolderGroupRow>`. Each is its own component with its own row body. Removing the slider from `FolderGroupRow.tsx` does not visually or behaviorally affect any of these four sliders.

**Implication:** The 60px column persists in three files' grid templates (`BasemapGroupRow.tsx`, `BasemapGroupEditorScene.tsx`, and `UnifiedStackPanel.tsx:430` for SublayerRow). **Do NOT update these grid templates.** Only `FolderGroupRow.tsx:152` changes.

### **IN-SCOPE** sibling files

- `frontend/src/components/builder/UnifiedStackPanel.tsx` — partially in scope: only the `FolderGroupRowWrapper` interface + destructure + `<FolderGroupRow>` instantiation + the outer `<FolderGroupRowWrapper>` callsite (lines 302, 322, 362, 375, 383, 910). Group/sublayer/basemap paths untouched.

---

## 6. Storybook / fixtures / demo seed scripts

**None found.**

- No `.stories.tsx` or `.stories.ts` files in the repo (verified during 260515-rdn).
- No `.storybook/` directory.
- No demo seeder script references `FolderGroupRow` or its `onOpacityChange`.

**Action: nothing.**

---

## 7. Public API spot-check

`FolderGroupRow` is an **internal frontend component** under `frontend/src/components/builder/`. No `index.ts` re-export, no external module boundary.

- Searched `/Users/ishiland/Code/geolens-enterprise/` for `FolderGroupRow` — **zero matches**. (Enterprise overlay is backend-only; no React component crossover.)
- `frontend/src/types/api.ts` — no `FolderGroupRow` types exported.
- The `getgeolens.com` repo is a separate marketing/docs site and does not import from this repo.

**Conclusion: zero public API impact.**

---

## 8. Estimated blast radius

### File count
- **Files modified:** 4
  1. `frontend/src/components/builder/FolderGroupRow.tsx`
  2. `frontend/src/components/builder/UnifiedStackPanel.tsx`
  3. `frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx`
  4. `.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md`
  5. — (no i18n changes per §3)
  6. — (no e2e changes per §2)
  7. — (no other tests changed per §2)

- **Files NOT modified despite mentioning `onOpacityChange`:** ~18 (verified — see §1 "Files that stay untouched", §2 test table, §5 OUT-OF-SCOPE table). Most notably the four `UnifiedStackPanel.*.test.tsx` mocks of FolderGroupRow do NOT destructure `onOpacityChange`, so they need no edits.

### LOC delta (estimate)

| File | Removed | Added | Net |
|------|---------|-------|-----|
| `FolderGroupRow.tsx` | 1 import + 2 interface lines (`opacity`, `onOpacityChange`) + 2 destructure lines + 1 local `opacity` computation + 23-line Cell-6 block + 1 comment-text edit | ~1 line (grid template change) | **−27 to −29** |
| `UnifiedStackPanel.tsx` | 1 interface line + 1 destructure line + 1 local `opacity` computation + 1 `opacity={opacity}` prop + 1 `onOpacityChange={onOpacityChange}` prop in wrapper + 1 `onOpacityChange={onOpacityChange}` prop at callsite (line 910) | 0 | **−6** |
| `FolderGroupRow.test.tsx` | 2 defaultProps lines (`opacity`, `onOpacityChange`) | ~1 line (test name string edit — net 0) | **−2** |
| `layer-rows-and-groups.md` | ~6 lines of the old forward note | ~10 lines of the rewritten forward note + 1 HTML comment | **+5** |
| **Total** | **~38** | **~13** | **−25 LOC** (matches user's "~−25 LOC" estimate exactly) |

### Risk
- **LOW** — the change is mechanical removal with a clean type-system safety net: dropping `onOpacityChange` from `FolderGroupRowProps` will trigger TypeScript errors at `FolderGroupRowWrapperProps` interface declaration and at the wrapper destructure + child instantiation, which in turn surfaces the `onOpacityChange={onOpacityChange}` prop on line 910 of UnifiedStackPanel.tsx. Same safety net that worked in 260515-rdn.
- **One sharp edge — already neutralized:** the i18n decision in CONTEXT.md proactively says DO NOT delete the key (lesson learned from 260515-rdn). §3 confirms the precondition still holds — 3 consumers today, 2 after this task. Planner must hold the line if any executor proposes "tidying up" the key.
- **One ambiguity (Claude's discretion, see §4):** the sketch-doc group-row HTML example illustrates a row with `.opacity`. After this task that only describes basemap-group rows, not user-folder-group rows. Recommended path: keep the example, add a one-line HTML comment + update the forward note. Both paths are safe; the planner picks.
- **Test risk:** zero. No dedicated row-slider test exists in `FolderGroupRow.test.tsx`, so test count does not change. Phase 1041 multi-select props on the component (lines 41–46, 65–69) don't couple to opacity. Verified.

### Verification checkpoints for the executor
1. `cd frontend && pnpm typecheck` should pass after §1 + §2 edits (TS surfaces any missed callsite — e.g. if the executor forgets line 910).
2. `pnpm vitest run src/components/builder/__tests__/FolderGroupRow.test.tsx` should remain at 18 passing tests (no test removed, only two `defaultProps` lines + one test-name string updated).
3. `pnpm vitest run src/components/builder/__tests__` should remain green — no other test asserts FolderGroupRow row-slider presence; the four UnifiedStackPanel.* mocks of FolderGroupRow do not destructure `onOpacityChange` so they keep working.
4. `pnpm test:e2e:smoke:builder` should remain green (no e2e refs).
5. `grep -n "onOpacityChange\|opacity:" frontend/src/components/builder/FolderGroupRow.tsx` should return 0 matches after edits.
6. `grep -n "onOpacityChange" frontend/src/components/builder/UnifiedStackPanel.tsx | grep -E "FolderGroupRow"` should return 0 matches (no `onOpacityChange` reference within FolderGroupRow* identifier context).
7. `grep -rn "stackRow\.opacitySlider" frontend/src/components/builder/` should return exactly 2 matches (down from 3): `BasemapGroupRow.tsx` and `BasemapGroupEditorScene.tsx`.
8. `grep -n '"opacitySlider"' frontend/src/i18n/locales/{en,de,es,fr}/builder.json` should return exactly 4 matches (one per locale, key untouched).
9. Manual smoke: in the Map Builder, create or open a map with a user-folder group. The folder-group row has NO opacity slider (only caret, grip, eye, type-icon, name, kebab). Clicking the row opens LayerEditorPanel; the basemap-group row at the top STILL has its slider; any expanded basemap sublayers STILL have their sliders.

---

## Sources

All findings verified directly against the live repo at the working directory; no web sources needed.

- `rg -n "onOpacityChange"` over `frontend/src/`
- `rg -n "stackRow\.opacitySlider"` over `frontend/src/components/builder/`
- `rg -n "Opacity for"` over `frontend/src/`
- `rg -n "FolderGroupRow"` over `frontend/src/`
- `grep -n "opacity\|Opacity\|slider\|Slider"` over `FolderGroupRow.test.tsx`
- `grep -n "60px"` over `.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md`
- `grep -rn "FolderGroupRow"` over `/Users/ishiland/Code/geolens-enterprise/`
- `ls /Users/ishiland/Code/geolens/e2e/` then `grep` for FolderGroupRow / onOpacityChange / opacitySlider — zero matches
- Direct read of: `FolderGroupRow.tsx`, `FolderGroupRow.test.tsx`, `UnifiedStackPanel.tsx` (lines 1–200, 200–500, 600–700, 895–1024), `UnifiedStackPanel.test.tsx` (lines 80–115), `UnifiedStackPanel.a11y.test.tsx` (lines 95–145), `UnifiedStackPanel.multi-select.test.tsx` (lines 90–130), `UnifiedStackPanel.empty-state.test.tsx` (lines 65–90), `layer-rows-and-groups.md`, locale files `en/de/es/fr/builder.json` (line 814)
- Precedent: `260515-rdn-RESEARCH.md` and `260515-rdn-PLAN.md` (same pattern, neighboring component)
