---
quick_id: 260515-rdn
type: quick-task-plan
status: ready-for-execution
planned: 2026-05-15
plan: 01
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/builder/StackRow.tsx
  - frontend/src/components/builder/UnifiedStackPanel.tsx
  - frontend/src/components/builder/__tests__/StackRow.test.tsx
  - .claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md
autonomous: true
requirements:
  - RDN-01  # Remove per-row opacity Slider from StackRow (markup, import, prop, opacity local, grid template)
  - RDN-02  # Remove SortableStackRow's onOpacityChange forwarding path (interface, destructure, two instantiations)
  - RDN-03  # Remove StackRow opacity-slider tests (defaultProps key, embedded assertions, dedicated aria-label test)
  - RDN-04  # Update layer-rows-and-groups.md sketch doc to reflect 6-column StackRow + retained group sliders
  - RDN-05  # Verify no callsite, locale key, group slider, or e2e regressed (typecheck + vitest + manual smoke)

must_haves:
  truths:
    - "Per-row Opacity slider no longer renders on any non-group layer row in the Map Builder layer list"
    - "Clicking a layer row opens LayerEditorPanel and the Visibility-section opacity slider remains the canonical control"
    - "Group rows (BasemapGroupRow, FolderGroupRow) and basemap-editor sublayer rows still render their own opacity sliders, unchanged"
    - "frontend typecheck passes (TS surfaces any missed onOpacityChange callsite into StackRow)"
    - "vitest suites for StackRow and the rest of __tests__/builder remain green after dropping exactly one StackRow opacity test"
    - "The sketch reference doc at .claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md no longer claims StackRow has a row slider, but still documents group-row sliders"
    - "stackRow.opacitySlider i18n key remains present in en/de/es/fr (still used by 3 sibling sliders) — no locale files are touched"
  artifacts:
    - path: frontend/src/components/builder/StackRow.tsx
      provides: "StackRow with no Slider import, no onOpacityChange prop, 6-column grid template, and no Cell-6 opacity block"
      contains: "grid-cols-[16px_14px_22px_22px_1fr_22px]"
    - path: frontend/src/components/builder/UnifiedStackPanel.tsx
      provides: "SortableStackRow wrapper no longer declares/destructures/forwards onOpacityChange to StackRow; DragOverlay ghost StackRow render also drops the prop"
      contains: "<StackRow"
    - path: frontend/src/components/builder/__tests__/StackRow.test.tsx
      provides: "StackRow test file with no opacity-slider assertions and no dedicated aria-label opacity test"
    - path: .claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md
      provides: "Updated sketch reference: 6-column StackRow anatomy + 6-column .group-children .row template + forward note explaining the move; group-row HTML example untouched"
      contains: "grid-template-columns: 16px 14px 22px 22px 1fr 22px"
  key_links:
    - from: frontend/src/components/builder/StackRow.tsx
      to: frontend/src/components/builder/LayerEditorPanel.tsx
      via: "Row click selects the layer; LayerEditorPanel Visibility section is now the only place opacity is editable for non-group layers"
      pattern: "selectRow|onRowClick|onSelect"
    - from: frontend/src/components/builder/UnifiedStackPanel.tsx
      to: frontend/src/components/builder/StackRow.tsx
      via: "SortableStackRow + DragOverlay render <StackRow ... /> — must NOT pass onOpacityChange after this change"
      pattern: "<StackRow"
    - from: frontend/src/components/builder/BasemapGroupRow.tsx
      to: frontend/src/i18n/locales/en/builder.json
      via: "Still consumes t('stackRow.opacitySlider', { name }) — locale key MUST remain"
      pattern: "stackRow\\.opacitySlider"
---

<objective>
Remove the redundant per-row Opacity slider from `StackRow.tsx` so the LayerEditorPanel
Visibility-section slider becomes the single canonical opacity control for non-group
layers in the Map Builder. The change is mechanical removal across one row component,
its sole forwarding wrapper (`SortableStackRow` in `UnifiedStackPanel.tsx`), the
StackRow tests, and the sketch reference doc that documents the row anatomy.

Purpose: Single source of truth for layer opacity, decluttered row, and an end to user
confusion about whether the fiddly 60px slider works. The blast radius is fully
inventoried in `260515-rdn-RESEARCH.md` — the type system safety net (dropping
`onOpacityChange` from `StackRowProps`) catches any missed callsite at typecheck.

Output: A 6-column StackRow with no slider; clean `SortableStackRow` and DragOverlay
callsites; updated tests; updated sketch doc; locales untouched; group sliders
untouched.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/260515-rdn-remove-the-redundant-per-row-opacity-sli/260515-rdn-CONTEXT.md
@.planning/quick/260515-rdn-remove-the-redundant-per-row-opacity-sli/260515-rdn-RESEARCH.md
@frontend/src/components/builder/StackRow.tsx
@frontend/src/components/builder/UnifiedStackPanel.tsx
@frontend/src/components/builder/__tests__/StackRow.test.tsx
@.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md

<interfaces>
<!-- Read RESEARCH.md §1 + §2 + §4 for the full line-by-line touchpoint inventory. -->
<!-- Below is just the call shape that must change so the executor sees it without -->
<!-- chasing files. -->

`StackRowProps` (in StackRow.tsx) currently includes:
  onOpacityChange: (layerId: string, opacity: number) => void

After this plan, that prop is GONE from StackRowProps. TypeScript will then surface
the two instantiation sites in UnifiedStackPanel.tsx (line ~201 in SortableStackRow
and line ~1020 in the DragOverlay ghost) plus the SortableStackRowProps interface
declaration (~131) and its destructure (~155).

`onOpacityChange` continues to flow through:
  - `UnifiedStackPanelProps` (top-level — KEEP, group rows still need it)
  - `MapBuilderPage` handlers object (KEEP, LayerEditorPanel + group rows still need it)
  - `BasemapGroupRow`, `FolderGroupRow`, `BasemapGroupEditorScene`, `SublayerRow`
    (KEEP — these are OUT-OF-SCOPE per CONTEXT.md "group-level opacity behavior")

The `stackRow.opacitySlider` i18n key stays in all 4 locales — 3 OUT-OF-SCOPE
sliders still consume it. **DO NOT touch `frontend/src/i18n/locales/*/builder.json`.**
</interfaces>
</context>

<tasks>

<task type="auto" tdd="false">
  <name>Task 1: Remove the row Slider from StackRow + drop SortableStackRow's onOpacityChange forwarding</name>
  <files>
    frontend/src/components/builder/StackRow.tsx,
    frontend/src/components/builder/UnifiedStackPanel.tsx
  </files>
  <action>
Apply the StackRow.tsx edits per RESEARCH.md §1, in this order:

1. Delete the `import { Slider } from '@/components/ui/slider';` line (StackRow.tsx, top-of-file imports — currently line 7 per research). If after deletion no other slider import remains, the line is simply gone.
2. Remove the `onOpacityChange: (layerId: string, opacity: number) => void;` member from the `StackRowProps` interface (currently line 34).
3. Remove `onOpacityChange,` from the component-parameter destructure (currently line 107).
4. Remove the local `const opacity = typeof layer.opacity === 'number' && Number.isFinite(layer.opacity) ? layer.opacity : 1;` line (currently line 131). It is only consumed by the slider being deleted; if grep shows another consumer, leave it — but research confirms it is only the slider.
5. Update the row container className grid template from `grid-cols-[16px_14px_22px_22px_1fr_60px_22px]` to `grid-cols-[16px_14px_22px_22px_1fr_22px]` (currently line 178). This is the sole grid-template change in StackRow.tsx — sibling group/sublayer files keep their 7-column templates per RESEARCH.md §5.
6. Delete the entire `{/* Cell 6: Opacity slider ... */}` wrapper `<div>` and its child `<Slider>` element (currently lines ~302–324), including the `t('stackRow.opacitySlider', { name: layer.name })` aria label and the `onValueChange={(value) => onOpacityChange(layer.id, value[0])}` handler.
7. Update the comment that currently reads `Cell 7: Kebab menu` (currently line 326) to `Cell 6: Kebab menu` so the source comments match the new column count.

Then apply the UnifiedStackPanel.tsx edits per RESEARCH.md §1 sub-checklist for `SortableStackRow`:

8. Remove the `onOpacityChange: (layerId: string, opacity: number) => void;` member from the `SortableStackRowProps` interface (currently ~line 131). The top-level `UnifiedStackPanelProps` (currently ~line 76) keeps its `onOpacityChange` member because group/sublayer rows still need it — DO NOT touch line 76.
9. Remove `onOpacityChange,` from the `SortableStackRow` component destructure (currently ~line 155).
10. Remove the `onOpacityChange={onOpacityChange}` prop from the `<StackRow ... />` element rendered inside `SortableStackRow` (currently ~line 201).
11. Remove the `onOpacityChange={NOOP}` prop from the `<StackRow ... />` element rendered inside the `<DragOverlay>` ghost block (currently ~line 1020). If `NOOP` becomes unused after this edit, remove its import/declaration too; if it is still used elsewhere in the file, leave it.

DO NOT touch any other `onOpacityChange` reference in UnifiedStackPanel.tsx (lines 234, 254, 285, 305, 325, 386, 597, 783, 913, 938, 969 — all forward to group/sublayer wrappers per RESEARCH.md §1). DO NOT touch `BasemapGroupRow.tsx`, `FolderGroupRow.tsx`, `BasemapGroupEditorScene.tsx`, or `SublayerRow` inside `UnifiedStackPanel.tsx`. DO NOT touch any `frontend/src/i18n/locales/*/builder.json` file — the `stackRow.opacitySlider` key stays per CONTEXT.md REVISED i18n decision.

After edits, the type system is the safety net: `pnpm typecheck` will fail if any callsite still tries to pass `onOpacityChange` into StackRow. Run typecheck BEFORE moving to Task 2.
  </action>
  <verify>
    <automated>cd frontend &amp;&amp; pnpm typecheck</automated>
  </verify>
  <done>
- `frontend/src/components/builder/StackRow.tsx` no longer imports `Slider`, `StackRowProps` no longer declares `onOpacityChange`, the destructure no longer references it, the local `opacity` variable is gone, the grid template is `grid-cols-[16px_14px_22px_22px_1fr_22px]`, the Cell-6 opacity block is removed, and the trailing comment reads `Cell 6: Kebab menu`.
- `frontend/src/components/builder/UnifiedStackPanel.tsx` `SortableStackRowProps` no longer declares `onOpacityChange`, `SortableStackRow` no longer destructures it, neither the `SortableStackRow` `<StackRow>` instantiation nor the `<DragOverlay>` ghost `<StackRow>` instantiation passes the prop. The top-level `UnifiedStackPanelProps.onOpacityChange` and all group/sublayer forwarding paths remain unchanged.
- `cd frontend && pnpm typecheck` passes (zero errors).
- No `frontend/src/i18n/locales/*/builder.json` file is modified in this commit.
  </done>
</task>

<task type="auto" tdd="false">
  <name>Task 2: Update StackRow tests to drop opacity-slider assertions and the dedicated aria-label test</name>
  <files>
    frontend/src/components/builder/__tests__/StackRow.test.tsx
  </files>
  <action>
Apply the StackRow.test.tsx edits per RESEARCH.md §2:

1. In the `defaultProps()` factory, remove the `onOpacityChange: vi.fn(),` line (currently ~line 95). The prop no longer exists on `StackRow`; TypeScript would reject it after Task 1.
2. In the test currently titled `'renders the six interactive cells in DOM order: grip → eye → name → opacity slider → kebab (caret hidden)'` (currently ~line 104):
   - Update the test description to remove `opacity slider →` so it reads (verbatim): `'renders the five interactive cells in DOM order: grip → eye → name → kebab (caret hidden)'`.
   - Delete the three assertion lines that read (currently ~lines 126–128):
     ```
     const slider = screen.getByRole('slider', { name: /Opacity for/i });
     expect(slider).toBeInTheDocument();
     ```
     (and the matching blank/`expect` for the slider). All other assertions in the same test block remain.
3. Delete the entire `it('opacity slider aria-label reads "Opacity for {layer name}"', ...)` test block (currently ~lines 282–288). Remove the surrounding blank line if it leaves a double blank.

DO NOT touch any other test file. RESEARCH.md §2 has confirmed that:
- `UnifiedStackPanel.test.tsx`, `UnifiedStackPanel.a11y.test.tsx`, `UnifiedStackPanel.multi-select.test.tsx`, `UnifiedStackPanel.empty-state.test.tsx` all pass `onOpacityChange: vi.fn()` to UnifiedStackPanel (still needed by the top-level prop) — leave alone.
- `BasemapGroupRow.test.tsx`, `FolderGroupRow.test.tsx` test the GROUP slider — out of scope per CONTEXT.md.
- `LayerEditorPanel.test.tsx`, `LayerStyleEditor.test.tsx`, `RasterLayerControls.test.tsx`, `DEMEditorScene.test.tsx`, `BasemapSublayerEditorScene.test.tsx` test in-flyout controls — leave alone.
- `ChatPanel.test.tsx` tests semantic dispatch to onOpacityChange — leave alone.

DO NOT touch any `e2e/*.spec.ts` file — RESEARCH.md §2 confirmed zero e2e references to the row slider.

After edits, run the StackRow tests to confirm the file is internally consistent, then run the broader builder test directory to confirm no other test depended on the row slider.
  </action>
  <verify>
    <automated>cd frontend &amp;&amp; pnpm vitest run src/components/builder/__tests__/StackRow.test.tsx src/components/builder/__tests__</automated>
  </verify>
  <done>
- `defaultProps()` in `StackRow.test.tsx` no longer includes `onOpacityChange`.
- The renamed `'renders the five interactive cells ...'` test exists (was `'renders the six interactive cells ...'`) and contains no `getByRole('slider')` assertion.
- The `'opacity slider aria-label reads "Opacity for {layer name}"'` test block is fully removed.
- `pnpm vitest run src/components/builder/__tests__/StackRow.test.tsx` passes; the StackRow test count drops by exactly 1 vs. baseline.
- `pnpm vitest run src/components/builder/__tests__` passes (all builder tests green).
- No e2e file is modified.
  </done>
</task>

<task type="auto" tdd="false">
  <name>Task 3: Update sketch reference doc + run final manual-smoke checkpoint</name>
  <files>
    .claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md
  </files>
  <action>
Apply the sketch-doc edits per RESEARCH.md §4 to `.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md`. The doc is consumed by future agents — leaving the old spec causes drift.

1. Row anatomy diagram (currently line 21): change
   ```
   [caret] [grip] [eye] [type-icon] [name ............] [opacity] [kebab]
   ```
   to
   ```
   [caret] [grip] [eye] [type-icon] [name ............] [kebab]
   ```
2. Width annotation directly underneath (currently line 22): change
   ```
     16px   14px   22px    22px         1fr               60px      22px
   ```
   to
   ```
     16px   14px   22px    22px         1fr               22px
   ```
3. Bullet list under the diagram: remove the line `- `opacity`: 60px range slider, primary-colored thumb` (currently line 32). Leave the `kebab`, `caret`, `grip`, `eye`, `type-icon`, `name` bullets untouched.
4. CSS `.row` block (currently line 81): change
   ```
   grid-template-columns: 16px 14px 22px 22px 1fr 60px 22px;
   ```
   to
   ```
   grid-template-columns: 16px 14px 22px 22px 1fr 22px;
   ```
5. CSS `.group-children .row` block (currently line 133): change the same `grid-template-columns` from `16px 14px 22px 22px 1fr 60px 22px` to `16px 14px 22px 22px 1fr 22px`. This template documents StackRow's child-of-group rendering — same component, must match Task 1's change.
6. HTML example "A loose (non-group) layer row" (currently lines 141–151): delete the line `<input class="opacity" type="range" min="0" max="100" value="100" />` (currently line 148). Leave the surrounding `<span>` lines untouched.
7. HTML example "A group row (basemap or user folder)" (currently lines 154–167): **DO NOT TOUCH** — group rows retain their opacity slider per CONTEXT.md and RESEARCH.md §5. The `<input class="opacity">` line inside the group example stays.
8. "What to Avoid" rejection bullet about `Numeric opacity inputs on the row` (currently lines 182–184): delete this bullet. The row no longer has any opacity affordance, so the warning is moot.
9. Add a forward note at the end of the "Row anatomy (every row, including group rows)" section (after the existing bullet list, before "Type icons + colors") that reads (verbatim, with one leading blank line):

   ```
   > **Note (2026-05-15, quick task 260515-rdn):** The per-row opacity slider on
   > non-group rows was removed. Opacity is now edited exclusively in the
   > LayerEditorPanel Visibility section (see `layer-editor-flyout.md`). The
   > 60px slider column was collapsed; the new row template is six columns:
   > `16px 14px 22px 22px 1fr 22px`. **Group rows (basemap, user folder) and
   > basemap-editor sublayer rows still render their own opacity sliders** —
   > the HTML example for the group row below intentionally retains
   > `<input class="opacity">`.
   ```

After the doc edit, run the manual-smoke checkpoint described below to close out the plan.

**Manual smoke (executor performs, no human handback):**
- Stack must be up. If not: `docker compose up -d`. Browse to `http://localhost:8080`, log in (`admin`/`admin` per `.env.example`), open the Map Builder.
- Add or open a map with at least one non-group vector or raster layer.
- Confirm the layer row in the sidebar has NO opacity slider (only grip, eye, type-icon, name, kebab visible — the row is denser by 60px).
- Click the layer row. The LayerEditorPanel flyout opens. Confirm the Visibility section shows an Opacity slider that adjusts the layer's opacity on the map.
- Confirm the basemap group row at the top of the stack STILL shows its own opacity slider (it should be untouched).
- If a folder/user group exists, confirm it also still has a slider.

If Playwright MCP is available and the stack is up, drive this verification through MCP rather than handing back to the user (per the `feedback_playwright_mcp_self_verify.md` memory entry).
  </action>
  <verify>
    <automated>grep -c "60px" .claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md</automated>
  </verify>
  <done>
- The row anatomy diagram, width annotation, CSS `.row` template, CSS `.group-children .row` template, and the loose-row HTML example in `layer-rows-and-groups.md` all reflect the new 6-column layout (`16px 14px 22px 22px 1fr 22px`); the `[opacity]` token, the `60px` column, the `- opacity:` bullet, the loose-row `<input class="opacity">` line, and the "Numeric opacity inputs on the row" rejection bullet are all removed.
- The group-row HTML example in the same doc is unchanged (still contains `<input class="opacity">`).
- The forward note crediting quick task 260515-rdn is appended to the row-anatomy section.
- `grep -c "60px" .claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md` returns `0` (the only `60px` occurrences in the file were the four StackRow-related ones; group/sublayer 60px columns are documented in sibling sketch docs, not this one).
- Manual smoke (or Playwright MCP equivalent) confirms: row has no slider; LayerEditorPanel Visibility opacity slider works; group row sliders still render and still work.
  </done>
</task>

</tasks>

<verification>
End-to-end gate (executor runs in order; any failure halts):

1. `cd frontend && pnpm typecheck` — must pass. This catches any missed `onOpacityChange`-into-StackRow callsite that the planned edits didn't cover.
2. `cd frontend && pnpm vitest run src/components/builder/__tests__/StackRow.test.tsx` — must pass; baseline test count minus 1.
3. `cd frontend && pnpm vitest run src/components/builder/__tests__` — must pass; entire builder test directory green.
4. `grep -n "onOpacityChange" frontend/src/components/builder/StackRow.tsx` — must return `0` matches (prop fully gone from StackRow).
5. `grep -n "onOpacityChange" frontend/src/components/builder/UnifiedStackPanel.tsx | grep -v -E "BasemapGroupRow|FolderGroupRow|SublayerRow|UnifiedStackPanelProps|GroupRowWrapper|handleOpacityChange|onSublayerOpacityChange"` — must NOT include any line where `onOpacityChange` is forwarded to a `<StackRow>` element. (The matches that remain should all be on group/sublayer paths or on the top-level prop.)
6. `grep -n '"opacitySlider"' frontend/src/i18n/locales/en/builder.json frontend/src/i18n/locales/de/builder.json frontend/src/i18n/locales/es/builder.json frontend/src/i18n/locales/fr/builder.json` — must return exactly 4 matches (one per locale). Locale keys are intentionally preserved. NOTE: the JSON nests the key as `"stackRow": { "opacitySlider": ... }` so a literal `"stackRow.opacitySlider"` search returns 0; use the bare key. Cross-check the consuming source files with `grep -rn "stackRow\\.opacitySlider" frontend/src/components/builder/` — must return exactly 3 matches after Task 1 (BasemapGroupRow.tsx, FolderGroupRow.tsx, BasemapGroupEditorScene.tsx); was 4 before.
7. `grep -n "<input class=\"opacity\"" .claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md` — must return exactly 1 match (the surviving group-row HTML example). The loose-row example's opacity input is removed.
8. Manual smoke (per Task 3): row has no slider, LayerEditorPanel Visibility slider works, group sliders still work. Use Playwright MCP if available.
</verification>

<success_criteria>
- All 7 truths in `must_haves.truths` hold.
- `cd frontend && pnpm typecheck` passes.
- `cd frontend && pnpm vitest run src/components/builder/__tests__` passes.
- StackRow test count drops by exactly 1 vs. baseline.
- 4 i18n locale files for `stackRow.opacitySlider` remain present (zero locale edits).
- Sketch reference doc updated per RESEARCH.md §4 (loose-row template + `.group-children .row` template both changed; group-row HTML example untouched).
- Manual/Playwright smoke confirms LayerEditorPanel opacity is functional and group sliders are unaffected.
- One commit on a single branch (atomic quick-task shape).
</success_criteria>

<output>
On completion, create `.planning/quick/260515-rdn-remove-the-redundant-per-row-opacity-sli/260515-rdn-SUMMARY.md` capturing:
- Files modified (4 expected: StackRow.tsx, UnifiedStackPanel.tsx, StackRow.test.tsx, layer-rows-and-groups.md).
- Verification command results (typecheck pass, vitest pass with N−1 StackRow tests, grep counts).
- Confirmation that locales were intentionally NOT touched and group sliders were intentionally NOT touched.
- Manual smoke result (or Playwright MCP transcript) showing row has no slider + LayerEditorPanel Visibility slider works + group sliders still render.
- Commit SHA.
</output>
