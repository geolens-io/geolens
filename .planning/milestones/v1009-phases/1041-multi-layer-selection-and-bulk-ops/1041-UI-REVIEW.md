# Phase 1041 — UI Review

**Audited:** 2026-05-14
**Baseline:** 1041-UI-SPEC.md (approved)
**Screenshots:** Not captured (no dev server detected on ports 3000/5173/8080 at audit time — note: port 8080 returned 200 but Playwright not installed in this session)

---

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 3/4 | All spec copy keys present in en; duplicate JSON blocks in builder.json structurally unsafe |
| 2. Visuals | 3/4 | Button labels hidden at all sidebar-compatible widths; no mount animation on bar entry |
| 3. Color | 4/4 | Token usage matches spec exactly; no hardcoded hex values; 60/30/10 preserved |
| 4. Typography | 4/4 | Only text-sm, text-xs, text-[13px] used — all within spec-declared sizes |
| 5. Spacing | 3/4 | Grid anatomy and h-12 correct; bar container gap-1 (4px) is below spec's sm=8px element gap |
| 6. Experience Design | 3/4 | CR-01 and CR-02 fixes applied; WR-02 aria-live fixed; Cancel uses `secondary` variant not `ghost`; no mount animation; opacity does not debounce to API |

**Overall: 20/24**

---

## Top 3 Priority Fixes

1. **Duplicate top-level keys in builder.json** — The file contains two complete copies of `unifiedStack`, `rail`, `stackRow`, `basemapGroup`, `basemapSublayer`, `demEditor`, `folderGroup`, and `layerEditor` (8 namespaces duplicated, lines 715–997). JavaScript JSON.parse keeps only the last occurrence; if i18next loads the file differently (e.g., via a tree-shaking bundler that preserves first-seen), any key unique to the first block (none currently) could be lost silently. The structural debt makes the file brittle: any future addition to a first-block namespace will be ignored. Fix: remove lines 715–826 (the first copies of the 8 duplicate namespaces) and verify no keys were exclusive to the first blocks.

2. **Action button labels invisible at all practical sidebar widths** — The "Visibility", "Opacity", "Group", "Ungroup", and "Delete" text labels in `BulkActionBar.tsx` are gated on `hidden xl:inline`. Tailwind's `xl` breakpoint is 1280px viewport-wide. The sidebar itself is 340px; it will never exceed `xl`. The buttons therefore render as icon-only at all real usage widths. The enabled buttons (Visibility, Opacity, Delete) have aria-labels but no visible Tooltip wrappers — only the disabled Group and Ungroup buttons have tooltips. This fails the spec anatomy which shows text labels and the general accessibility principle that icon-only interactive controls should have visible-on-hover labels. Fix: either lower the breakpoint threshold to `sm:inline` (640px) so labels show inside the sidebar, or wrap enabled Visibility and Delete buttons in a Tooltip matching the disabled-button pattern.

3. **Cancel button uses `variant="secondary"` instead of spec-required `variant="ghost"`** — UI-SPEC §5 states "Two buttons appear: `Cancel` (ghost, sm) on the left and `Delete {N} layers` (ghost + `text-destructive`, sm) on the right." `BulkActionBar.tsx:145` uses `variant="secondary"`, which applies a filled background color from the design system. This makes Cancel visually heavier than Delete, inverting the intended weight hierarchy (safe default should be visually recessive, destructive confirm should be foreground-colored but still ghost). Fix: change `variant="secondary"` to `variant="ghost"` on the Cancel button in the confirmation state.

---

## Detailed Findings

### Pillar 1: Copywriting (3/4)

**Passing:**
- All spec-mandated bulk action copy keys are present in `en/builder.json` under `bulkActions`: `selectedCount`, `toolbarLabel`, `liveAnnouncement`, `visibility`, `visibilityAriaLabel`, `opacity`, `opacityAriaLabel`, `group`, `groupAriaLabel`, `groupDisabledTooltip`, `ungroup`, `ungroupAriaLabel`, `ungroupDisabledTooltip`, `delete`, `deleteAriaLabel`, `deleteConfirmLabel`, `deleteConfirmAction`, `deleteConfirmCancel`, `errorUpdateRolledBack`, `errorDeleteRolledBack`, `selectRow`, `selectGroup`.
- Copy values match the spec verbatim: `"Delete {{count}} layers? This cannot be undone."`, `"Cancel"`, `"Failed to update layers — changes rolled back."`, etc.
- All four locale files (en/de/fr/es) have the `bulkActions` namespace with all 22 keys. Phase 1044 handles non-English translations.

**WARNING — Duplicate JSON namespace blocks:**
`en/builder.json` contains two full copies of `unifiedStack` (lines 715 and 884), `rail` (728, 898), `stackRow` (731, 901), `basemapGroup` (746, 916), `basemapSublayer` (757, 927), `demEditor` (773, 943), `folderGroup` (790, 960), and `layerEditor` (797, 968). JavaScript `JSON.parse` keeps the last duplicate key's value, so the second blocks win at runtime. The `listboxLabel` key is only in the second `unifiedStack` block (line 896) and therefore is accessible. However this structure is a maintenance hazard: future additions to the first-block copy will be silently ignored, and any tooling (linters, type generators) that processes the file may report on first-seen keys only.

**WARNING — `bulkActions.deleteConfirmCancel` value inconsistency:**
The value `"Cancel"` appears at line 878 (correct, matches spec). But `folderGroup.deleteConfirmCancel` at lines 795 and 965 reads `"Keep group"` — this is correct for the folder group flow but the close proximity to the bulk delete cancel key may cause confusion during future edits. No functional bug, but naming divergence within a single action type (`deleteConfirmCancel`) across two namespaces merits a comment or rename of one to avoid confusion.

---

### Pillar 2: Visuals (3/4)

**Passing:**
- Bulk action bar is correctly positioned as a sticky footer outside the scrollable `div.flex-1.overflow-y-auto` (line 1008), inside the `flex.flex-col.h-full.overflow-hidden` container. It pins to the bottom of the panel without reflowing the layer list.
- Checkbox renders in the caret column (16px wide) for `StackRow` and `FolderGroupRow` during `isMultiSelectionActive` — matches the spec's "reveal on activation" idiom. No persistent checkbox column.
- `BasemapGroupRow` applies `cursor-not-allowed` when `isMultiSelectionActive` (line 84) with no toast — silent boundary signal exactly per spec.
- Confirmation state unmounts normal bar buttons and renders the `role="alertdialog"` inline panel with focused Cancel — matches spec §5 two-step confirmation sequence.
- Visual disambiguation table from spec is implemented: rest = no tint, hover = `var(--surface-2)`, single-selected = `primary-50 + inset 2px`, multi-selected = `primary-50 + inset 2px + checkbox`.

**WARNING — Action button labels invisible at all practical widths:**
All five action button labels (Visibility, Opacity, Group, Ungroup, Delete) use `hidden xl:inline` (`xl` = 1280px viewport). The sidebar is 340px; the label text will never be visible. The spec anatomy diagram shows `[ {N} selected | Visibility | Opacity | Group | Ungroup | Delete ]` with text labels. At 340px width only icon + count span are visible — this reads as an icon toolbar with no text labels. The enabled buttons (Visibility, Delete) do not have Tooltip wrappers (unlike disabled Group/Ungroup which have tooltips explaining why they're disabled). Hover context is missing for the enabled actions.

**WARNING — No mount animation on BulkActionBar entry:**
The spec states: "Enter animation: `translate-y-0 opacity-100 duration-150` from `translate-y-2 opacity-0`." The component uses `transition-all duration-150` but is mounted/unmounted conditionally (`selectedIds.size >= 2`). A CSS `transition` cannot animate an element's initial mount — it only transitions between values. No `AnimatePresence`, no initial class swap, no `useEffect`-delayed class addition is present. The bar appears and disappears instantaneously rather than sliding up. This is a polish miss, not a functional blocker.

---

### Pillar 3: Color (4/4)

**Passing:**
All color usage aligns with the spec's reserved accent list:

- Multi-selected row tint: `bg-[var(--primary-50)]` — correct (StackRow:177, FolderGroupRow:154)
- Left rail: `shadow-[inset_2px_0_0_var(--primary)]` — correct (StackRow:177, FolderGroupRow:154)
- Checkbox: inherits `var(--primary)` via shadcn Checkbox component token — no override needed
- Bulk action bar background: `bg-[var(--surface-2)]` — correct (BulkActionBar:113)
- Bulk action bar border: `border-[var(--border)]` — correct (BulkActionBar:113)
- Delete text: `text-destructive` — correct on both Delete button (BulkActionBar:328) and confirmation label (BulkActionBar:139)
- Settings button active state: `bg-[var(--primary-50)] text-primary` — correct (UnifiedStackPanel:821)

No hardcoded hex or `rgb()` values in any of the 5 audited component files. 60/30/10 distribution intact: dominant `surface-0`/`surface-1` for row backgrounds, `surface-2` for bar and hover, `primary` accent only on selected state and checkbox.

Registry audit: 0 third-party registries listed in UI-SPEC.md. `Checkbox` is shadcn official. No registry flags.

---

### Pillar 4: Typography (4/4)

**Passing:**
Font sizes in BulkActionBar and StackRow stay within the spec-declared set:

| Class | Spec Role | Used In |
|-------|-----------|---------|
| `text-[13px]` | Heading / selected count | BulkActionBar:178 |
| `text-sm` | Body (row label, button text) | StackRow:282, BulkActionBar:139 |
| `text-xs` | Tooltip / icon-label (hidden at xl) | BulkActionBar:203, 244 |

`text-[10px]` appears in UnifiedStackPanel for the basemap eyebrow label and type icon glyph — this is pre-existing from Phase 1035, not introduced in Phase 1041.

Font weights: `font-medium` (selected count, BulkActionBar:178), `font-normal` (body), `font-semibold` (header badge) — all three within spec's declared weight set. No `font-bold` or `font-extrabold` added.

---

### Pillar 5: Spacing (3/4)

**Passing:**
- Row grid anatomy: `grid-cols-[16px_14px_22px_22px_1fr_60px_22px] gap-2` — matches locked spec exactly (StackRow:173, FolderGroupRow:152). `gap-2` = 8px is the spec's documented `gap: 6px` approximation in Tailwind (note: spec says 6px, Tailwind gap-2 = 8px — minor pre-existing discrepancy from v1008).
- Bar height: `h-12` = 48px — matches spec's `2xl` token (BulkActionBar:113).
- Bar horizontal padding: `px-3` = 12px — matches spec's `padding: 0 12px` exactly (BulkActionBar:112).
- Row vertical padding: `py-2` = 8px = `sm` token — matches spec.
- Opacity slider: `w-20` = 80px — matches spec's `w-20` (BulkActionBar:219).

**WARNING — Bar container gap-1 below spec's element gap:**
The BulkActionBar container uses `gap-1` (4px = `xs` token) between all flex children. The spec spacing table lists `sm = 8px` as the "bulk bar horizontal element gap." `gap-1` is the `xs` token (4px). At 340px sidebar width with 5 actions, gap-1 is more practical than gap-2, but it deviates from the spec's declared value. Advisory only.

**Minor — Header padding uses inline style instead of Tailwind:**
`style={{ padding: '16px 16px 8px' }}` (UnifiedStackPanel:797) — this is pre-existing from Phase 1036, not introduced in Phase 1041. Noted for completeness.

---

### Pillar 6: Experience Design (3/4)

**Passing:**
- Code review blockers CR-01 and CR-02 are confirmed fixed: `handleBulkDelete` now filters out `group:folder` IDs before making API calls (use-builder-layers.ts:525-530). The Escape/Shift+Arrow listener is attached to `stackPanelRef` (UnifiedStackPanel.tsx:690) not `document` — both the code and the comment are now accurate.
- WR-01 fixed: `.catch()` added to `handleBulkDelete` promise in MapBuilderPage (lines 407-410).
- WR-02 fixed: `aria-live="polite"` moved from the toolbar container to a dedicated `sr-only` span (BulkActionBar:123). The `liveAnnouncement` key is now referenced and rendered.
- WR-03 addressed: `onClearSelection` removed from `BulkActionBarProps` (comment at line 17 confirms the decision).
- WR-04 fixed: All 5 `handleBulk*` callbacks in MapBuilderPage use specific handler references (`[layers.handleBulkVisibility]` etc.) not the entire `layers` object.
- IN-02 addressed: `unifiedStack.listboxLabel` is present in the second (winning) `unifiedStack` block at line 896. `defaultValue: 'Map layers'` fallback also present in code (UnifiedStackPanel:851).
- Destructive confirmation follows AUD-09 pattern: `autoFocus` on Cancel (BulkActionBar:148), 2-step click pattern, `role="alertdialog"` wrapping.
- `aria-multiselectable="true"` present on listbox (UnifiedStackPanel:852).
- Rollback pattern: `Promise.allSettled` → single toast on any failure → selection preserved.
- All 5 clearing rules from POL-10 implemented: Escape, outside-click, route change (unmount), drag-start, successful op.

**WARNING — Cancel button variant deviates from spec:**
BulkActionBar:145 uses `variant="secondary"` for Cancel. The spec (§5) requires `variant="ghost"`. The `secondary` variant renders a filled background (muted/accent surface), making Cancel visually heavier than the destructive Delete confirmation button. The intended hierarchy is Cancel (recessive, ghost) vs Delete (foreground-colored ghost + `text-destructive`). Using `secondary` for Cancel means both buttons compete for visual weight.

**WARNING — No entry/exit animation on BulkActionBar mount:**
Spec: "`transition-all duration-150`" from `translate-y-2 opacity-0`. The bar appears and disappears instantaneously because CSS transitions do not apply at DOM mount. The `transition-all` class is present but has no effect without an initial state class. To implement: add a state flag that starts at `translate-y-2 opacity-0` and flips to `translate-y-0 opacity-100` after mount (via `useEffect` + `setTimeout(0)` or a layout effect), or use Framer Motion's `AnimatePresence`.

**WARNING — Bulk opacity clears selection only on drag end (deliberate deviation):**
The spec (§4 POL-09) states "Selection clears on successful bulk op completion." `handleBulkOpacity` in MapBuilderPage does not call `setSelectedIds(new Set())` after each slider change — the comment at lines 383-388 documents this as a deliberate decision (clearing selection mid-drag breaks subsequent drag events). The deviation is reasonable given the slider is not an "API call" in the per-layer PATCH sense; it writes to local state + `hasUnsavedChanges`. Selection is preserved until Escape or another row click. This is advisory — the comment should be surfaced in the next spec revision for POL-09.

**INFO — `isMultiSelectionActive` on FolderGroupRow does not show cursor-not-allowed:**
`FolderGroupRow` can be multi-selected (this is correct per spec — group rows can be in `selectedIds`). The cursor remains `cursor-pointer` during multi-selection mode, which is correct. No issue here; noted because `BasemapGroupRow` does show `cursor-not-allowed` and the contrast is intentional per POL-11.

---

## Files Audited

- `frontend/src/components/builder/BulkActionBar.tsx` (new)
- `frontend/src/components/builder/StackRow.tsx`
- `frontend/src/components/builder/FolderGroupRow.tsx`
- `frontend/src/components/builder/BasemapGroupRow.tsx`
- `frontend/src/components/builder/UnifiedStackPanel.tsx`
- `frontend/src/components/builder/hooks/use-builder-layers.ts` (partial: handleBulkDelete, handleBulkVisibility, handleBulkOpacity)
- `frontend/src/pages/MapBuilderPage.tsx` (partial: handleBulk*, isBasemapBoundaryId, selectedIds state)
- `frontend/src/i18n/locales/en/builder.json`
- `frontend/src/i18n/locales/de/builder.json` (key presence only)
- `frontend/src/i18n/locales/fr/builder.json` (key presence only)
- `frontend/src/i18n/locales/es/builder.json` (key presence only)
- `.planning/phases/1041-multi-layer-selection-and-bulk-ops/1041-UI-SPEC.md`
- `.planning/phases/1041-multi-layer-selection-and-bulk-ops/1041-REVIEW.md`
- `.planning/phases/1041-multi-layer-selection-and-bulk-ops/1041-04-SUMMARY.md`
- `.claude/skills/sketch-findings-geolens/SKILL.md`
