---
quick_id: 260515-rdn
type: quick-task-research
status: ready-for-planning
researched: 2026-05-15
mode: blast-radius
---

# Quick Task 260515-rdn: Remove per-row Opacity slider — Blast-Radius Research

**Researched:** 2026-05-15
**Confidence:** HIGH (every touchpoint located via rg with verbatim grep; sibling-row scoping confirmed by reading each file)
**Approach:** Decision is locked (CONTEXT.md). This document is a categorized inventory of touchpoints. Not a domain survey.

## User Constraints (from CONTEXT.md)

### Locked Decisions
- Remove the row slider entirely from `StackRow.tsx`.
- LayerEditorPanel Visibility-section slider becomes the single canonical opacity control.
- Collapse the freed 60px column. Grid becomes `16px 14px 22px 22px 1fr 22px`.
- Update `.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md` so the row anatomy spec no longer claims a row slider exists.
- Remove `stackRow.opacitySlider` i18n key from all four locales — **CAVEAT, see §3 below.**
- Remove/update tests in `StackRow.test.tsx` that assert the row slider.

### Claude's Discretion
- Whether to grep for storybook/fixtures/e2e selectors (done — see §2 and §6).
- Whether to remove the `onOpacityChange` prop from `StackRowProps` (recommended yes — confirmed safe, see §1).

### Deferred Ideas (OUT OF SCOPE)
- LayerEditorPanel opacity slider behavior (untouched).
- Other row controls (eye, kebab, drag handle, type icon, name).
- **Group-level opacity sliders on `BasemapGroupRow.tsx` and `FolderGroupRow.tsx`** — these are group controls, not per-row layer controls. The user explicitly scoped this to per-row sliders. See §5 for explicit IN-SCOPE / OUT-OF-SCOPE call-out.
- Basemap sublayer per-row sliders inside `BasemapGroupEditorScene.tsx` and the `SublayerRow` in `UnifiedStackPanel.tsx` — these are in the basemap-editor scene, not the main layer stack. OUT-OF-SCOPE.

---

## 1. Source code touchpoints

### Files that must change

| File | Line(s) | What's there | Action |
|------|---------|-------------|--------|
| `frontend/src/components/builder/StackRow.tsx` | 7 | `import { Slider } from '@/components/ui/slider';` | **Remove import** (only consumer in this file is the row slider being deleted) |
| `frontend/src/components/builder/StackRow.tsx` | 34 | `onOpacityChange: (layerId: string, opacity: number) => void;` in `StackRowProps` interface | **Remove prop** |
| `frontend/src/components/builder/StackRow.tsx` | 107 | `onOpacityChange,` destructure in component params | **Remove** |
| `frontend/src/components/builder/StackRow.tsx` | 131 | `const opacity = typeof layer.opacity === 'number' && Number.isFinite(layer.opacity) ? layer.opacity : 1;` | **Remove** (only used by the slider) |
| `frontend/src/components/builder/StackRow.tsx` | 178 | Grid template `'group/row grid grid-cols-[16px_14px_22px_22px_1fr_60px_22px] ...'` | **Update** → `grid-cols-[16px_14px_22px_22px_1fr_22px]` (collapse 60px slot) |
| `frontend/src/components/builder/StackRow.tsx` | 302–324 | `{/* Cell 6: Opacity slider ... */}` wrapper `<div>` + `<Slider>` block including `t('stackRow.opacitySlider', ...)` and `onValueChange={onOpacityChange(...)}` | **Remove entire block** (Cell 6 disappears; Cell 7 kebab becomes Cell 6) |
| `frontend/src/components/builder/StackRow.tsx` | 326 | Comment "Cell 7: Kebab menu" | **Update** to "Cell 6: Kebab menu" |

### Callsites passing `onOpacityChange` to `<StackRow>`

Both are in `UnifiedStackPanel.tsx`. After the prop is removed from `StackRowProps`, these must drop the prop or TypeScript fails:

| File | Line | What's there | Action |
|------|------|-------------|--------|
| `frontend/src/components/builder/UnifiedStackPanel.tsx` | 201 | `<StackRow ... onOpacityChange={onOpacityChange} ... />` inside `SortableStackRow` wrapper | **Remove prop** from instantiation |
| `frontend/src/components/builder/UnifiedStackPanel.tsx` | 1013–1024 | `<StackRow ... onOpacityChange={NOOP} ... />` inside the `<DragOverlay>` ghost render | **Remove prop** from instantiation |

### Files that pass `onOpacityChange` *through* but do NOT need the prop removed

After the prop is gone from `StackRow`, the layer-opacity callback chain still needs to exist for the LayerEditorPanel and the sibling group rows. **Do not chase these out — they are load-bearing for the surviving panel control.**

- `frontend/src/pages/MapBuilderPage.tsx:230` — `onOpacityChange: layers.handleOpacityChange` is on the `handlers` object passed to `<UnifiedStackPanel>` and `<LayerEditorPanel>`. Still needed by LayerEditorPanel + group rows. **Leave alone.**
- `frontend/src/pages/MapBuilderPage.tsx:792, 816, 988` — wiring into `<LayerEditorPanel>`, `<BasemapSublayerEditorScene>`, and the panel handlers prop. **Leave alone.**
- `frontend/src/components/builder/UnifiedStackPanel.tsx:76, 131, 155, 201, 234, 254, 285, 305, 325, 386, 597, 783, 913, 938, 969` — `onOpacityChange` continues to flow to `BasemapGroupRowWrapper`, `FolderGroupRowWrapper`, `SublayerRow`, and `SortableStackRow`. After §1 changes, the prop just stops being *forwarded into* StackRow specifically — the type signature on `SortableStackRowProps` (line 131) needs the prop removed too, because that wrapper exists only to render a `<StackRow>`. **Update line 131 + 155 + 201 to drop the prop on the `SortableStackRow` path. Other group/sublayer paths stay.** (See sub-checklist below.)

#### Sub-checklist for `UnifiedStackPanel.tsx`

| Line | Code | Action |
|------|------|--------|
| 131 | `onOpacityChange: (layerId: string, opacity: number) => void;` in `SortableStackRowProps` | **Remove** (this interface props the row, not the group) |
| 155 | `onOpacityChange,` destructure in `SortableStackRow()` | **Remove** |
| 201 | `onOpacityChange={onOpacityChange}` passed to `<StackRow>` | **Remove** |
| 76 | `onOpacityChange: (layerId: string, opacity: number) => void;` in `UnifiedStackPanelProps` (top-level) | **Leave** — group rows + LayerEditorPanel still need it |
| 234, 254, 285, 305, 325, 386 | Group-wrapper props + forwarding to `<BasemapGroupRow>` / `<FolderGroupRow>` | **Leave** — group sliders are out-of-scope |
| 597, 783, 913, 938, 969 | Other wrappers forwarding to children that still render group/sublayer sliders | **Leave** |
| 1020 | `<StackRow ... onOpacityChange={NOOP} ... />` in DragOverlay ghost | **Remove the prop** (StackRow no longer accepts it) |

### Hook touchpoint (no change)

- `frontend/src/components/builder/hooks/use-builder-layers.ts:944` — `onOpacityChange: handleOpacityChange,` is exported on the `handlers` object that the page composes. Still load-bearing for LayerEditorPanel + group rows. **Leave alone.**

### What stays untouched and why
- `LayerEditorPanel.tsx` — surviving canonical control. CONTEXT.md says do not touch.
- `LayerStyleEditor.tsx` (opacity slider inside Style/Appearance), `RasterLayerControls.tsx`, `BasemapSublayerEditorScene.tsx`, `DEMEditorScene.tsx` — all live in the LayerEditorPanel scene tree, not the row.

---

## 2. Test touchpoints

### `frontend/src/components/builder/__tests__/StackRow.test.tsx`

| Line(s) | What's there | Action |
|---------|-------------|--------|
| 95 | `onOpacityChange: vi.fn(),` in `defaultProps()` factory | **Remove** (prop no longer exists on StackRow) |
| 104 | Test description: `'renders the six interactive cells in DOM order: grip → eye → name → opacity slider → kebab (caret hidden)'` | **Update** description: remove "opacity slider →"; rename to "renders the five interactive cells" |
| 126–128 | ```const slider = screen.getByRole('slider', { name: /Opacity for/i }); expect(slider).toBeInTheDocument();``` inside that test | **Remove** these three lines |
| 282–288 | Whole test `it('opacity slider aria-label reads "Opacity for {layer name}"', ...)` | **Delete entire test block** |

No other test in this file references the row slider (verified by `rg "Opacity\|opacit"` over the file).

### Other test files — checked, no row-slider assertions

| File | Status |
|------|--------|
| `frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx:178` | Passes `onOpacityChange: vi.fn()` in shared defaults — **leave alone** (still needed for top-level prop on UnifiedStackPanel; group rows still use it) |
| `frontend/src/components/builder/__tests__/UnifiedStackPanel.a11y.test.tsx:239` | Same — **leave alone** |
| `frontend/src/components/builder/__tests__/UnifiedStackPanel.multi-select.test.tsx:237` | Same — **leave alone** |
| `frontend/src/components/builder/__tests__/UnifiedStackPanel.empty-state.test.tsx:143` | Same — **leave alone** |
| `frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx:67, 170` | Has its own `'Test 9: opacity slider calls onOpacityChange(groupId, value)...'` — this is the **group** slider, NOT the row. **OUT-OF-SCOPE per CONTEXT.md** — leave alone |
| `frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx:68` | Same — group slider, out of scope. **Leave alone** |
| `frontend/src/components/builder/__tests__/LayerEditorPanel.test.tsx:74` | Tests the surviving canonical panel control — **leave alone** |
| `frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx` (many lines) | Tests inside-flyout control — **leave alone** |
| `frontend/src/components/builder/__tests__/RasterLayerControls.test.tsx` | Tests inside-flyout control — **leave alone** |
| `frontend/src/components/builder/__tests__/DEMEditorScene.test.tsx:122` | Tests inside-flyout DEM scene — **leave alone** |
| `frontend/src/components/builder/__tests__/BasemapSublayerEditorScene.test.tsx:71` | Tests inside-flyout sublayer editor — **leave alone** |
| `frontend/src/components/builder/__tests__/ChatPanel.test.tsx:52, 63, 203, 215, 219` | Tests chat command `dispatches set_opacity to onOpacityChange` — semantic dispatch, **leave alone** |

### E2E touchpoints — **NONE**

Searched all of `/Users/ishiland/Code/geolens/e2e/`:
- No file contains `Opacity for`, `opacitySlider`, `opacity slider`, or `aria-label.*pacity`.
- `builder-v1-5.spec.ts`, `builder-unified-stack.spec.ts`, `builder-styling.spec.ts`, `builder.spec.ts` confirmed clean.

**Conclusion: no e2e updates required.**

---

## 3. i18n touchpoints — **CRITICAL CAVEAT**

The CONTEXT.md decision says "Remove the `stackRow.opacitySlider` i18n key from all four locales since no UI references it after this change." **This is incorrect as stated.** The key has four consumers, and only ONE goes away with this task:

| Consumer | File | Status after row-slider removal |
|----------|------|-------------------------------|
| Row slider (this task removes it) | `StackRow.tsx:310` | **Removed** |
| Group slider on basemap row (OUT-OF-SCOPE) | `BasemapGroupRow.tsx:189` | **Still uses the key** |
| Group slider on folder row (OUT-OF-SCOPE) | `FolderGroupRow.tsx:283` | **Still uses the key** |
| Sublayer slider in basemap editor scene (OUT-OF-SCOPE) | `BasemapGroupEditorScene.tsx:196` | **Still uses the key** |

### Action: DO NOT delete the i18n key.

The CONTEXT.md decision must be revised:
- **Keep** `stackRow.opacitySlider` in all four locale files (`frontend/src/i18n/locales/{en,de,es,fr}/builder.json:814`).
- The key remains in active use by the three OUT-OF-SCOPE sliders.
- A planner trying to follow the CONTEXT.md decision literally would delete the key and break aria-labels on three other live sliders.

### Locale file lines (for reference, in case planner re-decides)
| File | Line | Content |
|------|------|---------|
| `frontend/src/i18n/locales/en/builder.json` | 814 | `"opacitySlider": "Opacity for {{name}}",` |
| `frontend/src/i18n/locales/de/builder.json` | 814 | `"opacitySlider": "Deckkraft für {{name}}",` |
| `frontend/src/i18n/locales/es/builder.json` | 814 | `"opacitySlider": "Opacidad para {{name}}",` |
| `frontend/src/i18n/locales/fr/builder.json` | 814 | `"opacitySlider": "Opacité pour {{name}}",` |

No cousin keys (e.g. `opacityValue`, `opacityLabel`) exist — only `opacitySlider` under the `stackRow.*` namespace.

---

## 4. Sketch / planning doc touchpoints

### `.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md`

| Line | What's there | Action |
|------|-------------|--------|
| 21 | Row anatomy diagram: `[caret] [grip] [eye] [type-icon] [name ............] [opacity] [kebab]` | **Update** → remove `[opacity]` token; align widths |
| 22 | Width annotation: `  16px   14px   22px    22px         1fr               60px      22px` | **Update** → remove `60px` column |
| 32 | Bullet: `- `opacity`: 60px range slider, primary-colored thumb` | **Remove bullet** |
| 33 | Bullet: `- `kebab`: 0 opacity at rest, 100% on row hover or when row is selected` | **Leave** |
| 81 | CSS: `grid-template-columns: 16px 14px 22px 22px 1fr 60px 22px;` | **Update** → remove `60px` |
| 133 | CSS for `.group-children .row { grid-template-columns: 16px 14px 22px 22px 1fr 60px 22px; ... }` | **CAUTION** — this is the **group-children** row template, which (per current implementation) is still rendered by `StackRow` itself. After this task, child rows inside groups will use the new 6-column template. **Update to match** `16px 14px 22px 22px 1fr 22px`. |
| 141–151 | HTML example: loose layer row with `<input class="opacity" type="range" ...>` | **Remove the `<input class="opacity">` line** |
| 154–167 | HTML example: group row also has `<input class="opacity">` | **CAUTION** — group rows DO keep their opacity slider (OUT-OF-SCOPE per CONTEXT.md). **Leave this group-row example untouched**, or annotate "(group rows retain opacity slider — see §x)". |
| 182–184 | Rejection bullet: `- **Numeric opacity inputs** on the row (current `LayerItem.tsx` ships this). The slider already shows the value; the number input duplicates it and consumes horizontal space.` | **Remove bullet** (no longer relevant — slider itself is gone). Or replace with a new "Opacity moved to LayerEditorPanel" note per CONTEXT.md's intent. |

### `.claude/skills/sketch-findings-geolens/references/layer-editor-flyout.md`

- **Not changed** — this is the surviving canonical control's spec. Read for context only; do not edit.

### Add a forward note
Per CONTEXT.md: add a short note at the top of the row anatomy section (or end) explaining that the per-row opacity slider was removed in quick task 260515-rdn and the canonical opacity control now lives in the LayerEditorPanel Visibility section (cross-link to `layer-editor-flyout.md`).

---

## 5. Sibling-row touchpoints — IN-SCOPE / OUT-OF-SCOPE call-out

### **OUT-OF-SCOPE — DO NOT TOUCH** (per CONTEXT.md "Out of scope: Group-level opacity behavior, basemap opacity propagation")

These files render their OWN per-row Slider with the *same* `stackRow.opacitySlider` i18n key. They do **not** delegate to `StackRow` — each is an independent component:

| File | Line | Render type | Reason out-of-scope |
|------|------|-------------|---------------------|
| `frontend/src/components/builder/BasemapGroupRow.tsx` | 188–202 | Own `<Slider>` + own `onOpacityChange(groupId, ...)` callback | Group-level opacity, separate UX question |
| `frontend/src/components/builder/FolderGroupRow.tsx` | 282–296 | Own `<Slider>` + own `onOpacityChange(groupId, ...)` callback | Group-level opacity, separate UX question |
| `frontend/src/components/builder/BasemapGroupEditorScene.tsx` | 195–209 | Own `<Slider>` per sublayer + own `onSublayerOpacityChange(...)` callback | Lives inside the LayerEditorPanel scene tree (Scene B), not the main stack rows |
| `frontend/src/components/builder/UnifiedStackPanel.tsx:507–518` (SublayerRow) | 507–518 | Own `<Slider>` per sublayer + `onSublayerOpacityChange` | Sublayer-level, inside basemap-group expansion |

**Confirmed by reading each file:** None of these four render `<StackRow>`. Each is its own component with its own row body. Removing the slider from `StackRow.tsx` does not visually or behaviorally affect any of these four sliders.

**Implication:** The 60px column persists in three files' grid templates (`BasemapGroupRow.tsx:78`, `FolderGroupRow.tsx:152`, `BasemapGroupEditorScene.tsx:145`, `UnifiedStackPanel.tsx:433` for SublayerRow). **Do NOT update these grid templates.** Only `StackRow.tsx:178` changes.

### **IN-SCOPE** sibling files

- `frontend/src/components/builder/UnifiedStackPanel.tsx` — partially in scope as documented in §1 (only the `SortableStackRow` wrapper + `DragOverlay` instantiation paths; group/sublayer paths untouched).

---

## 6. Storybook / fixtures / demo seed scripts

**None found.**

- No `.stories.tsx` or `.stories.ts` files in the repo.
- No `.storybook/` directory.
- No demo seeder script references `StackRow` or `onOpacityChange`.

**Action: nothing.**

---

## 7. Public API spot-check

`StackRow` is an **internal frontend component** under `frontend/src/components/builder/`. No `index.ts` re-export, no external module boundary.

- Searched `/Users/ishiland/Code/geolens-enterprise/` for `StackRow`, `onOpacityChange`, `opacitySlider` — **zero matches**. (Enterprise overlay is backend-only; no React component crossover.)
- `frontend/src/types/api.ts` — no `StackRow` types exported.
- The `getgeolens.com` repo is a separate marketing/docs site (per MEMORY.md `project_domain_ownership.md`) and does not import from this repo.

**Conclusion: zero public API impact.**

---

## 8. Estimated blast radius

### File count
- **Files modified:** 6
  1. `frontend/src/components/builder/StackRow.tsx`
  2. `frontend/src/components/builder/UnifiedStackPanel.tsx`
  3. `frontend/src/components/builder/__tests__/StackRow.test.tsx`
  4. `.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md`
  5. — (no i18n changes per §3 caveat)
  6. — (no e2e changes per §2)

- **Files NOT modified despite mentioning `onOpacityChange`:** 18 (verified — see §1 "Files that stay unchanged" + §2 test table + §5 OUT-OF-SCOPE table).

### LOC delta (estimate)
| File | Removed | Added | Net |
|------|---------|-------|-----|
| `StackRow.tsx` | ~26 lines (import, prop, destructure, opacity variable, 23-line Cell 6 block, comment "Cell 7 → Cell 6") | ~1 line (grid template change) | **−25** |
| `UnifiedStackPanel.tsx` | 3 prop lines (interface decl, destructure, instantiation in SortableStackRow) + 1 line in DragOverlay = ~4 lines | 0 | **−4** |
| `StackRow.test.tsx` | 1 prop default + 3 assertion lines + 7-line full test = ~11 lines | ~1 line (test title rename) | **−10** |
| `layer-rows-and-groups.md` | ~5 lines + 1 HTML line | ~2 lines (new forward note) | **−4** |
| **Total** | **~46** | **~4** | **−42 LOC** |

### Risk
- **LOW** — the change is mechanical removal with a clean type-system safety net: dropping `onOpacityChange` from `StackRowProps` will trigger TypeScript errors at every callsite still trying to pass it, so the compiler enforces completeness of §1's UnifiedStackPanel edits.
- **One sharp edge:** the i18n decision in CONTEXT.md is wrong (§3). Planner must catch this OR every per-group/per-sublayer Slider loses its accessible name. Flag this to the planner explicitly.
- **Test risk:** Phase 1041 added multi-select props (`isMultiSelected`, etc.) to `StackRow`. None of those couple to opacity. Verified by reading `StackRow.tsx:48–56` and `handleRowClick` at line 152–165. No interaction with this task.

### Verification checkpoints for the executor
1. `cd frontend && pnpm typecheck` should pass after §1 edits (TS surfaces any missed callsite).
2. `pnpm vitest run StackRow` should drop from N passing tests to N−1 passing tests (the deleted `opacity slider aria-label` test).
3. `pnpm vitest run` over the whole `__tests__/builder` directory should remain green — no other test asserts row slider presence.
4. `pnpm test:e2e:smoke:builder` should remain 25/25 green (no e2e refs).
5. Manual smoke: in the Map Builder, opacity is still adjustable from `LayerEditorPanel` Visibility section after clicking a layer row. Group rows still have their own (group-level) opacity slider — that is correct, do not "fix" it.

---

## Sources

All findings verified directly against the live repo at the working directory; no web sources needed.

- `rg -n "onOpacityChange"` over entire repo
- `rg -n "stackRow\.opacitySlider"` over entire repo
- `rg -n "Opacity for"` over entire repo
- `rg -n "grid-cols-\[16px_14px_22px_22px_1fr_60px_22px\]"` over entire repo
- `rg -n "<StackRow"` over entire repo
- `rg -n "w-\[60px\]"` over `frontend/src/components/builder/`
- Direct read of: `StackRow.tsx`, `StackRow.test.tsx`, `BasemapGroupRow.tsx`, `FolderGroupRow.tsx` (lines 270–305), `BasemapGroupEditorScene.tsx` (lines 130–219), `UnifiedStackPanel.tsx` (lines 180–219, 295–399, 425–525, 990–1029), `layer-rows-and-groups.md`, locale files `en/de/es/fr/builder.json`
- Confirmed e2e directory contents; grepped all `.spec.ts` for opacity references — zero hits
- Confirmed no `.stories.*` or `.storybook/` exists
- Spot-checked `~/Code/geolens-enterprise/` for any StackRow reference — zero
