---
phase: 1043-error-empty-states-and-ia-cleanup
reviewed: 2026-05-14T22:30:00Z
depth: standard
files_reviewed: 12
files_reviewed_list:
  - frontend/src/components/builder/BasemapGroupEditorScene.tsx
  - frontend/src/components/builder/BasemapGroupRow.tsx
  - frontend/src/components/builder/DatasetSearchPanel.tsx
  - frontend/src/components/builder/EmptyStackState.tsx
  - frontend/src/components/builder/FolderGroupRow.tsx
  - frontend/src/components/builder/LayerEditorPanel.tsx
  - frontend/src/components/builder/SettingsEditorScene.tsx
  - frontend/src/components/builder/SidebarRail.tsx
  - frontend/src/components/builder/StackRow.tsx
  - frontend/src/components/builder/__tests__/DatasetSearchPanel.test.tsx
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/pages/MapBuilderPage.tsx
findings:
  critical: 3
  warning: 3
  info: 1
  total: 7
status: issues_found
---

# Phase 1043: Code Review Report

**Reviewed:** 2026-05-14T22:30:00Z
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found

## Summary

Phase 1043 closes AUD-09/11/14/18/20/22 and POL-16/17/18 across four plans. The core error-recovery pattern (AUD-11 retry button), empty-state matrix (AUD-22, AUD-14, POL-17), SidebarRail basemap button (AUD-20), destructive footer styling (AUD-18), and scroll/focus preservation (POL-18) are all implemented. The token sweep (7 `hover:bg-accent` sites) and eyebrow migration are complete.

Three blockers are found: AUD-09 was applied incompletely (FolderGroupRow's cancel button was missed), the entire `settings.*` i18n namespace is absent from `builder.json` despite SettingsEditorScene being explicitly in scope, and `BasemapGroupEditorFooter` nests a `<footer>` landmark inside `LayerEditorPanel`'s outer `<footer>`, producing invalid HTML with duplicate same-level landmarks. Three warnings address duplicate ARIA labels, the scroll-restore zero-guard, and an incomplete data-testid contract for the nested footer.

---

## Critical Issues

### CR-01: AUD-09 Incomplete — FolderGroupRow Cancel Button Not Migrated

**File:** `frontend/src/components/builder/FolderGroupRow.tsx:375`
**Issue:** The inline group-delete `alertdialog` confirm uses `variant="secondary"` on the safe "Keep group" button. AUD-09 mandates `variant="ghost"` for all cancel-side buttons in `role="alertdialog"` panels so the visual weight matches the keyboard-safety goal (Enter goes to cancel, not delete). `StackRow` (line 428) and `LayerEditorPanel` (lines 756, 796) were correctly migrated to `variant="ghost"` in Plan 01. `FolderGroupRow` was in scope for Plan 04 (the token sweep) but its dialog button was skipped. The `autoFocus` is already present (line 379) — only the variant is wrong.

Plan 01 SUMMARY says "StackRow inline alertdialog (formerly `variant='outline'`): changed to `variant='ghost'`" but does not list `FolderGroupRow`. The UI-SPEC states "Add `autoFocus` to the safe (non-destructive) button in **every** `role='alertdialog'` in the builder."

**Fix:**
```tsx
// frontend/src/components/builder/FolderGroupRow.tsx:373-382
<Button
  type="button"
  variant="ghost"   // was "secondary"
  className="flex-1"
  onClick={() => setConfirmingDelete(false)}
  // eslint-disable-next-line jsx-a11y/no-autofocus -- focus on safe choice per UI-SPEC accessibility
  autoFocus
>
  {t('folderGroup.deleteConfirmCancel', { defaultValue: 'Keep group' })}
</Button>
```

---

### CR-02: Missing `settings.*` i18n Namespace in builder.json

**File:** `frontend/src/i18n/locales/en/builder.json` (entire file — no `settings` top-level key)
**Issue:** `LayerEditorPanel.tsx` (modified in this phase) uses three `settings.*` keys at lines 233, 289, and 307 (`settings.regionLabel`, `settings.panelTitle`, `settings.closePanel`). `SettingsEditorScene.tsx` (also modified in this phase via the eyebrow migration) uses 19 additional `settings.*` keys (`settings.terrainLabel`, `settings.widgetsLabel`, `settings.projectionLabel`, `settings.terrainActiveHint`, etc.). None of these keys exist as a top-level `"settings"` object in `builder.json`.

All calls fall back to `defaultValue` strings — the UI renders correctly in English — but the Phase 1043 mandate explicitly includes "Close the Phase 1039 audit's missing i18n keys." Phase 1044 owns `de/es/fr` locale fill but cannot translate keys that have no English entry. The `settings.*` namespace must exist in `en/builder.json` for Phase 1044 to proceed without re-opening this file.

Confirmed via Python inspection: `data.get('settings')` is `None`; all 22 `settings.*` lookups return `None`.

**Fix:** Add the `settings` object to `builder.json`. Minimum required keys:

```json
"settings": {
  "regionLabel": "Map settings",
  "panelTitle": "Settings",
  "closePanel": "Close settings",
  "terrainLabel": "TERRAIN",
  "widgetsLabel": "WIDGETS",
  "projectionLabel": "PROJECTION",
  "terrainActiveHint": "{{value}}× exaggeration",
  "terrainInactiveCollapsedHint": "No terrain active",
  "exaggeration": "Exaggeration",
  "terrainExaggerationAria": "Terrain exaggeration",
  "boundTo": "Bound to: {{name}}",
  "terrainInactiveHint": "No terrain layer is active. Switch a DEM layer to Terrain mode to enable global terrain exaggeration.",
  "widgetsEnabledCount": "{{count}} enabled",
  "noWidgets": "No widgets available.",
  "widgetsGroupAria": "Widgets",
  "disableAction": "Disable",
  "enableAction": "Enable",
  "toggleWidget": "{{action}} {{name}} widget",
  "projectionMercator": "Mercator",
  "projectionGlobe": "Globe",
  "projectionAria": "Map projection",
  "globeDisclaimer": "Globe projection is experimental. Some layers may not render correctly."
}
```

---

### CR-03: Nested `<footer>` Landmark in BasemapGroupEditorFooter

**File:** `frontend/src/components/builder/BasemapGroupEditorScene.tsx:253` and `frontend/src/components/builder/LayerEditorPanel.tsx:727`
**Issue:** `BasemapGroupEditorFooter` renders its own `<footer>` element (line 253). `LayerEditorPanel` wraps all footer content — including `sceneFooter` — inside a single outer `<footer>` element (line 727). When `editorScene === 'basemap-group'` and `sceneFooter` is set, the rendered HTML is:

```html
<footer data-testid="layer-editor-footer">   <!-- LayerEditorPanel:727 -->
  <footer data-testid="layer-editor-footer">  <!-- BasemapGroupEditorFooter:253 -->
    ...buttons...
  </footer>
</footer>
```

Nested `<footer>` (contentinfo landmark) elements are invalid HTML5. The inner `<footer>` loses its landmark role per ARIA spec, and the `data-testid="layer-editor-footer"` appears twice in the DOM, breaking any test selector that relies on uniqueness. This was introduced in Phase 1035 and survives into Phase 1043 which modifies both files.

**Fix:** Remove the `<footer>` wrapper from `BasemapGroupEditorFooter` and replace it with a plain `<div>`. The outer `<footer>` in `LayerEditorPanel` provides the semantic wrapping:

```tsx
// frontend/src/components/builder/BasemapGroupEditorScene.tsx:247-268
// Replace <footer ...> with <div> — the outer LayerEditorPanel footer provides the landmark
export function BasemapGroupEditorFooter({
  onResetAppearance,
  onRemoveBasemap,
}: BasemapGroupEditorFooterProps) {
  const { t } = useTranslation('builder');
  return (
    <div className="flex gap-2">  {/* was: <footer data-testid="layer-editor-footer" className="shrink-0 border-t p-3"> */}
      <Button type="button" variant="ghost" className="flex-1" onClick={onResetAppearance}>
        {t('basemapGroup.resetAppearance', { defaultValue: 'Reset appearance' })}
      </Button>
      <Button
        type="button"
        variant="ghost"
        className="flex-1 text-destructive hover:bg-[oklch(0.97_0.02_27)] hover:text-destructive"
        onClick={onRemoveBasemap}
      >
        {t('basemapGroup.removeBasemap', { defaultValue: 'Remove basemap' })}
      </Button>
    </div>
  );
}
```

Also remove the standalone `data-testid="layer-editor-footer"` from `BasemapGroupEditorFooter` since the outer footer already carries that testid. Check `BasemapSublayerEditorFooter` in `BasemapSublayerEditorScene.tsx` for the same pattern and apply the same fix.

---

## Warnings

### WR-01: Duplicate `aria-label` on Two Simultaneous "Browse" Buttons in EmptyStackState

**File:** `frontend/src/components/builder/EmptyStackState.tsx:257` and `frontend/src/components/builder/EmptyStackState.tsx:267`
**Issue:** When `SUGGESTED_DATASETS.length === 0`, both the new starter-help fallback button (line 257) and the persistent "Browse all datasets" button (line 267) are rendered simultaneously with the identical `aria-label="Browse all datasets in the Add Data modal"`. Screen readers present two controls with indistinguishable names, violating WCAG 2.4.6 (Headings and Labels). The visible text differs — "Browse catalog →" vs "Browse all datasets →" — but the programmatic label is the same.

**Fix:** Update the starter-help button's `aria-label` to match its visible text:
```tsx
// EmptyStackState.tsx:255-262 — starter-help fallback button
<button
  type="button"
  aria-label="Browse catalog"  // was: "Browse all datasets in the Add Data modal"
  onClick={() => onOpenAddData()}
  className="text-xs text-primary self-center hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
>
  {t('unifiedStack.browseAllShort', { defaultValue: 'Browse catalog →' })}
</button>
```

---

### WR-02: Scroll Restore Guard Excludes Valid Zero-Scroll Position

**File:** `frontend/src/components/builder/LayerEditorPanel.tsx:188`
**Issue:** The scroll restore effect uses `savedScrollTopRef.current > 0` as its gate:
```tsx
if (bodyRef.current && savedScrollTopRef.current > 0) {
  bodyRef.current.scrollTop = savedScrollTopRef.current;
}
```
This correctly prevents spurious scroll restoration on initial render. However, it also prevents restoring a scroll position of exactly `0` after the user deliberately scrolled back to the top before a scene transition. If a user scrolls to top (scrollTop = 0), navigates to a sublayer scene, and returns, the panel will not restore to top — the browser will instead retain whatever the new scene's scroll position was. This is a minor behavioral inconsistency.

**Fix:** Track whether a scroll has been intentionally saved with a separate boolean ref, or use `null` as the "not yet saved" sentinel instead of `0`:
```tsx
const savedScrollTopRef = useRef<number | null>(null);  // null = "not yet saved"

// Save:
savedScrollTopRef.current = bodyEl.scrollTop;  // saves 0 correctly

// Restore:
if (bodyRef.current && savedScrollTopRef.current !== null) {
  bodyRef.current.scrollTop = savedScrollTopRef.current;
  savedScrollTopRef.current = null;  // consume after restore
}
```

---

### WR-03: `search.added` i18n Value Is `"(added)"` — Inconsistent with UI-SPEC Copy

**File:** `frontend/src/i18n/locales/en/builder.json:394`
**Issue:** The key `search.added` has the value `"(added)"` (with parentheses). `DatasetSearchPanel.tsx` line 489 renders this value inside a `<Badge>` as the "Added" indicator when a dataset is already on the map. The UI-SPEC and all surrounding copy use title-cased label text without parentheses (`"Added"` not `"(added)"`). The parentheses are likely a carry-over from a pre-redesign pattern. This is not new to Phase 1043, but Phase 1043 modified `DatasetSearchPanel.tsx` and `builder.json` — an opportune point to correct it.

**Fix:**
```json
// frontend/src/i18n/locales/en/builder.json:394
"added": "Added"
```

---

## Info

### IN-01: `search.metadata.*` Keys Missing From builder.json (defaultValue-only)

**File:** `frontend/src/i18n/locales/en/builder.json` / `frontend/src/components/builder/DatasetSearchPanel.tsx:157-161`
**Issue:** `DatasetSearchPanel` uses `t('search.metadata.type', ...)`, `t('search.metadata.source', ...)`, `t('search.metadata.count', ...)`, `t('search.metadata.crs', ...)`, and `t('search.metadata.attribution', ...)`. None of these sub-keys exist under `search` in `builder.json` (confirmed: `search.metadata` is `null`). They fall back to `defaultValue`, working correctly in English but untranslatable in Phase 1044. Phase 1043 explicitly touched both the search section of `builder.json` and `DatasetSearchPanel.tsx`, making this an in-scope omission.

**Fix:** Add the `metadata` sub-object under `search` in `builder.json`:
```json
"metadata": {
  "type": "Type",
  "source": "Source",
  "count": "Count",
  "crs": "CRS",
  "attribution": "Attribution"
}
```

Also add `search.basemap`, `search.inUse`, `search.anotherRendering`, `search.swap`, `search.importData`, `search.filters`, `search.previewAlt`, `search.previewUnavailable`, `search.allTypes`, `search.vector`, `search.raster` which are all referenced via `t()` but absent from the file.

---

_Reviewed: 2026-05-14T22:30:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
