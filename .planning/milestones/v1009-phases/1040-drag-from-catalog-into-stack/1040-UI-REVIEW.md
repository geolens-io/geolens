---
phase: 1040
slug: drag-from-catalog-into-stack
status: advisory
audited: 2026-05-14
baseline: 1040-UI-SPEC.md (approved)
screenshots: not captured (dev server at :8080 requires auth — code-only audit)
---

# Phase 1040 — UI Review

**Audited:** 2026-05-14
**Baseline:** 1040-UI-SPEC.md (approved 2026-05-14)
**Screenshots:** Not captured (dev server at :8080 is auth-gated; code-only audit performed)

---

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 3/4 | All spec copy present; builder.json has 8 duplicate top-level key blocks (last value wins in JSON parsers — functionally harmless but structurally dirty) |
| 2. Visuals | 3/4 | cursor-grab scoped to handle button only, not entire row as spec mandates; group children wash missing when expanded group is drop target |
| 3. Color | 4/4 | Token-only color; no hardcoded hex/rgb; accent reserved to spec-declared surfaces (insertion line, group tint, basemap tint, ghost swatch) |
| 4. Typography | 4/4 | Only text-xs and text-sm in phase files; font-medium and font-semibold; all within the 4-size / 2-weight spec budget |
| 5. Spacing | 3/4 | Structural pixel values ([16px 14px 22px 22px 1fr 60px 22px] grid) are locked-from-spec and correct; insertion line missing the specified 25% bloom shadow |
| 6. Experience Design | 3/4 | All five drop-case state machine branches handled; aria-live region with ZWS dedup wired; keyboard pickup announcement fires; entry animation (opacity 0→1, 150ms) for new rows not implemented |

**Overall: 20/24**

---

## Top 3 Priority Fixes

1. **builder.json duplicate key blocks (lines 715–860+)** — In most JSON environments duplicate keys cause the last value to silently overwrite the first. The eight duplicated top-level keys (`unifiedStack`, `rail`, `stackRow`, `basemapGroup`, `basemapSublayer`, `demEditor`, `folderGroup`, `layerEditor`) mean the `a11y` and `styleJson` keys (added in Plan 04, sitting between the two copies) are structurally isolated from the second copy but are preserved by the parser. The risk is any future append to builder.json will be appended to the second copy, diverging from the structure. Fix: deduplicate the file, keeping the first occurrence of each block and merging any differences.

2. **cursor-grab scoped to handle button, not entire row (DatasetSearchPanel.tsx:234, 324)** — The UI-SPEC §1 states "cursor changes to `cursor-grab` on the entire row (not just the handle)." The outer `div[ref=setNodeRef]` has no cursor class; only the grip `<button>` at line 246 has `cursor-grab`. Users mousing over the row body see the default cursor, only discovering drag affordance when hovering the tiny handle. Fix: add `cursor-grab` to the outer row div (`group/row`) conditionally on `!isDragging`, and `cursor-grabbing` when `isDragging`.

3. **Insertion line missing the 25% bloom shadow (index.css:515–517)** — The UI-SPEC §3a specifies `box-shadow: 0 0 0 2px oklch(0.55 0.18 250 / 25%)` on the insertion line to add a soft bloom behind the 2px primary line. The shipped CSS rule `[data-dnd-over="true"]` only sets `border-top: 2px solid var(--primary)` with no box-shadow. The bloom was explicitly included in the spec as the distinguishing element of "Variant A (winner)". Fix: add `box-shadow: 0 0 0 2px oklch(0.55 0.18 250 / 25%)` and `border-radius: var(--radius-full)` to `[data-dnd-over="true"]`.

---

## Detailed Findings

### Pillar 1: Copywriting (3/4)

**PASS items:**
- Grab handle aria-label: `"Drag to add to map"` — matches spec exactly. Wired via `t('search.dragHandle')` at `DatasetSearchPanel.tsx:245, 335`.
- Drop success toast (dataset): `"{{name}} added to map"` — matches spec. Key `toasts.datasetAdded` at `builder.json:576`, consumed at `use-builder-layers.ts:432`.
- Drop success toast (basemap): `"Basemap changed to {{name}}"` — matches spec. Key `toasts.basemapChanged` at `builder.json:577`, consumed at `MapBuilderPage.tsx:471`.
- All four a11y announcement keys match spec verbatim: `a11y.dragPickup`, `a11y.dragPosition`, `a11y.dragDropped`, `a11y.dragCancelled` at `builder.json:829–834`.
- Error toast `toasts.layerAddFailed` — spec listed it as `addLayerFailed` but the actual JSON key and hook call (`use-builder-layers.ts:443`) are consistent with each other. Spec wording was informal; implementation is correct.
- Expand/collapse aria-labels on modal rows (`DatasetSearchPanel.tsx:255, 345`) use raw template literal (`Collapse ${props.title}`) rather than an i18n key — acceptable given these are dynamic labels that combine a static verb with a dynamic name.

**WARNING items:**
- `builder.json` has 8 top-level keys duplicated (lines 715 and 860 both define `unifiedStack`, and similarly for `rail`, `stackRow`, `basemapGroup`, `basemapSublayer`, `demEditor`, `folderGroup`, `layerEditor`). JSON spec allows duplicate keys but behavior is implementation-defined; Node.js / `JSON.parse` silently keeps the last occurrence. The `a11y` and `styleJson` keys at lines 829–858 are between the two duplicate blocks and are preserved correctly. Functionally harmless in the shipped build (i18next parses via JSON.parse) but structurally incorrect and a maintenance hazard. Score deduction: -1.

### Pillar 2: Visuals (3/4)

**PASS items:**
- Grip handle visibility lifecycle correct: `opacity-0` at rest, `group-hover/row:opacity-35` on row hover, `hover:opacity-70` on direct focus (`DatasetSearchPanel.tsx:246, 336`). Matches spec §1 exactly.
- Source row dragging state: `opacity-40 bg-[var(--surface-2)]` applied via `cn()` conditional on `isDragging` (`DatasetSearchPanel.tsx:235, 325`). Matches spec §2 "source row becomes semi-transparent: opacity: 0.4, background: var(--surface-2)".
- `CatalogDragGhost` renders compact pill with type-swatch (V/R/B glyph) + name, `maxWidth: 260`, `minHeight: 36`, `boxShadow: '0 4px 12px oklch(0 0 0 / 15%)'` (`UnifiedStackPanel.tsx:503–522`). Matches spec §2 ghost spec.
- `DragOverlay dropAnimation={null}` at `UnifiedStackPanel.tsx:824` — matches spec §7.
- Basemap group drop target tint: `[data-basemap-drop-target="true"]` fires `background: var(--primary-50)` + `box-shadow: inset 2px 0 0 var(--primary)` (`index.css:537–540`). Matches spec §3c.
- Folder group drop target tint: `[data-group-drop-target="true"]` fires same treatment (`index.css:543–546`). Matches spec §3b primary states.
- `isCatalogDragActive` guard in `FolderGroupRowWrapper` (`UnifiedStackPanel.tsx:299, 318`) correctly prevents group tint during intra-stack drags.

**WARNING items (two deductions, -1 total):**

1. **cursor-grab on entire row — not implemented.** The UI-SPEC §1 explicitly states: "Cursor changes to `cursor-grab` on the entire row (not just the handle)." The outer `<div ref={setNodeRef}>` at `DatasetSearchPanel.tsx:232–236` has no cursor class. `cursor-grab` appears only on the grip `<button>` at line 246. Users mousing over the row label, the type badge, or the action button area see the default cursor, which breaks the discoverability of drag. The entire row is registered as the drag node via `setNodeRef`, so only a CSS addition is needed.

2. **Group children wash missing.** The UI-SPEC §3b states: "If group is expanded, children container also gets `background: oklch(0.97 0.02 250 / 60%)` wash + `border-radius: var(--radius-md)`." The `data-group-drop-target="true"` attribute is set on the `FolderGroupRowWrapper`'s inner `div` which wraps only the `FolderGroupRow` component. The `folder-group-children-{id}` container is a DOM sibling rendered by the outer `<div key={layer.id}>` in `UnifiedStackPanel.tsx:769–794` — it is not a descendant of the drop-target div and receives no CSS cascade. No CSS rule applies the wash. A CSS sibling or child selector (`[data-group-drop-target="true"] + div`, or moving the children inside the wrapper) would fix this.

3. **New-row entry animation absent.** UI-SPEC §5 specifies: "The stack row for the newly-added layer appears at the drop position with a brief entry animation: `opacity: 0 → 1` over 150ms (`transition-opacity duration-150`)." No `freshLayerId` or equivalent tracking is implemented in `use-builder-layers.ts` or `UnifiedStackPanel.tsx`. Rows appear with no opacity transition on drop. This is a polish gap, not a functional gap; counted as one of the -1 deductions combined with cursor-grab above.

### Pillar 3: Color (4/4)

**All accent uses match the spec's reserved list:**
1. Insertion line: `border-top: 2px solid var(--primary)` on `[data-dnd-over="true"]` (`index.css:516`).
2. Group drop target left rail: `box-shadow: inset 2px 0 0 var(--primary)` on `[data-group-drop-target="true"]` and `[data-basemap-drop-target="true"]` (`index.css:539, 545`).
3. Group drop target fill: `background: var(--primary-50)` on both drop targets (`index.css:538, 544`).
4. CatalogDragGhost basemap swatch: `background: var(--primary-50)`, `color: var(--primary-700)` (`UnifiedStackPanel.tsx:487–488`).

No hardcoded hex or rgb values in the phase-touched files (`DatasetSearchPanel.tsx`, `UnifiedStackPanel.tsx`). All color references use `var(--*)` tokens or Tailwind semantic classes. The oklch fallback values inside `var(...)` second arguments are present at the correct values matching `index.css` definitions. Primary scale (`--primary-*`) correctly sourced from `index.css:29–38`.

Type-icon palette for vector/raster/basemap in `CatalogDragGhost` uses `var(--type-raster-bg)`, `var(--type-raster)`, `var(--type-vector-bg)`, `var(--type-vector)` — consistent with the spec type-icon palette table.

### Pillar 4: Typography (4/4)

Phase-touched files (`DatasetSearchPanel.tsx`, `UnifiedStackPanel.tsx`) use:
- **Sizes:** `text-xs` (24 uses), `text-sm` (10 uses). No `text-base`, `text-lg`, or larger in these files.
- **Weights:** `font-semibold` (8 uses), `font-medium` (6 uses). No `font-bold` or lighter weights.

Both within the spec budget (max 4 sizes, max 2 weights).

Spec type scale compliance:
- Body (dataset row label): `text-sm font-medium` at `DatasetSearchPanel.tsx:261, 356` — spec says 14px (text-sm) weight 400 for dataset name. Note: `font-medium` is weight 500, slightly heavier than the spec's weight 400 for dataset row names. The spec also says "Group row name uses weight 500" — for dataset rows it says 400. This is a minor deviation (500 vs 400) but not visually impactful. Not scored down.
- Toast messages: `text-sm` via sonner defaults — correct.
- CatalogDragGhost name: `text-sm` at `UnifiedStackPanel.tsx:520` — correct.
- CatalogDragGhost swatch glyph: `text-[10px] font-semibold uppercase` at `UnifiedStackPanel.tsx:517` — within spec (eyebrow-level text at 10–11px).
- Group eyebrow labels in `UnifiedStackPanel.tsx:625`: `text-[10px] font-semibold tracking-wide uppercase` — minor discrepancy with spec's 11px eyebrow; 10px is consistent with the rest of the v1008 locked stack row anatomy, and the spec for this phase says "no new type sizes introduced." Acceptable.

### Pillar 5: Spacing (3/4)

**Structural values (locked from v1008 spec):**
- Row grid `grid-cols-[16px_14px_22px_22px_1fr_60px_22px] gap-2` at `UnifiedStackPanel.tsx:374` — exact match to the locked spec anatomy.
- Group-children indent `marginLeft: '28px', paddingLeft: '12px'` at `UnifiedStackPanel.tsx:773` — exact match to locked v1008 value.
- Ghost card `px-3 py-2` = 12px/8px at `UnifiedStackPanel.tsx:504` — matches spec's "padding: 8px 12px".
- Grip handle button `h-7 w-5` = 28×20px at `DatasetSearchPanel.tsx:246` — within spec's 32px touch target guidance (the handle is supplementary; the row itself is the primary touch area).

**WARNING items:**
- Insertion line `[data-dnd-over="true"]` missing `border-radius: var(--radius-full)` and `box-shadow: 0 0 0 2px oklch(0.55 0.18 250 / 25%)` bloom (index.css:515–517). The spec explicitly includes both for Variant A (winner): "border-radius: var(--radius-full); box-shadow: 0 0 0 2px oklch(0.55 0.18 250 / 25%)". The shipped rule only applies `border-top: 2px solid var(--primary)`. This is a visual fidelity gap against the locked sketch 007 spec, reducing the insertion line's clarity against the row background.
- Arbitrary values `[22px]`, `[10px]`, `[24rem]`, `[260px]` in the phase files are all structural/dimensional values justified by the locked row anatomy or ghost card max-width spec. They do not represent ad-hoc spacing decisions. Acceptable.
- Standard Tailwind spacing classes used: `px-2`, `px-3`, `py-2`, `gap-2`, `gap-1`, `p-2` — all within the declared spacing scale (4px multiples).

### Pillar 6: Experience Design (3/4)

**PASS items:**
- Five-case drop state machine fully implemented in `MapBuilderPage.handleDragEnd` (`MapBuilderPage.tsx:439–514`): Case 1 (basemap swap), Case 2 (basemap to non-basemap — silent reject), Case 3 (non-basemap to basemap group — silent reject), Case 4 (non-basemap to folder group — parentGroupId wired), Case 5 (loose row add).
- Modal stays open on all drop cases (POL-05). No `onClose()` call anywhere in handleDragEnd or handleAddDataset for catalog drops.
- Toast deduplication keys: `add-layer-${datasetId}` (`use-builder-layers.ts:433`) and `swap-basemap-${datasetId}` (`MapBuilderPage.tsx:472`). Prevents duplicate toasts on rapid drops.
- `document.documentElement.classList.add('dragging-active')` on `handleDragStart` (`MapBuilderPage.tsx:430`), `.remove()` on both `handleDragEnd` and `handleDragCancel`. No leaked drag state.
- aria-live region: `role="status" aria-live="polite" aria-atomic="true"` with ZWS+timestamp dedup trick (`MapBuilderPage.tsx:764–771`). All four announcement types wired.
- `handleDragOver` correctly throttled to fire only on over-id change via `lastOverIdRef` (`MapBuilderPage.tsx:527–538`).
- `KeyboardSensor` with `sortableKeyboardCoordinates` already wired in Plan 01 (`MapBuilderPage.tsx:108–111`). Space/Arrow/Enter/Escape keyboard path functional.
- `activationConstraint: { distance: 8 }` on PointerSensor prevents accidental drag on click (`MapBuilderPage.tsx:105–107`).
- Add-layer failure path: `toast.error(t('toasts.layerAddFailed'))` at `use-builder-layers.ts:443`.
- `cursor: grabbing !important` on `html.dragging-active` prevents cursor flicker during cross-panel drag (`index.css:532–534`).
- `.dragging-active .kebab { opacity: 0 !important }` AUD-03 rule added (`index.css:527–529`).

**WARNING items (one deduction):**
- New stack row entry animation not implemented. UI-SPEC §5 specifies `opacity: 0 → 1` over 150ms `transition-opacity duration-150` for the newly dropped row. No `freshLayerId` tracking state or CSS animation class exists in `UnifiedStackPanel.tsx` or `use-builder-layers.ts`. This is a polish item that the spec explicitly requires to complete the drop confirmation loop — the user's only visual confirmation that the drop succeeded is the toast, since the new row appears without any entrance signal.

---

## Registry Safety

Registry audit: 0 third-party blocks checked. UI-SPEC §Registry Safety table lists only "shadcn official" — no third-party registry blocks introduced in this phase. `@dnd-kit/core` and `@dnd-kit/sortable` are pre-installed npm packages, not shadcn registry blocks. No registry audit required.

---

## Files Audited

| File | Lines | Audit Depth |
|------|-------|-------------|
| `frontend/src/components/builder/DatasetSearchPanel.tsx` | 719 | Full read |
| `frontend/src/components/builder/UnifiedStackPanel.tsx` | ~867 | Full read |
| `frontend/src/pages/MapBuilderPage.tsx` | ~1100 | Lines 1–540, 760–810 |
| `frontend/src/i18n/locales/en/builder.json` | 974 | Full read |
| `frontend/src/index.css` | ~550 | Lines 1–50, 505–547 |
| `frontend/src/components/builder/hooks/use-builder-layers.ts` | ~730 | Key sections grep |
| `.planning/phases/1040-*/1040-UI-SPEC.md` | 307 | Full read |
| `.planning/phases/1040-*/1040-0{1-4}-SUMMARY.md` | — | Full read |
| `.claude/skills/sketch-findings-geolens/SKILL.md` | 147 | Full read |
