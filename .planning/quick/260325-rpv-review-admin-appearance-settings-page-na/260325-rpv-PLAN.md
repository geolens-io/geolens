---
phase: 260325-rpv
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/persistent_config.py
  - frontend/src/api/settings.ts
  - frontend/src/components/admin/AdminSidebar.tsx
  - frontend/src/components/admin/__tests__/AdminSidebar.test.tsx
  - frontend/src/components/admin/settings/SettingsAppearanceTab.tsx
  - frontend/src/pages/admin/AdminSettingsPage.tsx
  - frontend/src/App.tsx
  - frontend/src/lib/basemap-utils.ts
  - frontend/src/i18n/locales/en/admin.json
  - frontend/src/i18n/locales/es/admin.json
  - frontend/src/i18n/locales/fr/admin.json
  - frontend/src/i18n/locales/de/admin.json
  - frontend/src/components/builder/BuilderMap.tsx
  - frontend/src/components/dataset/DatasetMap.tsx
  - frontend/src/components/viewer/ViewerMap.tsx
  - frontend/src/components/search/SpatialFilterPanel.tsx
  - frontend/src/components/search/BboxMapPicker.tsx
autonomous: true
requirements: [RPV-01]

must_haves:
  truths:
    - "Admin sidebar shows 'Map' instead of 'Appearance' for the basemap/map-defaults settings page"
    - "Stamen Terrain preset is replaced with OpenFreeMap Bright in both backend defaults and any existing DB records"
    - "All maps display basemap attribution text via MapLibre AttributionControl"
    - "BasemapEntry type includes an attribution field populated for all presets"
    - "Custom basemap form includes an optional Attribution text input"
    - "Custom basemap URL help text mentions GL style JSON support"
  artifacts:
    - path: "frontend/src/components/admin/settings/SettingsAppearanceTab.tsx"
      provides: "Map settings tab with attribution field in custom basemap form"
    - path: "backend/app/persistent_config.py"
      provides: "Updated preset basemaps with OpenFreeMap Bright and attribution strings"
    - path: "frontend/src/api/settings.ts"
      provides: "BasemapEntry interface with optional attribution field"
  key_links:
    - from: "backend/app/persistent_config.py"
      to: "frontend/src/api/settings.ts"
      via: "BasemapEntry shape with attribution field"
      pattern: "attribution"
    - from: "frontend/src/api/settings.ts"
      to: "frontend/src/lib/basemap-utils.ts"
      via: "BasemapEntry type import"
      pattern: "import.*BasemapEntry"
    - from: "frontend/src/lib/basemap-utils.ts"
      to: "BuilderMap/DatasetMap/ViewerMap"
      via: "toMaplibreStyle consumed by map components"
      pattern: "toMaplibreStyle"
---

<objective>
Fix three issues on the admin basemap/map-defaults settings page: rename "Appearance" to "Map" across the full stack, replace the Stamen Terrain preset (which requires Stadia Maps API key auth in production) with OpenFreeMap Bright, and add basemap attribution support (field on BasemapEntry, AttributionControl re-enabled on all maps).

Purpose: Prevent production basemap failures (Stamen Terrain 429s), comply with OSM/CARTO terms of service via attribution, and eliminate naming confusion with the user-level "Appearance" theme picker.
Output: Renamed tab, working free basemap preset, attribution displayed on all maps.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/260325-rpv-review-admin-appearance-settings-page-na/260325-rpv-RESEARCH.md
@frontend/src/api/settings.ts
@frontend/src/lib/basemap-utils.ts
@frontend/src/components/admin/settings/SettingsAppearanceTab.tsx
@frontend/src/components/admin/AdminSidebar.tsx
@frontend/src/pages/admin/AdminSettingsPage.tsx
@backend/app/persistent_config.py

<interfaces>
<!-- Key types and contracts the executor needs -->

From frontend/src/api/settings.ts:
```typescript
export interface BasemapEntry {
  id: string;
  label: string;
  url: string;
  enabled: boolean;
  is_preset: boolean;
  // attribution field to be added
}
```

From frontend/src/lib/basemap-utils.ts:
```typescript
export function toMaplibreStyle(url: string): string | StyleSpecification;
export function getThemeBasemap(basemaps: BasemapEntry[], resolvedTheme: 'dark' | 'light'): BasemapEntry | undefined;
export function findBasemapById(basemaps: BasemapEntry[], id: string): BasemapEntry | undefined;
```

From frontend/src/pages/admin/AdminSettingsPage.tsx:
```typescript
const TAB_KEYS = ['general', 'auth', 'ai', 'network', 'storage', 'appearance', 'permissions'] as const;
// 'appearance' to be renamed to 'map'
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Rename Appearance to Map + replace Stamen Terrain preset</name>
  <files>
    backend/app/persistent_config.py,
    frontend/src/components/admin/AdminSidebar.tsx,
    frontend/src/components/admin/__tests__/AdminSidebar.test.tsx,
    frontend/src/pages/admin/AdminSettingsPage.tsx,
    frontend/src/App.tsx,
    frontend/src/i18n/locales/en/admin.json,
    frontend/src/i18n/locales/es/admin.json,
    frontend/src/i18n/locales/fr/admin.json,
    frontend/src/i18n/locales/de/admin.json
  </files>
  <action>
    **Rename "Appearance" tab to "Map" across the full stack:**

    1. **backend/app/persistent_config.py** (~line 466, 473): Change `tab="appearance"` to `tab="map"` on both BASEMAPS and MAP_DEFAULTS PersistentConfig entries. Also replace the Stamen Terrain preset (lines 452-458) with:
       ```python
       {
           "id": "openfreemap-bright",
           "label": "OpenFreeMap Bright",
           "url": "https://tiles.openfreemap.org/styles/bright",
           "enabled": True,
           "is_preset": True,
       },
       ```
       Add an `"attribution"` field to each preset basemap:
       - CARTO Positron: `"&copy; <a href='https://carto.com/'>CARTO</a>, &copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors"`
       - CARTO Dark Matter: same as above
       - OpenStreetMap: `"&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors"`
       - OpenFreeMap Bright: `"&copy; <a href='https://openfreemap.org'>OpenFreeMap</a>, &copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors"`

    2. **frontend/src/pages/admin/AdminSettingsPage.tsx**: In TAB_KEYS array, change `'appearance'` to `'map'`. Update TAB_LABELS and TAB_COMPONENTS to use `map` key instead of `appearance`. The import name `SettingsAppearanceTab` can stay (it is internal).

    3. **frontend/src/components/admin/AdminSidebar.tsx** (line 60): Change `labelKey` from `'admin:settings.tabs.appearance'` to `'admin:settings.tabs.map'`, change `to` from `'/admin/settings/appearance'` to `'/admin/settings/map'`, change icon from `Palette` to `Globe` (already imported). Remove `Palette` from imports since it will be unused.

    4. **frontend/src/App.tsx** (lines 81-82): Update the two legacy redirect Routes: change `element={<Navigate to="/admin/settings/appearance" replace />}` to `element={<Navigate to="/admin/settings/map" replace />}`. Add a third redirect for the old appearance path: `<Route path="admin/settings/appearance" element={<Navigate to="/admin/settings/map" replace />} />`.

    5. **All 4 admin.json locale files**: Change the `"appearance"` key under `settings.tabs` to `"map"`:
       - en: `"map": "Map"`
       - es: `"map": "Mapa"`
       - fr: `"map": "Carte"`
       - de: `"map": "Karte"`

    6. **frontend/src/i18n/locales/en/admin.json** (line 445): Update the `customDescription` from `"Add custom XYZ/TMS tile sources."` to `"Add custom XYZ/TMS tile URLs or MapLibre GL style JSON URLs."` Also update `tileUrlPlaceholder` to `"https://tiles.example.com/{z}/{x}/{y}.png or .json style URL"`.

    7. **frontend/src/components/admin/__tests__/AdminSidebar.test.tsx**: Update mock i18n key from `'admin:settings.tabs.appearance': 'Appearance'` to `'admin:settings.tabs.map': 'Map'`. Update assertion from `screen.getByText('Appearance')` to `screen.getByText('Map')`.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx vitest run frontend/src/components/admin/__tests__/AdminSidebar.test.tsx --reporter=verbose 2>&1 | tail -20</automated>
  </verify>
  <done>
    - Admin sidebar shows "Map" with Globe icon linking to /admin/settings/map
    - Backend groups basemap/map-defaults settings under tab="map"
    - TAB_KEYS, TAB_LABELS, TAB_COMPONENTS all use "map" key
    - Legacy /admin/settings/appearance redirects to /admin/settings/map
    - All 4 locale files updated with translated "Map" label
    - Stamen Terrain replaced with OpenFreeMap Bright in backend defaults
    - All preset basemaps include attribution strings in backend defaults
    - Custom basemap help text mentions GL style JSON support
  </done>
</task>

<task type="auto">
  <name>Task 2: Add attribution field to BasemapEntry and re-enable AttributionControl on maps</name>
  <files>
    frontend/src/api/settings.ts,
    frontend/src/components/admin/settings/SettingsAppearanceTab.tsx,
    frontend/src/lib/basemap-utils.ts,
    frontend/src/components/builder/BuilderMap.tsx,
    frontend/src/components/dataset/DatasetMap.tsx,
    frontend/src/components/viewer/ViewerMap.tsx,
    frontend/src/components/search/SpatialFilterPanel.tsx,
    frontend/src/components/search/BboxMapPicker.tsx
  </files>
  <action>
    **Add attribution to BasemapEntry type and re-enable MapLibre AttributionControl:**

    1. **frontend/src/api/settings.ts**: Add optional `attribution?: string` field to the `BasemapEntry` interface.

    2. **frontend/src/components/admin/settings/SettingsAppearanceTab.tsx**: Add `attribution?: string` to the local `BasemapEntry` interface (line 14-20). In the custom basemap add form (the `!envOnly` block starting ~line 142), add an "Attribution" text input between the URL input and the Add button:
       - Add state: `const [newAttribution, setNewAttribution] = useState('');`
       - Add input with label from i18n key `settings.basemaps.attributionLabel` (fallback: "Attribution")
       - Add placeholder: `"(c) Provider Name"` (or use i18n key `settings.basemaps.attributionPlaceholder`)
       - In `handleAdd()`, include `attribution: newAttribution.trim() || undefined` in the entry object
       - Reset `setNewAttribution('')` after add
       - Also add a small helper text under the Attribution input: `"Optional. HTML allowed for links."`

    3. **frontend/src/i18n/locales/en/admin.json**: Add under `settings.basemaps`:
       ```json
       "attributionLabel": "Attribution",
       "attributionPlaceholder": "\u00a9 Provider Name",
       "attributionHelp": "Optional. HTML allowed for links."
       ```
       (The \u00a9 is the copyright symbol. Use the actual symbol in the JSON.)

    4. **frontend/src/lib/basemap-utils.ts**: Update `toMaplibreStyle()` to accept an optional second parameter `attribution?: string`. When building the inline StyleSpecification for XYZ raster basemaps, set `attribution` on the raster source if provided:
       ```typescript
       export function toMaplibreStyle(url: string, attribution?: string): string | StyleSpecification {
         if (url.endsWith('.json')) return url;
         return {
           version: 8 as const,
           sources: {
             basemap: {
               type: 'raster' as const,
               tiles: [url],
               tileSize: 256,
               ...(attribution ? { attribution } : {}),
             },
           },
           layers: [{ id: 'basemap-tiles', type: 'raster' as const, source: 'basemap' }],
           glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
         };
       }
       ```
       Note: For GL style JSON basemaps (`.json` URLs), attribution is baked into the style spec by the provider, so no modification needed -- MapLibre's AttributionControl reads it automatically.

    5. **Re-enable AttributionControl on all 5 map components** by removing `attributionControl={false}`:
       - `frontend/src/components/builder/BuilderMap.tsx` (line 339): Remove `attributionControl={false}`
       - `frontend/src/components/dataset/DatasetMap.tsx` (line 813): Remove `attributionControl={false}`
       - `frontend/src/components/viewer/ViewerMap.tsx` (line 556): Remove `attributionControl={false}`
       - `frontend/src/components/search/SpatialFilterPanel.tsx` (line 331): Remove `attributionControl={false}`
       - `frontend/src/components/search/BboxMapPicker.tsx` (line 96): Remove `attributionControl={false}`

       MapLibre's default is `attributionControl={true}`, so simply removing the prop is sufficient. The AttributionControl renders as a small collapsible "i" button in the bottom-right corner -- it does not consume significant map space.

    6. **Pass attribution to toMaplibreStyle**: Find all call sites of `toMaplibreStyle()` and check if the calling context has access to the basemap's `attribution` field. The main consumers are in the map components that resolve the active basemap. If the basemap object is available at the call site, pass `basemap.attribution` as the second argument. If the call site only has a URL string, leave as-is (GL JSON styles carry their own attribution).
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && npx vitest run --reporter=verbose 2>&1 | tail -30</automated>
  </verify>
  <done>
    - BasemapEntry interface includes optional attribution field in both api/settings.ts and the tab component
    - Custom basemap form has Attribution text input with helper text
    - toMaplibreStyle() passes attribution to raster source when provided
    - All 5 map components no longer set attributionControl={false}
    - MapLibre AttributionControl renders attribution text from basemap source
    - i18n keys added for attribution label, placeholder, help text
  </done>
</task>

</tasks>

<verification>
1. Run full test suite: `npx vitest run` -- all tests pass
2. Build check: `npx tsc --noEmit` -- no type errors
3. Grep confirmation: `grep -r "attributionControl={false}" frontend/src/` returns no results
4. Grep confirmation: `grep -r "stamen-terrain\|Stamen Terrain" backend/` returns no results (except possibly test data)
5. Grep confirmation: `grep -r "tab=\"appearance\"" backend/` returns no results
</verification>

<success_criteria>
- Admin sidebar displays "Map" with Globe icon at /admin/settings/map
- Old /admin/settings/appearance URL redirects to /admin/settings/map
- Stamen Terrain preset replaced by OpenFreeMap Bright in backend defaults
- All preset basemaps carry attribution strings
- BasemapEntry type includes optional attribution field
- Custom basemap form includes Attribution input with help text
- All 5 map components display MapLibre AttributionControl
- All tests pass, TypeScript compiles cleanly
</success_criteria>

<output>
After completion, create `.planning/quick/260325-rpv-review-admin-appearance-settings-page-na/260325-rpv-SUMMARY.md`
</output>
