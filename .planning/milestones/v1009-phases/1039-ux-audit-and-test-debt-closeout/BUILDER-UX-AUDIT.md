---
phase: 1039-ux-audit-and-test-debt-closeout
artifact: BUILDER-UX-AUDIT
requirement: POL-12
created: 2026-05-14
---

# Map Builder UX Audit — v1008 Surface Sweep

**Scope:** Six builder surfaces of the v1008 unified-stack Map Builder.
**Audited against:** `sketch-findings-geolens` token set + v1008 locked design decisions.
**Severity:** P0 = must fix before v1009 close · P1 = should fix this milestone · P2 = nice to have / defer.
**Fix priority column:** v1009 phase that should own the fix (1042 spacing/density/states; 1043 error/empty/IA) or `deferred`.

## Summary

- 24 findings across six surfaces.
- 4 P0 / 17 P1 / 3 P2.
- Phase 1042 owns 18 findings (spacing/density/typography/states/loading; includes the P2 cosmetic-polish triplet).
- Phase 1043 owns 6 findings (error/empty-states/IA cleanup).
- 0 findings deferred to backlog (every P2 is folded into the 1042 polish sweep).

Per-surface counts: UnifiedStackPanel 4 · LayerEditorPanel 5 · DatasetSearchPanel 6 · Settings scene 3 · SidebarRail 3 · EmptyStackState 3.

---

## UnifiedStackPanel

**File(s):** `frontend/src/components/builder/UnifiedStackPanel.tsx` (820 lines), `frontend/src/components/builder/StackRow.tsx` (392 lines), `frontend/src/components/builder/BasemapGroupRow.tsx` (232 lines), `frontend/src/components/builder/FolderGroupRow.tsx` (349 lines).

**Context:** The primary builder surface — header chrome with title/count/Settings/＋Add data, the listbox region rendering StackRow / BasemapGroupRow / FolderGroupRow, the basemap dock children container, drag/drop affordances (insertion line, group-tint).

| ID | Finding | Severity | Fix priority |
|---|---|---|---|
| AUD-01 | `UnifiedStackPanel.tsx:659` — Header Settings cog button uses `h-[22px] w-[22px]` while the adjacent ＋ Add data Button uses `h-7` (28px) at line 677; the 6px size gap breaks the header CTA rhythm. `sketch-findings-geolens/references/sidebar-structure.md` `.btn-add` spec implies parity with adjacent interactive icons at ~28-32px. Normalize both to `h-8` (32px). | P1 | 1042 |
| AUD-02 | `UnifiedStackPanel.tsx:585-595` — Basemap dock eyebrow label uses `text-[10px] font-semibold tracking-wide` but EmptyStackState SUGGESTED label at `EmptyStackState.tsx:227` uses the same classes inline (literal duplication); neither references a shared token like `--text-xs` or a utility class. Risk of drift when one changes. | P2 | 1042 |
| AUD-03 | `UnifiedStackPanel.tsx:527,532,544` — Drag start/end toggle a `dragging-active` class on `document.documentElement` but `frontend/src/index.css` defines no `.dragging-active .kebab` rule; sketch 007 (`layer-rows-and-groups.md` extension §"Global drag-active state") mandates `.kebab { opacity: 0 !important }` during drag to clear hover noise. Currently kebabs remain visible on hovered rows during drag. | P1 | 1042 |
| AUD-04 | `UnifiedStackPanel.tsx:518-522` — `sortableIds` deliberately excludes the basemap groupId so basemap is non-draggable. A11y consequence: the `role="listbox"` (line 689) advertises a draggable collection but the basemap row's drag handle (`BasemapGroupRow.tsx:108-122`) still renders `cursor-grab` and registers `useSortable` (`UnifiedStackPanel.tsx:225`), producing a silent no-op on drag. Either disable the grip visually for basemap rows or remove `useSortable` registration. | P1 | 1042 |

---

## LayerEditorPanel

**File(s):** `frontend/src/components/builder/LayerEditorPanel.tsx` (766 lines).

**Context:** The 380px side-by-side flyout owning render-mode, paint, visibility, filter, labels, source, and delete; renders breadcrumb-style header at the top, collapsible sections in the middle, and footer button row at bottom.

| ID | Finding | Severity | Fix priority |
|---|---|---|---|
| AUD-05 | `LayerEditorPanel.tsx:203` — Header uses `px-2 py-2` (8px×8px) vs the sketch `editor-header { padding: 14px 14px 12px }` from `sketch-findings-geolens/references/layer-editor-flyout.md`. Effective header height is ~32px not the spec'd ~48px — visually compressed against the type pill+title row. Adopt `px-4 py-3 pb-3` to match the sketch density rhythm. | P1 | 1042 |
| AUD-06 | `LayerEditorPanel.tsx:90` — `LayerEditorTypePill` uses `bg-[var(--surface-2)] text-muted-foreground` for every layer type; sketch `layer-editor-flyout.md` §"Header chrome" specifies type pills use `type-vector-bg` / `type-raster-bg` / `--primary-50` per record kind (mirroring the row type-icon palette). Pill currently provides no type-color identity in the header. | P1 | 1042 |
| AUD-07 | `LayerEditorPanel.tsx:284-572` vs `LayerEditorPanel.tsx:450,485,519` — Always-expanded sections (Render as / Appearance / Visibility) wrap their content in `<div className="px-4 py-2">` while collapsible sections (Filter / Labels / Source) place content in `<div className="px-4 py-2 border-b">` but their carets use `transition-transform duration-150`. Row-level carets in `BasemapGroupRow.tsx:99` / `FolderGroupRow.tsx:142` use only `transition-transform` with no duration. Define one motion utility (e.g., a documented `--motion-fast` token — currently absent from `index.css`; see AUD-08) and apply consistently. | P1 | 1042 |
| AUD-08 | `frontend/src/index.css:62-65,358-361` — `--surface-0..3` and `--radius-*` tokens exist, but `--motion-fast` and `--motion-base` (referenced explicitly in `sketch-findings-geolens/references/empty-state.md` and sketch SKILL §"Token reference") are NOT defined in the live stylesheet. Code references like `transition-colors` (LayerEditorPanel.tsx:313, EmptyStackState.tsx:196) fall back to Tailwind defaults. Either add the two motion tokens to `index.css` `:root` or drop the spec's motion-token language. | P1 | 1042 |
| AUD-09 | `LayerEditorPanel.tsx:710-718` — Delete-confirm "Keep" Cancel button has no `autoFocus`; compare `FolderGroupRow.tsx:340` and `BasemapSublayerEditorScene.tsx:338` which both `autoFocus` the safe button per their inline comments. Inconsistent destructive-dialog focus is a real safety regression: in LayerEditorPanel and StackRow (StackRow.tsx:380-386), focus stays on the Delete trigger when the alertdialog opens. | P0 | 1043 |

---

## Add Dataset Modal (DatasetSearchPanel)

**File(s):** `frontend/src/components/builder/DatasetSearchPanel.tsx` (604 lines).

**Context:** The catalog search/filter/preview/add-to-map modal triggered by ＋Add data, by the SidebarRail Add data icon, and by the EmptyStackState inline search + Browse all.

| ID | Finding | Severity | Fix priority |
|---|---|---|---|
| AUD-10 | `DatasetSearchPanel.tsx:496-501` — Results list shows ONLY a small `Loader2 h-4 w-4` spinner (line 454) during fetch, no skeleton rows. With `limit=20` results (line 230) the empty-then-populated transition is jarring. POL-15 mandates loading affordances for every async fetch. Add per-row skeleton placeholders sized to match the populated row (`h-[58px]` from observed line-height of populated rows at lines 553-590). | P0 | 1042 |
| AUD-11 | `DatasetSearchPanel.tsx:443-448` — Error state renders only a `<p>` "Failed to load datasets. Check your connection and try again." with no retry affordance; the next user action requires changing tabs or query to trigger a refetch. POL-16 mandates "every async failure point surfaces a localized error message with a retry affordance." Add a `<Button>` invoking `queryClient.invalidateQueries(...)`. | P0 | 1043 |
| AUD-12 | `DatasetSearchPanel.tsx:365,376,397,524` — Filter-region heights are inconsistent: search `Input h-9` (36px), `ToggleGroupItem h-7` (28px), filter chip `Button h-6` (24px), basemap badge `h-5` (20px). Five distinct heights inside ~80px of vertical real estate — exactly the "two-row filter bar at visual limit" the project memory flags in `feedback_filter_bar_density.md`. Normalize chips + tabs to `h-7` (28px) and the inline RecordTypeBadge to `h-5` only when small. | P1 | 1042 |
| AUD-13 | `DatasetSearchPanel.tsx:496-499` — When `isFetching && !isLoading`, the results list applies `pointer-events-none opacity-50` to the EXISTING populated list, freezing interactions but offering no inline progress affordance. Users on slow connections lose ~300ms of "did my filter take effect" confidence. Pair with the spinner from AUD-10 (relocate spinner to overlay the results list at top, similar to a sticky progress band) or add a `aria-busy="true"` indicator. | P1 | 1042 |
| AUD-14 | `DatasetSearchPanel.tsx:457-472` — Empty-catalog state offers ONLY "Upload a file →" CTA; per `sketch-findings-geolens/references/empty-state.md` §"What to Avoid": the modal-level empty state should retain catalog-orientation language. Today a user with zero datasets sees a single Upload CTA, which contradicts the v1008 catalog-first positioning. Add a secondary "Browse curated suggestions" or "Visit /collections" link below the Upload CTA. | P1 | 1043 |
| AUD-15 | `DatasetSearchPanel.tsx:553-591` — Each result row uses a `ChevronRight`→`ChevronDown` swap (line 561) for the expand affordance, but every other collapsible in the builder (`LayerEditorPanel.tsx:449,484,518`, `BasemapSublayerEditorScene.tsx:288`) uses `ChevronRight` with a `rotate-90` class transition. Two disclosure idioms for the same affordance fragments the builder's interaction vocabulary. | P1 | 1042 |

---

## Settings Scene

**File(s):** `frontend/src/components/builder/BasemapGroupEditorScene.tsx` (248 lines), `frontend/src/components/builder/BasemapSublayerEditorScene.tsx` (363 lines), `frontend/src/components/builder/SettingsEditorScene.tsx` (268 lines), `frontend/src/components/builder/DEMEditorScene.tsx` (474 lines), plus the settings-route branches of `LayerEditorPanel.tsx`.

**Context:** The non-layer scenes reached via ⚙ Settings — basemap group editor, basemap sublayer editor, terrain/widgets/projection settings, DEM editor.

| ID | Finding | Severity | Fix priority |
|---|---|---|---|
| AUD-16 | `BasemapGroupEditorScene.tsx:78,128,207` vs `LayerEditorPanel.tsx:291,335,372` — Settings-scene sections wrap content in `<div className="px-4 py-3">` while default-scene sections use `<div className="px-4 py-2">`. 4px of vertical inconsistency per section across the same flyout chrome. Pick one (sketch 003 → 12px/14px) and apply both. | P1 | 1042 |
| AUD-17 | `BasemapGroupEditorScene.tsx:137-203` (sublayer list inside Scene B) vs `UnifiedStackPanel.tsx:351-462` (SublayerRow in the sidebar dock) — TWO different sublayer-row layouts render the same data: scene B uses an inline `style={{ height: '32px', ...}}` flex row with no caret/grip cells; sidebar uses the canonical `grid-cols-[16px_14px_22px_22px_1fr_60px_22px]` 7-cell grid. Pick the canonical 7-cell grid (with caret + grip hidden) for both to preserve the unified-row contract from `sketch-findings-geolens/references/layer-rows-and-groups.md`. | P1 | 1042 |
| AUD-18 | `BasemapGroupEditorScene.tsx:237-246` — Footer button arrangement gives `Reset appearance` and `Remove basemap` the same `variant="ghost"` styling and equal width. "Remove basemap" is the destructive action and should look like `LayerEditorPanel.tsx:691` `text-destructive` ghost variant; "Reset appearance" is benign. Sketch 004's footer-asymmetry rule (`layer-editor-flyout.md` §"Footer button asymmetry") requires the two scene B actions to be visually distinguishable. | P1 | 1043 |

---

## SidebarRail

**File(s):** `frontend/src/components/builder/SidebarRail.tsx` (138 lines).

**Context:** The 64px icon column shown at <1100px (per `sketch-findings-geolens/references/responsive.md`) — Settings cog at top, ＋Add data icon below, divider, layer icons.

| ID | Finding | Severity | Fix priority |
|---|---|---|---|
| AUD-19 | `SidebarRail.tsx:76,93` — Settings icon and ＋ icon render at `h-[26px] w-[26px]` inside `h-10 w-10` (40px) buttons; the header Settings cog in `UnifiedStackPanel.tsx:667` uses `h-4 w-4` (16px) inside a `h-[22px] w-[22px]` (22px) button. Settings icon visual weight differs by ~10px between surfaces. Normalize via shared icon-button sizing — sketch `responsive.md` §"Rail (sidebar minified) — visual spec" mandates 40×40 with 26×26 glyph; header should also adopt 26×26 glyph in its 32×32 box. | P1 | 1042 |
| AUD-20 | `SidebarRail.tsx:107-135` — Rail layer buttons never render basemap; `layers` prop is the user-layers array only, so the rail never shows the basemap group at all. Sketch `responsive.md` (visual spec, "The divider sits between user layers and the basemap group") expects a final rail item representing basemap. Today the rail divider (line 102) shows only when `layers.length > 0` and dangles with nothing below it. Render a final rail button for `basemapGroup.id` below the divider. | P1 | 1043 |
| AUD-21 | `SidebarRail.tsx:117-122` — Selected rail row uses `bg-[var(--primary-50,...)] shadow-[inset_2px_0_0_var(--primary)]`. Matches StackRow selected (StackRow.tsx:153) — good consistency. However, hover state uses `hover:bg-accent` (line 121) while StackRow uses `hover:bg-[var(--surface-2,...)]`. Same hover trigger, two different tokens (`--accent` vs `--surface-2`). | P1 | 1042 |

---

## EmptyStackState

**File(s):** `frontend/src/components/builder/EmptyStackState.tsx` (256 lines), `frontend/src/components/builder/suggested-datasets.ts` (32 lines).

**Context:** The catalog-first empty state shown when `layers.length === 0` — heading + inline search + suggested-cards list + Browse-all link.

| ID | Finding | Severity | Fix priority |
|---|---|---|---|
| AUD-22 | `EmptyStackState.tsx:223-243` + `suggested-datasets.ts:32` — `SUGGESTED_DATASETS` ships empty by default. The component still renders the "SUGGESTED" eyebrow label (lines 225-230) followed by an empty `<ul>`. Result: live default render shows an orphan eyebrow with no content beneath it. Either conditionally render the eyebrow only when at least one `SuggestCard` survives the UUID/404 gate (`EmptyStackState.tsx:48-60`), or change the eyebrow copy to a starter-help block when empty. | P0 | 1043 |
| AUD-23 | `EmptyStackState.tsx:80-86` — Suggest card uses `bg-[var(--surface-1)]` for the base background but `sketch-findings-geolens/references/empty-state.md` §"Suggested dataset card" specifies `background: var(--color-surface)` (= `--surface-0`). One level too dark at rest; hover correctly lifts to `--surface-2`. | P2 | 1042 |
| AUD-24 | `EmptyStackState.tsx:192-220` — Inline search container uses `bg-[var(--surface-2)]` (line 194) and `focus-within:border-primary` (line 195); the wrapping div has `transition-colors` but no `duration-*` qualifier and no `--motion-fast` token (see AUD-08). The search icon's hover (line 208 `hover:text-foreground`) is the only color change with no transition class at all; the icon snaps without easing. | P2 | 1042 |

---

## P0 Roll-up

These findings MUST be addressed before v1009 milestone close (ROADMAP success criterion #4).

- **AUD-09** (LayerEditorPanel) — Destructive-confirm "Keep" button is not `autoFocus`'d in `LayerEditorPanel.tsx:710-718` / `StackRow.tsx:380-386`; focus stays on the Delete trigger when the alertdialog opens. Owner: Phase 1043.
- **AUD-10** (DatasetSearchPanel) — Results list shows only a 16px spinner during fetch with no skeleton rows; violates POL-15 loading-affordance requirement. Owner: Phase 1042.
- **AUD-11** (DatasetSearchPanel) — Network/fetch error state has no retry button (`DatasetSearchPanel.tsx:443-448`); silent dead-end on failures violates POL-16. Owner: Phase 1043.
- **AUD-22** (EmptyStackState) — "SUGGESTED" eyebrow renders with an empty `<ul>` beneath it because `SUGGESTED_DATASETS` ships empty; orphan label is broken UX on every fresh install. Owner: Phase 1043.

## P1 Roll-up

Should fix this milestone if scope allows; otherwise defer to backlog with justification.

- **AUD-01** (UnifiedStackPanel) — Header Settings cog (22×22) vs ＋ Add data button (28×28) size gap breaks header rhythm. Owner: Phase 1042.
- **AUD-03** (UnifiedStackPanel) — `dragging-active` body class toggles but `.kebab { opacity: 0 }` rule never written; kebabs stay visible during drag. Owner: Phase 1042.
- **AUD-04** (UnifiedStackPanel) — Basemap row registers `useSortable` but is excluded from sortableIds → silent no-op on drag attempt. Owner: Phase 1042.
- **AUD-05** (LayerEditorPanel) — Header uses `px-2 py-2` (8/8px) instead of sketch's `14/14/12px`; visually compressed. Owner: Phase 1042.
- **AUD-06** (LayerEditorPanel) — Type pill always uses `--surface-2` background; should color by type per sketch (vector/raster/basemap palettes). Owner: Phase 1042.
- **AUD-07** (LayerEditorPanel) — Collapsible carets use `duration-150` but row carets have no duration qualifier; motion inconsistency across the same affordance. Owner: Phase 1042.
- **AUD-08** (LayerEditorPanel) — `--motion-fast` / `--motion-base` referenced by sketch SKILL but NOT defined in `index.css`. Owner: Phase 1042.
- **AUD-12** (DatasetSearchPanel) — Filter-region renders 5 different button heights (36/28/24/20px) within ~80px of vertical real estate. Owner: Phase 1042.
- **AUD-13** (DatasetSearchPanel) — During `isFetching && !isLoading`, results list applies `pointer-events-none opacity-50` with no inline progress affordance. Owner: Phase 1042.
- **AUD-14** (DatasetSearchPanel) — Empty-catalog state offers only Upload CTA; loses catalog-first positioning. Owner: Phase 1043.
- **AUD-15** (DatasetSearchPanel) — Disclosure uses ChevronRight↔ChevronDown swap; rest of builder uses ChevronRight + rotate-90. Owner: Phase 1042.
- **AUD-16** (Settings scene) — Section vertical padding `py-3` in scene editors vs `py-2` in default-scene sections. Owner: Phase 1042.
- **AUD-17** (Settings scene) — Two different sublayer-row layouts: scene B uses inline-styled flex row, sidebar uses the canonical 7-cell grid. Owner: Phase 1042.
- **AUD-18** (Settings scene) — `BasemapGroupEditorFooter` footers Reset and Remove buttons identical-ghost, no danger styling on Remove. Owner: Phase 1043.
- **AUD-19** (SidebarRail) — Settings icon 26×26 in rail but 16×16 in header; same icon, two visual weights. Owner: Phase 1042.
- **AUD-20** (SidebarRail) — Rail divider renders but no basemap rail button below it; sketch responsive.md expects the basemap group to appear on the rail. Owner: Phase 1043.
- **AUD-21** (SidebarRail) — Rail uses `hover:bg-accent`, StackRow uses `hover:bg-[var(--surface-2,...)]` for the same hover trigger. Owner: Phase 1042.

## P2 / Deferred Roll-up

- **AUD-02** (UnifiedStackPanel) — Eyebrow class string literal-duplicated between UnifiedStackPanel basemap dock and EmptyStackState. Owner: Phase 1042 (cosmetic refactor).
- **AUD-23** (EmptyStackState) — Suggest card background `--surface-1` should be `--surface-0` per sketch. Owner: Phase 1042 (cosmetic).
- **AUD-24** (EmptyStackState) — Inline search container `transition-colors` has no duration qualifier; search icon hover has no transition at all. Owner: Phase 1042 (cosmetic; resolves with AUD-08).

## Notes for downstream phases

- **Phase 1042** (spacing/density/states/loading) — total findings owned: 14. Cite finding IDs in plan task descriptions: AUD-01, AUD-02, AUD-03, AUD-04, AUD-05, AUD-06, AUD-07, AUD-08, AUD-10, AUD-12, AUD-13, AUD-15, AUD-16, AUD-17, AUD-19, AUD-21, AUD-23, AUD-24 (18 IDs across P0/P1/P2; "owned by 1042" — see counts above).
- **Phase 1043** (error/empty/IA) — total findings owned: 6. Cite finding IDs: AUD-09, AUD-11, AUD-14, AUD-18, AUD-20, AUD-22.
- **Backlog** — 0 deferred. Every finding lands on a v1009 phase; nothing is intentionally pushed out by this audit. (P2 items are scoped to 1042 as part of the cosmetic-polish sweep — small enough to fold into the larger plan rather than splitting out.)
- **Bridge note for AUD-08** — Whatever phase 1042 picks up first should land the two missing motion tokens (`--motion-fast`, `--motion-base`) in `frontend/src/index.css :root` and reference them from the subsequent state/transition unifications. Several P1 findings (AUD-07, AUD-24) collapse to a one-line fix once those tokens exist.
