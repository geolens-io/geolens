---
phase: 1042
phase_name: spacing-density-states-polish
status: ready_for_planning
generated: auto (workflow.skip_discuss=true)
date: 2026-05-14
---

# Phase 1042: spacing-density-states-polish — Context

**Gathered:** 2026-05-14
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Apply Phase 1039's P0/P1 audit findings as a coordinated spacing/density/typography/state pass across `UnifiedStackPanel`, `LayerEditorPanel`, Add Dataset modal, and Settings — using only the existing `sketch-findings-geolens` token set, with unified hover/focus-visible/pressed/active states and consistent loading affordances everywhere an async fetch occurs.

**Requirements:** POL-13, POL-14, POL-15

**Success Criteria:**
1. UnifiedStackPanel + LayerEditorPanel + AddDatasetModal + Settings show normalized spacing/density/typography. No new tokens.
2. Hover/focus-visible/pressed/active state vocabulary is consistent across builder controls. Microinteractions use `--motion-fast`/`--motion-base` timing.
3. Every async fetch in builder shows a loading affordance (skeleton, spinner, or optimistic UI). No blank/frozen surfaces.
4. Playwright snapshot coverage (where added) gates visual regressions.

**Depends on:** Phase 1039 (audit findings — `BUILDER-UX-AUDIT.md`).

**Audit findings to consume:** `.planning/phases/1039-ux-audit-and-test-debt-closeout/BUILDER-UX-AUDIT.md` (24 findings; this phase scopes to P0 + P1 spacing/density/state items).

**Carry-over fixes from earlier v1009 reviews:**
- Phase 1040 UI review: row insertion line missing 25% bloom shadow; group-children wash missing on expanded folder drop target; cursor-grab on full row body (not just handle).
- Phase 1041 UI review: BulkActionBar button labels never visible (340px sidebar, gated `xl:inline`); Cancel button variant should be ghost not secondary; Bar mount/exit animation no-op (transition-all without initial-state).
- Pre-existing v1008: duplicate top-level key blocks in `frontend/src/i18n/locales/en/builder.json` (lines 715 vs 884) — this phase is the right place to dedupe.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — `workflow.skip_discuss=true`. Use audit, sketch-findings tokens, and prior UI reviews to drive the polish list.

### Hard Constraints (v1009)
- No saved-map shape changes
- No public viewer / shared / embed surface changes
- All work uses the `sketch-findings-geolens` token set; NO new tokens introduced
- No new backend endpoints

### Scope Discipline
Phase 1043 (next) handles error/empty states + IA. Phase 1044 handles i18n locale fill + a11y verification + Playwright UAT spec. This phase is the **visual polish + state vocabulary + loading affordances** pass — keep scope tight.

</decisions>

<code_context>
## Existing Code Insights

Will be gathered during pattern mapping. Surfaces in scope:
- `frontend/src/components/builder/UnifiedStackPanel.tsx`
- `frontend/src/components/builder/LayerEditorPanel.tsx`
- `frontend/src/components/builder/DatasetSearchPanel.tsx` (Add Dataset modal interior)
- `frontend/src/components/builder/BulkActionBar.tsx` (Phase 1041)
- `frontend/src/components/builder/StackRow.tsx`, `FolderGroupRow.tsx`, `BasemapGroupRow.tsx`
- `frontend/src/components/builder/InsertionLine.tsx` (if extracted) or inline drop indicator CSS
- `frontend/src/index.css` (Phase 1040 + 1041 drag-polish blocks; existing `--motion-fast`/`--motion-base`)
- Settings scene routes (`frontend/src/pages/Settings*.tsx` or admin equivalents)
- `frontend/src/i18n/locales/en/builder.json` (dedupe pre-existing duplicate keys)

</code_context>

<specifics>
## Specific Ideas (carry-over from prior reviews)

### From Phase 1039 BUILDER-UX-AUDIT.md (P0/P1 only)
Read the audit doc and pull the specific findings list. Examples likely include AUD-01 (header density), AUD-05/06 (state vocabulary), AUD-07 (skeleton loading), etc.

### From Phase 1040 UI review
- Insertion line: add `box-shadow: 0 0 0 2px oklch(0.55 0.18 250 / 25%)` bloom + `border-radius: var(--radius-full)` on `[data-dnd-over="true"]` (UI-SPEC §3a)
- Group children wash: add `oklch(0.97 0.02 250 / 60%)` to `.folder-group-children` when parent has `data-group-drop-target="true"` (UI-SPEC §3b)
- `cursor-grab` on full DatasetSearchPanel row body, not just the handle button
- Optional: new-stack-row entry animation `opacity 0 → 1 over 150ms` (`--motion-fast`)

### From Phase 1041 UI review
- BulkActionBar button labels: lower breakpoint to `sm:inline` OR add Tooltip wrapper to enabled buttons (currently `xl:inline` never triggers in 340px sidebar)
- Cancel button in delete confirmation: `variant="ghost"` not `variant="secondary"`
- BulkActionBar mount/exit: real transition (initial-state class + transition-all is a no-op without proper initial state — use Radix Transition or framer-motion if already a dep, else CSS keyframe)
- Bar gap: `gap-2` (8px) per spec, not `gap-1` (4px)

### Pre-existing v1008 cleanup
- Dedupe `frontend/src/i18n/locales/en/builder.json` lines 715–826 (shadowed by 884–998). After dedupe, run `cd frontend && npx vitest run src/i18n/__tests__/resources.test.ts` to confirm parity gate still green.

### Loading affordances
Audit fetch points in builder for blank-state windows:
- Add Dataset modal: column list per dataset, dataset preview, search results
- Stack reorder: optimistic UI; no loading needed
- Layer editor: per-layer style fetch, dataset metadata
Add skeleton or spinner where missing.

</specifics>

<deferred>
## Deferred Ideas

- New design tokens — out of scope (locked sketch-findings set only)
- Cross-surface design system unification beyond builder — out of scope
- Net-new visual treatments — out of scope (apply existing tokens only)

</deferred>
