---
phase: quick-260325-jpw
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/builder/map-sync.ts
  - frontend/src/components/builder/LayerStyleEditor.tsx
  - frontend/src/i18n/locales/en/builder.json
  - frontend/src/i18n/locales/fr/builder.json
  - frontend/src/i18n/locales/es/builder.json
  - frontend/src/i18n/locales/de/builder.json
  - frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx
autonomous: true
requirements: [TOGGLE-FILL, TOGGLE-STROKE, TOGGLE-I18N, TOGGLE-TESTS]

must_haves:
  truths:
    - "Polygon layers show fill and stroke toggle switches in style editor"
    - "Circle layers show stroke toggle switch only (no fill toggle)"
    - "Line layers show no toggle switches"
    - "Toggling fill OFF sets fill-opacity to 0 and collapses fill controls"
    - "Toggling fill ON restores saved fill-opacity (fallback 0.3)"
    - "Toggling stroke OFF sets outline width to 0 and collapses stroke controls"
    - "Toggling stroke ON restores saved outline width (fallback 1)"
  artifacts:
    - path: "frontend/src/components/builder/map-sync.ts"
      provides: "CUSTOM_PAINT_PROPS expanded with toggle metadata keys"
      contains: "_fill-disabled"
    - path: "frontend/src/components/builder/LayerStyleEditor.tsx"
      provides: "Fill/stroke toggle switches with collapse behavior"
      contains: "Switch"
    - path: "frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx"
      provides: "Unit tests for toggle behavior"
      contains: "toggle"
  key_links:
    - from: "LayerStyleEditor.tsx"
      to: "map-sync.ts"
      via: "CUSTOM_PAINT_PROPS filtering"
      pattern: "_fill-disabled|_stroke-disabled|_fill-opacity-saved|_outline-width-saved"
    - from: "LayerStyleEditor.tsx"
      to: "onPaintChange callback"
      via: "toggle handlers setting _fill-disabled/_stroke-disabled flags"
      pattern: "onPaintChange.*_fill-disabled"
---

<objective>
Add fill/stroke visibility toggles to LayerStyleEditor for polygon and circle layers, with saved-value persistence via custom paint props.

Purpose: Users can toggle fill/stroke on/off without losing their configured values, matching standard GIS tool UX.
Output: Toggle switches in style editor, custom paint prop persistence, unit tests, i18n keys.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@frontend/src/components/builder/map-sync.ts
@frontend/src/components/builder/LayerStyleEditor.tsx
@frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx
@frontend/src/i18n/locales/en/builder.json

<interfaces>
<!-- From map-sync.ts line 9 -->
```typescript
const CUSTOM_PAINT_PROPS = new Set(['_outline-width', '_outline-color']);
```

<!-- From LayerStyleEditor.tsx -->
```typescript
interface LayerStyleEditorProps {
  layer: MapLayerResponse;
  onPaintChange: (layerId: string, paint: Record<string, unknown>) => void;
  onOpacityChange: (layerId: string, opacity: number) => void;
  onStyleConfigChange: (layerId: string, config: StyleConfig | null, paint: Record<string, unknown>) => void;
  onLayoutChange: (layerId: string, layout: Record<string, unknown>) => void;
}

function getPaintValue<T>(paint: Record<string, unknown>, key: string, fallback: T): T;
```

<!-- Existing i18n style keys (en/builder.json) -->
```json
"style": {
  "fill": "Fill",
  "stroke": "Stroke",
  "line": "Line",
  "point": "Point",
  "opacity": "Opacity",
  "layer": "Layer",
  "color": "Color",
  "width": "Width",
  "radius": "Radius",
  "styledBy": "Styled by: {{column}}",
  "pattern": "Pattern",
  "dash": { "solid": "Solid", "dashed": "Dashed", "dotted": "Dotted", "dashDot": "Dash-dot" }
}
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add custom paint props and i18n keys</name>
  <files>
    frontend/src/components/builder/map-sync.ts
    frontend/src/i18n/locales/en/builder.json
    frontend/src/i18n/locales/fr/builder.json
    frontend/src/i18n/locales/es/builder.json
    frontend/src/i18n/locales/de/builder.json
  </files>
  <action>
1. In `map-sync.ts` line 9, expand `CUSTOM_PAINT_PROPS` to include the 4 new toggle metadata keys:
   ```typescript
   const CUSTOM_PAINT_PROPS = new Set([
     '_outline-width', '_outline-color',
     '_fill-disabled', '_stroke-disabled',
     '_fill-opacity-saved', '_outline-width-saved',
   ]);
   ```
   These keys are stored in the layer paint JSON but must NOT be passed to MapLibre as paint properties.

2. Add i18n keys to the `"style"` object in all 4 locale builder.json files (used as aria-labels only):
   - en: `"toggleFill": "Toggle fill visibility"`, `"toggleStroke": "Toggle stroke visibility"`
   - fr: `"toggleFill": "Basculer la visibilite du remplissage"`, `"toggleStroke": "Basculer la visibilite du contour"`
   - es: `"toggleFill": "Alternar visibilidad del relleno"`, `"toggleStroke": "Alternar visibilidad del trazo"`
   - de: `"toggleFill": "Fullsichtbarkeit umschalten"`, `"toggleStroke": "Kontursichtbarkeit umschalten"`

   Place them after the `"dash"` object in the `"style"` section. Use proper accented characters for fr/es/de.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -20</automated>
  </verify>
  <done>CUSTOM_PAINT_PROPS contains all 6 keys. All 4 locale files have toggleFill and toggleStroke keys in style section.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Implement fill/stroke toggles in LayerStyleEditor with tests</name>
  <files>
    frontend/src/components/builder/LayerStyleEditor.tsx
    frontend/src/components/builder/__tests__/LayerStyleEditor.test.tsx
  </files>
  <behavior>
    - Polygon layer renders two Switch components (fill + stroke) with correct aria-labels
    - Circle layer renders one Switch (stroke only), no fill toggle
    - Line layer renders zero Switch components
    - Toggle fill OFF: onPaintChange called with `_fill-disabled: true`, `_fill-opacity-saved: <current>`, `fill-opacity: 0`
    - Toggle fill ON: onPaintChange called with restored `fill-opacity` from `_fill-opacity-saved` (or 0.3 fallback), `_fill-disabled` and `_fill-opacity-saved` removed (deleted from paint)
    - Toggle stroke OFF (polygon): onPaintChange with `_stroke-disabled: true`, `_outline-width-saved: <current>`, `_outline-width: 0`
    - Toggle stroke ON (polygon): restore `_outline-width` from saved, remove flags
    - Toggle stroke OFF (circle): same pattern but `circle-stroke-width: 0` and `_outline-width-saved` for saved value
    - Fill color picker + opacity slider NOT rendered when fill toggled OFF
    - Stroke color picker + width slider NOT rendered when stroke toggled OFF
  </behavior>
  <action>
**In LayerStyleEditor.tsx:**

1. Add import: `import { Switch } from '@/components/ui/switch';`

2. Derive toggle states from paint (inside the component function, after `const paint = ...`):
   ```typescript
   const fillEnabled = !paint['_fill-disabled'];
   const strokeEnabled = !paint['_stroke-disabled'];
   ```

3. Add toggle handler functions inside the component:
   ```typescript
   function handleToggleFill() {
     const next = { ...paint };
     if (fillEnabled) {
       // Save current and disable
       next['_fill-opacity-saved'] = getPaintValue(paint, 'fill-opacity', FILL_DEFAULTS['fill-opacity']);
       next['fill-opacity'] = 0;
       next['_fill-disabled'] = true;
     } else {
       // Restore and enable
       const saved = getPaintValue(paint, '_fill-opacity-saved', FILL_DEFAULTS['fill-opacity']);
       next['fill-opacity'] = saved;
       delete next['_fill-disabled'];
       delete next['_fill-opacity-saved'];
     }
     onPaintChange(layer.id, next);
   }

   function handleToggleStroke() {
     const next = { ...paint };
     if (geomType === 'circle') {
       if (strokeEnabled) {
         next['_outline-width-saved'] = getPaintValue(paint, 'circle-stroke-width', CIRCLE_DEFAULTS['circle-stroke-width']);
         next['circle-stroke-width'] = 0;
         next['_stroke-disabled'] = true;
       } else {
         next['circle-stroke-width'] = getPaintValue(paint, '_outline-width-saved', CIRCLE_DEFAULTS['circle-stroke-width']);
         delete next['_stroke-disabled'];
         delete next['_outline-width-saved'];
       }
     } else {
       // polygon
       if (strokeEnabled) {
         next['_outline-width-saved'] = getPaintValue(paint, '_outline-width', FILL_DEFAULTS['_outline-width']);
         next['_outline-width'] = 0;
         next['_stroke-disabled'] = true;
       } else {
         next['_outline-width'] = getPaintValue(paint, '_outline-width-saved', FILL_DEFAULTS['_outline-width']);
         delete next['_stroke-disabled'];
         delete next['_outline-width-saved'];
       }
     }
     onPaintChange(layer.id, next);
   }
   ```

4. **Polygon fill section** — Replace the static `<div className="text-xs font-medium">{t('style.fill')}</div>` header (line ~81) with a header row containing the label and a Switch:
   ```tsx
   <div className="flex items-center justify-between">
     <div className="text-xs font-medium">{t('style.fill')}</div>
     <Switch
       checked={fillEnabled}
       onCheckedChange={handleToggleFill}
       aria-label={t('style.toggleFill')}
       className="scale-75"
     />
   </div>
   ```
   Then wrap the fill color picker and opacity slider in `{fillEnabled && ( ... )}` so they collapse when disabled. Keep the "Styled by" text visible even when fill is enabled (existing behavior).

5. **Polygon stroke section** — Replace the stroke header (line ~102) similarly:
   ```tsx
   <div className="flex items-center justify-between">
     <div className="text-xs font-medium mt-2">{t('style.stroke')}</div>
     <Switch
       checked={strokeEnabled}
       onCheckedChange={handleToggleStroke}
       aria-label={t('style.toggleStroke')}
       className="scale-75 mt-2"
     />
   </div>
   ```
   Wrap stroke color picker and width slider in `{strokeEnabled && ( ... )}`.

6. **Circle stroke section** — Same pattern for the circle stroke header (line ~217). Add Switch + collapse. No fill toggle for circles.

7. **Line layers** — No changes. No switches added.

Note: Use `className="scale-75"` on Switch to keep it proportional to the compact section headers.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx vitest run src/components/builder/__tests__/LayerStyleEditor.test.tsx 2>&1 | tail -30</automated>
  </verify>
  <done>
    - Polygon layers show fill + stroke Switch toggles
    - Circle layers show stroke Switch only
    - Line layers show no Switch
    - Toggling fill OFF calls onPaintChange with _fill-disabled, _fill-opacity-saved, fill-opacity:0
    - Toggling fill ON restores saved opacity, removes flags
    - Toggling stroke OFF/ON works for both polygon and circle with correct keys
    - Controls collapse/expand with toggle state
    - All existing dash preset tests still pass
    - TypeScript compiles cleanly
  </done>
</task>

</tasks>

<verification>
1. `cd frontend && npx tsc --noEmit` — no type errors
2. `cd frontend && npx vitest run src/components/builder/__tests__/LayerStyleEditor.test.tsx` — all tests pass (existing 5 + new ~8)
3. Grep CUSTOM_PAINT_PROPS in map-sync.ts contains all 6 keys
4. Grep all 4 locale files for toggleFill and toggleStroke keys
</verification>

<success_criteria>
- Polygon fill/stroke toggles save values via custom paint props and collapse controls when OFF
- Circle stroke toggle works with circle-stroke-width
- Line layers unaffected (no toggles)
- All 6 custom paint props in CUSTOM_PAINT_PROPS (filtered from MapLibre sync)
- i18n aria-labels in all 4 locales
- 8+ new unit tests passing alongside existing 5
</success_criteria>

<output>
After completion, create `.planning/quick/260325-jpw-fill-stroke-visibility-toggles-in-layers/260325-jpw-SUMMARY.md`
</output>
