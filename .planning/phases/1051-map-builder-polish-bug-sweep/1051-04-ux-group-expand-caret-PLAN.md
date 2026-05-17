---
phase: 1051
plan: 04
type: execute
wave: 4
depends_on: ["1051-03"]
files_modified:
  - frontend/src/components/builder/BasemapGroupRow.tsx
  - frontend/src/components/builder/FolderGroupRow.tsx
  - frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx
autonomous: false
requirements: [UX-01]
tags: [builder, ux, touch-target, caret]

must_haves:
  truths:
    - "Caret expand button on group rows (BasemapGroupRow, FolderGroupRow) has a hit-target box ≥24×24 px"
    - "Caret glyph uses Lucide ChevronRight at ≥16 px (h-4 w-4)"
    - "Caret column grid template still reserves 16px (per sketch 002 A 'A-strict' decision) — hit-target expansion uses negative margin -mx-1, not grid-column changes"
    - "Caret retains rotate-90 transition on expand"
    - "No regression to caret column alignment in non-group StackRow rows (caret column stays reserved)"
  artifacts:
    - path: "frontend/src/components/builder/BasemapGroupRow.tsx"
      provides: "Caret button uses ChevronRight Lucide icon with h-6 w-6 -mx-1 hit area"
      contains: "ChevronRight"
    - path: "frontend/src/components/builder/FolderGroupRow.tsx"
      provides: "Caret button uses ChevronRight Lucide icon with h-6 w-6 -mx-1 hit area (same pattern as BasemapGroupRow)"
      contains: "ChevronRight"
    - path: "frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx"
      provides: "Regression test asserting caret <button> has h-6 w-6 classes AND wraps a ChevronRight (snapshot or class assertion since jsdom lacks getBoundingClientRect for layout)"
      contains: "h-6 w-6"
  key_links:
    - from: "BasemapGroupRow.tsx caret button"
      to: "UnifiedStackPanel.tsx grid template `grid-cols-[16px_14px_22px_22px_1fr_22px]`"
      via: "16px caret column unchanged; -mx-1 extends visual hit area"
      pattern: "16px"
---

<objective>
Fix UX-01: Layer-group expand caret meets touch-target size. The expand/collapse caret on group rows (BasemapGroupRow, FolderGroupRow) gets a ≥24×24 px hit area and a ≥16 px visible glyph, using the Lucide ChevronRight icon. Caret column grid (16px) is preserved per the locked sketch 002 A "A-strict" decision; the hit-target expansion uses negative horizontal margin (`-mx-1`) to extend the visual box within the grid column without altering layout.

Per PATTERNS.md finding #5: replace the Unicode `▸` text character with `<ChevronRight className="h-4 w-4" aria-hidden="true" />` in BOTH BasemapGroupRow.tsx (line ~103) and FolderGroupRow.tsx (line ~178). Wrap the icon in a button with `flex items-center justify-center h-6 w-6 -mx-1` classes to achieve a 24×24 hit target inside the 16px grid column.

Note (jsdom limitation per critical_planning_directive #10): vitest cannot reliably measure `getBoundingClientRect`. Regression test must assert the className tokens are present (`h-6 w-6`), NOT measure DOM rects. Playwright MCP measures the actual rendered hit-target.

Purpose: Tap-friendly caret on tablet/touch; visually-aligned modern iconography.
Output: Caret swap in BasemapGroupRow + FolderGroupRow; className-based regression test; Playwright MCP confirms ≥24×24.
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
<!-- From PATTERNS.md — current caret text-glyph and the locked grid template. -->

From frontend/src/components/builder/BasemapGroupRow.tsx (lines 89-104 — current text glyph):
```tsx
<button
  type="button"
  aria-expanded={isExpanded}
  aria-controls={`basemap-group-children-${groupId}`}
  onClick={(e) => { e.stopPropagation(); onToggleExpand(groupId); }}
  className={cn(
    'text-xs text-muted-foreground transition-transform duration-[--motion-fast] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded',
    isExpanded && 'rotate-90',
  )}
  aria-label={t('basemapGroup.toggleExpand', { defaultValue: 'Toggle basemap group' })}
>
  ▸
</button>
```

From frontend/src/components/builder/FolderGroupRow.tsx (lines 163-180 — same text glyph):
```tsx
<button
  type="button"
  aria-expanded={isExpanded}
  ...
  className={cn(
    'text-xs text-muted-foreground transition-transform duration-[--motion-fast]',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded',
    isExpanded && 'rotate-90',
  )}
>
  ▸
</button>
```

From frontend/src/components/builder/StackRow.tsx (line 174 — locked grid template):
```tsx
'group/row grid grid-cols-[16px_14px_22px_22px_1fr_22px] gap-2 items-center py-2 px-2 ...'
```
The 16px column MUST be preserved. Hit-target expansion uses `-mx-1` (negative 4px on each side) on the button so the 24×24 box extends 4px beyond the 16px column without altering the grid.

Lucide ChevronRight reference (SettingsEditorScene.tsx:152-156):
```tsx
<ChevronRight
  className={cn('h-4 w-4 shrink-0 transition-transform duration-[--motion-fast]', isOpen && 'rotate-90')}
  aria-hidden="true"
/>
```
</interfaces>
</context>

<tasks>

<task type="checkpoint:orchestrator">
  <name>Task 1: Playwright MCP pre-fix measurement</name>
  <files>(no files modified)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 04 — Lucide icon swap)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md (UX-01 caret hit target contract)
  </read_first>
  <action>
    Orchestrator drives Playwright MCP. Steps: (1) Open a map with a basemap group + ≥1 folder group. (2) Use `mcp_browser_evaluate` to locate the caret `<button>` via aria-label matching `/toggle.*group/i`. (3) Call `el.getBoundingClientRect()` for each caret button. (4) Record current width × height (expected ~12-16 px each — text-xs glyph). (5) Screenshot the sidebar. Add incidental issues to scratch list for EMRG-01.
  </action>
  <verify>
    <automated>Playwright MCP records current caret bounding box dimensions for BasemapGroupRow + FolderGroupRow carets.</automated>
  </verify>
  <acceptance_criteria>
    - Pre-fix caret hit-target box dimensions recorded (width × height for both BasemapGroupRow and FolderGroupRow caret buttons)
    - Confirms current size is < 24×24
  </acceptance_criteria>
  <done>Pre-fix measurement captured.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Swap text glyph for Lucide ChevronRight + size up hit target</name>
  <files>frontend/src/components/builder/BasemapGroupRow.tsx, frontend/src/components/builder/FolderGroupRow.tsx, frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx</files>
  <read_first>
    - frontend/src/components/builder/BasemapGroupRow.tsx (caret button around lines 89-104, top imports)
    - frontend/src/components/builder/FolderGroupRow.tsx (caret button around lines 163-180, top imports)
    - frontend/src/components/builder/SettingsEditorScene.tsx (ChevronRight import + className pattern around lines 152-156)
    - frontend/src/components/builder/StackRow.tsx (grid template line 174 — locked at 16px caret column)
    - frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx (existing harness if present; otherwise see __tests__/FolderGroupRow.test.tsx for shape)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 04 — Pattern E Lucide icon swap)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-UI-SPEC.md (UX-01 caret table)
  </read_first>
  <behavior>
    - Test 1: BasemapGroupRow caret button has className tokens `h-6 w-6` (or equivalent producing ≥24px box)
    - Test 2: BasemapGroupRow caret renders a Lucide ChevronRight icon (test via test-id or by checking for `<svg>` with `lucide` class)
    - Test 3: BasemapGroupRow caret rotates (`rotate-90` className) when isExpanded=true
    - Test 4: BasemapGroupRow caret button has `aria-expanded` reflecting isExpanded
    - Test 5: No `▸` Unicode char remains in BasemapGroupRow.tsx or FolderGroupRow.tsx caret JSX
  </behavior>
  <action>
    Edit `frontend/src/components/builder/BasemapGroupRow.tsx`: (a) add `import { ChevronRight } from 'lucide-react';` (likely already imported via other Lucide icons — verify). (b) Replace the caret button (around lines 89-104) so the button has className `flex items-center justify-center h-6 w-6 -mx-1 rounded text-muted-foreground transition-transform duration-[--motion-fast] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring` plus the existing `isExpanded && 'rotate-90'` token, and its children is `<ChevronRight className="h-4 w-4" aria-hidden="true" />` (NOT the `▸` text). Preserve the `aria-expanded`, `aria-controls`, `onClick={(e) => { e.stopPropagation(); onToggleExpand(groupId); }}`, and the `aria-label` translation key. Apply the SAME treatment to `frontend/src/components/builder/FolderGroupRow.tsx` caret button (around lines 163-180): same className shape, same icon swap. Update or create `frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx` with the 5 behavior assertions. Use `screen.getByRole('button', { name: /toggle basemap group/i })` and assert `el.className` contains the size tokens. Tests fail before fix, pass after.
    
    NOTE the locked grid (StackRow.tsx:174 `grid-cols-[16px_14px_22px_22px_1fr_22px]`) MUST NOT be changed — the 16px caret column stays per sketch 002 A "A-strict". The `-mx-1` provides the visual hit-area expansion without altering grid.
  </action>
  <verify>
    <automated>cd frontend && npx vitest run src/components/builder/__tests__/BasemapGroupRow.test.tsx</automated>
  </verify>
  <acceptance_criteria>
    - `grep -n '▸' frontend/src/components/builder/BasemapGroupRow.tsx frontend/src/components/builder/FolderGroupRow.tsx` returns 0 matches (Unicode glyph removed)
    - `grep -n 'ChevronRight' frontend/src/components/builder/BasemapGroupRow.tsx` returns ≥1 match (import + JSX usage)
    - `grep -n 'h-6 w-6' frontend/src/components/builder/BasemapGroupRow.tsx frontend/src/components/builder/FolderGroupRow.tsx` returns ≥2 matches (one per caret)
    - Vitest regression assertions pass
    - StackRow.tsx grid template at line 174 (`grid-cols-[16px_14px_22px_22px_1fr_22px]`) is unchanged (diff this file shows no modification OR file is not in diff at all)
    - `cd frontend && npx tsc --noEmit` returns 0 errors
  </acceptance_criteria>
  <done>Carets swapped to Lucide; vitest green; grid template unchanged.</done>
</task>

<task type="checkpoint:orchestrator">
  <name>Task 3: Playwright MCP post-fix measurement + atomic commit</name>
  <files>(no files modified beyond commit)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md
  </read_first>
  <action>
    Orchestrator drives Playwright MCP. Steps: (1) Reload page. (2) Use `mcp_browser_evaluate` to call `getBoundingClientRect()` on each caret button. (3) Assert width ≥24 AND height ≥24 (the canonical UX-01 success criterion). (4) Test tap on tablet emulation (`mcp_browser_resize` to 1024×768) — confirm caret is easily targetable. (5) Spot-check: caret column alignment in non-group rows (regular StackRow) is unchanged — basemap sublayer rows + data layer rows still align. After MCP verify passes, create atomic commit with subject: `fix(builder): group-row expand caret meets 24px touch target (UX-01)`. Stage only BasemapGroupRow.tsx + FolderGroupRow.tsx + the test file.
  </action>
  <verify>
    <automated>git log --oneline -1 && git show --stat HEAD</automated>
  </verify>
  <acceptance_criteria>
    - Playwright MCP confirms caret hit-target box ≥24×24 for both BasemapGroupRow and FolderGroupRow
    - Caret column alignment unchanged for non-group StackRow rows
    - Commit exists with subject `fix(builder): group-row expand caret meets 24px touch target (UX-01)`
    - `git diff HEAD~1 HEAD --stat` shows only the in-scope files modified
  </acceptance_criteria>
  <done>UX-01 fix verified live + committed atomically.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| client-only UI | Pure visual change; no API surface; no untrusted input |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1051-04 | (n/a) | caret hit-target | accept | No security surface |
</threat_model>

<verification>
- Playwright MCP confirms caret hit-target ≥24×24
- Vitest regression (className-based) passes
- `npx tsc --noEmit` returns 0 errors
- StackRow grid template at line 174 unchanged
</verification>

<success_criteria>
- Caret button hit-target box is ≥24×24 px on BasemapGroupRow AND FolderGroupRow
- Caret glyph is the Lucide ChevronRight at h-4 w-4 (16px)
- StackRow grid template `grid-cols-[16px_14px_22px_22px_1fr_22px]` unchanged
- No regression to caret column alignment in non-group rows
- Atomic commit on main with subject `fix(builder): group-row expand caret meets 24px touch target (UX-01)`
</success_criteria>

<output>
Create `.planning/phases/1051-map-builder-polish-bug-sweep/1051-04-SUMMARY.md` when done with: pre/post bounding-box measurements, files modified, test result, MCP screenshots.
</output>
