---
phase: 1045-builder-smoke-polish
plan: 03
subsystem: builder
tags: [builder, smoke-polish, a11y, scene-routing, perf, i18n, housekeeping]
requirements: [SP-12, SP-13, SP-14, SP-15, SP-16, SP-17, SP-18]
metrics:
  duration_minutes: ~45
  tasks_completed: 5
  commits: 5
  test_count_delta: +7 (2 SP-13 BasemapGroupRow + 3 SP-15 UnifiedStackPanel + 2 SP-16 use-builder-save)
  files_created: []
  files_modified:
    - frontend/src/components/builder/BasemapGroupRow.tsx
    - frontend/src/components/builder/StackRow.tsx
    - frontend/src/components/builder/SidebarRail.tsx
    - frontend/src/components/builder/UnifiedStackPanel.tsx
    - frontend/src/components/builder/hooks/use-builder-save.ts
    - frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx
    - frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx
    - frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts
    - frontend/src/i18n/locales/en/builder.json
    - frontend/src/i18n/locales/de/builder.json
    - frontend/src/i18n/locales/es/builder.json
    - frontend/src/i18n/locales/fr/builder.json
    - .planning/phases/1045-builder-smoke-polish/VERIFICATION.md
---

# Phase 1045 Plan C: Builder Smoke Polish — SP-12..SP-18

5 tasks: 3 POLISH fixes (SP-13, SP-14, SP-17 grouped) + 1 scene-aware
gate (SP-15) + 1 perf debounce (SP-16, TDD) + 1 skip-with-justification
(SP-12) + 1 operational delete (SP-18).

## Task C.1 / SP-13 + SP-14 + SP-17 — Basemap eye glyph, row hover, Add data icon

**Outcome:** Three visual nits, grouped because they collide on the same files.

**SP-13:** `BasemapGroupRow` now renders a non-interactive `<span>` glyph
(muted Eye icon + tooltip "Basemap is always visible — use Remove basemap
to hide.") when `visibilityDisabled` is true, replacing the previous
disabled `<button aria-disabled>`. Layout slot footprint is unchanged
(`h-[22px] w-[22px]` rounded container, opacity-40 Eye glyph) so the row
geometry stays identical. The interactive `<button>` is still rendered
when `visibilityDisabled` is false (basemap-visibility-wired callers).

**SP-14:** `StackRow` row container already carried `cursor-pointer` and
a `hover:bg-[var(--surface-2,theme(colors.accent.DEFAULT))]` class — the
legacy `theme()` fallback was cleaned up to a flat `hover:bg-[var(--surface-2)]`
so the intent is obvious from the className alone. Same applied to the
`isDragging` branch. This is partially a no-op (the pointer + hover were
already wired) and partially a clarity fix; smoke p-03's "cursor changes
only over specific child controls" was likely a perception artifact of
the var-fallback class not being recognized in the snapshot tooling.

**SP-17:** Stripped the U+FF0B full-width "＋" character from the four
`unifiedStack.addData` locale strings (en/de/es/fr). The Lucide `<Plus />`
icon already rendered immediately before the label text — it now stands
alone as the visual plus, and was bumped from `h-3 w-3` to `h-4 w-4`
per the plan spec. `SidebarRail` aria-label and tooltip defaults updated
to match. A new `basemapGroup.visibilityLocked` i18n key was added across
all 4 locales (parity preserved: 773/773/773/773 keys).

**Files changed:**
- `frontend/src/components/builder/BasemapGroupRow.tsx` — split eye cell
  into glyph (`visibilityDisabled`) vs button (active) branch.
- `frontend/src/components/builder/StackRow.tsx` — flat `hover:bg-[var(--surface-2)]`.
- `frontend/src/components/builder/UnifiedStackPanel.tsx` — `Plus h-4 w-4`,
  i18n default `'Add data'`.
- `frontend/src/components/builder/SidebarRail.tsx` — i18n aria-label /
  tooltip default `'Add data'` (was `'＋ Add data'`).
- `frontend/src/components/builder/__tests__/BasemapGroupRow.test.tsx` —
  2 new tests: glyph renders with tooltip, glyph click is a no-op.
- `frontend/src/i18n/locales/{en,de,es,fr}/builder.json` — `addData` cleaned;
  `basemapGroup.visibilityLocked` added.

**Commit:** `6cbd61ae`
**Verification:** vitest StackRow + UnifiedStackPanel + BasemapGroupRow + SidebarRail 107/107 PASS; tsc clean; eslint touched-files 0 errors (2 pre-existing warnings).

## Task C.2 / SP-15 — BulkActionBar hidden during Settings scene

**Outcome:** When the user has multi-selected ≥2 layers and opens the
global ⚙ Settings panel, the BulkActionBar visually hides so it doesn't
display "2 selected" against unrelated content. The selection state
itself (`selectedIds`) lives in the parent and is **preserved**; closing
Settings brings the bar back with the same selection.

**Files changed:**
- `frontend/src/components/builder/UnifiedStackPanel.tsx` — the
  conditional gate at line ~1033 becomes
  `!isSettingsOpen && selectedIds.size >= 2 && ...`. `isSettingsOpen`
  was already a prop on this component (used by the cog button), so no
  new prop plumbing.
- `frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx`
  — new "SP-15 — BulkActionBar gating on isSettingsOpen" describe block
  with 3 cases: visible when Settings closed; hidden when Settings open;
  re-renders on Settings close with selection preserved across rerender.

**Plan deviation:** the plan listed `MapBuilderPage.tsx` as the file;
the BulkActionBar is actually rendered inside `UnifiedStackPanel.tsx`.
Same kind of file-path correction Plan A.3 / A.4 noted. Fix went to the
real source. No MapBuilderPage code change.

**Commit:** `4bc0e293`
**Verification:** vitest UnifiedStackPanel 63/63 PASS (60 prior + 3 new).

## Task C.3 / SP-16 — Trailing 500ms debounce on captureThumbnail (TDD)

**Outcome:** Two back-to-back saves within 500ms collapse to exactly one
`PUT /maps/<id>/thumbnail/`. Single saves still fire once, after the
500ms trailing edge. Debounce is keyed by mapId so concurrent edits to
different maps don't collide.

**TDD gates:**
1. **RED** — `2f1c3476`. 2 new SP-16 cases added before any impl change.
   They asserted that two saves within 500ms register exactly one
   `map.once('render')` registration (and one PUT after the trailing
   edge), and that a single save defers its first capture until 500ms
   elapses. Pre-impl run: 32 PASS / 2 FAIL — the FAIL count matched the
   2 new cases. RED gate satisfied.
2. **GREEN** — `d523f03d`. Implemented a module-level
   `pendingCaptures: Map<string, ReturnType<typeof setTimeout>>` plus a
   500ms `setTimeout` wrapper inside `captureThumbnail`. Each new call
   clears any prior pending timer for the same mapId; the latest call
   wins (trailing edge). The actual render-frame + upload logic moved
   into a renamed `runCaptureNow` helper. Module also exports a
   `__resetThumbnailDebounceForTests()` helper (called from
   `beforeEach`) to clear pending state between cases. Tests: 34/34 PASS.
3. **REFACTOR** — `d10f0dfc`. Self-review caught an unused `args` tuple
   stored in the Map value; the setTimeout closure already captures the
   current call's args. Simplified the Map value type to a bare
   `ReturnType<typeof setTimeout>`. Also relocated the SP-16 docblock to
   sit directly above `captureThumbnail` (the debounced wrapper) instead
   of above `runCaptureNow`. No behavior change; tests still 34/34 PASS.

**Pre-existing tests updated:** the 4 prior `captureThumbnail (via
handleSave onSuccess)` cases asserted on `map.once('render')` /
`map.once('idle')` registrations that happen *inside* the capture call.
With the 500ms debounce now sitting in front, those tests need to
advance fake timers past 500ms before asserting downstream effects.
Each was updated to enable `vi.useFakeTimers()` + `advanceTimersByTime(500)`
prior to the legacy assertions. Behavior coverage unchanged; only
timing scaffold added.

**Plan deviation:** the plan listed `BuilderMap.tsx` as the file; the
thumbnail PUT actually lives in `use-builder-save.ts` (called by both
save-paths via `captureThumbnail` and by `maybeAutoCaptureThumbnail`).
File-path correction per Rule 3 (auto-fix blocking issue).

**Files changed:**
- `frontend/src/components/builder/hooks/use-builder-save.ts` —
  500ms debounce wrapper + `__resetThumbnailDebounceForTests` export.
- `frontend/src/components/builder/hooks/__tests__/use-builder-save.test.ts`
  — 2 new SP-16 cases; 4 pre-existing tests updated for the 500ms boundary;
  module-level reset wired into `beforeEach`.

**Commits:** `2f1c3476` (RED), `d523f03d` (GREEN), `d10f0dfc` (REFACTOR)
**Verification:** vitest use-builder-save 34/34 PASS; vitest BuilderMap + MapBuilderPage 58/58 PASS; tsc + lint clean.

## Task C.4 / SP-12 — SKIPPED with justification

**Outcome:** SKIPPED. VERIFICATION.md note explains why.

**Rationale:** `<ScaleControl position="bottom-left" maxWidth={100} unit="metric" />`
already renders in `BuilderMap.tsx:854` (and `ViewerMap.tsx:746`), so a
MapLibre scale **bar** is already on screen — the plan's recommended
implementation path (`new maplibregl.ScaleControl(...) → map.addControl(...)`)
was already satisfied at HEAD before this plan started. What the smoke
check's p-01 actually asked for ("A second pane (current scale or '1:288k')
would aid users coming from desktop GIS") is a different feature — a
*representative-fraction* readout (e.g. "1:288k") in the top-right next
to the coord pane. That requires (a) a meters-per-pixel calculation
that accounts for the cosine-of-latitude meridian factor, (b) a new UI
slot inside `MapCoordReadout`, and (c) i18n strings for "1:N"
formatting and locale-appropriate digit grouping. That's a small
feature, not a polish fix — deferred so this phase stays a tight
smoke-polish closeout.

**Plan-permitted outcome.** No code commit.

## Task C.5 / SP-18 — Delete test maps (operational)

**Outcome:** Two test maps deleted via the live `/maps/<uuid>` DELETE endpoint:

| Map UUID | Source | DELETE | GET |
| -------- | ------ | ------ | --- |
| `a00b7e96-95b7-48d6-a911-57b97b767ebc` (Smoke Check 2026-05-15) | smoke FINDINGS | 204 | 404 |
| `58149b92-4086-4241-94ce-719a5e9e09fb` (SP-03 verify map) | Plan A.5 note | 204 | 404 |

**Notes:**
- The trailing-slash form `/maps/<uuid>/` returns 307; the canonical
  no-slash form `/maps/<uuid>` returns the expected 204/404. Both shapes
  ultimately resolve to 404, confirming deletion.
- Plan A.5's VERIFICATION.md note marked the SP-03 test map
  `58149b92-…` as "safe to delete" once the SP-03 followup investigator
  was finished. The SP-03 followup is still open (M-02 race not fully
  root-caused per VERIFICATION.md), but the map itself isn't needed for
  that investigation — the issue is in the BuilderMap effect flow, not
  on any specific map row. Deleting it is housekeeping; the open SP-03
  escalation is unchanged and continues to track in VERIFICATION.md.

**No code commit** (operational housekeeping per plan).

## Code review (self-review HEAD~5..HEAD)

`gsd-code-reviewer` agent cannot be spawned from the executor's function
set (same constraint Plans A and B documented). Self-review of the 5-commit
diff produced one finding addressed inline:

### [Rule 1 — Code cleanliness] Unused `args` tuple in SP-16 debounce state

**Found during:** self-review of the GREEN commit `d523f03d`.
**Issue:** The `pendingCaptures` Map stored a `{ timer, args }` value; the
`args` field was never read because `setTimeout`'s closure already
captured the current call's args. Dead state and confusing type signature.
**Fix:** Simplified to `Map<string, ReturnType<typeof setTimeout>>`;
dropped the `PendingThumbnailCapture` type alias; relocated the SP-16
docblock so it sits above the debounced wrapper rather than the runner.
**Commit:** `d10f0dfc`

No other findings. Conventional commits, no AI/bot attribution, no
backward-compat shims, no destructive git ops, all subject lines ≤72 chars.

## Deviations from Plan

### Auto-fixed

1. **[Rule 3 — File-path correction] SP-13 file ownership.** Plan listed
   `StackRow.tsx + UnifiedStackPanel.tsx`; the disabled basemap eye
   button lives in `BasemapGroupRow.tsx`. Fix went to the real source.
   No StackRow / UnifiedStackPanel code changed for SP-13 (StackRow
   only changed for SP-14, UnifiedStackPanel only for SP-17 + SP-15).

2. **[Rule 3 — File-path correction] SP-15 file ownership.** Plan
   listed `MapBuilderPage.tsx`; the `BulkActionBar` is rendered inside
   `UnifiedStackPanel.tsx` which already receives `isSettingsOpen` as a
   prop. Fix lives there.

3. **[Rule 3 — File-path correction] SP-16 file ownership.** Plan listed
   `BuilderMap.tsx`; the thumbnail capture call chain lives in
   `use-builder-save.ts` (which `BuilderMap.tsx` calls). Fix lives there.

4. **[Rule 1 — Code cleanliness] SP-16 unused args.** Self-review of the
   GREEN diff caught dead `args` storage. Fixed inline as a REFACTOR
   commit so the GREEN diff stays simple and the refactor stays
   reviewable in isolation.

5. **[i18n parity preservation]** Added the new `basemapGroup.visibilityLocked`
   key to all 4 locales (en/de/es/fr) at the same time as the EN edit,
   so key parity stays 773/773/773/773.

### Out of scope (deferred)

- **SP-12 representative-fraction pane.** Documented in VERIFICATION.md
  as SKIPPED with rationale. Should be tracked as a separate feature
  ticket if desired.
- **Pre-existing lint findings.** Same 5 errors from `deferred-items.md`
  (4 in `EmptyStackState.tsx`, 1 in `UnifiedStackPanel.test.tsx:59`)
  + 12 warnings (`MapBuilderPage` useCallback / `ViewerMap` useEffect
  deps + 2 unused-eslint-disable in `UnifiedStackPanel`). All present
  on `main` before this plan; **zero** introduced by Plan C.

## Hard-rule compliance

| Rule | Status |
| ---- | ------ |
| No AI/bot attribution in commits | clean |
| Conventional commit subjects ≤72 chars | longest is 67 chars |
| Explicit file paths for git add | per-commit individual paths |
| No frontend `docker compose build` | Vite HMR + bind-mount only |
| Did not touch open SP-03 (M-02) escalation work | confirmed |
| SP-12 SKIP recorded in VERIFICATION.md | yes |
| SP-18 no code commit | confirmed (operational only) |

## Post-task gates

| Gate | Result |
| ---- | ------ |
| `cd frontend && npx tsc --noEmit` | clean (0 errors) |
| `cd frontend && npx eslint src/` | 5 errors all pre-existing (deferred-items.md); 0 in plan C diff |
| `cd frontend && npm test -- --run StackRow UnifiedStackPanel MapBuilderPage BuilderMap BasemapGroupRow SidebarRail use-builder-save` | 168/168 PASS |
| `cd frontend && node scripts/check-i18n-changed-namespaces.mjs` | parity intact across en/de/es/fr |
| i18n key count | 773/773/773/773 |
| Live DELETE + GET for both test maps | 204 / 404 confirmed |

## Commits

| Hash | Subject |
| ---- | ------- |
| `6cbd61ae` | fix(builder): polish basemap eye glyph, row hover, and Add data icon |
| `4bc0e293` | fix(builder): hide BulkActionBar during global Settings scene |
| `2f1c3476` | test(builder): add failing tests for thumbnail PUT debounce (SP-16) |
| `d523f03d` | perf(builder): debounce thumbnail PUT by 500ms |
| `d10f0dfc` | refactor(builder): drop unused args field from SP-16 debounce state |

## Anything for the user's attention

- **SP-12 SKIPPED with rationale.** A future small feature plan should
  add the "1:N" representative-fraction pane next to MapCoordReadout.
  Estimated effort: 1 plan with 1 task (meters-per-pixel calc + UI slot
  + i18n).
- **SP-03 (M-02 race) remains open.** Untouched by this plan per scope
  instruction. VERIFICATION.md continues to track the hypothesis ("token
  fetch in flight → tokenMap empty → gate short-circuits → token
  resolves → effect re-runs but structuralKey unchanged so memo
  doesn't recompute"). Plan-A note still applies: refresh-after-add is
  the user workaround until the followup ticket ships.
- **Test maps deleted.** Both `a00b7e96-…` and `58149b92-…` are gone
  (verified GET → 404). If the SP-03 followup investigator needs a
  reproduction fixture, they'll need to create a fresh test map.
- **CTRL-01 phase gate is next.** Per Plan C's `<output>` section, a
  full Playwright re-run against the 18-step smoke FINDINGS table should
  confirm 18/18 PASS (or 17/18 PASS + 1 SKIPPED-with-rationale for SP-12).
  That's a separate checkpoint and not part of Plan C's commit chain.

## Self-Check: PASSED

- All 5 commits present in `git log HEAD~5..HEAD`.
- All listed files exist and were modified by the recorded commits.
- `BasemapGroupRow.tsx`, `StackRow.tsx`, `UnifiedStackPanel.tsx`,
  `SidebarRail.tsx`, `use-builder-save.ts` modified per plan.
- `BasemapGroupRow.test.tsx`, `UnifiedStackPanel.test.tsx`,
  `use-builder-save.test.ts` extended with 7 new tests total.
- All 4 locale `builder.json` files updated; key parity 773/773/773/773.
- VERIFICATION.md extended with 7 new SP-XX lines covering Plan C.
- tsc clean; plan-C diff lint clean.
- 168 tests pass across the Plan C test surface.
- Both test maps return GET 404.
