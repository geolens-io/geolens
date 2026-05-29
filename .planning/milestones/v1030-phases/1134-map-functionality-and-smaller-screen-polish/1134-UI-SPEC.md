---
phase: 1134
slug: map-functionality-and-smaller-screen-polish
status: draft
shadcn_initialized: true
preset: not applicable (existing project — components.json present)
created: 2026-05-27
---

# Phase 1134 — UI Design Contract

> Visual and interaction contract for Phase 1134: Map Functionality and Smaller-Screen Polish.
> This is a **polish + bug-fix phase**. No new design tokens, no new component variants, no new
> typographic decisions. The contract pins layout invariants, timing contracts, and regression
> shapes that existing `gsd-ui-checker` and `gsd-ui-auditor` consumers verify against.

---

## Design System

| Property | Value | Source |
|----------|-------|--------|
| Tool | shadcn (via Radix Dialog primitive) | components.json present |
| Preset | existing project — no init required | components.json |
| Component library | Radix UI (via shadcn) | frontend/src/components/ui/ |
| Icon library | Lucide React | existing |
| Font (sans) | IBM Plex Sans Variable | frontend/src/index.css line 262 |
| Font (mono) | IBM Plex Mono | frontend/src/index.css line 263 — coord readout |

---

## Spacing Scale

Standard 8-point scale in use project-wide. No new spacing values introduced in this phase.

| Token | Value | Usage |
|-------|-------|-------|
| xs | 4px | Icon gaps, tight inline padding |
| sm | 8px | Compact element spacing, pill padding |
| md | 16px | Default element spacing |
| lg | 24px | Section padding |
| xl | 32px | Layout gaps |
| 2xl | 48px | Major section breaks |
| 3xl | 64px | Page-level spacing |

Exceptions for this phase:
- **MapCoordReadout right offset:** 56px (`right-14` = 3.5rem = 56px). Load-bearing for NavigationControl clearance in ViewerMap context. Not a spacing-scale deviation — it is a positioning contract. See §Layout Invariants.
- **NavigationControl top-left margin-top:** 32px (`data-builder-canvas="true"` scoped CSS). Locks vertical clearance for the MapLibre control in the builder canvas. Not a spacing-scale deviation.
- **Notes presence indicator dot:** 6px diameter (1.5 Tailwind units = `size-1.5`). Sub-4px not used; 6px is the smallest readable dot.

---

## Typography

No new sizes or weights introduced in this phase. All type is from the existing scale in `frontend/src/index.css`.

| Role | Size | Weight | Line Height | Usage |
|------|------|--------|-------------|-------|
| Body / label | 14px (`text-sm`) | 400 | 1.43 (Tailwind default) | Layer row labels, editor labels, tooltip copy |
| Micro / caption | 12px (`text-xs`) | 400 | 1.33 | Filter chip labels, badge text |
| Instrument (mono) | 10px (`text-2xs` + `font-mono`) | 400 | 0.875rem | MapCoordReadout lat/lng/zoom readout |
| Section heading | 14px (`text-sm`) | 500 | 1.43 | Panel header titles (BuilderRail, SheetHeader) |

**Rule:** No new `text-*` class beyond this set is introduced in this phase.

---

## Color

All color tokens come from `frontend/src/index.css`. No new tokens added.

| Role | Token | Value (light mode) | Usage |
|------|-------|--------------------|-------|
| Dominant (60%) | `--background` | `oklch(0.985 0.003 85)` — warm atlas-paper off-white | Map canvas container, sidebar bg, sheet bg |
| Secondary (30%) | `--muted` / `--card` | `oklch(0.97 0.003 85)` | Layer row hover, chip bg, tooltip bg |
| Accent (10%) | `--accent` / `--primary` | `oklch(0.97 0.003 85)` / `oklch(0.55 0.18 250)` — OKLCH blue hue 250 | See reserved-for list below |
| Destructive | `--destructive` | `oklch(0.577 0.245 27.325)` | Delete layer confirmation only |
| Muted foreground | `--muted-foreground` | `oklch(0.45 0.005 250)` | Secondary labels, coord readout text |

**Accent reserved for (exhaustive list):**
1. Active rail button background (`bg-accent text-primary` in BuilderRail)
2. Notes presence indicator dot (uses `--primary` = OKLCH blue)
3. Layer row selection state (primary tint + 2px left rail per sketch-findings-geolens 007)
4. Focus ring (`--ring` = `oklch(0.55 0.18 250)`)
5. Primary CTA button ("Add data")

**Accent NOT used for:** general hover states (use `bg-accent text-foreground`), filter chips (use `bg-background/90`), coord readout background.

---

## Layout Invariants

These positions are locked. The executor MUST NOT modify them. Regression pins specified per invariant.

### INV-01: NavigationControl position — top-left (locked)

- **Contract:** NavigationControl stays at `position: 'top-left'` in `BuilderMap.tsx`. Never moved to top-right, bottom-*, or any other position.
- **Enforcement:** `data-builder-canvas="true"` attribute on the outer BuilderMap wrapper + scoped CSS rule `[data-builder-canvas="true"] .maplibregl-ctrl-top-left { margin-top: 32px }` provides the 32px clearance from the MapTitleBar.
- **Source:** v1011 RESP-01/02 contract (commits `391459bb`, `4f4a9917`); confirmed live WALK-SS-01.
- **What is NOT in scope for this phase:** Moving NavigationControl. If sidebar overlap exists at ≤800px, the fix is the **sidebar collapse trigger**, NOT NavigationControl position (Pitfall #10).

### INV-02: MapCoordReadout offset — right-14 (load-bearing)

- **Contract:** MapCoordReadout pill anchors at `top-2 right-14` (8px from top, 56px from right).
- **Rationale:** 56px clears the MapLibre NavigationControl when it is at `top-right` (ViewerMap context). In BuilderMap, NavigationControl is at `top-left`, so the 56px right offset is not required for builder collision avoidance — but it MUST NOT be reduced because it is the ViewerMap contract.
- **Source:** RESP-02 (Phase 1051 Plan 09); `MapCoordReadout.tsx` docstring lines 26-37; confirmed live WALK-SS-02.
- **Regression test:** Positive-form `queryBy*` pin in `MapCoordReadout.test.tsx` asserting the `right-14` class is present. (MAP-08)

### INV-03: SheetContent showCloseButton={false} in builder canvas (locked)

- **Contract:** Every `<SheetContent>` rendered inside the builder canvas (not catalog/admin flows) MUST pass `showCloseButton={false}`. The wrapped Sheet content owns its own close affordance (either a `ChevronRight` close button in BuilderRail, or the LayerEditorPanel close control).
- **API:** `frontend/src/components/ui/sheet.tsx` — `showCloseButton` prop defaults to `true`. Builder canvas call sites override to `false`.
- **Confirmed sites (as of 2026-05-27):**
  - `MapBuilderPage.tsx:1252` — layer list sheet (`showCloseButton={false}`)
  - `MapBuilderPage.tsx:1364` — mobile rail sheet (`showCloseButton={false}`)
- **What MAP-10 requires:** Grep all `<SheetContent` usages in `frontend/src/pages/MapBuilderPage.tsx` and `frontend/src/components/builder/` — every hit in the builder canvas path must have `showCloseButton={false}`. Negative-control regression pin: `sheet-close-button.test.tsx` asserts that querying `getByRole('button', { name: /close/i })` on a builder-canvas Sheet returns null (no auto-X rendered).
- **Source:** v1011 RESP-03; confirmed live WALK-SS-03/06.

---

## Interaction Contracts

### IC-01: Visibility-toggle visual feedback — zero flicker

- **Contract:** When the user toggles a layer's visibility off or on, the MapLibre canvas must reflect the change synchronously (within the same rAF tick as the `set_visibility` dispatch).
- **Acceptable timing:** Canvas update within 1 rAF tick (≤16ms at 60fps). No fade transition for the canvas itself — MapLibre sets `layout.visibility: 'none'` which is instantaneous.
- **What is NOT acceptable:** A visible flash where the layer briefly appears at wrong opacity, or a frame where the layer is partially hidden. This is the v1011 BUG-01 `syncVisibility` initial-layout pattern — all adapters must honor `visible === false` at `addLayer` time (not just after a separate `setLayoutProperty` call).
- **Adapter contract:**
  - At `addLayer`: pass `layout.visibility = input.visible ? 'visible' : 'none'` in the `addLayer` call itself (not a subsequent `setLayoutProperty`).
  - At `syncVisibility`: call `syncSingleLayerVisibility(map, layerId, visible)` for EVERY companion layer the adapter registers (e.g., fill-adapter: `layerId` + `${layerId}-outline` + `${layerId}-extrusion`; cluster-adapter: all 3 sub-layers).
  - `syncLayerFilter` must be called in `syncPaint` for adapters that support filters: circle-adapter (WALK-C-01) and heatmap-adapter (WALK-H-01) are currently missing this call.
- **Source:** WALK-C-01, WALK-H-01, MAP-18.

### IC-02: Rename-group focus — rAF-deferred (exact pattern)

- **Contract:** When the user initiates a group rename (via kebab menu or double-click), the text input for the rename receives focus on the **first rendered frame after the dnd-kit / Radix DropdownMenu pointer-event sequence completes**.
- **Implementation pattern:** Use `requestAnimationFrame(() => inputRef.current?.focus())` — one rAF deferral. NOT `setTimeout(fn, 0)` and NOT synchronous focus.
- **Rationale:** dnd-kit restores focus to the drag handle after drag end; Radix DropdownMenu restores focus to the trigger on close. A synchronous `focus()` call inside `onSelect` or `onClick` fires before these library focus-restoration callbacks and is silently overwritten. One rAF deferral places the focus call after all library callbacks have completed.
- **Regression test:** `UnifiedStackPanel.test.tsx` — rename input has `.focus()` asserted after `act(() => {})` wrapping the trigger (covers the rAF flush via `jest.useFakeTimers` + `jest.runAllTimers`).
- **Source:** v1011 BUG-03; MAP-16.

### IC-03: Delete-layer — no orphan sources

- **Contract:** When `remove_layer` is dispatched, the reconciler (`map-sync.ts`) must remove ALL MapLibre layers registered by the adapter's `getLayerIds()` PLUS the source (if not shared). The sequence is: (1) remove layers in `getLayerIds()` order; (2) remove source if `map.getSource(sourceId)` exists and no other layer references it.
- **Affected adapters requiring explicit verification:**
  - fill-adapter: `getLayerIds` returns `[layerId, '${layerId}-outline', '${layerId}-extrusion']` — all three must be removed. WALK-F-02 flags potential orphan for fill layers with height column.
  - cluster-adapter: `getLayerIds` returns `[clusterCircleLayerId, clusterCountLayerId, layerId]`. WALK-X-02 flags potential source-race on delete.
  - raster-adapter: `addLayers` early-return bug (WALK-R-05) means source may exist without a layer. Delete path must remove layer if present AND source regardless.
- **State contract:** After `remove_layer`, `map.getStyle().layers` must contain zero entries matching any id from `getLayerIds(sourceId)`, and `map.getStyle().sources` must contain zero entries for the removed source id.
- **Regression test:** `use-builder-layers.test.tsx` — one case per render mode (fill / line / circle / symbol / heatmap / cluster / raster) asserting clean layer + source removal.
- **Source:** WALK-F-02, WALK-X-02, MAP-17.

### IC-04: Raster-adapter addLayers early-return — distinguish source-exists from layer-exists

- **Contract:** `raster-adapter.ts addLayers` currently guards `if (map.getSource(sourceId)) return` — this prevents re-adding the layer when the source already exists but the layer was removed (e.g., after basemap style reload via reconciler). The fix must distinguish:
  - Source does not exist → add source, then add layer.
  - Source exists, layer does not exist → skip source-add, add layer only.
  - Source exists, layer exists → no-op (current guard is correct for this case).
- **Source:** WALK-R-05, MAP-18.

### IC-05: Map container scroll isolation

- **Contract:** Pan and zoom gestures on the BuilderMap canvas MUST NOT scroll the page body.
- **Mechanism:** The MapLibre canvas element must have `touch-action: none` (MapLibre sets this itself on the canvas). The containing `<div>` chain from `BuilderMap` up to `MapBuilderPage` must not have `overflow: auto` or `overflow: scroll` on any ancestor that would capture wheel events before MapLibre.
- **Verification:** At 800×600, scroll the wheel over the map — page body `scrollY` must remain 0.
- **Source:** MAP-19.

---

## Notes Presence Indicator

MAP-22: The Notes icon in BuilderRail must show a presence indicator when `dockNotes` is non-empty (length > 0 after trimming).

### Visual spec

| Property | Value | Rationale |
|----------|-------|-----------|
| Shape | Filled circle (dot) | Matches tab-pip convention in LayerEditorPanel (`LayerEditorPanel.tsx:97`) |
| Size | 6px diameter (`size-1.5` = 1.5 × 4px = 6px) | Smallest readable dot at 16px icon; matches `SublayerConfigIndicators` dot pattern |
| Color | `--primary` (`oklch(0.55 0.18 250)` — OKLCH blue) | Primary accent — indicates active state, not error |
| Position | Top-right corner of the Notes icon button | Offset: `-top-0.5 -right-0.5` (absolute, relative to the `h-8 w-8` button) |
| Visibility threshold | `dockNotes.trim().length > 0` | No indicator for empty or whitespace-only notes |
| Animation | None — static dot. Appears/disappears without transition | Avoids distraction; dot is not a notification, it is a state indicator |

### Implementation

```tsx
// Inside BuilderRail railButtons for 'notes':
// Add a relative wrapper on the button and absolutely-position the dot:
<button className="relative ...">
  <FileText className="h-4 w-4" />
  {notes.trim().length > 0 && (
    <span
      aria-label={t('rail.notesPresent', { defaultValue: 'Map has notes' })}
      className="absolute -top-0.5 -right-0.5 size-1.5 rounded-full bg-primary"
    />
  )}
</button>
```

The dot is `aria-label`-annotated so screen readers hear "Map has notes" alongside the button label. It uses `bg-primary` (OKLCH blue). No border needed at this size.

---

## Filter-Pill vs Measure-Widget Collision Avoidance

MAP-20: Filter chips must not collide with the MeasurementWidget chrome.

### Current positions (from source)

| Element | Anchor | Tailwind classes | Effective position |
|---------|--------|------------------|--------------------|
| ActiveFilterChips | `top-left` slot inside WidgetHost | Rendered after any `top-left` widgets in the `flex-col gap-2` container | Flows below `top-12 left-3`; stacks downward |
| MeasurementWidget | `bottom-left` floating | `absolute bottom-14 left-4 z-10` | 56px from bottom, 16px from left |

### Collision condition

At ≤800px viewport height (600px), the `top-left` container grows downward with each filter chip. The `bottom-left` MeasurementWidget sits at `bottom-14` (56px from bottom). With a 600px viewport height and a MapTitleBar at ~40px, the map canvas is ~560px tall. `top-12` = 48px from canvas top. Each filter chip is ~28px tall with 8px gap. After ~16 chips the `top-left` container could theoretically reach `bottom-14` — but in practice, filter chips overflow before that.

### Spatial contract (no z-order conflict needed)

The two elements are in different horizontal bands at normal viewport sizes:
- `top-left` chip column: top-anchored, flows down from `top-12`.
- `bottom-left` measurement widget: bottom-anchored at `bottom-14`.

They share the same `z-10` and the same left band, but are vertically separated. The fix for MAP-20 is:

**Add `max-h` + `overflow-y: auto` to the filter chip container** so that at ≤800px the chip column does not grow past the midpoint of the canvas (half the map canvas height = `max-h-[40vh]`). This prevents the column from ever reaching the measurement widget regardless of chip count.

| Property | Value |
|----------|-------|
| max-height on filter chip container | `max-h-[40vh]` |
| overflow | `overflow-y-auto` |
| scroll style | `scrollbar-thin` or plain (no styled scrollbar needed) |

**Z-order:** No z-index change required. Both elements sit at `z-10`. Since they are in the same stacking context and vertically separated by the `max-h` constraint, z-order is not the fix surface.

**Source:** WALK-SS-05, MAP-20.

---

## Smaller-Screen (≤800px) Contract

### Breakpoint definitions

| Breakpoint | Value | Behavior |
|------------|-------|----------|
| Full layout | ≥1100px | 3-column (sidebar 340px + map + editor 380px) |
| Rail mode | <1100px | Sidebar minifies to 64px SidebarRail icon column; editor stays 380px |
| Editor-hidden | <800px | Editor flyout hidden until user selects a layer; mobile rail buttons at `right-2 top-16 z-30` |

Source: sketch-findings-geolens responsive.md (sketch 008 A).

### ≤800px invariants

1. **NavigationControl** stays `top-left` with `margin-top: 32px` via `data-builder-canvas` scoped CSS. Confirmed WALK-SS-01.
2. **MapCoordReadout** stays at `top-2 right-14`. Confirmed WALK-SS-02. No visual change in this phase.
3. **Every `<SheetContent>` in builder canvas** uses `showCloseButton={false}`. Confirmed WALK-SS-03. Phase 1134 adds the negative-control regression pin for MAP-10.
4. **Sidebar collapse trigger (MAP-07):** At 800×600, the right-sidebar Sheet must not visually overlap the NavigationControl. The audit (WALK-SS-04) flags this as unverified live. The fix is in the sidebar Sheet's width/offset — NOT in NavigationControl position. The Sheet already has `className="w-[22rem] max-w-[calc(100vw-5rem)]"` (MapBuilderPage.tsx:1371) which limits the overlay to `100vw - 80px`. At 800px, max-width = 720px. The navigation controls sit at `top-left` so the overlap surface is vertical (height of the Sheet vs. top of the NavigationControl). If vertical overlap is confirmed live via MCP, add a `mt-12` (48px) to the Sheet's `inset-y-0 top-0` to shift it below the MapTitleBar row. Exact offset is determined during Phase 1133 MCP re-verify.
5. **Mobile rail buttons** at `right-2 top-16 z-30` (44×44px touch targets) must not overlap MapCoordReadout at `top-2 right-14`. At 800px: mobile rail buttons are at x=800-8-44=748px, MapCoordReadout pill ends at x=800-56=744px. These are at the same horizontal band (top-2 vs top-16 = 8px vs 64px vertical) — no collision.

---

## Copywriting Contract

This phase introduces no new UI copy surfaces. The contracts below document existing copy for the elements being modified or pinned.

| Element | Copy | Source |
|---------|------|--------|
| Notes rail button label | "Notes" | `t('dock.notes', { defaultValue: 'Notes' })` |
| Notes presence indicator aria-label | "Map has notes" | New — add i18n key `builder.rail.notesPresent` |
| Notes empty placeholder | "Add notes about this map…" | `t('dock.notesPlaceholder', { defaultValue: 'Add notes about this map…' })` |
| Filter chip "clear filter" aria | Per-layer display name + " filter" | Existing ActiveFilterChips |
| Sheet close (sr-only, suppressed) | "Close" | `t('common.close')` — present in sheet.tsx but hidden by `showCloseButton={false}` |
| Delete layer confirmation | No modal in this phase — delete dispatches immediately with optimistic + rollback (v1011 BUG-02 pattern) | MAP-17 |

**No new destructive confirmation dialogs are introduced in Phase 1134.** Delete layer uses the existing optimistic + rollback pattern from v1011 BUG-02.

**New i18n key required (MAP-22):**
- Key: `builder.rail.notesPresent`
- Default (en): `"Map has notes"`
- Required in: de, es, fr (i18n parity — same 4-language requirement as all builder strings)

---

## Component Inventory

Components modified in this phase. No new components created.

| Component | File | Modification |
|-----------|------|-------------|
| `BuilderRail` | `frontend/src/components/builder/BuilderRail.tsx` | Add notes presence dot to Notes button (MAP-22) |
| `circle-adapter` | `frontend/src/components/builder/layer-adapters/circle-adapter.ts` | Add `syncLayerFilter` call in `syncPaint` (WALK-C-01 / MAP-18) |
| `heatmap-adapter` | `frontend/src/components/builder/layer-adapters/heatmap-adapter.ts` | Add `syncLayerFilter` call in `syncPaint` (WALK-H-01 / MAP-18) |
| `raster-adapter` | `frontend/src/components/builder/layer-adapters/raster-adapter.ts` | Fix `addLayers` source-exists/layer-exists early-return (WALK-R-05 / MAP-18) |
| `MapBuilderPage` | `frontend/src/pages/MapBuilderPage.tsx` | MAP-07 sidebar collapse trigger; verify all SheetContent `showCloseButton={false}` |
| `ActiveFilterChips` | `frontend/src/components/builder/ActiveFilterChips.tsx` | Add `max-h-[40vh] overflow-y-auto` (MAP-20) |
| `UnifiedStackPanel` | `frontend/src/components/builder/UnifiedStackPanel.tsx` | rAF-deferred focus for rename-group input (MAP-16) |

Components that are **read-only** in this phase (verified, not modified):
- `sheet.tsx` — API is correct; `showCloseButton` prop already exists. No modification.
- `MapCoordReadout.tsx` — position contract already correct. No modification (MAP-08 adds regression pin only).

---

## Regression Test Contracts

Named test files the executor MUST create or extend. Each ties to a specific requirement.

| Test File | Requirement | What to Pin |
|-----------|-------------|-------------|
| `frontend/src/components/builder/__tests__/use-builder-layers.test.tsx` | MAP-17 | One case per render mode (7 modes): `remove_layer` leaves zero orphan MapLibre layers and zero orphan sources |
| `frontend/src/components/builder/layer-adapters/__tests__/circle-adapter.test.ts` | MAP-18 | `syncPaint` with a filter calls `syncLayerFilter`; visibility toggle calls `syncSingleLayerVisibility` |
| `frontend/src/components/builder/layer-adapters/__tests__/heatmap-adapter.test.ts` | MAP-18 | `syncPaint` with a filter calls `syncLayerFilter`; visibility toggle calls `syncSingleLayerVisibility` |
| `frontend/src/components/builder/layer-adapters/__tests__/raster-adapter.test.ts` | MAP-18 | `addLayers` with source-exists/layer-missing adds layer without re-adding source |
| `frontend/src/components/builder/__tests__/UnifiedStackPanel.test.tsx` | MAP-16 | Rename-group trigger → rAF flush → input has focus; synchronous focus is NOT asserted (negative control) |
| `frontend/src/components/builder/__tests__/sheet-close-button.test.tsx` | MAP-10 | Negative-control: every builder-canvas `<SheetContent showCloseButton={false}>` renders zero auto-X close buttons |
| `frontend/src/components/map/__tests__/MapCoordReadout.test.tsx` | MAP-08 | Positive-form: component renders with `right-14` class present (regression guard against position drift) |

---

## Registry Safety

No new shadcn blocks or third-party registries introduced in this phase.

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| shadcn official | Sheet, Badge, existing primitives | not required — no new blocks |
| Third-party | none | not applicable |

---

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS
- [ ] Dimension 2 Visuals: PASS
- [ ] Dimension 3 Color: PASS
- [ ] Dimension 4 Typography: PASS
- [ ] Dimension 5 Spacing: PASS
- [ ] Dimension 6 Registry Safety: PASS

**Approval:** pending

---

## Pre-Populated From

| Source | Decisions Used |
|--------|---------------|
| 1134-CONTEXT.md | 5 (Pitfall #10/11, dispatchLayerAction stability, no-architecture-rewrite, named test files) |
| 1133-BUILDER-WALKTHROUGH-AUDIT.md | 8 (WALK-C-01, WALK-H-01, WALK-R-05, WALK-F-02, WALK-X-02, WALK-SS-01..06) |
| REQUIREMENTS.md | 10 (MAP-07..10, MAP-16..20, MAP-22) |
| sketch-findings-geolens SKILL.md | 3 (responsive breakpoints, dot vocabulary, OKLCH primary token) |
| frontend/src/index.css | 6 (all color tokens, typography scale, motion tokens) |
| frontend/src/components/ui/sheet.tsx | 1 (showCloseButton API confirmed) |
| frontend/src/components/map/MapCoordReadout.tsx | 2 (right-14 contract, docstring cross-context note) |
| frontend/src/pages/MapBuilderPage.tsx | 3 (SheetContent call sites, ActiveFilterChips position, mobile rail button position) |
| frontend/src/components/map-widgets/WidgetHost.tsx | 2 (ANCHOR_POSITIONS, bottom-left measurement widget offset) |
| User input | 0 (discuss phase skipped; all decisions from upstream artifacts) |
