---
phase: 1051
plan: 10
type: execute
wave: 10
depends_on: ["1051-09"]
files_modified:
  - frontend/src/pages/MapBuilderPage.tsx
  - frontend/src/components/builder/LayerEditorPanel.tsx
  - frontend/src/components/builder/__tests__/MapBuilderPage.sheet-close-button.test.tsx
autonomous: false
requirements: [RESP-03]
tags: [builder, responsive, duplicate-close-button, sheet-overlay]

must_haves:
  truths:
    - "At <800px viewport (editor-hidden mode), the Sheet overlay rendering LayerEditorPanel shows EXACTLY ONE close button (the inner LayerEditorPanel X OR the Sheet's built-in X — never both)"
    - "Audit covers: LayerEditorPanel flyout (Sheet variant), BasemapGroupEditorScene-via-Sheet, BasemapSublayerEditorScene-via-Sheet, any other right-sidebar element rendered inside a Sheet"
    - "At full-viewport mode (≥800px) where LayerEditorPanel is a sibling grid column (not in Sheet), behavior is unchanged"
    - "Vitest regression asserts exactly one close button via DOM query"
  artifacts:
    - path: "frontend/src/pages/MapBuilderPage.tsx"
      provides: "Sheet overlay at <800px (lines 1138-1230) sets showClose={false} OR isDrillDown={true} OR otherwise deduplicates X"
      contains: "SheetContent"
    - path: "frontend/src/components/builder/LayerEditorPanel.tsx"
      provides: "Close X (line ~316-325) preserved (the canonical close) — only Sheet's built-in X is suppressed when in Sheet"
      contains: "onClose"
    - path: "frontend/src/components/builder/__tests__/MapBuilderPage.sheet-close-button.test.tsx"
      provides: "Regression test rendering MapBuilderPage at <800px viewport (matchMedia mock) and asserting exactly one close-labeled button in DOM"
      contains: "close"
  key_links:
    - from: "MapBuilderPage.tsx Sheet wrapping LayerEditorPanel"
      to: "LayerEditorPanel.tsx inner close button"
      via: "Sheet renders both a built-in X (shadcn default) AND wraps LayerEditorPanel which has its own X"
      pattern: "SheetContent"
---

<objective>
Fix RESP-03: At narrow viewport widths, right-sidebar flyouts (specifically the `<800px` Sheet overlay wrapping `LayerEditorPanel`) render EXACTLY ONE "X" close button. Per critical_planning_directive #5 and PATTERNS.md finding #6:
- `BasemapPicker.tsx` is dead code — NOT the source of the duplicate-X bug
- The actual duplicate source is the Sheet overlay at `MapBuilderPage.tsx:1138-1230` which renders `BasemapGroupEditorScene` / `LayerEditorPanel` whose chrome already includes a close X (`LayerEditorPanel.tsx:316-325`). The shadcn Sheet component adds its own built-in X by default — total = 2 visible close buttons.

Fix strategy (per PATTERNS.md Plan 10): either (a) pass `showClose={false}` to the shadcn `<SheetContent>` (verify shadcn version supports this prop — current shadcn-ui Sheet usually has a `hideClose` prop OR `showClose` prop), OR (b) when inside a Sheet, suppress the `LayerEditorPanel`'s internal X (e.g., set `isDrillDown` to `true` so the back-arrow shows instead, OR pass a `hideClose` prop to LayerEditorPanel).

Preferred: option (a) — keep the canonical `LayerEditorPanel` close X (which already correctly calls `onClose`), suppress the Sheet's auto-X. This keeps the close affordance in the same DOM position whether the layer editor is in a Sheet (rail mode) or a sibling column (full viewport).

Audit (per ROADMAP Plan 10 task 1): inventory all other right-sidebar elements rendered in a Sheet at narrow widths. If any others have the same duplicate-X bug, fix in the same commit.

Purpose: Confusing UX — two close buttons make users unsure which to click; reduces trust.
Output: Sheet-content close suppressed for the in-scope flyout(s); audit inventory recorded; vitest regression.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/1051-map-builder-polish-bug-sweep/1051-CONTEXT.md
@.planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md
@.planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md

<interfaces>
<!-- From PATTERNS.md — confirmed single inner close + Sheet overlay path. -->

From frontend/src/components/builder/LayerEditorPanel.tsx (lines 316-325 — single close X in the panel header):
```tsx
<button
  type="button"
  onClick={onClose}
  aria-label={isPureSettings
    ? t('settings.closePanel', { defaultValue: 'Close settings' })
    : t('layerEditor.close', { defaultValue: 'Close layer editor' })}
  className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-[var(--surface-2)] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
>
  <X className="h-4 w-4" aria-hidden="true" />
</button>
```

From frontend/src/pages/MapBuilderPage.tsx (lines 1138-1230 — Sheet overlay rendering LayerEditorPanel at <800px):
- Sheet (from shadcn `@/components/ui/sheet`) is rendered when `isEditorHidden=true`
- SheetContent wraps the editor panel + scene
- shadcn SheetContent renders its own built-in close X by default

To suppress the Sheet's X (option a):
- Check shadcn Sheet API: it may be `showClose={false}` OR `hideClose` OR may require a custom `SheetContent` variant. Read `frontend/src/components/ui/sheet.tsx` to confirm.

To suppress LayerEditorPanel X when in Sheet (option b):
- Add a `hideClose` prop (default false) to LayerEditorPanel
- Set `<LayerEditorPanel hideClose />` inside the Sheet wrapper
</interfaces>
</context>

<tasks>

<task type="checkpoint:orchestrator">
  <name>Task 1: Playwright MCP audit at <800px — inventory all duplicate-X surfaces</name>
  <files>(no files modified)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 10 — Sheet overlay analysis + finding #6 BasemapPicker is dead)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md (RESP-03)
  </read_first>
  <action>
    Orchestrator drives Playwright MCP. Steps: (1) Resize viewport to 780px (below 800px breakpoint — editor-hidden mode). (2) Open a map. (3) Click a layer row to open the layer editor → confirm a Sheet overlay appears. (4) Use `mcp_browser_evaluate` to query the Sheet's DOM and count buttons matching `aria-label` regex `/close/i`. (5) Confirm pre-fix count is 2 (or whatever the actual current count is). (6) Repeat for: (a) clicking a basemap row at <800px (BasemapGroupEditorScene in Sheet), (b) clicking a basemap sublayer at <800px (BasemapSublayerEditorScene in Sheet), (c) opening Map Settings at <800px (SettingsEditorScene in Sheet, if applicable). (7) Inventory each surface: file path + observed close-button count. Add incidental issues to scratch list for EMRG-01.
  </action>
  <verify>
    <automated>Playwright MCP captures DOM close-button counts at <800px for each right-sidebar surface.</automated>
  </verify>
  <acceptance_criteria>
    - Inventory complete: per-surface close-button count recorded
    - Duplicate-X surfaces identified (likely 1+)
    - Pre-fix screenshot captured per surface
  </acceptance_criteria>
  <done>Audit complete; fix scope confirmed.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Suppress duplicate close button(s) in Sheet overlay(s)</name>
  <files>frontend/src/pages/MapBuilderPage.tsx, frontend/src/components/builder/LayerEditorPanel.tsx, frontend/src/components/builder/__tests__/MapBuilderPage.sheet-close-button.test.tsx</files>
  <read_first>
    - frontend/src/pages/MapBuilderPage.tsx (Sheet overlay block around lines 1138-1230)
    - frontend/src/components/builder/LayerEditorPanel.tsx (close button line ~316-325, close-related props)
    - frontend/src/components/ui/sheet.tsx (the shadcn Sheet/SheetContent component — check its props for `showClose`/`hideClose`/etc.)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 10 — Fix strategy options a vs b)
  </read_first>
  <behavior>
    - Test 1: At <800px viewport (matchMedia mock), clicking a layer row opens the Sheet AND `screen.queryAllByRole('button', { name: /close/i })` returns exactly 1 (1 element)
    - Test 2: Same assertion for BasemapGroupEditorScene-in-Sheet (open a basemap)
    - Test 3: Same for BasemapSublayerEditorScene-in-Sheet (open a basemap sublayer)
    - Test 4: At ≥800px viewport (no Sheet), opening LayerEditorPanel still renders its canonical close X (regression check — Plan 10 must not remove the X at full-viewport)
    - Test 5: Clicking the surviving close button calls onClose (functional preserved)
  </behavior>
  <action>
    Determine the chosen strategy from Task 1 audit. Preferred: option (a) — suppress Sheet's built-in X.
    
    Option (a) implementation: in `frontend/src/pages/MapBuilderPage.tsx` (lines 1138-1230), update the `<SheetContent>` to pass whichever prop the shadcn Sheet uses to hide its built-in close — verify via reading `frontend/src/components/ui/sheet.tsx`. Common patterns:
    - shadcn-ui Sheet uses a `<SheetClose>` slot that can be omitted by NOT rendering it; some versions auto-render an X via `SheetPrimitive.Close` inside `SheetContent` — if so, customize the `SheetContent` variant locally OR fork it to add a `hideClose` prop.
    - If a `hideClose` / `showClose={false}` prop is supported, pass it.
    - If neither is supported, modify `frontend/src/components/ui/sheet.tsx` to accept and respect a `hideClose` prop (preferred small change since it's a leaf shadcn primitive customization — verify the file is not a generated artifact before editing).
    
    Option (b) fallback: add `hideClose?: boolean` prop to `LayerEditorPanel` (default false). When true, do NOT render the close X at line ~316-325. Set `<LayerEditorPanel hideClose />` inside the Sheet wrapper in MapBuilderPage.tsx.
    
    Document the chosen option in the commit body.
    
    Create `frontend/src/components/builder/__tests__/MapBuilderPage.sheet-close-button.test.tsx` with the 5 behavior tests. Mock matchMedia to simulate <800px viewport. Use the existing MapBuilderPage test harness if present; otherwise render the Sheet-overlay branch directly with stub props.
  </action>
  <verify>
    <automated>cd frontend && npx vitest run src/components/builder/__tests__/MapBuilderPage.sheet-close-button.test.tsx && cd frontend && npx tsc --noEmit</automated>
  </verify>
  <acceptance_criteria>
    - Sheet overlay at <800px renders exactly 1 close button per surface (LayerEditorPanel, BasemapGroupEditorScene, BasemapSublayerEditorScene)
    - At ≥800px, no regression to close button presence in LayerEditorPanel sibling-column rendering
    - Vitest tests pass
    - `cd frontend && npx tsc --noEmit` returns 0 errors
    - Diff is minimal: MapBuilderPage.tsx Sheet wrapper + either ui/sheet.tsx (option a) OR LayerEditorPanel.tsx (option b) + test file
  </acceptance_criteria>
  <done>Duplicate close buttons eliminated; tests green.</done>
</task>

<task type="checkpoint:orchestrator">
  <name>Task 3: Playwright MCP post-fix re-verify each surface + atomic commit</name>
  <files>(no files modified beyond commit)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md
  </read_first>
  <action>
    Orchestrator drives Playwright MCP. Steps: (1) Reload page. (2) Resize viewport to 780px. (3) Open layer editor via Sheet → confirm exactly 1 close X visible. (4) Click X → confirm Sheet closes. (5) Repeat for basemap group editor + basemap sublayer editor + (if applicable) Settings drawer at <800px. (6) Resize to 1200px. (7) Confirm LayerEditorPanel sibling-column close X still works (no regression at full viewport). (8) Spot-check: keyboard Escape still closes the Sheet (shadcn default behavior preserved). After MCP verify passes, create atomic commit with subject: `fix(builder): right-sidebar flyouts render exactly one close button at narrow viewports (RESP-03)`. Stage the in-scope files (3 maximum: MapBuilderPage.tsx + either ui/sheet.tsx OR LayerEditorPanel.tsx + the test file).
  </action>
  <verify>
    <automated>git log --oneline -1 && git show --stat HEAD</automated>
  </verify>
  <acceptance_criteria>
    - Playwright MCP confirms exactly 1 close button per surface at <800px
    - At ≥800px, sibling-column LayerEditorPanel close still functional
    - Escape-to-close preserved
    - Commit exists with subject `fix(builder): right-sidebar flyouts render exactly one close button at narrow viewports (RESP-03)`
    - Inventory of audited flyouts recorded in commit message body
    - `git diff HEAD~1 HEAD --stat` shows ≤3 files modified
  </acceptance_criteria>
  <done>RESP-03 fix verified live + committed atomically.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| client-only UI | Pure visual deduplication; no API surface |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1051-10 | (n/a) | Sheet close button | accept | No security surface; close still functional |
</threat_model>

<verification>
- Playwright MCP confirms exactly 1 close button per Sheet surface at <800px
- No regression at ≥800px
- Vitest regression passes
- `npx tsc --noEmit` returns 0 errors
</verification>

<success_criteria>
- The basemap selector flyout AND any other right-sidebar Sheet overlay renders exactly ONE close button at all viewport widths
- Inventory of audited flyouts is recorded in commit message
- Vitest regression confirms the DOM has 1 close button at <800px
- Atomic commit on main with subject `fix(builder): right-sidebar flyouts render exactly one close button at narrow viewports (RESP-03)`
</success_criteria>

<output>
Create `.planning/phases/1051-map-builder-polish-bug-sweep/1051-10-SUMMARY.md` with: audit inventory (per-surface close-button counts before fix), chosen strategy (a or b), files modified, test result, MCP screenshots before/after.
</output>
