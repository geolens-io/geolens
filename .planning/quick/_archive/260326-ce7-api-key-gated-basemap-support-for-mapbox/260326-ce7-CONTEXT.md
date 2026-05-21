# Quick Task 260326-ce7: API-key-gated basemap support for Mapbox and MapTiler - Context

**Gathered:** 2026-03-26
**Status:** Ready for planning

<domain>
## Task Boundary

Implement API-key-gated basemap support for third-party providers. Admin enters API keys in settings, provider basemaps become available in basemap picker. API key is optional for any basemap — not every custom basemap needs one.

</domain>

<decisions>
## Implementation Decisions

### Admin UX
- Add an "API Keys" or "Provider Keys" section to the existing Admin > Settings > Map page
- Positioned below basemap presets, contextually close to where basemaps are managed
- Each key is a simple label + masked text input + save

### Provider Scope — Generic Pattern
- Any custom basemap can optionally include an API key
- The key gets interpolated into the URL via `{api_key}` placeholder
- Works for Mapbox, MapTiler, Thunderforest, or any provider
- No hard-coded provider presets — keeps the system extensible
- API key field is OPTIONAL on the custom basemap form (user clarification: "API key should be optional for a basemap")

### Basemap Picker Behavior
- Basemaps requiring an API key (URL contains `{api_key}`) are hidden from the picker if no key value is available
- Once the admin enters a key and the URL can be resolved, the basemap appears in the picker
- This keeps the picker clean with no grayed-out/disabled items

</decisions>

<specifics>
## Specific Ideas

- Extend the existing custom basemap form with an optional "API Key" field
- Backend stores API keys in PersistentConfig (same pattern as basemaps, map_defaults)
- URL interpolation: replace `{api_key}` in the basemap URL before sending to MapLibre
- The `{api_key}` placeholder is distinct from existing `{z}/{x}/{y}` tile URL placeholders
- Frontend filters out basemaps with unresolved `{api_key}` placeholders from the picker

</specifics>

<canonical_refs>
## Canonical References

- Existing basemap settings: `backend/app/settings/router.py`, `backend/app/persistent_config.py`
- Basemap admin UI: `frontend/src/components/admin/settings/useSettingsForm.ts`
- Basemap picker: `frontend/src/components/builder/BasemapPicker.tsx`
- Basemap utils: `frontend/src/lib/basemap-utils.ts`

</canonical_refs>
