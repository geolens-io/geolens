---
phase: 1141-fill-pattern-editor-control
reviewed: 2026-05-28T00:00:00Z
depth: deep
files_reviewed: 12
files_reviewed_list:
  - frontend/src/components/builder/layer-adapters/fill-pattern-images.ts
  - frontend/src/components/builder/FillPatternPicker.tsx
  - frontend/src/components/builder/layer-adapters/fill-adapter.ts
  - frontend/src/components/builder/LayerStyleEditor/FillEditor.tsx
  - frontend/src/components/builder/layer-adapters/__tests__/fill-pattern-images.test.ts
  - frontend/src/components/builder/__tests__/FillPatternPicker.test.tsx
  - frontend/src/components/builder/LayerStyleEditor/__tests__/FillEditor.test.tsx
  - frontend/src/components/builder/__tests__/layer-adapters.test.ts
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/i18n/locales/de/builder.json
  - frontend/src/i18n/locales/es/builder.json
  - frontend/src/i18n/locales/fr/builder.json
findings:
  critical: 0
  warning: 2
  info: 1
  total: 3
status: fixed
---

# Phase 1141: Code Review Report

**Reviewed:** 2026-05-28
**Depth:** deep (cross-file analysis, maplibre type verification, pixel-level logic trace)
**Files Reviewed:** 12
**Status:** issues_found

## Summary

The phase delivers a correct, well-structured fill-pattern editor control. The registrar mirrors `ensureArrowImage` faithfully, the clear/restore path through `syncOwnedPaintProperties` with `clearMissing=true` works correctly, and the FillEditor gate (`fillEnabled && isPolygon`) is accurate. i18n parity is clean across all four locales. The `pixelRatio` omission in `addImage` is NOT a bug — maplibre-gl v5 defaults `pixelRatio` to 1 when the options argument is absent (confirmed in `maplibre-gl/src/ui/map.ts:2561`).

Two substantive defects are present:

1. **`makeCrosshatch` and `makeGrid` produce byte-for-byte identical pixel data** — both use the condition `(y % 4 === 0 || x % 4 === 0)`. The catalog effectively contains only 4 distinct patterns. The CSS swatch previews for these two patterns are also identical, so the user sees two indistinguishable swatches. No test guards uniqueness across pattern outputs.

2. **The `addLayers` test asserting `addImage` called exactly 5 times is fragile** — it will silently break if the number of built-in patterns ever changes, because the assertion hardcodes `5` rather than `FILL_PATTERN_IDS.length`.

---

## Warnings

### WR-01: `makeCrosshatch` and `makeGrid` are byte-for-byte identical

**File:** `frontend/src/components/builder/layer-adapters/fill-pattern-images.ts:41-50` and `81-91`

**Issue:** Both functions use the condition `y % 4 === 0 || x % 4 === 0` (operand order differs but `||` is commutative). Node.js verification confirms the two `Uint8ClampedArray` outputs are equal for every byte. As a result the pattern catalog exposes only 4 visually distinct patterns, not 5, and the two swatches for "Crosshatch" and "Grid" are indistinguishable to the user (confirmed: the CSS `patternPreviewStyle` cases for `geolens-fill-crosshatch` and `geolens-fill-grid` in `FillPatternPicker.tsx:29-54` are also identical strings).

The conventional meaning of "crosshatch" is diagonal lines crossing at 45 degrees (like `/` and `\` overlaid), distinct from a straight H+V grid. `makeHatch` already occupies the straight-horizontal-only slot; `makeDiagonal` covers 45-degree single-direction; a true crosshatch should combine `/` and `\` diagonals.

**Fix:** Replace `makeCrosshatch` with a true diagonal crosshatch (45° + 135° lines), and update its CSS preview:

```typescript
/** True diagonal crosshatch: 45-degree lines in both directions. */
function makeCrosshatch(): { width: number; height: number; data: Uint8ClampedArray } {
  const data = new Uint8ClampedArray(TILE * TILE * 4);
  for (let y = 0; y < TILE; y++) {
    for (let x = 0; x < TILE; x++) {
      // Forward diagonal (/) and backward diagonal (\), spaced every 4 pixels
      if ((x + y) % 4 === 0 || (x - y + TILE * 4) % 4 === 0) {
        setPixel(data, x, y, 80, 80, 80, 255);
      }
    }
  }
  return { width: TILE, height: TILE, data };
}
```

Update `patternPreviewStyle` in `FillPatternPicker.tsx`:

```typescript
case 'geolens-fill-crosshatch':
  return {
    backgroundImage: `
      repeating-linear-gradient(45deg, #6b7280 0px, #6b7280 1px, transparent 1px, transparent 4px),
      repeating-linear-gradient(-45deg, #6b7280 0px, #6b7280 1px, transparent 1px, transparent 4px)
    `,
    backgroundSize: '5.66px 5.66px',
  };
```

Add a pixel-uniqueness regression test to `fill-pattern-images.test.ts`:

```typescript
it('all patterns produce distinct pixel data', () => {
  const images = FILL_PATTERN_IDS.map((id) => makeFillPatternImage(id));
  for (let i = 0; i < images.length; i++) {
    for (let j = i + 1; j < images.length; j++) {
      const same = images[i].data.every((v, k) => v === images[j].data[k]);
      expect(same, `patterns[${i}] and patterns[${j}] are identical`).toBe(false);
    }
  }
});
```

---

### WR-02: Hardcoded `5` in `addLayers` integration test is not future-proof

**File:** `frontend/src/components/builder/__tests__/layer-adapters.test.ts:1384`

**Issue:** The test asserts `expect(map.addImage).toHaveBeenCalledTimes(5)`. If `FILL_PATTERN_IDS` is ever extended (e.g., to add a brick or stipple pattern), this test silently fails to enforce the new count. The intent is "addImage called once per id", but the coupling to a magic literal `5` makes the test lie about its invariant. The same literal appears in the `syncPaint` test at line 1402.

**Fix:**

```typescript
// line 1384
expect(map.addImage).toHaveBeenCalledTimes(FILL_PATTERN_IDS.length);

// line 1402
expect(map.addImage).toHaveBeenCalledTimes(FILL_PATTERN_IDS.length);
```

`FILL_PATTERN_IDS` is already imported in the test file (it appears in the `fill-pattern-images.test.ts` import and is available via the `fill-pattern-images` module already transitively imported through `fill-adapter`). Add the direct import at the top of `layer-adapters.test.ts`:

```typescript
import { FILL_PATTERN_IDS } from '../layer-adapters/fill-pattern-images';
```

---

## Info

### IN-01: `FillPatternId` type is exported but not consumed

**File:** `frontend/src/components/builder/layer-adapters/fill-pattern-images.ts:12`

**Issue:** `export type FillPatternId` is defined and exported but no other file imports it. Under `noUnusedLocals: true` in tsconfig this would normally flag, but exported symbols are excluded from that rule. The type is harmless but adds API surface that may cause future confusion about whether callers are expected to use it.

**Fix:** Either remove it (if it has no planned consumers in this phase) or annotate with a comment indicating its intended use:

```typescript
/** Narrowed string type for programmatic pattern-id validation. Consumers may use this
 *  with `includes`-style guards: `FILL_PATTERN_IDS.includes(value as FillPatternId)`. */
export type FillPatternId = typeof FILL_PATTERN_IDS[number];
```

---

_Reviewed: 2026-05-28_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
