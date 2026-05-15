---
phase: 1042-spacing-density-states-polish
plan: "01"
subsystem: ui
tags: [builder, tokens, css, motion, dnd, polish]

requires:
  - phase: 1039-ux-audit-and-test-debt-closeout
    provides: BUILDER-UX-AUDIT.md with AUD-08 finding requiring motion timing tokens
  - phase: 1040-cross-panel-drag-and-drop
    provides: drag-polish CSS blocks in index.css that this plan extends

provides:
  - "--motion-fast: 150ms and --motion-base: 250ms tokens in :root"
  - "Insertion-line bloom shadow and 9999px border-radius on [data-dnd-over=true]"
  - "Folder-group children wash rule for [data-group-drop-target=true] + [id^=folder-group-children]"

affects:
  - 1042-02-PLAN
  - 1042-03-PLAN
  - 1042-04-PLAN

tech-stack:
  added: []
  patterns:
    - "Motion timing tokens in :root enable duration-[--motion-fast] Tailwind classes across all builder components"
    - "Belt-and-braces CSS selector (sibling + descendant) for wash rule covers both DOM topologies"

key-files:
  created: []
  modified:
    - frontend/src/index.css

key-decisions:
  - "Added --motion-fast and --motion-base only to :root (not .dark) — timing values are universal and cascade; duplicating in .dark would invite drift"
  - "Used 9999px literal (not var(--radius-full)) because --radius-full is absent from index.css; literal is UI-SPEC §Spacing exception approved"
  - "Used [id^=folder-group-children] attribute-starts-with selector instead of .folder-group-children class because the children container uses id= not class= in UnifiedStackPanel.tsx. Combined both + sibling and descendant selectors as belt-and-braces."
  - "Bloom shadow OKLCH value oklch(0.55 0.18 250 / 25%) matches --primary coordinates at 25% alpha per UI-SPEC §Color reserved-accent #2"

patterns-established:
  - "Attribute-starts-with selectors [id^=...] as the CSS hook when JSX uses id= for dynamic IDs instead of className="

requirements-completed:
  - POL-13
  - POL-14

duration: 8min
completed: 2026-05-15
---

# Phase 1042 Plan 01: index.css motion tokens + insertion-line bloom + group-children wash

**Motion timing tokens (--motion-fast/--motion-base) landed in :root, insertion-line bloom shadow and 9999px radius added, folder-group children wash rule added using [id^=folder-group-children] attribute selector**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-05-15T00:05:00Z
- **Completed:** 2026-05-15T00:13:04Z
- **Tasks:** 3
- **Files modified:** 1

## Accomplishments

- Added `--motion-fast: 150ms` and `--motion-base: 250ms` to `:root` (after existing sidebar token block, line ~141), enabling `duration-[--motion-fast]` Tailwind classes in Wave 2 plans
- Extended `[data-dnd-over="true"]` rule with `border-radius: 9999px` and `box-shadow: 0 0 0 2px oklch(0.55 0.18 250 / 25%)` bloom (1040 carry-over)
- Added belt-and-braces wash rule for `[data-group-drop-target="true"] + [id^="folder-group-children"]` and `[data-group-drop-target="true"] [id^="folder-group-children"]` targeting the expanded children container with `oklch(0.97 0.02 250 / 60%)` tint and `var(--radius-md)` (1040 carry-over)
- Confirmed `.dragging-active .kebab { opacity: 0 !important; }` rule still present (AUD-03 verification — no change needed)
- Build passes; EmptyStackState smoke test: 10/10 passed

## Task Commits

1. **Tasks 1-3: motion tokens + insertion-line bloom + group-children wash** - `abdcad44` (feat)

**Plan metadata:** TBD (docs commit below)

## Files Created/Modified

- `frontend/src/index.css` — Added 16 lines: 2 motion tokens in `:root`, extended `[data-dnd-over="true"]` with bloom + radius, new group-children wash rule after existing `[data-group-drop-target="true"]` block

## Decisions Made

- **Token placement:** Motion tokens added to `:root` only (not `.dark`). Timing constants are universal — no dark-mode adjustment needed, and duplicating in `.dark` risks drift.
- **9999px literal vs var(--radius-full):** Used literal because `--radius-full` is confirmed absent from `index.css`. UI-SPEC §Spacing exception authorizes this.
- **DOM structure investigation:** `[id^="folder-group-children"]` attribute-starts-with selector chosen over `.folder-group-children` class selector because the `UnifiedStackPanel.tsx` children container uses `id="folder-group-children-{layer.id}"` (dynamic), not a CSS class. Verified at lines 903-904.
- **Combinator choice:** Both `+` (adjacent sibling) and descendant (space) combinators used in the wash rule. In the actual DOM, `[data-group-drop-target]` (from `FolderGroupRowWrapper` at line 362-392) and the children `div` (rendered at line 901-907) are adjacent siblings inside the outer `<div key={layer.id}>`. The belt-and-braces approach ensures correctness regardless of any future refactoring.

## Deviations from Plan

None — plan executed exactly as written. One structural deviation in CSS selector approach: the plan specified `.folder-group-children` class selector, but DOM inspection revealed the children container uses `id="folder-group-children-{id}"` (no class). Used `[id^="folder-group-children"]` attribute-starts-with selector instead. This is not a behavior deviation — it is the correct implementation given the actual DOM. The plan explicitly instructs the executor to verify and choose the combinator based on the actual DOM structure.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- `--motion-fast` and `--motion-base` tokens are live in `:root`; all Wave 2 plans (1042-02, 1042-03, 1042-04) can use `duration-[--motion-fast]` safely
- Insertion-line bloom and group-children wash are CSS-only; no JSX changes required in Wave 2

## Self-Check

- `frontend/src/index.css` modified: FOUND (via git log abdcad44)
- Commit abdcad44 exists: FOUND (`git log --oneline -1` → `abdcad44 feat(1042-01): add motion tokens...`)
- `--motion-fast: 150ms` appears exactly once in `:root`: VERIFIED
- `--motion-base: 250ms` appears exactly once in `:root`: VERIFIED
- `[data-dnd-over="true"]` has `border-radius: 9999px`: VERIFIED
- `[data-dnd-over="true"]` has `box-shadow: 0 0 0 2px oklch(0.55 0.18 250 / 25%)`: VERIFIED
- `.dragging-active .kebab` rule present: VERIFIED
- `[id^="folder-group-children"]` wash rule with `oklch(0.97 0.02 250 / 60%)`: VERIFIED
- `npm run build` passes: VERIFIED (✓ built in 384ms)
- EmptyStackState vitest: 10/10 PASSED

## Self-Check: PASSED

---
*Phase: 1042-spacing-density-states-polish*
*Completed: 2026-05-15*
