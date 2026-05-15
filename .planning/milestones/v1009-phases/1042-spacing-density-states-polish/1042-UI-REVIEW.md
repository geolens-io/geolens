# Phase 1042 — UI Review

**Audited:** 2026-05-14
**Baseline:** 1042-UI-SPEC.md (approved)
**Screenshots:** Not captured (dev server at :8080 confirmed live but Playwright-MCP unavailable in this session; code-only audit)

---

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 3/4 | All CTA/empty/error copy is specific and i18n-backed; eyebrow token has a tracking inconsistency across surfaces |
| 2. Visuals | 3/4 | Motion token adoption complete; kebab and expand-button cursor-grab bleed is a residual UX friction point; group-children wash uses `:has()` (correct but browser-support advisory) |
| 3. Color | 3/4 | Accent correctly reserved; `hover:bg-accent` persists on kebab triggers, LEP icon buttons, and DatasetSearchPanel expand buttons — 7 deviating call sites vs the AUD-21 state vocabulary |
| 4. Typography | 3/4 | Two distinct `tracking-*` values for the same eyebrow role (`tracking-wide` vs `tracking-[0.08em]`) — eyebrow canonicalisation is incomplete |
| 5. Spacing | 3/4 | Scene py normalization complete (zero residual py-3); StackRow h-[22px] grid columns are locked structural values per spec; BulkActionBar gap-2 confirmed; minor arbitrary values in SettingsEditorScene projection pill (`px-[10px] py-[5px]`) |
| 6. Experience Design | 3/4 | Skeleton + progress band for DatasetSearchPanel confirmed; freshLayerId entry animation wired; group-children wash CSS selector uses `:has()` (resolves CR-01); `freshLayerTimeoutRef` not self-nulled on fire (latent stale-ref hazard from WR-03) |

**Overall: 18/24**

---

## Top 3 Priority Fixes

1. **`hover:bg-accent` on 7 builder interactive elements instead of `hover:bg-[var(--surface-2)]`** — Breaks token-level consistency mandated by AUD-21 state vocabulary. Inline editors (LayerEditorPanel close/pin at lines 234/278), StackRow kebab (line 337), DatasetSearchPanel expand buttons (lines 253/343), BasemapGroupRow kebab (line 203), FolderGroupRow kebab (line 314) all deviate. At current palette values the visual difference is ~1 OKLCH chroma unit (effectively invisible), but any palette adjustment will expose the inconsistency. Fix: replace `hover:bg-accent` with `hover:bg-[var(--surface-2)]` at all 7 call sites.

2. **Eyebrow tracking token split: `tracking-wide` in `eyebrowClassName` vs `tracking-[0.08em]` in `SettingsEditorScene`** — Three eyebrow labels in SettingsEditorScene (lines 104/155/213) use `tracking-[0.08em]` while the canonical `eyebrowClassName` constant uses `tracking-wide` (Tailwind's `0.1em`). The AUD-02 extraction is correct for the surfaces that use `eyebrowClassName`, but SettingsEditorScene has its own inline eyebrow strings that were not migrated to the shared constant. These labels look identical at font-size 10px but represent a divergence from the single-source-of-truth goal. Fix: replace the three inline `<span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">` strings in `SettingsEditorScene.tsx` with `<span className={eyebrowClassName}>` (importing `eyebrowClassName` from EmptyStackState).

3. **`cursor-grab` applied to entire `DraggableDatasetRow`/`DraggableBasemapRow` outer div bleeds onto the expand-chevron button** — The 1040 carry-over fix adds `cursor-grab` to the outermost `setNodeRef` div (DatasetSearchPanel lines 235–236), which wraps both the grip handle and the expand chevron. Users hovering the expand button see a grab cursor, signalling drag instead of click. The expand button functions correctly but the cursor mismatch creates interaction ambiguity. Fix: move the `cursor-grab`/`cursor-grabbing` classes to the inner content `<div>` (line 239) below the outer DnD registration wrapper, or add `cursor-pointer` explicitly on the expand button to override the inherited grab cursor.

---

## Detailed Findings

### Pillar 1: Copywriting (3/4)

**Contract:** Phase 1042 makes no user-visible copy changes. All copy carries forward from Phases 1040/1041. builder.json dedup is structural only.

**Findings:**

WARNING — Eyebrow token inconsistency bleeds into copy surfaces. `eyebrowClassName` canonicalises `'block text-[10px] font-semibold tracking-wide text-muted-foreground uppercase px-1'` (EmptyStackState.tsx:17). Three section headers in `SettingsEditorScene.tsx` (lines 104, 155, 213) use literal `<span>` with `tracking-[0.08em]` — a different tracking value for the same visual role. Because these are text-bearing elements, they count as copywriting surface inconsistencies: if i18n teams extract these strings and swap them into the eyebrowClassName constant later, the tracking value will silently change. The strings themselves (`TERRAIN`, `WIDGETS`, `PROJECTION`) are appropriate context-specific labels, not generic copy — no text change needed, only the class normalisation.

PASS — i18n dedup confirmed via 1042-VERIFICATION.md: 51 unique top-level keys, zero duplicates, `listboxLabel: "Map layers"` present.

PASS — Error state in DatasetSearchPanel is specific: `'Failed to load datasets. Check your connection and try again.'` (line 633). Not a generic "Something went wrong."

PASS — Empty state copy specific: `'Your catalog is empty. Upload a dataset to get started.'` (line 657) and `"No datasets match '{{query}}'"` (line 673) use templated, contextual strings.

PASS — All BulkActionBar labels match spec: Visibility, Group, Ungroup, Delete — confirmed by grep of `hidden sm:inline` spans at lines 213/259/282/311/362.

INFO — `basemapGroup.toggleExpand` i18n key absent from builder.json (BasemapGroupRow.tsx:107 uses defaultValue fallback). Carried from code review IN-01. Phase 1044 owns locale fill.

INFO — Four `basemapSublayer.*` aria label keys (strokeColor, strokeWidth, casingColor, casingWidth) absent from builder.json (BasemapSublayerEditorScene.tsx:147/159/175/188). Same as above.

---

### Pillar 2: Visuals (3/4)

**Contract:** Motion tokens complete, caret rotation consistent, BulkActionBar mount animation, freshLayerId entry animation, DnD insertion line with bloom.

**Findings:**

PASS — Motion token adoption: all section carets in LayerEditorPanel (lines 456/491/525), BasemapGroupRow (line 104), FolderGroupRow (line 180), SettingsEditorScene (lines 101/152/210), BasemapSublayerEditorScene (line 288), DatasetSearchPanel (lines 257/347), StackRow (line 183), BulkActionBar (line 122), EmptyStackState (lines 200/212) all use `duration-[--motion-fast]`. Zero `duration-150` remaining in modified files.

PASS — Type pill is colorized by record kind: vector → `--type-vector-bg`/`--type-vector`, raster/vrt → `--type-raster-bg`/`--type-raster`, basemap → `--primary-50`/`--primary-700`, fallback → `--surface-2`/`muted-foreground` (LayerEditorPanel.tsx:92–95).

PASS — Insertion line bloom: `[data-dnd-over="true"]` has `border-radius: 9999px; box-shadow: 0 0 0 2px oklch(0.55 0.18 250 / 25%)` (index.css:520–523).

PASS — Group-children wash uses `div:has(> [data-group-drop-target="true"]) > [id^="folder-group-children"]` (index.css:558+). The REVIEW.md CR-01 called this a no-op (the `+` adjacent-sibling selector) but the shipped CSS uses `:has()`, which correctly targets from the common ancestor. `:has()` is supported in all major browsers at baseline 2023 — acceptable for this application's target.

WARNING — `cursor-grab` on outer DnD wrapper bleeds onto expand-chevron buttons. See Priority Fix #3 above. Confirmed at DatasetSearchPanel.tsx:235–236 (outer `<div ref={setNodeRef}>` receives cursor classes). The expand toggle buttons at lines 253 and 343 also use `hover:bg-accent` rather than `--surface-2`, compounding the visual signal confusion.

WARNING — BulkActionBar action button labels use `hidden sm:inline`. At 340px sidebar width the viewport is >640px, so `sm:` should trigger at full viewport width — but the sidebar itself is 340px. At a 768px total viewport, `sm:inline` shows the label. The Tooltip fallback (lines 207–214) covers AT accessibility, but visual label visibility depends on the total viewport width, not sidebar width. The spec acknowledges this behaviour and defers to Tooltip; this is working-as-designed per UI-SPEC §Carry-overs. Flagged for human visual confirmation.

INFO — `role="button"` redundant on native `<button>` elements in EmptyStackState (lines 93/114) per code review IN-03. Harmless noise.

---

### Pillar 3: Color (3/4)

**Contract:** Accent reserved for 9 specific use cases. Secondary hover: `--surface-2`. `hover:bg-accent` targeted for elimination per AUD-21.

**Findings:**

Total `text-primary|bg-primary|border-primary` references in builder components: 43. The spec permits accent on insertion lines, drop targets, selected rows, focus rings, and type pills — these account for the majority.

WARNING — `hover:bg-accent` persists on 7 call sites in Phase 1042 scope that the state vocabulary table specifies should use `--surface-2`:
- `LayerEditorPanel.tsx:234` — close/back button wrapper
- `LayerEditorPanel.tsx:278` — pin/popout button wrapper
- `StackRow.tsx:337` — kebab trigger button
- `DatasetSearchPanel.tsx:253` — DraggableDatasetRow expand button
- `DatasetSearchPanel.tsx:343` — DraggableBasemapRow expand button
- `BasemapGroupRow.tsx:203` — kebab trigger button
- `FolderGroupRow.tsx:314` — kebab trigger button

The AUD-21 fix was correctly applied to `SidebarRail.tsx:121` (layer icon buttons) and the Settings cog at `SidebarRail.tsx:72` was updated to `--surface-2` per Plan 03. But the kebab triggers and panel icon buttons were not swept. `--accent` and `--surface-2` are ~1 chroma unit apart in the current palette (virtually indistinguishable), so there is no visible regression, but the token contract is not fully enforced.

PASS — No hardcoded hex colors in the Phase 1042 modified files. Hardcoded hex in `LineGradientControls.tsx`, `BuilderMap.tsx`, `DEMEditorScene.tsx`, `LabelEditor.tsx` are all pre-existing color picker defaults or MapLibre paint defaults — not visual theme tokens. These are out of Phase 1042 scope.

PASS — EmptyStackState suggest card uses `bg-[var(--surface-0)]` at rest, `hover:bg-[var(--surface-2)]` on hover (line 86). AUD-23 fix confirmed.

PASS — DnD drop targets use correct tokens: `[data-group-drop-target="true"]` uses `var(--primary-50)` + `inset 2px 0 0 var(--primary)` (index.css); `[data-basemap-drop-target="true"]` same.

---

### Pillar 4: Typography (3/4)

**Contract:** Body `text-sm` / `font-normal`; Label/eyebrow `text-[10px]–text-[11px]` / `font-semibold`; Heading `text-base` / `font-medium`; Count/tooltip `text-[13px]` / `font-medium`. No new type sizes.

**Findings from codebase grep (builder components, non-test):**

Distinct standard sizes in use: `text-xs` (316 hits), `text-sm` (54 hits). No `text-lg`, `text-xl`, or larger in Phase 1042 modified files.

Distinct weights: `font-medium` (61 hits), `font-semibold` (42 hits), `font-normal` (1 hit). Exactly 3 weights — within spec's implied constraint.

WARNING — Eyebrow tracking token not unified. `eyebrowClassName` = `tracking-wide` (0.1em Tailwind). SettingsEditorScene eyebrow spans = `tracking-[0.08em]`. These are distinct values for the same typographic role. At 10px font size the rendered difference is 0.2px per character — invisible at glance but a contract deviation. Other surfaces using eyebrowClassName (EmptyStackState, UnifiedStackPanel basemap dock) render at 0.1em. SettingsEditorScene was in scope for AUD-16 (padding) but not explicitly in scope for AUD-02 (eyebrow extraction). This is a gap in scope rather than a regression.

WARNING — `text-[12px]` in `SettingsEditorScene.tsx:241` (projection preset pill tab). This is a one-off size below `text-xs` (12px is the same as `text-xs`) — Tailwind `text-xs` is 12px, so `text-[12px]` is functionally equivalent but the arbitrary value obscures that. Minor.

PASS — No new font sizes introduced. All sizes are from the pre-existing `sketch-findings-geolens` token vocabulary.

PASS — BulkActionBar selected-count display uses `text-xs` (appropriate for compact toolbar).

---

### Pillar 5: Spacing (3/4)

**Contract:** Spacing scale: xs=4px, sm=8px, md=16px (px-4), lg=24px (py-3 header), xl=32px (h-8). Scene sections: `px-4 py-2`. LayerEditorPanel header: `px-4 py-3`. Row grid: `grid-cols-[16px_14px_22px_22px_1fr_60px_22px] gap-2` (structural locked value). BulkActionBar: gap-2. Header buttons: h-8.

**Findings:**

PASS — LayerEditorPanel header: `px-4 py-3` confirmed at line 209. Correct.

PASS — Scene padding normalization: zero `py-3` in non-comment lines of all four scene files (grep returns empty). BasemapGroupEditorScene (3 sections `py-2`), BasemapSublayerEditorScene (5 sections `py-2`), SettingsEditorScene (5 sections `py-2`), DEMEditorScene (3 sections `py-2`).

PASS — BulkActionBar container: `gap-2` at line 119. Confirmed.

PASS — Header buttons: Settings cog `h-8 w-8` and Add data `h-8` confirmed at UnifiedStackPanel lines 825/843.

PASS — StackRow canonical grid: `grid-cols-[16px_14px_22px_22px_1fr_60px_22px] gap-2` at StackRow.tsx:176. The arbitrary column values are a spec-locked structural exception, not a spacing token violation.

WARNING — `SettingsEditorScene.tsx:241` has `px-[10px] py-[5px]` on a projection preset pill button (not from the standard spacing scale). This is a pre-existing element in a file that was in scope for AUD-16 padding fixes. The `px-[10px]` and `py-[5px]` values do not appear on the spec spacing table and are arbitrary. Minor — the pill is a display component, not a primary interactive control.

INFO — `DatasetSearchPanel.tsx:691` uses `max-h-[24rem]` as an arbitrary height constraint on the results list scroll container. This is a layout-stability value, not a design token value — acceptable.

INFO — `BasemapGroupEditorScene.tsx` sublayer grid cell 1 uses `style={{ visibility: 'hidden' }}` inline style alongside Tailwind. This is the intentional spec approach for the caret placeholder column (AUD-17). Structural, not a token deviation.

---

### Pillar 6: Experience Design (3/4)

**Contract:** Loading: skeleton on first fetch, progress band on refetch; Entry animation for new stack rows; Error boundary; Empty states; Disabled states; Confirmation for destructive actions.

**Findings:**

PASS — DatasetSearchPanel first-fetch: 5 skeleton rows at `h-[58px]` rendered when `isLoading && activeTab !== 'basemap'` (lines 639–645). Correct skeleton count and height per spec.

PASS — DatasetSearchPanel refetch: `h-0.5 w-full bg-[var(--primary)] animate-pulse` progress band at line 651. Stale list gets `opacity-50 pointer-events-none` (line 692). Both affordances confirmed.

PASS — StackRow freshLayerId entry animation: `isFresh` prop drives `animate-in fade-in duration-[--motion-fast]` (StackRow.tsx:183). Wire confirmed at UnifiedStackPanel lines 936 and 967.

PASS — BulkActionBar mount animation: `useState(false)` → `rAF` flip → `translate-y-0 opacity-100` confirmed (lines 49–53, 123). Duration uses `--motion-fast` token.

PASS — Destructive delete confirmation: `role="alertdialog"` + `aria-labelledby` at BulkActionBar lines 140–141. Cancel button `variant="ghost"` at line 153. Correct pattern.

PASS — All action buttons carry aria-labels via i18n keys with count interpolation (BulkActionBar lines 201/235/251/277/303/329/354).

WARNING — `freshLayerTimeoutRef` not self-nulled when the 200ms timeout fires (use-builder-layers.ts:655). After the timeout fires, `freshLayerTimeoutRef.current` holds a stale timer ID. If `handleAddDataset` is called again, `clearTimeout(freshLayerTimeoutRef.current)` on line 653 calls `clearTimeout` on the already-fired timer (a no-op, but semantically incorrect — the ref should be `null` to accurately represent "no pending timer"). This is WR-03 from the code review. Functionally correct under normal usage; the hazard is a future maintainer seeing a non-null ref and assuming a timer is active.

Fix: In `use-builder-layers.ts` at line 655, change to:
```ts
freshLayerTimeoutRef.current = setTimeout(() => {
  setFreshLayerId(null);
  freshLayerTimeoutRef.current = null;
}, 200);
```

WARNING — Group-children wash (`:has()` selector) requires CSS `:has()` baseline support. Baseline 2023 — all major browsers support it; Safari 16+, Chrome 105+, Firefox 121+. If the product targets any enterprise browser configurations below these versions (e.g. locked Chrome 104), the wash would silently not render. Flagged as advisory only; the app's browser support policy is not visible in this audit.

WARNING — DatasetSearchPanel `basemap` tab path bypasses skeleton logic (`activeTab !== 'basemap'` guard at lines 639/647). The basemap tab renders directly from a static list (no async fetch), so this is correct. But the guard is string-literal equality, not typed against the `activeTab` state type. If a future tab is added with a different name, the skeleton would incorrectly show for it. Minor DX concern.

---

## Registry Safety

Registry audit: 0 third-party blocks checked (UI-SPEC §Registry Safety lists only shadcn official blocks — Button, Slider, Checkbox, Tooltip, TooltipProvider). No third-party registry entries. Audit skipped as not applicable.

---

## Files Audited

| File | Audit Path |
|------|-----------|
| `frontend/src/index.css` | Motion tokens, insertion line, group-children wash CSS |
| `frontend/src/components/builder/UnifiedStackPanel.tsx` | Header buttons, eyebrowClassName usage, freshLayerId wiring, hover tokens |
| `frontend/src/components/builder/StackRow.tsx` | isFresh prop, entry animation, kebab hover token |
| `frontend/src/components/builder/BulkActionBar.tsx` | gap-2, ghost Cancel, mount animation, label breakpoint |
| `frontend/src/components/builder/DatasetSearchPanel.tsx` | Skeleton, progress band, cursor-grab, filter heights, hover tokens |
| `frontend/src/components/builder/LayerEditorPanel.tsx` | Header padding, type pill, caret duration, hover tokens |
| `frontend/src/components/builder/EmptyStackState.tsx` | surface-0 card, eyebrowClassName export, transition duration |
| `frontend/src/components/builder/BasemapGroupEditorScene.tsx` | py-2 sections, 7-cell sublayer grid |
| `frontend/src/components/builder/BasemapSublayerEditorScene.tsx` | py-2 sections, caret duration |
| `frontend/src/components/builder/SettingsEditorScene.tsx` | py-2 sections, caret duration, eyebrow tracking deviation |
| `frontend/src/components/builder/DEMEditorScene.tsx` | py-2 sections |
| `frontend/src/components/builder/BasemapGroupRow.tsx` | Grip replaced, caret duration, hover tokens |
| `frontend/src/components/builder/FolderGroupRow.tsx` | Caret duration, hover token |
| `frontend/src/components/builder/SidebarRail.tsx` | hover:bg-[var(--surface-2)] at lines 72/121 |
| `frontend/src/components/builder/hooks/use-builder-layers.ts` | freshLayerId state, timeout ref lifecycle |
| `frontend/src/i18n/locales/en/builder.json` | Dedup: 51 unique keys, listboxLabel present |
| `.planning/phases/1042-spacing-density-states-polish/1042-UI-SPEC.md` | Design contract (baseline) |
| `.planning/phases/1042-spacing-density-states-polish/1042-VERIFICATION.md` | Automated verification results |
| `.planning/phases/1042-spacing-density-states-polish/1042-REVIEW.md` | Code review findings |
| `.planning/phases/1042-spacing-density-states-polish/1042-01-SUMMARY.md` through `1042-04-SUMMARY.md` | What was built |
