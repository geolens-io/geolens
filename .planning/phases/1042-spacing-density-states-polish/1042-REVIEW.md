---
phase: 1042-spacing-density-states-polish
reviewed: 2026-05-14T18:00:00Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - frontend/src/index.css
  - frontend/src/components/builder/BasemapGroupEditorScene.tsx
  - frontend/src/components/builder/BasemapGroupRow.tsx
  - frontend/src/components/builder/BasemapSublayerEditorScene.tsx
  - frontend/src/components/builder/BulkActionBar.tsx
  - frontend/src/components/builder/DatasetSearchPanel.tsx
  - frontend/src/components/builder/DEMEditorScene.tsx
  - frontend/src/components/builder/EmptyStackState.tsx
  - frontend/src/components/builder/FolderGroupRow.tsx
  - frontend/src/components/builder/LayerEditorPanel.tsx
  - frontend/src/components/builder/SettingsEditorScene.tsx
  - frontend/src/components/builder/SidebarRail.tsx
  - frontend/src/components/builder/StackRow.tsx
  - frontend/src/components/builder/UnifiedStackPanel.tsx
  - frontend/src/components/builder/hooks/use-builder-layers.ts
  - frontend/src/i18n/locales/en/builder.json
  - .planning/phases/1042-spacing-density-states-polish/1042-CONTEXT.md
  - .planning/phases/1042-spacing-density-states-polish/1042-UI-SPEC.md
findings:
  critical: 1
  warning: 4
  info: 4
  total: 9
status: issues_found
---

# Phase 1042: Code Review Report

**Reviewed:** 2026-05-14T18:00:00Z
**Depth:** standard
**Files Reviewed:** 18
**Status:** issues_found

## Summary

Phase 1042 is a coordinated spacing/density/typography/state/loading-affordance polish pass across the Map Builder surfaces. The implementation addresses 18 audit findings and 9 carry-over items. Code quality is generally high — the motion token additions, BulkActionBar mount animation, skeleton loading, and i18n dedup are all correctly implemented.

One critical bug is present: the CSS `[data-group-drop-target="true"] + [id^="folder-group-children"]` adjacent-sibling selector never matches due to a DOM nesting mismatch, silently causing the folder group-children wash to be a permanent no-op regardless of drag state. Four warnings cover incomplete motion token adoption (three scene files still use `duration-150`), a cursor-grab click-interference issue, a `setTimeout` scope gap in freshLayerId cleanup, and a `SidebarRail` hover token that was not migrated per AUD-21. Four informational items cover minor i18n completeness gaps, a missing `basemapGroup.toggleExpand` i18n key, and dead prop documentation.

---

## Critical Issues

### CR-01: Group-children wash CSS selector never matches — permanent no-op

**File:** `frontend/src/index.css:558-562`

**Issue:** The CSS rule for the folder group-children drop-target wash uses two selectors:

```css
[data-group-drop-target="true"] + [id^="folder-group-children"],
[data-group-drop-target="true"] [id^="folder-group-children"]
```

The `+` (adjacent sibling) combinator cannot match because `folder-group-children` is a sibling of the `FolderGroupRowWrapper` component (which contains the `data-group-drop-target` div), not a sibling of the `data-group-drop-target` div itself.

The actual DOM structure in `UnifiedStackPanel.tsx` lines 889–914:
```
<div key={layer.id}>                          ← outer wrapper
  <FolderGroupRowWrapper>
    <div data-group-drop-target="true">       ← drop target div (inside FolderGroupRowWrapper)
      <FolderGroupRow ... />
    </div>
  </FolderGroupRowWrapper>                    ← FolderGroupRowWrapper ends here
  {expanded && <div id="folder-group-children-...">}  ← sibling of FolderGroupRowWrapper, NOT of data-group-drop-target
</div>
```

The `data-group-drop-target` div is the sole child of `FolderGroupRowWrapper`'s return. The `folder-group-children` div is a sibling of the entire `FolderGroupRowWrapper` output, not a sibling of the `data-group-drop-target` div. The `+` combinator is therefore structurally impossible to satisfy. The descendant combinator (second rule) also cannot match because `folder-group-children` is outside the `data-group-drop-target` subtree entirely.

The wash feature (AUD carry-over from Phase 1040) never applies at runtime.

**Fix:** Add `data-group-drop-target` to the outer `<div key={layer.id}>` wrapper in `UnifiedStackPanel.tsx` (line 889), or restructure the CSS selector to target a common ancestor. The simplest fix is to hoist the attribute to the keyed wrapper:

In `UnifiedStackPanel.tsx` around line 889:
```tsx
<div
  key={layer.id}
  data-group-drop-target={/* pass isOver from FolderGroupRowWrapper up */}
>
  <FolderGroupRowWrapper ... />
  {expanded && <div id={`folder-group-children-${layer.id}`} ...>...</div>}
</div>
```

Alternatively, restructure the CSS to use a class on a common ancestor, or use JavaScript to set the attribute on the outer wrapper when `isOver && isCatalogDragActive`.

A stop-gap CSS-only fix (no JS change required) is to match on the outer keyed wrapper by adding a `data-folder-group` attribute to it and applying the wash to its child with `[data-folder-group][data-group-drop-target] + [id^="folder-group-children"]` — but this still requires the attribute to be on the right element. The correct surgical fix is to propagate `isOver && isCatalogDragActive` out of `FolderGroupRowWrapper` to the parent `div key={layer.id}`.

---

## Warnings

### WR-01: `SettingsEditorScene` and `BasemapSublayerEditorScene` collapsible carets still use `duration-150` — AUD-07 incomplete

**File:** `frontend/src/components/builder/SettingsEditorScene.tsx:101,152,210` and `frontend/src/components/builder/BasemapSublayerEditorScene.tsx:288`

**Issue:** AUD-07 requires all collapsible caret elements to use `duration-[--motion-fast]` after the motion tokens land in AUD-08. Both files were listed in the UI-SPEC Component Inventory (AUD-16 targets) but were not updated for AUD-07. All three `ChevronRight` carets in `SettingsEditorScene` and the single caret in `BasemapSublayerEditorScene` still use `duration-150`:

```tsx
// SettingsEditorScene.tsx:101, 152, 210 — same pattern in all 3:
className={cn('h-4 w-4 shrink-0 transition-transform duration-150', terrainOpen && 'rotate-90')}
```

```tsx
// BasemapSublayerEditorScene.tsx:288:
className={cn('h-4 w-4 shrink-0 transition-transform duration-150', resetOpen && 'rotate-90')}
```

`LayerEditorPanel.tsx` (also AUD-07 scope) correctly uses `duration-[--motion-fast]`. The inconsistency means that section carets inside Settings and BasemapSublayerEditorScene will animate at 150ms hardcoded while other carets animate via the CSS variable. If `--motion-fast` is ever changed, these two files will drift.

**Fix:** Replace `duration-150` with `duration-[--motion-fast]` in the four affected `ChevronRight` className strings:

```tsx
// SettingsEditorScene.tsx — apply to all 3 ChevronRight carets:
className={cn('h-4 w-4 shrink-0 transition-transform duration-[--motion-fast]', terrainOpen && 'rotate-90')}

// BasemapSublayerEditorScene.tsx:288:
className={cn('h-4 w-4 shrink-0 transition-transform duration-[--motion-fast]', resetOpen && 'rotate-90')}
```

---

### WR-02: `cursor-grab` on `DraggableDatasetRow` outer div interferes with the expand/collapse button click

**File:** `frontend/src/components/builder/DatasetSearchPanel.tsx:232-237`

**Issue:** The 1040 carry-over fix adds `cursor-grab` to the entire outer `<div ref={setNodeRef}>` of `DraggableDatasetRow`. This div wraps both the grip handle button and the expand/collapse chevron button. The `cursor-grab` cursor applied to the outer div covers the expand chevron button as well, giving users the visual signal that clicking the expand button will initiate a drag. The chevron button does not stop the grab cursor because CSS `cursor` on a child element is overridden by an explicit `cursor-grab` on a parent when the parent has higher specificity in the cascade.

In practice, the expand button works correctly (it calls `setExpandedRowId`), but the grab cursor on it is misleading UX and may cause users to hesitate before clicking to expand a row.

The `DraggableBasemapRow` at line 322 has the same pattern.

**Fix:** Scope `cursor-grab` to the inner content div (line 239) rather than the outermost `setNodeRef` div. The `setNodeRef` div must be present for DnD registration but does not need the grab cursor — only the content area below the grip handle should convey draggability. Alternatively, apply `cursor-default` to the expand button explicitly:

```tsx
// Option A: move cursor-grab to inner content div
<div ref={setNodeRef} className={cn('group/row rounded-md border border-border/60 bg-background', isDragging && 'opacity-40 bg-[var(--surface-2)]')}>
  <div className={cn('flex items-center gap-2 px-2 py-2', !isDragging && 'cursor-grab', isDragging && 'cursor-grabbing')}>
    ...
  </div>
</div>

// Option B: add cursor-default to the expand chevron button:
<button ... className="... cursor-default">
```

---

### WR-03: `freshLayerId` setTimeout ref cleared on unmount but not on component re-mount / `handleAddDataset` re-invocation race

**File:** `frontend/src/components/builder/hooks/use-builder-layers.ts:652-656`

**Issue:** The `freshLayerTimeoutRef` cleanup on unmount (lines 130-132) correctly calls `clearTimeout`. However, when `handleAddDataset` is called while a prior `freshLayerId` timeout is still pending, the code does clear the old timer before setting a new one (line 653: `if (freshLayerTimeoutRef.current) clearTimeout(...)`). This part is correct.

The gap is that `freshLayerTimeoutRef.current` is set to the new `setTimeout` return value (line 655), but the timeout callback closes over `setFreshLayerId` only — it does not clear `freshLayerTimeoutRef.current` itself when it fires. After 200ms, `freshLayerTimeoutRef.current` still holds a stale (already-fired) timer ID. If `handleAddDataset` is called again after the 200ms window, the `if (freshLayerTimeoutRef.current) clearTimeout(...)` guard at line 653 calls `clearTimeout` on the stale fired ID (a no-op, but incorrect). More importantly, for correctness, the ref should be nulled out when the timeout fires so that any future guard checks see `null`.

```ts
// line 655 — current code:
freshLayerTimeoutRef.current = setTimeout(() => setFreshLayerId(null), 200);
```

**Fix:** Clear the ref when the timeout fires:

```ts
freshLayerTimeoutRef.current = setTimeout(() => {
  setFreshLayerId(null);
  freshLayerTimeoutRef.current = null;
}, 200);
```

This is a robustness fix, not a correctness crash — current behavior is functionally correct for normal usage but the stale ref is a latent hazard.

---

### WR-04: `SidebarRail` Settings button hover still uses `hover:bg-accent` — AUD-21 not applied

**File:** `frontend/src/components/builder/SidebarRail.tsx:72`

**Issue:** AUD-21 specifies changing all rail button hover states from `hover:bg-accent` to `hover:bg-[var(--surface-2)]` to match StackRow token consistency. The layer icon buttons in `SidebarRail` (lines 118-123) were correctly updated to `hover:bg-[var(--surface-2)]`. However, the Settings button at line 72 still uses `hover:bg-accent`:

```tsx
// SidebarRail.tsx:72 — not updated
: 'text-muted-foreground hover:bg-accent hover:text-foreground',
```

`--accent` and `--surface-2` resolve to nearly identical computed values in the current palette, so this is visually invisible in production. However, the AUD-21 fix is explicitly about token-level consistency, and this occurrence was missed.

**Fix:**
```tsx
: 'text-muted-foreground hover:bg-[var(--surface-2)] hover:text-foreground',
```

---

## Info

### IN-01: `basemapGroup.toggleExpand` i18n key referenced in `BasemapGroupRow` but absent from `builder.json`

**File:** `frontend/src/components/builder/BasemapGroupRow.tsx:107`

**Issue:** Line 107 calls `t('basemapGroup.toggleExpand', { defaultValue: 'Toggle basemap group' })`. The `basemapGroup` namespace in `builder.json` (lines 802–812) does not contain a `toggleExpand` key. i18next will fall through to the `defaultValue` so users see correct text, but the key is absent from the translation file. Phase 1044 owns locale fill; this is a pre-existing gap that was not addressed by the dedup pass.

**Fix:** Add `"toggleExpand": "Toggle basemap group"` to the `basemapGroup` block in `frontend/src/i18n/locales/en/builder.json`.

---

### IN-02: `basemapSublayer.strokeColor` / `strokeWidth` / `casingColor` / `casingWidth` aria label keys missing from `builder.json`

**File:** `frontend/src/components/builder/BasemapSublayerEditorScene.tsx:147,159,175,188`

**Issue:** Four `t(...)` calls reference keys `basemapSublayer.strokeColor`, `basemapSublayer.strokeWidth`, `basemapSublayer.casingColor`, `basemapSublayer.casingWidth` (or their label variants). The `basemapSublayer` block in `builder.json` (lines 813–828) does not contain these keys. Like IN-01, i18next falls through to `defaultValue`, so there is no visible regression, but the locale file is incomplete for future translations.

**Fix:** Add the missing keys to the `basemapSublayer` block:
```json
"strokeColor": "Color",
"strokeWidth": "Width",
"strokeWidthLabel": "Stroke width",
"casingColor": "Casing color",
"casingWidth": "Casing width",
"casingWidthLabel": "Casing width"
```

---

### IN-03: `SuggestCard` has redundant `role="button"` on `<button>` elements

**File:** `frontend/src/components/builder/EmptyStackState.tsx:93,114`

**Issue:** Lines 93 and 114 have `<button type="button" role="button" ...>`. The `role="button"` attribute on a native `<button>` element is redundant — the implicit ARIA role of `<button>` is already `button`. This is harmless but adds noise.

**Fix:** Remove `role="button"` from both `<button>` elements in `SuggestCard`.

---

### IN-04: `onReorder` prop silently unused in `UnifiedStackPanel` — missing documentation

**File:** `frontend/src/components/builder/UnifiedStackPanel.tsx:593-594`

**Issue:** The comment at line 593 correctly documents that `onReorder` is intentionally not destructured because drag-end was lifted to `MapBuilderPage`. However, the prop is still declared in `UnifiedStackPanelProps` (line 76) with no deprecation marker. Future maintainers may add back a destructure not knowing the intent. This is pre-existing but was not cleaned up during this phase.

**Fix:** Add a JSDoc comment to the `onReorder` prop in the interface explaining it is present only for call-site backward compatibility and is not used by the component body:

```tsx
/** @deprecated Drag-end is handled by the lifted DndContext in MapBuilderPage.
 *  This prop remains in the interface only for backward-compat. Do not destructure. */
onReorder: (layers: MapLayerResponse[]) => void;
```

---

_Reviewed: 2026-05-14T18:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
