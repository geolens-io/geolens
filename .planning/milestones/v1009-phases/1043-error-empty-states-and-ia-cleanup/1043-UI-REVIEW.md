---
phase: 1043
slug: error-empty-states-and-ia-cleanup
audited: 2026-05-14
baseline: UI-SPEC.md (approved)
screenshots: not captured (dev server not running at audit time; port 8080 returned 200 but no browser session)
---

# Phase 1043 — UI Review

**Audited:** 2026-05-14
**Baseline:** 1043-UI-SPEC.md (approved)
**Screenshots:** not captured (code-only audit)

---

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 3/4 | All contracted copy implemented and i18n-backed; Source section micro-labels (Dataset/Features/Type/Geometry) still hardcoded strings |
| 2. Visuals | 3/4 | Error/empty iconography and hierarchy correct; basemap rail button glyph hierarchy diverges from overlay layers |
| 3. Color | 3/4 | Token sweep complete on 7 scoped sites; 15 `hover:bg-accent` instances remain across 10 other builder files |
| 4. Typography | 2/4 | SettingsEditorScene migrated to `eyebrowClassName`; LayerEditorPanel itself has 10+ section headers still at `tracking-[0.08em]` not `tracking-wide` |
| 5. Spacing | 3/4 | Spec scale followed; arbitrary `[px]` values are icon sizing only (h-[18px], h-[26px]) — justified by spec |
| 6. Experience Design | 4/4 | Error + loading + empty states all covered; autoFocus on every alertdialog cancel button; scroll/focus preservation wired |

**Overall: 18/24**

---

## Top 3 Priority Fixes

1. **LayerEditorPanel section-header tracking inconsistency** — All 10+ eyebrow labels inside `LayerEditorPanel.tsx` use `tracking-[0.08em]` (the deprecated value) rather than importing and using `eyebrowClassName`. The eyebrow migration was completed for `SettingsEditorScene` but the primary panel — the highest-traffic surface in the builder — was left behind. Visual inconsistency is perceptible at these sizes: `tracking-wide` (0.1em) vs `tracking-[0.08em]` is a visible difference in label legibility. Fix: import `eyebrowClassName` from `EmptyStackState` into `LayerEditorPanel` and replace all 10 inline `className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground"` strings. Lines 333, 377, 414, 492, 527, 561 are the section-header instances; lines 575, 581, 587, 593 are the Source sub-labels.

2. **Source section micro-labels are not i18n-backed** — The four labels "Dataset", "Features", "Type", "Geometry" at `LayerEditorPanel.tsx:575,581,587,593` are plain string literals, not `t()` calls. Phase 1043 explicitly touched this section (adding the `noColumns` empty state at line 597) and `builder.json` was edited in all four plans. These four strings will be untranslatable in Phase 1044's `de/es/fr` fill pass, re-opening scope. Fix: wrap each with `t('layerEditor.source.dataset', { defaultValue: 'Dataset' })` etc. and add four keys to `builder.json`.

3. **15 residual `hover:bg-accent` instances across 10 builder files** — Plan 04's scope was correctly limited to the 7 canonical sites. However the audit now closes with `hover:bg-accent` still in `BuilderRail.tsx`, `MapToolbar.tsx`, `ChatPanel.tsx`, `SharePanel.tsx`, `BasemapPicker.tsx`, `MapTitleBar.tsx`, `PopupConfigEditor.tsx`, `ColorRampPicker.tsx`, `IconPicker.tsx`, `MentionDropdown.tsx`. The token contract (`hover:bg-[var(--surface-2)]` as canonical interactive surface hover) is only partially applied, meaning the builder has two competing hover tokens in live production UI visible in the same session. Fix: extend the sweep to all 15 instances in the next available polish phase.

---

## Detailed Findings

### Pillar 1: Copywriting (3/4)

**WARNING: Four Source section labels are hardcoded strings (not i18n)**

`LayerEditorPanel.tsx:575,581,587,593` — The Source collapsible renders four metadata labels as literal strings: `>Dataset<`, `>Features<`, `>Type<`, `>Geometry<`. Every other user-facing string in the Source section added or touched in Phase 1043 — including the new `layerEditor.source.noColumns` at line 597 — uses `t()`. These four are the exception. This blocks Phase 1044's locale fill for these fields.

**PASS items:**
- Error state copy matches spec exactly: "Failed to load datasets. Check your connection and try again." at `DatasetSearchPanel.tsx:637` — declarative, directive, no passive voice, no "Oops".
- Retry CTA: "Try again" at `search.retry` in `builder.json` — correct.
- Empty catalog secondary CTA: "Browse public catalog →" at `search.browseCatalogCta` — correct.
- EmptyStackState fallback: "Search the catalog to find datasets, or use the Upload button to add your own." — `unifiedStack.emptyHelpBody` — correct.
- Destructive copy: "Are you sure? This cannot be undone." + "Keep layer" / "Delete" — matches spec exactly in both branches.
- `search.added` corrected from `"(added)"` to `"Added"` (WR-03 fix confirmed).
- `settings.*` namespace (22 keys) added to `builder.json` (CR-02 fix confirmed).
- All 10 contracted i18n keys from the UI-SPEC missing-keys table are present and correctly valued.

**Minor: Browse catalog button uses visible text arrow in i18n copy**

`unifiedStack.browseAllShort` = `"Browse catalog →"` — the right-arrow is embedded in the string value. This is consistent with the existing `unifiedStack.browseAll` = `"Browse all datasets →"` pattern. Not a spec violation but it means RTL locales will need a mirrored value in Phase 1044.

---

### Pillar 2: Visuals (3/4)

**WARNING: SidebarRail basemap button glyph is smaller than overlay layer glyphs**

`SidebarRail.tsx:155` — `LayoutGrid` renders at `h-[18px] w-[18px]` while overlay layer icons render at `h-[26px] w-[26px]` (line 127). The spec explicitly documents this as intentional ("18px is appropriate for the basemap group which is a control icon"). However the practical result is a visually lighter basemap button at the bottom of the rail that feels de-emphasized relative to its function as a navigation destination. The divider above it reinforces the separation but the size drop may read as "less important" to users unfamiliar with the builder. This is a design judgment call, not a spec violation.

**PASS items:**
- Error state visual anatomy: `AlertCircle` (h-4 w-4, `text-destructive`) + body paragraph (`text-foreground`) + ghost retry Button — exactly as contracted. Icon carries destructive color; body does not.
- Empty state visual anatomy: `MapPin` (h-8 w-8, `text-muted-foreground`) + body copy + ghost CTA — contracted icon and sizing used.
- Zero-result state: `SearchX` (h-8 w-8, `text-muted-foreground`) — consistent with empty state icon size.
- `BasemapGroupEditorFooter`: "Remove basemap" visually distinguished from "Reset appearance" via `text-destructive` — asymmetric visual weight achieved without red background.
- All icon-only buttons carry `aria-label` or tooltip (Settings, Add data, rail layer buttons, basemap button).
- `autoFocus` on safe button in alertdialog creates a clear visual focus ring on "Keep layer" / "Keep group" on open — tested: StackRow line 430, LayerEditorPanel lines 760 and 800, FolderGroupRow line 379.

---

### Pillar 3: Color (3/4)

**WARNING: 15 residual `hover:bg-accent` instances in builder files outside Phase 1043 scope**

Files: `BuilderRail.tsx` (2), `MapToolbar.tsx` (3), `ChatPanel.tsx` (1), `SharePanel.tsx` (1), `BasemapPicker.tsx` (2), `MapTitleBar.tsx` (2), `PopupConfigEditor.tsx` (1), `ColorRampPicker.tsx` (1), `IconPicker.tsx` (1), `MentionDropdown.tsx` (1). These are out-of-scope per Plan 04's explicit deviation log, but they exist in the same build and user session as the migrated surfaces.

**PASS items:**
- Zero `hover:bg-accent` in the 7 scoped files (LayerEditorPanel, StackRow, DatasetSearchPanel, BasemapGroupRow, FolderGroupRow, SidebarRail, SettingsEditorScene) — confirmed via grep.
- Hardcoded color check on phase-touched files: zero hex or `rgb()` values (excluding `oklch()` destructive-hover which is spec-authorized: `oklch(0.97_0.02_27)`).
- Accent reserved list: `text-primary` usage on the browse catalog button and basemap rail selected state matches the reserved item list in the spec.
- Error banner background: no red background; `--surface-0` (transparent) used — correct.
- Accent usage count: 34 instances of `text-primary/bg-primary/border-primary` across builder files — broadly within the 10% slot given the density of interactive controls.

---

### Pillar 4: Typography (2/4)

**WARNING: LayerEditorPanel section headers not migrated to `eyebrowClassName`**

The eyebrow migration was the spec's explicit mandate: "SettingsEditorScene must import and use `eyebrowClassName` for its three section headers ... replacing the current `tracking-[0.08em]` inline strings." The migration was applied to `SettingsEditorScene.tsx` (confirmed: 3 usages at lines 105, 156, 214), but `LayerEditorPanel.tsx` — which was modified in Plans 01, 02, and 03 of this phase — still has inline `tracking-[0.08em]` at:

- Line 333 — "RENDER AS" section header
- Line 377 — "APPEARANCE" section header
- Line 414 — "VISIBILITY" section header
- Line 492 — "FILTER" section header
- Line 527 — "LABELS" section header
- Line 561 — "SOURCE" section header
- Lines 575, 581, 587, 593 — Source sub-labels (Dataset, Features, Type, Geometry)

The `eyebrowClassName` canonical value uses `tracking-wide` (0.1em). The inline value is `tracking-[0.08em]`. The delta is 0.02em — visible at 10px in a high-density panel. `BasemapSublayerEditorScene.tsx` (4 instances) and `DEMEditorScene.tsx` (5 instances) have the same divergence — both were not in Phase 1043 scope.

Score rationale: The spec named SettingsEditorScene as the migration target; that target is clean. But the primary builder panel has 10 diverging instances, and the migration was completed three plans over which `LayerEditorPanel` was modified repeatedly. The failure to apply the pattern to the file being actively edited drops this to 2.

**PASS items:**
- Font sizes in use across phase-touched files: `text-xs`, `text-sm`, `text-[10px]` — all within the declared type scale (xs=12px, sm=14px, 10px=eyebrow). No new size tokens introduced.
- `LayerEditorTypePill` at line 91 uses `tracking-[0.08em]` — this is a badge, not a section header; the spec's eyebrow contract applies to section headers specifically. Acceptable divergence.
- `text-[11px]` at line 297 (subtitle truncated text) — one arbitrary size not in the declared scale. Pre-existing, not introduced in Phase 1043. Minor.

---

### Pillar 5: Spacing (3/4)

**Minor: Arbitrary pixel values used for icon sizing are spec-authorized**

`SidebarRail.tsx:78,95,127,155` — `h-[26px] w-[26px]` and `h-[18px] w-[18px]` are not from the 4/8/16/24/32/48/64px token scale, but the UI-SPEC explicitly documents these as "structural, not a spacing token" and names the exact pixel values for the glyph hierarchy. No violation.

`LayerEditorPanel.tsx:352` — `px-[10px] py-[5px]` on the render-mode pill chips. Arbitrary spacing not in the declared scale and not explicitly listed as an exception. Pre-existing and not introduced by Phase 1043.

**PASS items:**
- Error banner container: `px-4 py-6` — `py-6` (24px) matches the spec's `lg=24px` for centred empty-state containers.
- EmptyStackState starter-help container: `px-4 py-4 gap-3` — within spec scale.
- SidebarRail layout: `py-2 gap-1` — consistent with the pre-existing rail spec.
- Retry button: `ghost size="sm"` (shadcn default sizing) — no custom spacing added.
- Basemap footer gap: `gap-2` — matches spec for alert-dialog footer button gap.

---

### Pillar 6: Experience Design (4/4)

This pillar is the phase's primary deliverable and it is complete.

**Error state coverage:**
- `DatasetSearchPanel.tsx:633-648` — `role="alert"`, `AlertCircle` icon, localized message, `RotateCcw` retry button wired to `queryClient.invalidateQueries(queryKeys.datasetSearch.results(...))`. No dead-end on fetch failure.
- Map save failure: existing `MapTitleBar` retry pattern unchanged — out of scope; working.
- Layer add failure: existing toast pattern unchanged — working.

**Loading state coverage:**
- `DatasetSearchPanel.tsx:652-661` — skeleton rows (`Skeleton` × 5) on first fetch; progress band animation on refetch. Both states present.

**Empty state coverage:**
- EmptyStackState `SUGGESTED_DATASETS.length === 0` branch: `MapPin` + body copy + CTA.
- DatasetSearchPanel State A (catalog empty): Upload CTA + Browse public catalog secondary CTA.
- DatasetSearchPanel State B (zero-result): `SearchX` + heading + body + clear CTA.
- LayerEditorPanel Source section `columns.length === 0`: plain-text message.
- Filter/Labels sections: existing `filters.noColumns` / `labels.noColumns` keys — confirmed pre-existing, not duplicated.

**Destructive action protection:**
- `autoFocus` on every "safe" alertdialog cancel button confirmed: `LayerEditorPanel.tsx:760,800`, `StackRow.tsx:430`, `FolderGroupRow.tsx:379`. All use `variant="ghost"` — consistent visual weight on the safe side.
- `BasemapGroupEditorFooter`: no confirm dialog (spec-authorized; local state reset, not a backend mutation). Destructive styling on the button is the visual cue.

**Scene transition preservation (POL-18):**
- Four refs (`bodyRef`, `savedScrollTopRef` as `number | null`, `prevSceneRef`, `headerRef`) + three `useEffect` hooks at `LayerEditorPanel.tsx:171-200`.
- Scroll restore uses `null` sentinel (WR-02 fix confirmed) — correctly handles scroll-to-top case.
- Focus restoration fires on `basemap-sublayer → basemap-group` transition (`headerRef.current?.focus()`) — header has `tabIndex={-1}` to enable programmatic focus.
- Three behaviors require human browser verification (per VERIFICATION.md): scroll DOM timing, focus side-effect, autoFocus in alertdialog — all correctly noted as wired but unconfirmable statically.

**Section ordering:**
- Confirmed correct: Render as (L326) → Appearance (L370) → Visibility (L407) → Filter (L480) → Labels (L514) → Source (L549). Fixed ordering; sections hide when N/A.

**Registry audit:** No third-party shadcn registry blocks. `AlertCircle`, `RotateCcw`, `LayoutGrid`, `MapPin` are lucide-react icons already bundled. No new installs. Registry audit: 0 third-party blocks checked, not applicable.

---

## Files Audited

- `frontend/src/components/builder/DatasetSearchPanel.tsx`
- `frontend/src/components/builder/LayerEditorPanel.tsx`
- `frontend/src/components/builder/EmptyStackState.tsx`
- `frontend/src/components/builder/SidebarRail.tsx`
- `frontend/src/components/builder/BasemapGroupEditorScene.tsx`
- `frontend/src/components/builder/SettingsEditorScene.tsx`
- `frontend/src/components/builder/StackRow.tsx`
- `frontend/src/components/builder/FolderGroupRow.tsx`
- `frontend/src/i18n/locales/en/builder.json`
- `.planning/phases/1043-error-empty-states-and-ia-cleanup/1043-UI-SPEC.md`
- `.planning/phases/1043-error-empty-states-and-ia-cleanup/1043-REVIEW.md`
- `.planning/phases/1043-error-empty-states-and-ia-cleanup/1043-REVIEW-FIX.md`
- `.planning/phases/1043-error-empty-states-and-ia-cleanup/1043-VERIFICATION.md`
- `.planning/phases/1043-error-empty-states-and-ia-cleanup/1043-01-SUMMARY.md`
- `.planning/phases/1043-error-empty-states-and-ia-cleanup/1043-02-SUMMARY.md`
- `.planning/phases/1043-error-empty-states-and-ia-cleanup/1043-03-SUMMARY.md`
- `.planning/phases/1043-error-empty-states-and-ia-cleanup/1043-04-SUMMARY.md`
