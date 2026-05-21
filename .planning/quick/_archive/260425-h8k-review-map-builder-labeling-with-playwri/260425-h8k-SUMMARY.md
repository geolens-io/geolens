---
quick_id: 260425-h8k
description: Review map builder labeling with Playwright MCP
status: complete
date: 2026-04-25
---

# Map Builder Labeling — QA Review Summary

**Map tested:** Conflict Events 2024 (UCDP GED) — 3 layers (Country Borders, Individual Events, Conflict Heatmap)
**Basemaps tested:** OpenFreeMap Dark, OpenFreeMap Positron

---

## What Works

| Feature | Status | Notes |
|---------|--------|-------|
| Basemap label toggle | ✅ | ON/OFF correctly shows/hides all basemap symbol layers |
| Layer label toggle | ✅ | Enables/disables data labels per layer; icon appears in layer list |
| Column selector | ✅ | Full dropdown of dataset columns; switches label text immediately |
| Font size slider | ✅ | 8–24px range, real-time map update |
| Allow overlap toggle | ✅ | Correctly toggles `text-allow-overlap` — visible density change |
| Placement options | ✅ | Point-only for polygon layers (correct constraint) |
| Anchor & Offset | ✅ | UI present and functional |
| Zoom range sliders | ✅ | Min/Max zoom controls available |
| Text color / Halo color | ✅ | Color picker buttons present (not deeply tested) |
| Text opacity / Halo width | ✅ | Sliders present with correct defaults (100%, 1.5px) |
| Z-ordering on initial load | ✅ | Data labels correctly above basemap labels above data geometries |
| Basemap label toggle across basemaps | ✅ | Toggle state persists when switching basemaps |

---

## Bugs Found

### BUG 1: Data labels fall below basemap labels after basemap switch (HIGH)

**Severity:** High — labels are no longer the top layer after switching basemaps

**Reproduction:**
1. Open any map with data labels enabled
2. Verify z-order is correct (data label is topmost layer)
3. Switch basemap (e.g., Dark → Positron, or back)
4. Inspect layer order — data label is now BELOW all basemap labels

**Layer order on initial load (CORRECT):**
```
[data geometries] → [basemap labels] → [DATA LABEL] (top)
```

**Layer order after basemap switch (BROKEN):**
```
[data geometries] → [DATA LABEL] → [basemap labels] (top)
```

**Root cause:** `frontend/src/components/builder/map-sync.ts:306-312`

```typescript
reorderDataLayers(map, layers, prefix);           // Step 1: data labels → top
reorderBasemapLabels(map, options.showBasemapLabels, sourcePrefix); // Step 2: basemap labels → top (pushes ABOVE data labels!)
```

The two reorder functions are called in the wrong order. `reorderBasemapLabels()` runs AFTER `reorderDataLayers()`, pushing basemap labels above data labels.

**Fix:** Swap the order — call `reorderBasemapLabels()` first, then `reorderDataLayers()`:

```typescript
if (options?.showBasemapLabels !== undefined) {
  reorderBasemapLabels(map, options.showBasemapLabels, sourcePrefix);
}
reorderDataLayers(map, layers, prefix);
```

---

### BUG 2: Heatmap layers allow label toggle when they shouldn't (LOW)

**Severity:** Low — cosmetic/UX issue, no crash

**Reproduction:**
1. Open a map with a heatmap layer
2. Expand layer → Labels tab
3. Toggle labels ON → labels appear on individual points (visually wrong for heatmaps)

**Root cause:** The Labels tab and toggle are shown for all vector layers regardless of render mode. The `syncVectorLayer()` code at `map-sync.ts:194` correctly blocks label creation for heatmaps (`!isHeatmap`), but:
- The UI doesn't disable/hide the toggle for heatmap mode
- The imperative `syncLabelLayer()` path (called from `handleLabelChange`) doesn't check for heatmap mode
- Labels briefly appear until the next full sync cycle hides them

**Fix options:**
- Hide the Labels tab when render mode is heatmap (`layer-capabilities.ts`)
- Or disable the toggle with a message: "Labels are not supported for heatmap layers"

---

### BUG 3: Font glyph 404 errors for data labels (MEDIUM)

**Severity:** Medium — labels render via fallback but with potentially degraded quality

**Console errors:**
```
404: https://tiles.openfreemap.org/fonts/Noto%20Sans%20Regular,Open%20Sans%20Regular,Arial%20Unicode%20MS%20Regular/0-255.pbf
WARNING: Unable to load glyph range 0, 0-255. Rendering codepoint U+XXXX locally instead.
```

**Root cause:** `frontend/src/components/builder/label-layer-utils.ts:35`
```typescript
'text-font': ['Noto Sans Regular', 'Open Sans Regular', 'Arial Unicode MS Regular'],
```

The font stack used for data labels doesn't match fonts available on the basemap's font server. MapLibre constructs the glyph URL by joining the font names with commas, and the resulting path doesn't exist on OpenFreeMap's CDN. MapLibre falls back to local glyph rendering.

**Fix options:**
- Use font names that match the basemap's available fonts (check the basemap style's available font stacks)
- Or serve custom fonts from the GeoLens backend via a `/fonts/{fontstack}/{range}.pbf` endpoint
- Or read the font stack from the basemap style at runtime and use those fonts for data labels

---

## Additional Observations

- **Label indicator icon:** A small icon appears next to the layer name in the layer list when labels are enabled — good UX signal
- **Save state:** The Save button correctly shows unsaved state after label changes
- **Default column:** First alphabetical column is selected by default when enabling labels (e.g., "featurecla") — consider defaulting to "name" if available
- **`circle-11` missing image warning:** Unrelated to labels — a sprite image is missing from the basemap style
- **Type mismatch warning:** "Expected value to be of type number, but found string instead" — likely from a label or style property receiving a string where MapLibre expects a number
