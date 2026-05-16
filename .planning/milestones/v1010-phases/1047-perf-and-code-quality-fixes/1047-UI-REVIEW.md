# Phase 1047 — UI Review

**Audited:** 2026-05-16
**Baseline:** 1047-UI-SPEC.md (approved)
**Screenshots:** Captured (dev server at localhost:3000) — builder route requires auth; screenshot shows login gate only. Audit is code-only for component-level findings.

---

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 3/4 | Partial-failure toast body deviates from spec; aria-label in SceneSpinnerFallback is hardcoded English |
| 2. Visuals | 3/4 | Double Loader2 spinner in deleting state; cursor-not-allowed scoped to button only, not BulkActionBar container |
| 3. Color | 4/4 | No hardcoded colors; --surface-2 is a valid project token; muted-foreground/destructive correctly used |
| 4. Typography | 3/4 | text-[13px] arbitrary size at BulkActionBar:227 violates spec type scale |
| 5. Spacing | 4/4 | All new components use standard Tailwind scale; no arbitrary [px]/[rem] values |
| 6. Experience Design | 4/4 | All three toast paths wired; LazyLoadErrorBoundary on every Suspense; aria-busy + aria-live both present |

**Overall: 21/24**

---

## Top 3 Priority Fixes

1. **Partial-failure toast body omits "— tap to retry." suffix** — Screen reader and sighted users who dismiss the toast quickly see no affordance hint that a retry action exists inside the notification. Fix: update `bulkActions.deletePartialFailure` in all four locales to append "Tap to retry." (or equivalent translated form) to match UI-SPEC copy contract. Alternatively, document in UI-SPEC that the action button is the sole affordance and remove the suffix from the spec.

2. **`cursor-not-allowed` applied to disabled button only, not the BulkActionBar container** — UI-SPEC §PERF-03 Pending state specifies "BulkActionBar cursor `not-allowed`" implying the toolbar container itself signals the blocked state. Currently the container remains default-cursor while only the disabled button shows the not-allowed cursor, which is invisible to users not hovering the button. Fix: add `isDeleting ? 'cursor-not-allowed' : ''` to the container `cn()` at BulkActionBar.tsx:129–135.

3. **`text-[13px]` arbitrary Tailwind value at BulkActionBar.tsx:227** — UI-SPEC Typography section and REQUIREMENTS.md "Out of Scope" (no new design tokens) forbid off-scale sizing. The selected-count label uses `text-[13px]` which falls between `text-xs` (12px) and `text-sm` (14px) and is outside the declared type scale for this phase. Fix: change to `text-xs` (12px) or `text-sm` (14px) matching the Label or Body role in the UI-SPEC typography table.

---

## Detailed Findings

### Pillar 1: Copywriting (3/4)

**Contract source:** UI-SPEC §Copywriting Contract, all 5 keys declared.

**PASS — i18n key parity:**
All 5 new keys (`bulkActions.deletingLayers`, `deleteSuccess`, `deletePartialFailure`, `deleteRollback`, `retryAction`) are present in all four locales (en/de/es/fr). Verified by grep across locale files. Key content is semantically appropriate in each language.

**PASS — No raw string CTAs:**
"Cancel" in the confirmation state is `t('bulkActions.deleteConfirmCancel')` at BulkActionBar.tsx:199 — not a hardcoded label. The grep hit for "Cancel" is the i18n fallback key, not a raw string.

**WARNING — Partial-failure toast body copy deviates from spec:**
- **UI-SPEC says:** `"N of M layers deleted. N failed — tap to retry."`
- **Implemented key (en):** `"{{deleted}} of {{count}} layers deleted. {{failed}} failed."` (builder.json:789)
- **Gap:** The " — tap to retry." suffix is absent from the body. The retry affordance exists as a sonner `action` button — which is likely better UX — but the spec's explicit copy contract is not met. Since translations (de/es/fr) also lack the suffix, all four locales diverge identically.
- **Severity:** WARNING — retry is discoverable via the action button; the deviation does not break the flow.

**WARNING — SceneSpinnerFallback aria-label is hardcoded English:**
- `aria-label="Loading panel"` at SceneSpinnerFallback.tsx:14 is a raw string, not an i18n-keyed value.
- The UI-SPEC accessibility contract specifies `aria-label="Loading panel"` verbatim, so the implementation matches the spec — but the spec itself failed to require localization of this string.
- Impact: screen reader users in de/es/fr hear "Loading panel" in English instead of a translated string.
- **Severity:** WARNING — the spec is the source of truth here; this is a spec gap, not an implementation gap. File as a follow-up to add a common i18n key (e.g., `common.loadingPanel`).

---

### Pillar 2: Visuals (3/4)

**PASS — Visual hierarchy in BulkActionBar deleting state:**
The deleting state correctly dims the action area: Loader2 uses `text-muted-foreground`, status text uses `text-sm text-muted-foreground`, and the disabled button uses `text-destructive` to maintain the destructive color signal even while blocked.

**PASS — Icon-only buttons have aria-labels and tooltips:**
Every icon-only button in BulkActionBar (visibility toggle, overflow trigger, group/ungroup/delete menu items) has an `aria-label` with count interpolation and, for pointer users, a `<TooltipContent>` companion. All decorative icons carry `aria-hidden="true"`.

**WARNING — Double Loader2 spinner in deleting state:**
BulkActionBar.tsx:153 renders a standalone `Loader2` leading the deleting-state row, then BulkActionBar.tsx:166 renders a second `Loader2` inside the disabled Delete button. The UI-SPEC (§PERF-03 Pending state) specifies: "Delete button shows Loader2 animate-spin icon in place of trash icon." The spec mentions one spinner on the button — the standalone leading spinner is additive and uncontracted. Having two simultaneous spinners may read as noisy; the pattern differs from the single-spinner convention the project uses elsewhere (e.g., LoadingState, SceneSpinnerFallback).
- **Severity:** WARNING — not a functional break, but spec diverges.

**WARNING — cursor-not-allowed limited to disabled button, not BulkActionBar container:**
The UI-SPEC §PERF-03 states "BulkActionBar cursor `not-allowed`" in the Pending row. The container `<div role="toolbar">` at BulkActionBar.tsx:126–138 does not add `cursor-not-allowed` when `isDeleting` is true. The class appears only on the disabled button at line 161 (`cursor-not-allowed` in the Button className). Users hovering non-button regions of the bar during delete get no visual signal that the bar is locked.
- **Severity:** WARNING — minor UX gap, does not block task completion.

---

### Pillar 3: Color (4/4)

No violations found.

**Color token usage in new components:**
- `bg-[var(--surface-2)]` at BulkActionBar.tsx:131 — `--surface-2` is defined in index.css:62–65 (oklch surface scale). Valid project token, not a new one.
- `border-[var(--border)]` at BulkActionBar.tsx:131 — valid project border token.
- `text-muted-foreground` — correct per spec (muted foreground for spinner and status text).
- `text-destructive` — correct per spec (destructive color for delete-related UI).
- `text-sm text-muted-foreground` in SceneSpinnerFallback — matches spec: "muted-foreground: Suspense fallback spinner".

**No hardcoded hex or rgb() values** in any of the three audited new components (BulkActionBar.tsx, SceneSpinnerFallback.tsx, RenderModeSwitch.tsx).

**No accent (--primary) overuse.** Primary is not used in any of the new component surfaces, consistent with the spec's restriction to CTA buttons and active-layer rail only.

---

### Pillar 4: Typography (3/4)

**UI-SPEC declared type scale for this phase:**
- Body: text-sm (14px) / weight 400
- Label: text-xs (12px) / weight 400
- Heading: text-base (16px) / weight 600 (semibold) — not used in new components

**Sizes found in new components:**
- `text-sm` — BulkActionBar.tsx:154 (deleting status text), :183 (confirmation text) — CORRECT
- `text-xs` — BulkActionBar.tsx:254 (visibility label), :267 (opacity label) — CORRECT
- `text-[13px]` — BulkActionBar.tsx:227 (selected count label) — VIOLATION

**WARNING — text-[13px] at BulkActionBar.tsx:227:**
```tsx
<span className="text-[13px] font-medium text-muted-foreground shrink-0">
  {t('bulkActions.selectedCount', { count: N })}
</span>
```
The value 13px is not in the declared type scale (12px / 14px / 16px) and uses an arbitrary Tailwind bracket value. The `text-[13px]` pattern is pre-existing elsewhere in the codebase (OverviewTab, SearchResultCard, import forms) but the UI-SPEC §Constraints for this phase explicitly prohibits new design tokens, and an off-scale font size is a defacto new size token.
- **Fix:** Change to `text-xs` (12px) for a tight label, or `text-sm` (14px) to match the Body role.

**Font weights found:** `font-medium` at BulkActionBar.tsx:227 only. The spec lists Body/Label as weight 400 (regular). `font-medium` (500) is a minor deviation from the Label role's declared weight. No `font-semibold` or heavier weight in new components.

---

### Pillar 5: Spacing (4/4)

No violations found.

**Standard spacing classes verified in new components:**
- `gap-2` (8px), `gap-1.5` (6px), `gap-1` (4px) — all within 8-point scale or half-steps
- `px-3` (12px), `px-2` (8px) — on-scale
- `p-8` (32px = xl per spec) in SceneSpinnerFallback — matches spec xl=32px
- `mx-1` (4px) — xs per spec, appropriate for the divider
- `w-20` (80px) for opacity slider — fixed size for UI element, not a spacing token concern

**No arbitrary [px] or [rem] spacing values** in BulkActionBar.tsx or SceneSpinnerFallback.tsx.

**h-12 (48px)** BulkActionBar height — consistent with the project's 44px+ touch target convention (spec: "44px min for interactive controls"). The 48px bar height meets the standard.

---

### Pillar 6: Experience Design (4/4)

All state machine paths verified; accessibility contract met.

**PASS — Three bulk-delete toast paths all wired:**
- Full success: `toast.success(t('bulkActions.deleteSuccess', ...))` at use-builder-layers.ts:578
- Full rollback: `toast.error(t('bulkActions.deleteRollback'))` at use-builder-layers.ts:585
- Partial failure: `toast.error(...)` with `action: { label, onClick }` retry at use-builder-layers.ts:601–612

**PASS — isDeleting state machine with finally{} cleanup:**
`setIsDeleting(true)` in try block, `setIsDeleting(false)` in finally block at use-builder-layers.ts (lines 566–618). No risk of stuck spinner on API error.

**PASS — aria-busy + aria-live:**
- `aria-busy={true}` on disabled Delete button at BulkActionBar.tsx:163 — matches UI-SPEC accessibility contract
- `aria-live="polite" aria-atomic="true"` sr-only region at BulkActionBar.tsx:143 extends message to include `deletingLayers` copy during pending state
- `role="alertdialog"` on confirmation div at BulkActionBar.tsx:176

**PASS — LazyLoadErrorBoundary on every Suspense boundary:**
MapBuilderPage.tsx shows `<LazyLoadErrorBoundary>` wrapping every `<Suspense>` for the 7 lazy-loaded editor scenes (lines 760, 782, 796, 830, 841, 858, 1082, 1156). Chunk-load failures surface with auto-retry + user-visible retry button per threat mitigation T-1047-02-01.

**PASS — SceneSpinnerFallback accessibility contract:**
`role="status"` + `aria-label="Loading panel"` at SceneSpinnerFallback.tsx:13–14 — matches UI-SPEC accessibility table exactly.

**MINOR — SceneSpinnerFallback aria-label not i18n-keyed (spec gap):**
Noted under Pillar 1. Not scored against Experience Design since the spec itself mandates the hardcoded string value.

---

## Registry Safety

Registry audit: 0 third-party blocks declared for Phase 1047 (UI-SPEC §Registry Safety: "Third-party | none | not applicable"). shadcn official components only. Registry vetting not applicable.

---

## Files Audited

**Implementation files (read in full):**
- `frontend/src/components/builder/BulkActionBar.tsx`
- `frontend/src/components/builder/SceneSpinnerFallback.tsx`
- `frontend/src/components/builder/LayerStyleEditor/RenderModeSwitch.tsx`
- `frontend/src/components/builder/hooks/use-builder-layers.ts` (lines 1–80, 565–625, 1055–1065)
- `frontend/src/i18n/locales/en/builder.json` (lines 760–815)
- `frontend/src/pages/MapBuilderPage.tsx` (lazy/Suspense lines)

**Design contract:**
- `.planning/phases/1047-perf-and-code-quality-fixes/1047-UI-SPEC.md`
- `.planning/phases/1047-perf-and-code-quality-fixes/1047-CONTEXT.md`

**Summary files reviewed:**
- `1047-01-SUMMARY.md` through `1047-06-SUMMARY.md`

**Grep-audited:**
- All new i18n keys across de/es/fr locales
- Hardcoded color values across BulkActionBar, SceneSpinnerFallback, RenderModeSwitch
- font-size and font-weight classes in new components
- spacing classes in new components
- aria-* attributes in new components
- `text-[13px]` prevalence across `frontend/src`
- `--surface-2` token definition in `frontend/src/index.css`
