---
phase: 1051
plan: 03
type: execute
wave: 3
depends_on: ["1051-02"]
files_modified:
  - frontend/src/components/builder/FolderGroupRow.tsx
  - frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx
autonomous: false
requirements: [BUG-03]
tags: [builder, bugfix, autofocus, rename-group]

must_haves:
  truths:
    - "Clicking 'Rename group' on a folder group's kebab puts text-input focus into the rename field immediately"
    - "Typing immediately enters the rename input without an extra click"
    - "Existing existing-name select behavior (inputRef.current?.select() on mount) continues to work"
    - "No regression to the Escape-cancel / Enter-commit / blur-commit flows"
  artifacts:
    - path: "frontend/src/components/builder/FolderGroupRow.tsx"
      provides: "Rename input mounts focused — DropdownMenu close path no longer steals focus back"
      contains: "requestAnimationFrame"
    - path: "frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx"
      provides: "Regression test asserting document.activeElement === inputRef after Rename menu item click"
      contains: "activeElement"
  key_links:
    - from: "frontend/src/components/builder/FolderGroupRow.tsx kebab onSelect"
      to: "frontend/src/components/builder/FolderGroupRow.tsx rename input mount"
      via: "handleStartRename → setEditing(true) → input renders → autoFocus + rAF-deferred focus()"
      pattern: "handleStartRename"
---

<objective>
Fix BUG-03: rename-group autofocus. Clicking "Rename group" on a folder group row immediately puts text-input focus into the rename field; typing immediately enters text without an extra click.

Per PATTERNS.md finding #4: the existing FolderGroupRow rename input ALREADY has `autoFocus` and `inputRef.current?.select()` in a `useEffect`. The bug is a focus-restoration race with Radix DropdownMenu portal: the kebab `onSelect` calls `_e.preventDefault()` (keeps the menu open) and the menu's `restoreFocus` steals focus back to the kebab button shortly after the input mounts.

Per critical_planning_directive #2: use `requestAnimationFrame` deferred focus to win the race against Radix's restoreFocus. Do NOT just add `autoFocus` (already present).

Purpose: Tiny but persistent affordance bug — wastes a click on every rename.
Output: Fix the focus-race in `FolderGroupRow.tsx`; vitest regression asserts `document.activeElement === input` after the rename menu item is clicked.
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
<!-- From PATTERNS.md — current FolderGroupRow rename flow. -->

From frontend/src/components/builder/FolderGroupRow.tsx (lines 230-254 — input already has autoFocus + select-on-mount):
```tsx
<input
  ref={inputRef}
  type="text"
  className="h-6 w-full min-w-0 border-b border-primary bg-transparent text-sm font-semibold outline-none focus:ring-1 focus:ring-ring"
  value={nameValue}
  onChange={(e) => setNameValue(e.target.value)}
  onBlur={commitRename}
  onKeyDown={(e) => { if (e.key === 'Enter') { ... } if (e.key === 'Escape') { ... } }}
  onClick={(e) => e.stopPropagation()}
  // eslint-disable-next-line jsx-a11y/no-autofocus -- triggered by explicit rename action
  autoFocus
/>
```

From frontend/src/components/builder/FolderGroupRow.tsx (lines 81-85 — useEffect select on edit):
```ts
useEffect(() => {
  if (editing && inputRef.current) {
    inputRef.current.select();
  }
}, [editing]);
```

From frontend/src/components/builder/FolderGroupRow.tsx (lines 293-298 — kebab onSelect with the focus-stealing preventDefault):
```tsx
<DropdownMenuItem
  onSelect={(_e) => {
    _e.preventDefault(); // keep menu open while we set editing=true
    handleStartRename();
  }}
>
```
</interfaces>
</context>

<tasks>

<task type="checkpoint:orchestrator">
  <name>Task 1: Playwright MCP pre-fix repro</name>
  <files>(no files modified)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 03 — DropdownMenu restoreFocus race)
  </read_first>
  <action>
    Orchestrator drives Playwright MCP. Steps: (1) Open a map and create or locate a folder group in the sidebar (UnifiedStackPanel). (2) Click the group's kebab (3-dot button). (3) Click "Rename group". (4) Without clicking the input, use `mcp_browser_evaluate` to read `document.activeElement.tagName` and `document.activeElement.getAttribute('aria-label')`. (5) Confirm the active element is NOT the rename `<input>` (likely the kebab button or document body). (6) Capture the timing of focus transitions if possible. Add incidental issues to scratch list for EMRG-01.
  </action>
  <verify>
    <automated>Playwright MCP captures document.activeElement after Rename click; confirms input not focused.</automated>
  </verify>
  <acceptance_criteria>
    - Pre-fix behavior confirmed: rename input is NOT focused after the kebab → Rename click
    - Active element identified (likely kebab button)
    - Timing/race nature confirmed (focus transiently lands on input then bounces back to kebab)
  </acceptance_criteria>
  <done>Pre-fix repro confirmed.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Fix focus-race via rAF-deferred focus + remove preventDefault</name>
  <files>frontend/src/components/builder/FolderGroupRow.tsx, frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx</files>
  <read_first>
    - frontend/src/components/builder/FolderGroupRow.tsx (handleStartRename around line 75-90, kebab onSelect around lines 293-298, rename input + useEffect select around lines 81-85 + 230-254)
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md (Plan 03 — DropdownMenu restoreFocus race + fix strategy)
    - frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx (existing harness, if present; otherwise look at __tests__/StackRow.test.tsx for pattern)
  </read_first>
  <behavior>
    - Test 1: Clicking kebab → "Rename group" → the rename `<input>` mounts AND becomes `document.activeElement` (focus assertion after `await screen.findByRole('textbox')`)
    - Test 2: The existing-name text is selected on mount (preserve current `inputRef.current?.select()` behavior — assert input.selectionStart === 0 and selectionEnd === nameValue.length)
    - Test 3: Pressing Escape inside the input cancels editing and restores the static name (no regression to Escape-cancel)
    - Test 4: Pressing Enter inside the input commits the rename via onCommitRename callback (no regression to Enter-commit)
    - Test 5: Blurring the input commits the rename (no regression to blur-commit)
  </behavior>
  <action>
    Modify `frontend/src/components/builder/FolderGroupRow.tsx` to fix the focus race: (a) in the kebab `DropdownMenuItem` onSelect (around lines 293-298), REMOVE `_e.preventDefault()` so the dropdown menu closes cleanly before the input mounts. (b) In the existing `useEffect(() => { if (editing && inputRef.current) inputRef.current.select(); }, [editing])` (around lines 81-85), defer the focus + select to a `requestAnimationFrame` callback so it wins the race vs Radix's restoreFocus that fires synchronously on menu close. Replace the body with: `requestAnimationFrame(() => { if (inputRef.current) { inputRef.current.focus(); inputRef.current.select(); } });`. Keep the existing `autoFocus` attribute on the input — defense in depth in case rAF is skipped in tests. Update or create `frontend/src/components/builder/__tests__/FolderGroupRow.test.tsx` with the 5 behavior assertions above. Use `userEvent` for menu interaction; flush the microtask + rAF via `vi.runOnlyPendingTimers()` or `await act(async () => { await new Promise(r => requestAnimationFrame(r)); })`. Tests must fail before fix, pass after.
  </action>
  <verify>
    <automated>cd frontend && npx vitest run src/components/builder/__tests__/FolderGroupRow.test.tsx</automated>
  </verify>
  <acceptance_criteria>
    - FolderGroupRow.tsx kebab onSelect no longer calls `_e.preventDefault()` (grep returns 0 hits in the rename onSelect block)
    - FolderGroupRow.tsx contains `requestAnimationFrame` inside the editing useEffect (grep `requestAnimationFrame` returns ≥1 match)
    - Regression test asserts `document.activeElement === input` post-mount
    - Regression test asserts existing-name selection preserved
    - Escape/Enter/blur flows still pass
    - `cd frontend && npx tsc --noEmit` returns 0 errors
    - Diff is minimal: only FolderGroupRow.tsx + test file
  </acceptance_criteria>
  <done>Rename input autofocuses on mount; regression test green; no flow regressions.</done>
</task>

<task type="checkpoint:orchestrator">
  <name>Task 3: Playwright MCP post-fix re-verify + atomic commit</name>
  <files>(no files modified beyond commit)</files>
  <read_first>
    - .planning/phases/1051-map-builder-polish-bug-sweep/1051-PATTERNS.md
  </read_first>
  <action>
    Orchestrator drives Playwright MCP. Steps: (1) Open a map with a folder group. (2) Click kebab → "Rename group". (3) Without clicking the input, type a single character via `mcp_browser_press_key` or `mcp_browser_type` — confirm the character appears in the input. (4) Press Escape — confirm rename cancels. (5) Re-open rename, type a new name, press Enter — confirm commit. (6) Verify document.activeElement transitions correctly. After MCP verify passes, create atomic commit with subject: `fix(builder): rename-group input autofocuses on open (BUG-03)`. Stage only FolderGroupRow.tsx + the test file.
  </action>
  <verify>
    <automated>git log --oneline -1 && git show --stat HEAD</automated>
  </verify>
  <acceptance_criteria>
    - Playwright MCP confirms typing immediately after clicking "Rename group" enters the input
    - Escape cancels, Enter commits
    - Commit exists with subject `fix(builder): rename-group input autofocuses on open (BUG-03)`
    - `git diff HEAD~1 HEAD --stat` shows only FolderGroupRow.tsx + test file
  </acceptance_criteria>
  <done>BUG-03 fix verified live + committed atomically.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| client-only UI | Focus management is entirely client-side; no API surface; no untrusted input |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-1051-03 | (n/a) | rename input focus management | accept | No security surface; pure UX bug |
</threat_model>

<verification>
- Playwright MCP confirms autofocus on Rename click
- Vitest regression case passes
- `npx tsc --noEmit` returns 0 errors
- No regression to Escape/Enter/blur flows
</verification>

<success_criteria>
- Clicking "Rename group" on any folder group row gives the rename input focus immediately
- Typing immediately enters the rename input without an extra click
- Escape cancels, Enter commits, blur commits — no regression to existing flows
- Vitest confirms focus on mount
- Atomic commit on main with subject `fix(builder): rename-group input autofocuses on open (BUG-03)`
</success_criteria>

<output>
Create `.planning/phases/1051-map-builder-polish-bug-sweep/1051-03-SUMMARY.md` when done with: root-cause (DropdownMenu restoreFocus race), fix description (preventDefault removal + rAF-deferred focus), files modified, test result, MCP verification screenshots/notes.
</output>
