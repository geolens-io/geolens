---
phase: 1059-basemap-sublayer-editor-path-b-fix
reviewed: 2026-05-20T00:00:00Z
depth: standard
files_reviewed: 14
files_reviewed_list:
  - backend/app/modules/catalog/maps/schemas.py
  - backend/tests/test_basemap_sublayer_overrides.py
  - frontend/src/types/api.ts
  - frontend/src/lib/basemap-utils.ts
  - frontend/src/lib/builder/basemap-style-mutation.ts
  - frontend/src/lib/builder/__tests__/basemap-style-mutation.test.ts
  - frontend/src/components/builder/BuilderMap.tsx
  - frontend/src/components/viewer/ViewerMap.tsx
  - frontend/src/components/builder/BasemapSublayerEditorScene.tsx
  - frontend/src/components/builder/__tests__/BasemapSublayerEditorScene.test.tsx
  - frontend/src/components/viewer/__tests__/ViewerMap.basemap-config.test.tsx
  - frontend/src/components/builder/__tests__/sublayer-overrides.round-trip.test.ts
  - frontend/src/pages/MapBuilderPage.tsx
  - frontend/src/i18n/locales/en/builder.json
findings:
  critical: 1
  warning: 2
  info: 2
  total: 5
status: clean
fixes_applied_at: 2026-05-20T00:28:00Z
---

# Phase 1059: Code Review Report

**Reviewed:** 2026-05-20
**Depth:** standard
**Files Reviewed:** 14
**Status:** issues_found

## Summary

Phase 1059 restores the basemap sublayer editor controls (stroke/casing/zoom) with real persistence through a new `SublayerOverride` Pydantic model and `MapBasemapConfig.sublayer_overrides` jsonb field. The backend schema work is correct and well-tested. The `applySublayerOverrides` helper is sound and its idle-retry pattern is correctly implemented. The i18n parity across all four locales is complete.

However, there is a critical wiring defect in `MapBuilderPage.tsx`: the sublayer IDs stored in `sublayer_overrides` use the `'basemap:roads'`/`'basemap:labels'` namespaced format from the UI routing layer, while `SUBLAYER_CLASSIFIERS` expects the bare semantic IDs `'road'`/`'label'`/etc. as documented in `KnownSublayerId`. As a result, every override written by the UI is stored under an unknown key and `applySublayerOverrides` silently no-ops on classifier lookup — the entire feature produces zero visual effect in production despite all unit tests passing (the unit tests use the correct bare keys).

---

## Critical Issues

### CR-01: Sublayer ID format mismatch — overrides stored under wrong keys, zero visual effect

**File:** `frontend/src/pages/MapBuilderPage.tsx:863-878`

**Issue:** The `basemapGroup.sublayers` array uses namespaced IDs (`'basemap:roads'`, `'basemap:labels'`, `'basemap:buildings'`, `'basemap:boundaries'`) for expanded-layer routing. When `updateSublayerOverride(sublayer.id, ...)` is called, `sublayer.id` carries this namespaced format, so `basemap_config.sublayer_overrides` is saved as:

```json
{ "basemap:roads": { "stroke_color": "#ff0000" } }
```

`applySublayerOverrides` then looks up `SUBLAYER_CLASSIFIERS['basemap:roads']` which is `undefined`, hits the `if (!classifier) continue;` guard, and skips every sublayer. `SUBLAYER_CLASSIFIERS` only has keys `'road'`, `'boundary'`, `'building'`, `'label'` — exactly matching `KnownSublayerId`.

The backend stores whatever key string it receives (opaque per D-01), so the wrong-keyed payload round-trips cleanly. All unit tests pass because they call `applySublayerOverrides` directly with `{ road: ... }` (correct keys), never going through the production `MapBuilderPage` path.

The same defect applies to ViewerMap for shared/embed links: data loaded from the API carries `'basemap:roads'` keys, which ViewerMap's `applySublayerOverrides` call also silently ignores.

**Fix:** Strip or transform the `'basemap:'` prefix to the bare semantic ID before writing to `sublayer_overrides`. The cleanest approach is a mapping constant at the `updateSublayerOverride` call sites:

```typescript
// Add near the updateSublayerOverride helper (MapBuilderPage.tsx ~line 481)
const SUBLAYER_ID_OVERRIDE_KEY: Record<string, string> = {
  'basemap:roads': 'road',
  'basemap:labels': 'label',
  'basemap:buildings': 'building',
  'basemap:boundaries': 'boundary',
};

const updateSublayerOverride = useCallback(
  (sublayerId: string, field: keyof MapSublayerOverride, value: string | number | null) => {
    const overrideKey = SUBLAYER_ID_OVERRIDE_KEY[sublayerId] ?? sublayerId;
    layers.setBasemapConfig((prev) => {
      const currentBc = prev ?? DEFAULT_BASEMAP_CONFIG;
      const currentOverrides = currentBc.sublayer_overrides ?? {};
      const currentOverride: MapSublayerOverride = currentOverrides[overrideKey] ?? {};
      // ... rest unchanged, using overrideKey instead of sublayerId
    });
  },
  [layers],
);
```

Apply the same transform in the `onResetSublayer` callback (line ~886) which also uses `sublayer.id` directly as the `sublayer_overrides` key to delete.

---

## Warnings

### WR-01: `max_zoom` helper fallback (24) does not match UI default display (22)

**File:** `frontend/src/lib/builder/basemap-style-mutation.ts:126`

**Issue:** When a user sets only `min_zoom` (e.g., to 8) but leaves `max_zoom` unset, `applySublayerOverrides` calls `setLayerZoomRange(layerId, 8, 24)` because `override.max_zoom ?? 24` defaults to 24. The UI and `MapBuilderPage` both display/pass `max_zoom ?? 22` as the visual default. A user who sets `min_zoom=8` without touching `max_zoom` will see the UI show `22` but the actual MapLibre range becomes `[8, 24]` — a two-zoom-level discrepancy that could expose layers at zooms the user didn't intend.

**Fix:** Align the helper's null-fallback with the UI default:

```typescript
// basemap-style-mutation.ts:125-126
const minZoom = override.min_zoom ?? 0;
const maxZoom = override.max_zoom ?? 22;  // match UI default, not MapLibre max
```

Or, more defensively, only call `setLayerZoomRange` when both fields are non-null. Since partial zoom overrides are ambiguous by design, the caller could avoid writing a one-sided zoom entry.

### WR-02: No cross-field validation that `min_zoom <= max_zoom`

**File:** `backend/app/modules/catalog/maps/schemas.py:227-237`

**Issue:** `SublayerOverride` validates each zoom field independently (`ge=0, le=24`) but has no constraint that `min_zoom <= max_zoom`. A payload with `{"min_zoom": 20, "max_zoom": 5}` passes backend validation and reaches `setLayerZoomRange(layerId, 20, 5)`. MapLibre's behavior with an inverted zoom range is undefined and version-dependent; in practice the layer becomes permanently invisible. `safeSetZoomRange` catches any thrown error but cannot restore visibility — the layer stays hidden until the user corrects the values and resaves.

**Fix:** Add a `@model_validator` to `SublayerOverride`:

```python
@model_validator(mode='after')
def _validate_zoom_order(self) -> 'SublayerOverride':
    if self.min_zoom is not None and self.max_zoom is not None:
        if self.min_zoom > self.max_zoom:
            raise ValueError(
                f'min_zoom ({self.min_zoom}) must be <= max_zoom ({self.max_zoom})'
            )
    return self
```

---

## Info

### IN-01: Test name `applies_opacity_multiplicatively_over_layer_type_symbol` is misleading

**File:** `frontend/src/lib/builder/__tests__/basemap-style-mutation.test.ts:167`

**Issue:** The test name implies the helper composes (multiplies) opacity values, but the implementation assigns `override.opacity` absolutely — `map.setPaintProperty(layerId, 'text-opacity', 0.5)`. The test correctly asserts the absolute assignment. The word "multiplicatively" in the name implies behavior that doesn't exist and could mislead future maintainers into thinking there's a composition step.

**Fix:** Rename to `applies_per_sublayer_opacity_to_symbol_layer_text_and_icon` or similar.

### IN-02: `SublayerOverride.opacity` backend field has no UI write path in this phase

**File:** `backend/app/modules/catalog/maps/schemas.py:239-247` / `frontend/src/pages/MapBuilderPage.tsx:473-479`

**Issue:** `SublayerOverride.opacity` is defined, validated, and tested on the backend, and `applySublayerOverrides` correctly applies it when present. However, `MapBuilderPage`'s opacity slider writes to `sublayerState` (in-memory only, behind a `TODO(BUILDER-SUBLAYER-PERSIST)`) and never calls `updateSublayerOverride(..., 'opacity', ...)`. Per D-09 ("OPACITY — existing slider untouched"), this is intentional deferral — but future readers may be puzzled why the field exists with no production writer. The TODO comment at line 271 documents the intent.

**Fix (informational):** Add a comment to the `SublayerOverride.opacity` field doc that it is populated via API or future Phase milestone; the current UI opacity slider routes through the legacy `sublayerState` path.

---

_Reviewed: 2026-05-20_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

---

## Fixes Applied (inline, 2026-05-20)

All 5 findings fixed inline before Phase 1060 per `feedback_review_findings_inline.md`.

| Finding | Status | Commit | Files Modified |
|---------|--------|--------|----------------|
| CR-01 | fixed | `baabb411` | `frontend/src/pages/MapBuilderPage.tsx` |
| WR-01 | fixed | `05f6bc5c` | `frontend/src/lib/builder/basemap-style-mutation.ts`, `frontend/src/lib/builder/__tests__/basemap-style-mutation.test.ts` |
| WR-02 | fixed | `57fbb4a7` | `backend/app/modules/catalog/maps/schemas.py`, `backend/tests/test_basemap_sublayer_overrides.py` |
| IN-01 | fixed | `d18735b0` | `frontend/src/lib/builder/__tests__/basemap-style-mutation.test.ts` |
| IN-02 | fixed | `cbfddcb1` | `backend/app/modules/catalog/maps/schemas.py` |

**Post-fix verification:**
- `npx tsc --noEmit`: 0 errors
- `npm test basemap-style-mutation`: 19/19 pass
- `npm test sublayer-overrides.round-trip`: 7/7 pass
- `pytest tests/test_basemap_sublayer_overrides.py`: 26/26 pass (14 original + 4 new WR-02)
- `npm run test:i18n`: 2/2 pass

**Deviations from suggested code:**
- CR-01: `SUBLAYER_ID_OVERRIDE_KEY` typed as `Record<string, string>` (not `Record<string, KnownSublayerId>`) since the TypeScript type `KnownSublayerId` was not exported from `basemap-utils.ts` and narrowing to that union was not required for correctness. The runtime behavior is identical.
- WR-01: Chose "align to 22" variant (not the "skip setLayerZoomRange for one-sided" variant) because it produces a deterministic range when one side is unset, matching the user's expectation from the UI display. The test was updated to assert 22.

_Fixed: 2026-05-20_
_Fixer: Claude (gsd-code-fixer)_
