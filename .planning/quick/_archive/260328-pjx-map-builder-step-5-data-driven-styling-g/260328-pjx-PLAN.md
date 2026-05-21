---
phase: 260328-pjx
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/types/api.ts
  - frontend/src/lib/color-ramps.ts
  - frontend/src/components/builder/DataDrivenStyleEditor.tsx
  - frontend/src/components/builder/LayerStyleEditor.tsx
  - frontend/src/components/widgets/builtin/LegendWidget.tsx
  - frontend/src/components/builder/__tests__/DataDrivenStyleEditor.test.tsx
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/i18n/locales/de/builder.json
  - frontend/src/i18n/locales/es/builder.json
  - frontend/src/i18n/locales/fr/builder.json
autonomous: true
requirements: [STEP5-SIZE]

must_haves:
  truths:
    - "Point layers can apply graduated radius styling to a numeric column"
    - "Line layers can apply graduated width styling to a numeric column"
    - "Polygon layers show only color data-driven styling (no radius/width option)"
    - "Existing color-only data-driven styling continues to work unchanged"
    - "Legend widget displays graduated size entries with scaled circles or line-weight indicators"
    - "Clearing data-driven style resets both color and size paint properties"
    - "StyleConfig with no target field defaults to color behavior (backward compat)"
  artifacts:
    - path: "frontend/src/types/api.ts"
      provides: "Extended StyleConfig with target, sizes, sizeRange"
      contains: "target?: 'color' | 'radius' | 'width'"
    - path: "frontend/src/lib/color-ramps.ts"
      provides: "buildGraduatedSizeExpression and getSizeProperty"
      exports: ["buildGraduatedSizeExpression", "getSizeProperty", "getColorProperty"]
    - path: "frontend/src/components/builder/DataDrivenStyleEditor.tsx"
      provides: "Target selector UI, size expression generation"
      min_lines: 300
    - path: "frontend/src/components/widgets/builtin/LegendWidget.tsx"
      provides: "Size legend entries for graduated radius/width"
      min_lines: 80
  key_links:
    - from: "frontend/src/components/builder/DataDrivenStyleEditor.tsx"
      to: "frontend/src/lib/color-ramps.ts"
      via: "import buildGraduatedSizeExpression, getSizeProperty"
      pattern: "buildGraduatedSizeExpression|getSizeProperty"
    - from: "frontend/src/components/builder/DataDrivenStyleEditor.tsx"
      to: "frontend/src/types/api.ts"
      via: "import StyleConfig with target field"
      pattern: "target.*color.*radius.*width"
    - from: "frontend/src/components/builder/LayerStyleEditor.tsx"
      to: "frontend/src/components/builder/DataDrivenStyleEditor.tsx"
      via: "isDataDriven indicator includes target awareness"
      pattern: "style_config.*target|styledBy"
    - from: "frontend/src/components/widgets/builtin/LegendWidget.tsx"
      to: "frontend/src/types/api.ts"
      via: "reads style_config.target, sizes, sizeRange for legend"
      pattern: "target.*radius|target.*width|sizeRange"
---

<objective>
Extend the map builder's data-driven styling from color-only to support graduated radius (circle-radius for points) and graduated width (line-width for lines). Polygons remain color-only.

Purpose: Proportional symbol maps and weighted line maps are core GIS visualization patterns. This completes the data-driven styling toolset.

Output: Updated DataDrivenStyleEditor with target selector, new expression builders, size-aware legend, updated i18n.
</objective>

<execution_context>
@/Users/ishiland/.claude/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@frontend/src/types/api.ts (StyleConfig type at ~line 618)
@frontend/src/lib/color-ramps.ts (expression builders, getColorProperty)
@frontend/src/components/builder/DataDrivenStyleEditor.tsx (full component)
@frontend/src/components/builder/LayerStyleEditor.tsx (flat controls + "styled by" indicator)
@frontend/src/components/widgets/builtin/LegendWidget.tsx (legend rendering)
@frontend/src/components/builder/__tests__/DataDrivenStyleEditor.test.tsx (existing tests)
@frontend/src/lib/classification.ts (equalIntervalBreaks, quantileBreaks)

<interfaces>
<!-- Key types and contracts the executor needs -->

From frontend/src/types/api.ts (current):
```typescript
export interface StyleConfig {
  mode: 'categorical' | 'graduated';
  column: string;
  ramp: string;
  classCount?: number;
  method?: 'equal_interval' | 'quantile';
  categories?: { value: string; color: string }[];
  breaks?: number[];
  colors?: string[];
}
```

From frontend/src/lib/color-ramps.ts (current exports):
```typescript
export function getRampColors(rampName: string, count: number): string[];
export function buildCategoricalExpression(column: string, valueColorMap: [string, string][], fallback: string): unknown[];
export function buildGraduatedExpression(column: string, breaks: number[], colors: string[]): unknown[];
export function getColorProperty(geometryType: string | null): string;
```

From frontend/src/components/builder/map-sync.ts:
```typescript
export function getLayerType(geometryType: string | null): 'circle' | 'line' | 'fill';
```

From frontend/src/components/builder/DataDrivenStyleEditor.tsx:
```typescript
interface DataDrivenStyleEditorProps {
  layer: MapLayerResponse;
  onStyleConfigChange: (layerId: string, config: StyleConfig | null, paint: Record<string, unknown>) => void;
}
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Type extensions and expression builders</name>
  <files>
    frontend/src/types/api.ts,
    frontend/src/lib/color-ramps.ts,
    frontend/src/lib/__tests__/color-ramps.test.ts
  </files>
  <behavior>
    - buildGraduatedSizeExpression('pop', [100, 500, 1000], [3, 6, 10, 16]) returns ['step', ['get', 'pop'], 3, 100, 6, 500, 10, 1000, 16]
    - buildGraduatedSizeExpression throws if sizes.length !== breaks.length + 1
    - getSizeProperty('Point', 'radius') returns 'circle-radius'
    - getSizeProperty('MultiLineString', 'width') returns 'line-width'
    - getSizeProperty('Polygon', 'radius') returns null (polygons have no size property)
    - getSizeProperty('Point', 'color') returns null (color is not a size target)
    - getSizeProperty(null, 'radius') returns null
    - getColorProperty still works unchanged (regression)
  </behavior>
  <action>
    1. In `frontend/src/types/api.ts`, extend the `StyleConfig` interface:
       - Add `target?: 'color' | 'radius' | 'width'` — optional, defaults to 'color' when absent for backward compat
       - Add `sizes?: number[]` — parallel to `colors`, stores per-class size values for graduated size mode
       - Add `sizeRange?: [number, number]` — stores [min, max] size the user selected (for UI state restoration)
       Leave all existing fields untouched.

    2. In `frontend/src/lib/color-ramps.ts`, add two new exported functions (do NOT modify existing functions):

       ```typescript
       /**
        * Build a MapLibre graduated (step) expression for numeric size properties.
        * Identical shape to buildGraduatedExpression but with numeric sizes instead of color strings.
        * Returns: ['step', ['get', column], sizes[0], breaks[0], sizes[1], ..., breaks[n-1], sizes[n]]
        */
       export function buildGraduatedSizeExpression(
         column: string,
         breaks: number[],
         sizes: number[],
       ): unknown[]

       /**
        * Return the MapLibre paint property name for size-based styling, or null if not applicable.
        * Point + radius -> 'circle-radius'
        * Line + width -> 'line-width'
        * Everything else -> null (polygons have no size property; 'color' target returns null)
        */
       export function getSizeProperty(
         geometryType: string | null,
         target: 'color' | 'radius' | 'width',
       ): string | null
       ```

       `buildGraduatedSizeExpression`: Same logic as `buildGraduatedExpression` but accepts `sizes: number[]` instead of `colors: string[]`. Throw if `sizes.length !== breaks.length + 1`.

       `getSizeProperty`: Normalize geometryType (lowercase, strip 'multi'). If target is 'radius' and geom contains 'point', return 'circle-radius'. If target is 'width' and geom contains 'line', return 'line-width'. Otherwise return null.

    3. Create `frontend/src/lib/__tests__/color-ramps.test.ts` with tests for the new functions plus a regression test for getColorProperty. Follow the behavior spec above.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx vitest run src/lib/__tests__/color-ramps.test.ts --reporter=verbose 2>&1 | tail -30</automated>
  </verify>
  <done>
    StyleConfig type extended with target/sizes/sizeRange. buildGraduatedSizeExpression and getSizeProperty exported and tested. getColorProperty unchanged. All tests pass.
  </done>
</task>

<task type="auto">
  <name>Task 2: DataDrivenStyleEditor target UI, LayerStyleEditor indicators, legend size support, and i18n</name>
  <files>
    frontend/src/components/builder/DataDrivenStyleEditor.tsx,
    frontend/src/components/builder/LayerStyleEditor.tsx,
    frontend/src/components/widgets/builtin/LegendWidget.tsx,
    frontend/src/components/builder/__tests__/DataDrivenStyleEditor.test.tsx,
    frontend/src/i18n/locales/en/builder.json,
    frontend/src/i18n/locales/de/builder.json,
    frontend/src/i18n/locales/es/builder.json,
    frontend/src/i18n/locales/fr/builder.json
  </files>
  <action>
    **A. DataDrivenStyleEditor.tsx — add target selector and size expression generation**

    1. Add `target` state initialized from `existingConfig?.target ?? 'color'`. Add `sizeRange` state initialized from `existingConfig?.sizeRange ?? [2, 20]` (for radius) or `[1, 10]` (for width).

    2. Import `buildGraduatedSizeExpression`, `getSizeProperty` from `@/lib/color-ramps` and `getLayerType` from `@/components/builder/map-sync`.

    3. Compute available targets based on `getLayerType(layer.dataset_geometry_type)`:
       - `circle` -> targets: `['color', 'radius']`
       - `line` -> targets: `['color', 'width']`
       - `fill` -> targets: `['color']` (no selector shown)

       Only show the target selector row when `availableTargets.length > 1` AND `mode === 'graduated'` (categorical does not support size targets). Render it as a Select between "Color" / "Radius" (or "Width") placed just below the Mode selector, using i18n keys `dataDriven.target`, `dataDriven.targetColor`, `dataDriven.targetRadius`, `dataDriven.targetWidth`.

    4. When `target !== 'color'` and `mode === 'graduated'`:
       - Instead of the color ramp picker + per-class color swatches, show a "Size Range" UI: two sliders or a dual-value row for min size and max size (labeled `dataDriven.sizeMin` / `dataDriven.sizeMax`).
         - For radius: min range [1, 30], default [2, 20], step 1, format "px"
         - For width: min range [1, 20], default [1, 10], step 0.5, format "px"
       - Compute per-class sizes by linearly interpolating between sizeRange[0] and sizeRange[1] across the classCount. Store in `sizes` array.
       - Generate a step expression via `buildGraduatedSizeExpression(column, breaks, sizes)`.
       - Get the paint property via `getSizeProperty(layer.dataset_geometry_type, target)`.
       - Build the paint object: `{ ...layer.paint, [sizeProp]: sizeExpression }`. Also keep the existing color expression if present (color + size are independent and composable).
       - Build the config: `{ ...baseConfig, target, sizes, sizeRange }`.

    5. When `target === 'color'` (or absent), keep the existing behavior completely unchanged. The existing color path already works and must not be disturbed.

    6. In the useEffect dependency array, add `target` and `sizeRange` so changes re-trigger expression generation. In the graduated branch of the useEffect, check `target`:
       - If `target === 'color'` (or undefined): run the existing color expression logic unchanged
       - If `target === 'radius'` or `target === 'width'`: compute breaks the same way (equalInterval or quantile), then compute sizes via linear interpolation, build size expression, emit via `onStyleConfigChange`

    7. In `handleClear`:
       - Reset the color property (existing behavior)
       - Also reset the size property if one exists: get `getSizeProperty(...)` for the current geometry type and both 'radius' and 'width', and if non-null, delete that key from paint or reset it to the default scalar value from LayerStyleEditor (circle-radius: 5, line-width: 2)
       - Reset `target` state to `'color'`

    8. In `handleModeChange`:
       - When switching to `'categorical'`, force `target` back to `'color'` (categorical does not support size targets). Reset any size paint property to its default scalar value.

    9. Add the preservation guard for graduated size configs. In the graduated useEffect branch, when `target !== 'color'`, add an early-return guard similar to the existing graduated color guard: skip if `ec?.target === target && ec.column === column && ec.method === method && ec.classCount === classCount && ec.sizes && ec.sizeRange && ec.sizeRange[0] === sizeRange[0] && ec.sizeRange[1] === sizeRange[1]`.

    **B. LayerStyleEditor.tsx — "Styled by" indicator awareness**

    10. In each geometry section (fill, line, circle), the current `isDataDriven` check shows "Styled by: {column}" when `layer.style_config?.column` is set. Extend this to also mention the target when it is not 'color':
        - If `style_config.target === 'radius'`: show `t('style.radiusByColumn', { column })` instead of `t('style.styledBy', { column })`
        - If `style_config.target === 'width'`: show `t('style.widthByColumn', { column })`
        - If `style_config.target` is 'color' or undefined: keep existing `t('style.styledBy', { column })`

    11. When the style_config target is 'radius', the circle radius SliderRow should be disabled or hidden (it is now expression-driven). Similarly, when target is 'width', the line width SliderRow should be disabled. Check `Array.isArray(paint['circle-radius'])` or `Array.isArray(paint['line-width'])` — the existing `getPaintValue` already returns fallback for arrays, so the slider shows the default. Add a small italic note below the slider: `t('style.drivenByData')` when the value is expression-driven, or just rely on the existing "Styled by" indicator being sufficient. Keep it simple — the existing `getPaintValue` fallback behavior is adequate.

    **C. LegendWidget.tsx — size legend entries**

    12. In the graduated branch of the legend, detect `style_config.target`:
        - If `target === 'radius'` and `style_config.sizes` and `style_config.breaks` exist: render a size legend. For each class, render a circle SVG with diameter proportional to the size value (e.g., `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r={Math.min(size, 12)}/></svg>`). Use the layer's circle-color (flat or first color in color ramp) as fill. Keep the break labels the same as color legend.
        - If `target === 'width'` and `style_config.sizes` and `style_config.breaks` exist: render a width legend. For each class, render a horizontal line SVG with stroke-width proportional to the size value (`<svg width="24" height="16"><line x1="0" y1="8" x2="24" y2="8" stroke={lineColor} stroke-width={Math.min(size, 8)}/></svg>`). Use layer's line-color as stroke.
        - If `target === 'color'` or undefined: keep existing color swatch legend unchanged.

    **D. i18n — add new keys to all 4 locales**

    13. Add to the `dataDriven` section of each locale's builder.json:
        - `"target"`: "Target" / "Ziel" / "Objetivo" / "Cible"
        - `"targetColor"`: "Color" / "Farbe" / "Color" / "Couleur"
        - `"targetRadius"`: "Radius" / "Radius" / "Radio" / "Rayon"
        - `"targetWidth"`: "Width" / "Breite" / "Ancho" / "Largeur"
        - `"sizeMin"`: "Min size" / "Min. Groesse" / "Tamano min" / "Taille min"
        - `"sizeMax"`: "Max size" / "Max. Groesse" / "Tamano max" / "Taille max"

    14. Add to the `style` section:
        - `"radiusByColumn"`: "Radius by: {{column}}" / "Radius nach: {{column}}" / "Radio por: {{column}}" / "Rayon par: {{column}}"
        - `"widthByColumn"`: "Width by: {{column}}" / "Largeur par: {{column}}" / "Ancho por: {{column}}" / "Largeur par: {{column}}"

    15. Update `dataDriven.title` from "Data-Driven Color" to "Data-Driven Style" (and equivalents: "Datengesteuerter Stil" / "Estilo basado en datos" / "Style base sur les donnees") since it now covers color, radius, and width.

    **E. Update existing tests**

    16. In `DataDrivenStyleEditor.test.tsx`, add tests:
        - A point layer with graduated mode shows a target selector with "Color" and "Radius" options
        - Selecting "Radius" target hides the color ramp picker and shows size range controls
        - A polygon layer in graduated mode does NOT show a target selector
        - Clearing data-driven style resets target to 'color'
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx vitest run src/components/builder/__tests__/DataDrivenStyleEditor.test.tsx src/lib/__tests__/color-ramps.test.ts --reporter=verbose 2>&1 | tail -40</automated>
  </verify>
  <done>
    Point layers offer Radius target, line layers offer Width target, polygon layers are color-only.
    Size range UI replaces color ramp when target is radius/width.
    Graduated size expressions applied to paint dict.
    Legend widget renders proportional circles for radius, weighted lines for width.
    LayerStyleEditor shows "Radius by" / "Width by" indicators.
    All 4 locales updated. Existing tests still pass, new tests cover target selector behavior.
  </done>
</task>

</tasks>

<verification>
1. `cd frontend && npx vitest run src/lib/__tests__/color-ramps.test.ts src/components/builder/__tests__/DataDrivenStyleEditor.test.tsx` -- all tests pass
2. `cd frontend && npx tsc --noEmit` -- no type errors
3. Manual: open map builder, add a point layer, set graduated mode, confirm "Radius" target appears, select a numeric column, adjust size range, verify map shows proportional circles
4. Manual: open map builder, add a line layer, set graduated mode, confirm "Width" target appears, verify weighted lines render
5. Manual: open map builder, add a polygon layer, confirm only color target is available (no radius/width selector)
6. Manual: verify legend widget displays circle/line size indicators for size-driven layers
7. Manual: clear data-driven style, confirm radius/width resets to scalar defaults
</verification>

<success_criteria>
- StyleConfig.target optional field works with backward-compatible default
- buildGraduatedSizeExpression produces valid MapLibre step expressions
- getSizeProperty correctly maps geometry type + target to paint property
- Point layers support color + radius graduated styling
- Line layers support color + width graduated styling
- Polygon layers remain color-only
- Legend widget shows size indicators for graduated size layers
- All existing color-only data-driven styling works unchanged
- TypeScript compiles without errors
- All tests pass
</success_criteria>

<output>
After completion, create `.planning/quick/260328-pjx-map-builder-step-5-data-driven-styling-g/260328-pjx-SUMMARY.md`
</output>
