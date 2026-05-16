---
quick_id: 260515-sqf
type: quick-task-plan
status: ready-for-execution
planned: 2026-05-15
plan: 01
wave: 1
depends_on: []
predecessor: 260515-rdn
files_modified:
  - frontend/src/components/builder/FolderGroupRow.tsx
  - frontend/src/components/builder/UnifiedStackPanel.tsx
  - frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx
  - .claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md
autonomous: true
requirements:
  - SQF-01  # Remove per-row opacity Slider from FolderGroupRow (markup, import, opacity prop, onOpacityChange prop, opacity local, grid template, Cell-7→Cell-6 comment)
  - SQF-02  # Remove FolderGroupRowWrapper's opacity/onOpacityChange forwarding path (interface, destructure, local, two props, outer callsite at line 910)
  - SQF-03  # Update FolderGroupRow tests (drop opacity + onOpacityChange from defaultProps, retitle Test 4 to remove `/opacity`)
  - SQF-04  # Narrow sketch doc forward note + add HTML-comment annotation on the group-row example (per RESEARCH.md §4 option (a))
  - SQF-05  # Verify no callsite, locale key, sibling group/sublayer slider, or e2e regressed (typecheck + vitest + grep gates + manual smoke)

must_haves:
  truths:
    - "Per-row Opacity slider no longer renders on any user-folder group row in the Map Builder layer list"
    - "Clicking a folder-group row body still opens LayerEditorPanel and the Visibility-section opacity slider remains the canonical control for folder groups"
    - "BasemapGroupRow, BasemapGroupEditorScene, and UnifiedStackPanel SublayerRow still render their own opacity sliders, unchanged (out-of-scope siblings preserved)"
    - "StackRow rows (non-group, post-260515-rdn) remain slider-less and unchanged by this task"
    - "frontend typecheck passes (TS surfaces any missed onOpacityChange/opacity callsite into FolderGroupRow via the FolderGroupRowWrapper interface)"
    - "vitest suite for FolderGroupRow continues to pass with the same 18 tests (no test deleted, only two defaultProps fields removed and one test-name string narrowed)"
    - "The sketch reference doc at .claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md narrows the 260515-rdn forward note to clarify that ONLY basemap group rows retain their slider, with an inline HTML comment on the group-row example"
    - "stackRow.opacitySlider i18n key remains present in en/de/es/fr (still used by 2 sibling sliders) — no locale files are touched"
  artifacts:
    - path: frontend/src/components/builder/FolderGroupRow.tsx
      provides: "FolderGroupRow with no Slider import, no opacity prop, no onOpacityChange prop, 6-column grid template, and no Cell-6 opacity block"
      contains: "grid-cols-[16px_14px_22px_22px_1fr_22px]"
    - path: frontend/src/components/builder/UnifiedStackPanel.tsx
      provides: "FolderGroupRowWrapper no longer declares/destructures/computes/forwards opacity or onOpacityChange to FolderGroupRow; outer callsite at line 910 also drops onOpacityChange"
      contains: "<FolderGroupRowWrapper"
    - path: frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx
      provides: "FolderGroupRow test file with defaultProps stripped of opacity + onOpacityChange; Test 4 name narrowed to drop `/opacity`"
    - path: .claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md
      provides: "Narrowed forward note clarifying basemap-only retention + inline HTML comment on the group-row example noting user-folder group rows have no .opacity input as of 260515-sqf"
  key_links:
    - from: frontend/src/components/builder/FolderGroupRow.tsx
      to: frontend/src/components/builder/LayerEditorPanel.tsx
      via: "Row body click invokes onSelectGroup → onSelectLayer; LayerEditorPanel Visibility section is now the only place opacity is editable for folder groups"
      pattern: "onSelectGroup|onSelectLayer"
    - from: frontend/src/components/builder/UnifiedStackPanel.tsx
      to: frontend/src/components/builder/FolderGroupRow.tsx
      via: "FolderGroupRowWrapper renders <FolderGroupRow ... /> — must NOT pass opacity or onOpacityChange after this change"
      pattern: "<FolderGroupRow"
    - from: frontend/src/components/builder/BasemapGroupRow.tsx
      to: frontend/src/i18n/locales/en/builder.json
      via: "Still consumes t('stackRow.opacitySlider', { name }) — locale key MUST remain (BasemapGroupEditorScene is the second remaining consumer)"
      pattern: "stackRow\\.opacitySlider"
---

<objective>
Remove the redundant per-row Opacity slider from `FolderGroupRow.tsx` so the
LayerEditorPanel Visibility-section slider becomes the single canonical opacity
control for user-folder groups too. This mirrors the 260515-rdn StackRow change
exactly: same file shape, same TS-safety-net pattern, same i18n preservation,
same sketch-doc narrowing.

Purpose: Single source of truth for layer opacity across non-group rows
(post-260515-rdn) AND user-folder group rows (this task), with only basemap
group rows and basemap-editor sublayer rows retaining their own sliders going
forward. Removes the last redundant per-row opacity affordance from the
non-basemap surface.

Output: A 6-column FolderGroupRow with no slider; clean `FolderGroupRowWrapper`
interface + destructure + forwarding; updated tests (props-only edits, no test
deletion); narrowed sketch doc; locales untouched; basemap group sliders +
basemap-editor sublayer sliders untouched.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/260515-sqf-remove-the-redundant-per-row-opacity-sli/260515-sqf-CONTEXT.md
@.planning/quick/260515-sqf-remove-the-redundant-per-row-opacity-sli/260515-sqf-RESEARCH.md
@.planning/quick/260515-rdn-remove-the-redundant-per-row-opacity-sli/260515-rdn-PLAN.md
@frontend/src/components/builder/FolderGroupRow.tsx
@frontend/src/components/builder/UnifiedStackPanel.tsx
@frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx
@.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md

<interfaces>
<!-- Read RESEARCH.md §1 + §2 + §4 for the full line-by-line touchpoint inventory. -->
<!-- Below is just the call shape that must change so the executor sees it without -->
<!-- chasing files. -->

`FolderGroupRowProps` (in FolderGroupRow.tsx) currently includes:
  opacity: number;                                            // line 27
  onOpacityChange: (id: string, opacity: number) => void;     // line 35

After this plan, BOTH props are GONE from `FolderGroupRowProps`. TypeScript will
then surface the FolderGroupRowWrapper interface (UnifiedStackPanel.tsx line 302),
its destructure (line 322), the local `opacity` computation (line 362), the
`opacity={opacity}` prop on `<FolderGroupRow>` (line 375), the
`onOpacityChange={onOpacityChange}` prop on `<FolderGroupRow>` (line 383), AND
the outer `<FolderGroupRowWrapper ... onOpacityChange={onOpacityChange} ... />`
callsite at UnifiedStackPanel.tsx line 910.

`onOpacityChange` continues to flow through:
  - `UnifiedStackPanelProps` top-level (line 76 — KEEP, group/sublayer rows still need it)
  - `MapBuilderPage` handlers object (KEEP, LayerEditorPanel + group rows still need it)
  - `use-builder-layers.ts:944` `handlers.onOpacityChange` (KEEP, load-bearing)
  - `BasemapGroupRowWrapper` (UnifiedStackPanel.tsx:231, 251, 282 — KEEP, out-of-scope)
  - `UnifiedStackPanel.tsx:594` main-component destructure (KEEP, forwarded to BasemapGroupRowWrapper)
  - `UnifiedStackPanel.tsx:780` `onOpacityChange={() => {}}` on a basemap-related wrapper (KEEP, out-of-scope)
  - `BasemapGroupRow.tsx`, `BasemapGroupEditorScene.tsx`, SublayerRow (KEEP, out-of-scope)

The `stackRow.opacitySlider` i18n key stays in all 4 locales — 2 remaining
consumers after this task: `BasemapGroupRow.tsx:189` and
`BasemapGroupEditorScene.tsx:196`. **DO NOT touch `frontend/src/i18n/locales/*/builder.json`.**

Predecessor reference: this plan deliberately mirrors `260515-rdn-PLAN.md`'s
3-task shape (source + typecheck gate → tests → sketch doc + smoke). Read it
for the established workflow if anything below is ambiguous.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="false">
  <name>Task 1: Remove the row Slider from FolderGroupRow + drop FolderGroupRowWrapper's opacity/onOpacityChange forwarding</name>
  <files>
    frontend/src/components/builder/FolderGroupRow.tsx,
    frontend/src/components/builder/UnifiedStackPanel.tsx
  </files>
  <action>
Apply the FolderGroupRow.tsx edits per RESEARCH.md §1 (rows verified verbatim against the live file), in this order:

1. Delete the `import { Slider } from '@/components/ui/slider';` line (FolderGroupRow.tsx line 6 per RESEARCH.md §1). After deletion no Slider import remains in this file.
2. Remove the `opacity: number;` member from the `FolderGroupRowProps` interface (RESEARCH.md §1 line 27). Per the "Decision note on the `opacity` prop" in RESEARCH.md §1, this prop has zero remaining consumers after the slider is removed; the wrapper callsite that passes `opacity={opacity}` also goes (step 9 below).
3. Remove the `onOpacityChange: (id: string, opacity: number) => void;` member from the `FolderGroupRowProps` interface (RESEARCH.md §1 line 35).
4. Remove `opacity: opacityProp,` from the component-parameter destructure (RESEARCH.md §1 line 52). Note the destructure uses the `opacity` → `opacityProp` rename pattern; remove the whole `opacity: opacityProp,` line.
5. Remove `onOpacityChange,` from the component-parameter destructure (RESEARCH.md §1 line 60).
6. Remove the local `const opacity = typeof opacityProp === 'number' && Number.isFinite(opacityProp) ? opacityProp : 1;` line (RESEARCH.md §1 line 79). It is only consumed by the slider being deleted (RESEARCH.md §1 confirms).
7. Update the grid template at RESEARCH.md §1 line 152 from `grid-cols-[16px_14px_22px_22px_1fr_60px_22px]` to `grid-cols-[16px_14px_22px_22px_1fr_22px]` (the wrapping classNames `group/row grid ... gap-2 items-center ...` stay; only the `grid-cols-[...]` token changes). This collapses the freed 60px slot. This is the sole grid-template change in FolderGroupRow.tsx — sibling group/sublayer files keep their 7-column templates per RESEARCH.md §5 (BasemapGroupRow.tsx, BasemapGroupEditorScene.tsx, UnifiedStackPanel.tsx:430 SublayerRow all retain their 60px column).
8. Delete the entire `{/* Cell 6: Opacity slider */}` wrapper `<div>` and its child `<Slider>` element (RESEARCH.md §1 lines 275–297). The block includes the `onPointerDown` + `onClick` stopPropagation handlers, the `t('stackRow.opacitySlider', ...)` aria label, and the `onValueChange={([value]) => onOpacityChange(groupId, ...)}` handler. After deletion, Cell 7 becomes Cell 6.
9. Update the comment at RESEARCH.md §1 line 299 that currently reads `Cell 7: Kebab menu` to `Cell 6: Kebab menu` so source comments match the new column count.

Then apply the UnifiedStackPanel.tsx edits per RESEARCH.md §1 sub-checklist for `FolderGroupRowWrapper` (rows verified verbatim against the live file):

10. Remove the `onOpacityChange: (id: string, opacity: number) => void;` member from the `FolderGroupRowWrapperProps` interface (RESEARCH.md §1 line 302). The top-level `UnifiedStackPanelProps.onOpacityChange` (line 76) and the `BasemapGroupRowWrapperProps.onOpacityChange` (line 231) both stay — DO NOT touch those.
11. Remove `onOpacityChange,` from the `FolderGroupRowWrapper()` parameter destructure (RESEARCH.md §1 line 322).
12. Remove the local `const opacity = typeof layer.opacity === 'number' && Number.isFinite(layer.opacity) ? layer.opacity : 1;` line inside `FolderGroupRowWrapper` (RESEARCH.md §1 line 362). It is computed only to feed the `opacity={opacity}` prop on the child.
13. Remove the `opacity={opacity}` prop from the `<FolderGroupRow ... />` element rendered inside `FolderGroupRowWrapper` (RESEARCH.md §1 line 375). This tracks step 2's interface removal.
14. Remove the `onOpacityChange={onOpacityChange}` prop from the `<FolderGroupRow ... />` element rendered inside `FolderGroupRowWrapper` (RESEARCH.md §1 line 383).
15. Remove the `onOpacityChange={onOpacityChange}` prop from the `<FolderGroupRowWrapper ... />` outer instantiation at RESEARCH.md §1 line 910 (inside the `layers.map` render — the prop currently sits among ~17 forwarded props at lines 903–920; touch only line 910).

DO NOT touch any other `onOpacityChange` reference in UnifiedStackPanel.tsx. Specifically, RESEARCH.md §1 enumerates the "files / lines that pass `onOpacityChange` through but do NOT need the prop removed":
- line 76 (top-level `UnifiedStackPanelProps.onOpacityChange`) — leave alone
- lines 231, 251, 282 (`BasemapGroupRowWrapper` interface + destructure + forwarding to `<BasemapGroupRow>`) — leave alone
- line 594 (main `UnifiedStackPanel` destructure) — leave alone
- line 780 (`onOpacityChange={() => {}}` on a basemap-related wrapper) — leave alone

DO NOT touch `StackRow.tsx` (already slider-less post-260515-rdn), `BasemapGroupRow.tsx`, `BasemapGroupEditorScene.tsx`, or `SublayerRow` inside `UnifiedStackPanel.tsx`. DO NOT touch any `frontend/src/i18n/locales/*/builder.json` file — the `stackRow.opacitySlider` key stays per CONTEXT.md "DO NOT delete" decision (still consumed by 2 sibling sliders, verified in RESEARCH.md §3).

After edits, the type system is the safety net: `tsc -b` will fail if any callsite still tries to pass `opacity` or `onOpacityChange` into FolderGroupRow or FolderGroupRowWrapper. Run typecheck BEFORE moving to Task 2.
  </action>
  <verify>
    <automated>cd frontend &amp;&amp; ./node_modules/.bin/tsc -b</automated>
  </verify>
  <done>
- `frontend/src/components/builder/FolderGroupRow.tsx` no longer imports `Slider`; `FolderGroupRowProps` no longer declares `opacity` or `onOpacityChange`; the destructure no longer references `opacity: opacityProp,` or `onOpacityChange,`; the local `opacity` variable is gone; the grid template is `grid-cols-[16px_14px_22px_22px_1fr_22px]`; the Cell-6 opacity block (lines 275–297) is removed; the trailing comment reads `Cell 6: Kebab menu`.
- `frontend/src/components/builder/UnifiedStackPanel.tsx` `FolderGroupRowWrapperProps` no longer declares `onOpacityChange`; `FolderGroupRowWrapper` no longer destructures `onOpacityChange`; the local `const opacity = ...` inside `FolderGroupRowWrapper` is gone; neither `opacity={opacity}` nor `onOpacityChange={onOpacityChange}` is passed to the child `<FolderGroupRow>`; the outer `<FolderGroupRowWrapper>` callsite (line 910) no longer passes `onOpacityChange={onOpacityChange}`. The top-level `UnifiedStackPanelProps.onOpacityChange`, BasemapGroupRowWrapper paths, main-component destructure, and basemap-related `onOpacityChange={() => {}}` all remain unchanged.
- `cd frontend && ./node_modules/.bin/tsc -b` passes (zero errors).
- No `frontend/src/i18n/locales/*/builder.json` file is modified in this commit.
- No `StackRow.tsx`, `BasemapGroupRow.tsx`, `BasemapGroupEditorScene.tsx`, or SublayerRow code is modified.
  </done>
</task>

<task type="auto" tdd="false">
  <name>Task 2: Update FolderGroupRow tests to drop opacity + onOpacityChange from defaultProps and narrow Test 4 name</name>
  <files>
    frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx
  </files>
  <action>
Apply the FolderGroupRow.test.tsx edits per RESEARCH.md §2. The blast radius here is unusually narrow — RESEARCH.md §2 confirmed via grep that this file has NO dedicated opacity-slider test block (unlike 260515-rdn's StackRow.test.tsx which had one at line 282). The entire test impact is two `defaultProps()` field deletions + one test-name string edit. Test count does NOT change after this task — all 18 tests in the file continue to pass.

1. In the `defaultProps()` factory, remove the `opacity: 1,` line (RESEARCH.md §2 line 60). The prop no longer exists on `FolderGroupRow`; TypeScript would reject it after Task 1.
2. In the `defaultProps()` factory, remove the `onOpacityChange: vi.fn(),` line (RESEARCH.md §2 line 68). The prop no longer exists on `FolderGroupRow`; TypeScript would reject it after Task 1.
3. Update the Test 4 name string (RESEARCH.md §2 line 120). It currently reads (verbatim):
   ```
   'Test 4: Row body click (not on caret/eye/opacity/kebab) calls onSelectGroup(groupId)'
   ```
   Update to (verbatim — drop `/opacity`):
   ```
   'Test 4: Row body click (not on caret/eye/kebab) calls onSelectGroup(groupId)'
   ```
   The test BODY does NOT interact with any slider (it clicks the name span per RESEARCH.md §2) — no assertion changes are needed. Only the test description string changes.

DO NOT touch any other test file. RESEARCH.md §2 has confirmed that:
- `UnifiedStackPanel.test.tsx` (lines 84–113) mocks `FolderGroupRow` as a stub that does NOT destructure `onOpacityChange` — leave alone.
- `UnifiedStackPanel.a11y.test.tsx` (lines 101–144) same shape — leave alone.
- `UnifiedStackPanel.multi-select.test.tsx` (lines 95–127) same shape — leave alone.
- `UnifiedStackPanel.empty-state.test.tsx` (lines 71–85) same shape — leave alone.
- `BasemapGroupRow.test.tsx:170` tests the basemap group slider — out of scope per CONTEXT.md.
- `StackRow.test.tsx` was already updated in 260515-rdn — leave alone.
- `LayerEditorPanel.test.tsx`, `LayerStyleEditor.test.tsx`, `RasterLayerControls.test.tsx`, `DEMEditorScene.test.tsx`, `BasemapSublayerEditorScene.test.tsx` test in-flyout / sublayer-editor controls — leave alone.
- `ChatPanel.test.tsx` tests semantic dispatch to onOpacityChange — leave alone.

DO NOT touch any `e2e/*.spec.ts` file — RESEARCH.md §2 confirmed zero e2e references to the row slider (searched `FolderGroupRow`, `onOpacityChange`, `folder-group`, `opacitySlider`, `Opacity for`).

After edits, run the FolderGroupRow tests to confirm the file is internally consistent, then run the broader builder test directory to confirm no other test depended on the row slider.
  </action>
  <verify>
    <automated>cd frontend &amp;&amp; ./node_modules/.bin/vitest run src/components/builder/__tests__/FolderGroupRow.test.tsx src/components/builder/__tests__</automated>
  </verify>
  <done>
- `defaultProps()` in `FolderGroupRow.test.tsx` no longer includes `opacity` or `onOpacityChange`.
- The renamed Test 4 name string exists (drops `/opacity`); test body unchanged.
- `./node_modules/.bin/vitest run src/components/builder/__tests__/FolderGroupRow.test.tsx` passes; FolderGroupRow test count remains 18 (UNCHANGED — no test removed).
- `./node_modules/.bin/vitest run src/components/builder/__tests__` passes (all builder tests green).
- No other test file is modified; no e2e file is modified.
  </done>
</task>

<task type="auto" tdd="false">
  <name>Task 3: Update sketch reference doc forward note + run final manual-smoke checkpoint</name>
  <files>
    .claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md
  </files>
  <action>
Apply the sketch-doc edits per RESEARCH.md §4 to `.claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md`. The doc was updated in 260515-rdn; this task narrows that update's forward note and annotates the group-row HTML example, per the planner's choice of RESEARCH.md §4 option (a) — narrower, safer than option (b)'s second example. The CONTEXT.md "Sketch findings update" decision flagged this as Claude's discretion and the constraint block selects option (a).

1. **Rewrite the forward note at lines 34–41** (currently a single paragraph crediting 260515-rdn and claiming `(basemap, user folder)` group rows retain their sliders). Replace lines 34–41 verbatim with the wording proposed in RESEARCH.md §4 "Proposed forward-note rewrite":

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

2. **Add an inline HTML comment inside the group-row example** (RESEARCH.md §4 lines 161–170, with the `<input class="opacity">` line at line 168). Per the planner's choice of option (a), DO NOT split the example into two — keep it narrow and safe. Add a single-line HTML comment **immediately before the `<input class="opacity">` line** that reads (verbatim):

   ```
       <!-- basemap-group row; user-folder-group row has no .opacity input as of 260515-sqf -->
   ```

   Indentation should match the surrounding `<span>` / `<input>` lines (RESEARCH.md §4 shows the example uses 4-space indentation inside the `<div class="row">` block). The HTML comment lives INSIDE the example block, immediately preceding the `<input class="opacity">` line — the `<input>` itself stays (basemap group rows still render it).

3. **Do NOT modify any other section.** Specifically:
   - Row anatomy diagram, width annotation, bullet list — already updated in 260515-rdn for the 6-column StackRow change; the diagram already reflects the new 6-column layout. Leave alone.
   - CSS `.row` and `.group-children .row` blocks — already updated in 260515-rdn. Leave alone.
   - The loose-row HTML example — already updated in 260515-rdn (no `<input class="opacity">`). Leave alone.
   - "What to Avoid" section — already updated in 260515-rdn. Leave alone.

After the doc edit, run the manual-smoke checkpoint described below to close out the plan.

**Manual smoke (executor performs, no human handback):**
- Stack must be up. If not: `docker compose up -d`. Browse to `http://localhost:8080`, log in (`admin`/`admin` per `.env.example`), open the Map Builder.
- Open the test map at `http://localhost:8080/maps/dfbe4fd8-…` (the map used for 260515-rdn smoke). If it has at least one user-folder group, confirm the folder-group row has NO opacity slider (only caret, grip, eye, type-icon, name, kebab visible — the row is denser by 60px).
- Click the folder-group row body. The LayerEditorPanel flyout opens. Confirm the Visibility section shows an Opacity slider that adjusts the folder group's opacity on the map (the underlying `handlers.onOpacityChange` chain at `use-builder-layers.ts:944` is intact per RESEARCH.md §1).
- Confirm the basemap group row at the top of the stack STILL shows its own opacity slider (it MUST be untouched — out-of-scope per CONTEXT.md).
- Confirm any expanded basemap sublayer rows STILL show their own opacity sliders.
- StackRow non-group rows (post-260515-rdn) remain slider-less.

**If the test map at dfbe4fd8-… contains NO folder groups (none authored), record this fact in the SUMMARY and skip visual verification with the note: "no folder groups in test map — visual verification skipped, source post-conditions sufficient (typecheck PASS + vitest PASS + grep gates PASS)".** This fallback is explicitly authorized by the constraint block.

If Playwright MCP is available and the stack is up, drive this verification through MCP rather than handing back to the user (per the `feedback_playwright_mcp_self_verify.md` memory entry).
  </action>
  <verify>
    <automated>grep -v '^#' .claude/skills/sketch-findings-geolens/references/layer-rows-and-groups.md | grep -c "260515-sqf"</automated>
  </verify>
  <done>
- The forward note at lines 34–41 is replaced verbatim with the rewrite from RESEARCH.md §4, mentioning both 260515-rdn AND 260515-sqf, clarifying that only basemap group rows and basemap-editor sublayer rows retain sliders, and explicitly stating that the HTML example below illustrates a basemap-group row.
- A single-line HTML comment (`<!-- basemap-group row; user-folder-group row has no .opacity input as of 260515-sqf -->`) is added INSIDE the group-row HTML example, immediately preceding the `<input class="opacity">` line. The `<input>` line itself remains (basemap group rows still render it).
- No other section of the doc is modified (row anatomy diagram, width annotation, bullet list, both CSS blocks, loose-row HTML example, "What to Avoid" section all unchanged from their 260515-rdn state).
- The verify grep returns ≥ 1 match — confirming the new note text containing `260515-sqf` is present in non-comment (markdown body) lines of the file.
- Manual smoke (or Playwright MCP equivalent) confirms: folder-group row has no slider; LayerEditorPanel Visibility opacity slider works for the folder group; basemap-group row slider still renders and still works; basemap-editor sublayer sliders still render and still work; StackRow non-group rows remain slider-less. OR, if no folder groups exist in the test map, this is recorded in the SUMMARY with the authorized fallback note.
  </done>
</task>

</tasks>

<verification>
End-to-end gate (executor runs in order; any failure halts) — re-runs the 260515-rdn pattern adapted for FolderGroupRow:

1. `cd frontend && ./node_modules/.bin/tsc -b` — must pass. This catches any missed `opacity`-into-FolderGroupRow or `onOpacityChange`-into-FolderGroupRow callsite that Task 1's planned edits didn't cover.
2. `cd frontend && ./node_modules/.bin/vitest run src/components/builder/__tests__/FolderGroupRow.test.tsx` — must pass; test count UNCHANGED at 18 (no test deleted; only two defaultProps fields and one test-name string changed).
3. `cd frontend && ./node_modules/.bin/vitest run src/components/builder/__tests__` — must pass; entire builder test directory green.
4. `grep -n "onOpacityChange" frontend/src/components/builder/FolderGroupRow.tsx` — must return `0` matches (prop fully gone from FolderGroupRow).
5. `grep -n '"opacitySlider"' frontend/src/i18n/locales/en/builder.json frontend/src/i18n/locales/de/builder.json frontend/src/i18n/locales/es/builder.json frontend/src/i18n/locales/fr/builder.json` — must return exactly 4 matches (one per locale, line 814). Locale keys are intentionally preserved. NOTE: the JSON nests the key as `"stackRow": { "opacitySlider": ... }` so the bare `"opacitySlider"` token is the correct grep target; a literal `"stackRow.opacitySlider"` JSON search returns 0.
6. `grep -rn "stackRow\\.opacitySlider" frontend/src/components/builder/` — must return exactly **2** matches (was 3 before this task per RESEARCH.md §3): `BasemapGroupRow.tsx:189` and `BasemapGroupEditorScene.tsx:196`. The third consumer (`FolderGroupRow.tsx:283`) is removed by Task 1.
7. Manual smoke (per Task 3): folder-group row has no slider, LayerEditorPanel Visibility slider works for the folder group, basemap group + basemap-editor sublayer sliders still work. Use Playwright MCP if available. Acceptable fallback: "no folder groups in test map — visual verification skipped, source post-conditions sufficient" per the constraint block.
</verification>

<success_criteria>
- All 8 truths in `must_haves.truths` hold.
- `cd frontend && ./node_modules/.bin/tsc -b` passes.
- `cd frontend && ./node_modules/.bin/vitest run src/components/builder/__tests__` passes.
- FolderGroupRow test count UNCHANGED at 18 vs. baseline (RESEARCH.md §2 confirms no test is deleted; only two defaultProps fields + one test-name string change).
- 4 i18n locale files for `stackRow.opacitySlider` remain present (zero locale edits).
- `grep -rn "stackRow\\.opacitySlider" frontend/src/components/builder/` returns exactly 2 matches (down from 3).
- Sketch reference doc updated per RESEARCH.md §4 option (a) — forward note narrowed + inline HTML comment annotation on the group-row example; no second example added; no other doc section touched.
- Manual/Playwright smoke confirms folder-group row has no slider AND LayerEditorPanel Visibility slider is functional AND basemap group + basemap-editor sublayer sliders are unaffected (or authorized fallback note recorded).
- Three atomic commits on a single branch (atomic quick-task shape; mirrors 260515-rdn's `4bd92e87` / `6c2e79e1` / `dbf43ab5` triplet).
</success_criteria>

<output>
On completion, create `.planning/quick/260515-sqf-remove-the-redundant-per-row-opacity-sli/260515-sqf-SUMMARY.md` capturing:
- Files modified (4 expected: FolderGroupRow.tsx, UnifiedStackPanel.tsx, FolderGroupRow.test.tsx, layer-rows-and-groups.md).
- Verification command results (typecheck PASS, vitest PASS with FolderGroupRow at 18 UNCHANGED, grep counts: `onOpacityChange` in FolderGroupRow.tsx = 0, `"opacitySlider"` in 4 locale files = 4, `stackRow.opacitySlider` in builder source = 2).
- Confirmation that locales were intentionally NOT touched, that StackRow / BasemapGroupRow / BasemapGroupEditorScene / SublayerRow were intentionally NOT touched, and that the `handlers.onOpacityChange` callback chain in MapBuilderPage / use-builder-layers.ts STAYS load-bearing.
- Manual smoke result (or Playwright MCP transcript) showing folder-group row has no slider + LayerEditorPanel Visibility slider works for the folder group + basemap group / basemap-editor sublayer sliders still render. OR the authorized fallback note ("no folder groups in test map — visual verification skipped, source post-conditions sufficient").
- 3 commit SHAs (refactor / test / docs).
</output>
