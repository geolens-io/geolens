---
phase: 1047
slug: perf-and-code-quality-fixes
status: draft
shadcn_initialized: true
preset: "new-york / neutral base / CSS variables / lucide icons"
created: 2026-05-16
---

# Phase 1047 — UI Design Contract

> Minimal additive contract. This is a performance and code-quality phase, not a
> feature phase. The only net-new UI surfaces are: (1) bulk-op progress affordance
> and rollback toast (PERF-03), (2) lazy-load Suspense boundary during chunk fetch
> on /maps/:id scenes (PERF-05). All other changes are non-visual (debounce
> internals, refactors, dead code removal). No new design tokens, no new screens.

---

## Design System

| Property | Value | Source |
|----------|-------|--------|
| Tool | shadcn (new-york style) | components.json (confirmed present) |
| Preset | new-york / neutral base / CSS variables | components.json |
| Component library | Radix UI (via shadcn) | components.json |
| Icon library | Lucide (iconLibrary: lucide) | components.json |
| Font | IBM Plex Sans Variable (body/UI) + IBM Plex Mono (code/coords) | frontend/src/index.css:262-263 |
| Color space | OKLCH | frontend/src/index.css:28-59 |

**shadcn gate result:** `components.json` found. No initialization needed. Registry: shadcn official only. No third-party blocks declared for this phase — vetting gate not applicable.

---

## Spacing Scale

Inherited from project baseline. The 8-point scale is already codified in Tailwind classes.
No new spacing tokens introduced this phase.

| Token | Value | Usage in this phase |
|-------|-------|---------------------|
| xs | 4px | Icon gaps within BulkActionBar progress text |
| sm | 8px | Toast icon-to-text gap in rollback toast |
| md | 16px | Default element spacing (toast body padding) |
| lg | 24px | Section padding (unchanged) |
| xl | 32px | Layout gaps (unchanged) |
| 2xl | 48px | Major section breaks (unchanged) |
| 3xl | 64px | Page-level spacing (unchanged) |

Exceptions: none. Touch targets remain at the project standard (44px min for interactive controls, per existing popup button convention at frontend/src/index.css:483).

**Source:** REQUIREMENTS.md "Out of Scope" — new design tokens explicitly prohibited. sketch-findings-geolens SKILL.md — re-use existing tokens only.

---

## Typography

All type roles are pre-established. Phase 1047 introduces no new text roles.
Sizes are Tailwind utility classes mapped to the token scale in index.css.

| Role | Size | Weight | Line Height | Usage in this phase |
|------|------|--------|-------------|---------------------|
| Body | 14px (text-sm) | 400 (regular) | 1.5 | Toast body copy, BulkActionBar status text |
| Label | 12px (text-xs) | 400 (regular) | 1.5 | Progress sub-label ("Deleting N layers…") |
| Heading | 16px (text-base) | 600 (semibold) | 1.2 | Toast title ("N layers deleted") |
| Display | 20px (text-lg) | 600 (semibold) | 1.2 | Not used this phase |

**Source:** index.css:17-19 (--text-xs 12px, --text-sm 14px, --text-base 16px). sketch-findings-geolens SKILL.md theme section. No new type sizes added.

---

## Color

All color values are OKLCH variables from frontend/src/index.css. No new tokens introduced.

| Role | CSS Variable | Computed (light) | Usage |
|------|-------------|------------------|-------|
| Dominant (60%) | --background | oklch(0.985 0.003 85) | Map builder canvas surround, sidebar background |
| Secondary (30%) | --card / --secondary | oklch(0.99 0.002 85) | BulkActionBar surface, LayerEditorPanel background |
| Accent (10%) | --primary | oklch(0.55 0.18 250) | Bulk-delete progress indicator, active selection rail |
| Destructive | --destructive | oklch(0.577 0.245 27.325) | Bulk-delete rollback error toast, delete confirm |
| Muted | --muted-foreground | oklch(0.45 0.005 250) | Suspense fallback spinner, "Loading…" sub-text |

Accent reserved for: primary action CTA buttons, active-layer left rail, bulk-delete progress fill, focus rings. Accent is NOT used for hover states (those use --secondary/--muted), body text, or neutral icons.

**Source:** index.css:47-59. sketch-findings-geolens — OKLCH primary at hue ~250 is locked.

---

## Component Inventory

### Existing components reused (no changes to component API)

| Component | Path | Role in this phase |
|-----------|------|--------------------|
| `BulkActionBar` | `frontend/src/components/builder/BulkActionBar.tsx` | Add `isDeleting` prop to show in-progress state during bulk-delete; no new DOM structure |
| `LoadingState` | `frontend/src/components/layout/LoadingState.tsx` | Reused as `<Suspense>` fallback for lazy-loaded editor scenes (DEMEditorScene, SettingsEditorScene, basemap editors) — existing `Loader2 animate-spin` pattern |
| `toast` (sonner) | imported from `sonner` | Rollback toast on bulk-delete failure — matches existing `toast.error()` / `toast.success()` pattern in BuilderMap.tsx, use-maps.ts |
| `Skeleton` | `frontend/src/components/ui/skeleton.tsx` | Optional: may be used as a shell placeholder inside Suspense fallback for editor scene panel during first-load of lazy chunk, if LoadingState alone feels abrupt |

### New component (internal refactor — public contract preserved per CODE-06)

| Component | Path (proposed) | Notes |
|-----------|----------------|-------|
| `FillEditor`, `LineEditor`, `CircleEditor`, `SymbolEditor`, `RasterEditor` | `frontend/src/components/builder/LayerStyleEditor/` | Sub-components of LayerStyleEditor split (CB-07). Parent `LayerStyleEditor.tsx` retains its public import surface — callers see no API change. |
| `raf-coalesce.ts` | `frontend/src/lib/builder/raf-coalesce.ts` | Internal utility; no visual surface |
| `syncLayerFilter` | `frontend/src/lib/adapters/shared.ts` (extension) | Internal utility; no visual surface |

---

## Interaction Contracts

### PERF-03 — Bulk-delete progress affordance

**Trigger:** User selects N layers and clicks Delete in BulkActionBar.

**States:**

| State | UI | Copy |
|-------|----|------|
| Idle | BulkActionBar renders normally | — |
| Pending (request in flight) | "Delete" button shows `Loader2 animate-spin` icon in place of trash icon; button is `disabled`; BulkActionBar cursor `not-allowed` | "Deleting N layers…" (sr-only aria-live="polite") |
| Success | BulkActionBar dismisses (layers removed from stack); `toast.success()` fires | "N layers deleted" |
| Partial failure | `toast.error()` fires; successfully deleted layers are removed; failed layers remain selected | "N of M layers deleted. N failed — tap to retry." |
| Full rollback | All layers remain in stack; `toast.error()` fires | "Delete failed — no changes were made." |

**Implementation notes:**
- `isDeleting` boolean prop gates the spinner swap on the Delete button. No new component; extend existing `BulkActionBar` props.
- `toast.error()` with an action button ("Retry") for partial failure — use sonner's `action` option. This matches the ChatPanel undo-toast pattern (ChatPanel.tsx:203, toast.success with action).
- The `aria-live="polite"` region already exists in BulkActionBar (line 139 t('bulkActions.liveAnnouncement')). Extend its message to include the pending state copy.
- Duration: toast auto-dismiss at 5s for success, 8s for error (sonner defaults; match existing builder toasts).

**Source:** REQUIREMENTS.md PERF-03 ("rollback + progress affordances"). CONTEXT.md ("reuse existing v1009 BulkActionBar patterns"). No new visual tokens.

---

### PERF-04 — Debounce / rAF coalescing (no visible UI change)

No user-visible state change. The debounce is purely internal. The only user-perceptible difference is smoother frame rate during drag. No UI-SPEC entry required beyond this note.

Opacity slider: add 100ms debounce to `onOpacityChange` handler. Color picker already debounced (confirmed StyleColorPicker.tsx:46-48). Expression editor: add 200ms debounce.

---

### PERF-05 — Lazy-loaded scene Suspense boundary

**Trigger:** User opens `/maps/:id` route. Lazy chunks for DEMEditorScene, SettingsEditorScene, BasemapGroupEditorScene, BasemapSublayerEditorScene are fetched on demand.

**Fallback during chunk fetch:**

The existing `<Suspense fallback={<LoadingState />}>` pattern (already used at MapBuilderPage.tsx:1167) covers the initial page load. For per-scene lazy loading, a lighter fallback is appropriate since the sidebar is already visible:

| Context | Fallback |
|---------|----------|
| Full-page load (MapBuilderPage initial) | `<LoadingState message="Loading map…" />` (existing — no change) |
| Scene panel lazy boundary (inside LayerEditorPanel flyout) | `<div className="flex items-center justify-center p-8"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>` — inline spinner only, no message text |

**Why no Skeleton here:** The scene panels have variable structure (DEM compass, basemap grid, sublayer list). A generic Skeleton would misrepresent the layout. A simple centered spinner is honest and matches project loading conventions.

**Source:** REQUIREMENTS.md PERF-05. CONTEXT.md PB-01 lazy-load plan. Existing pattern: LoadingState component + Loader2 spinner.

---

## Copywriting Contract

Phase 1047 adds or modifies copy only in the bulk-op progress flow. All other
copy is pre-existing and unchanged.

| Element | Copy | i18n Key (proposed) |
|---------|------|---------------------|
| Bulk-delete pending aria-live | "Deleting {count} layers…" | `bulkActions.deletingLayers` |
| Bulk-delete success toast | "{count} layers deleted" | `bulkActions.deleteSuccess` |
| Bulk-delete partial failure toast | "{deleted} of {count} layers deleted. {failed} failed." | `bulkActions.deletePartialFailure` |
| Bulk-delete full rollback toast | "Delete failed — no changes were made." | `bulkActions.deleteRollback` |
| Bulk-delete retry action label | "Retry" | `bulkActions.retryAction` |
| Scene lazy-load fallback | (no text — spinner only) | n/a |

**Primary CTA for this phase:** Not applicable — no new primary CTA is introduced. The existing "Delete" label in BulkActionBar is unchanged.

**Empty state:** Not applicable — no new empty states introduced.

**Error state:** Bulk-delete failure surfaces via sonner toast (see above). Route-level errors (`/maps/:id` 403/404) use existing copy from `common:errors.*` keys — unchanged.

**Destructive confirmation:** Bulk delete already has a confirmation popover (BulkActionBar.tsx:156 — `bulkActions.deleteConfirmAction`). No change to confirmation copy or mechanism.

**Source:** CONTEXT.md ("no new visual vocabulary"), REQUIREMENTS.md PERF-03. Existing i18n patterns from frontend/src/i18n/locales/en/builder.json.

---

## Accessibility Contract

| Surface | Requirement |
|---------|-------------|
| BulkActionBar delete button (pending state) | `disabled` + `aria-busy="true"` when `isDeleting` is true |
| BulkActionBar live region | `aria-live="polite"` (existing) — extend message for pending state |
| Rollback error toast | `role="alert"` (sonner handles this) — no extra work |
| Suspense boundary spinner | `role="status"` + `aria-label="Loading panel"` on the wrapper div |

**Source:** Existing project accessibility patterns. WCAG 2.1 AA — no new requirements introduced.

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| shadcn official | Skeleton, Badge (pre-existing) | not required |
| Third-party | none | not applicable |

No third-party registry blocks introduced in Phase 1047.

---

## Constraints (from upstream)

| Constraint | Source | Implication |
|------------|--------|-------------|
| No new design tokens | REQUIREMENTS.md "Out of Scope" | All CSS variables are read-only; no additions to index.css |
| No new visual vocabulary | CONTEXT.md decisions | No new icon types, color roles, or layout patterns |
| Reuse sketch-findings-geolens patterns | CONTEXT.md decisions | BulkActionBar patterns from v1009, LoadingState from existing layout components |
| Public component contracts preserved (CODE-06) | REQUIREMENTS.md CODE-06 | LayerStyleEditor split must not change import surface seen by callers |
| No new screen/page/layout | Phase objective | Phase 1047 touches existing surfaces only |

---

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS
- [ ] Dimension 2 Visuals: PASS
- [ ] Dimension 3 Color: PASS
- [ ] Dimension 4 Typography: PASS
- [ ] Dimension 5 Spacing: PASS
- [ ] Dimension 6 Registry Safety: PASS

**Approval:** pending
