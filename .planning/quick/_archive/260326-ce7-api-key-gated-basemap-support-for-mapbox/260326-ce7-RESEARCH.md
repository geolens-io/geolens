# Quick Task 260326-ce7: API-Key-Gated Basemap Support - Research

**Researched:** 2026-03-26
**Domain:** Admin settings, basemap configuration, MapLibre GL
**Confidence:** HIGH

## Summary

This feature adds an optional `api_key` field to the existing custom basemap form. The admin enters an API key per basemap, and the URL contains an `{api_key}` placeholder that gets interpolated before being sent to MapLibre. Basemaps with unresolved `{api_key}` placeholders are filtered from the picker.

The existing codebase has clean extension points: `BasemapEntry` schema (backend + frontend), `PersistentConfig` for storage, `SettingsMapTab` for the admin form, `toMaplibreStyle()` for URL resolution, and `BasemapPicker` for filtering. No new backend endpoints or DB migrations needed.

**Primary recommendation:** Add `api_key` as an optional field on `BasemapEntry`, interpolate `{api_key}` in `toMaplibreStyle()`, and filter unresolved basemaps in the public `/settings/basemaps/` endpoint.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Add "API Keys" section to existing Admin > Settings > Map page, below basemap presets
- Generic pattern: any custom basemap can optionally include an API key via `{api_key}` URL placeholder
- No hard-coded provider presets
- API key field is OPTIONAL on custom basemap form
- Basemaps with `{api_key}` in URL are hidden from picker when no key value is available

### Specific Ideas
- Extend existing custom basemap form with optional "API Key" field
- Backend stores API keys in PersistentConfig (same pattern as basemaps)
- URL interpolation: replace `{api_key}` in basemap URL before sending to MapLibre
- Frontend filters out basemaps with unresolved `{api_key}` placeholders

</user_constraints>

## Provider URL Patterns (Confidence: HIGH)

The `{api_key}` placeholder approach works because each provider puts the key in a different query parameter:

| Provider | Style URL Pattern | Key Param |
|----------|-------------------|-----------|
| Mapbox | `https://api.mapbox.com/styles/v1/{username}/{style}?access_token={api_key}` | `access_token` |
| MapTiler | `https://api.maptiler.com/maps/streets-v2/style.json?key={api_key}` | `key` |
| Thunderforest | `https://tile.thunderforest.com/{style}/{z}/{x}/{y}.png?apikey={api_key}` | `apikey` |
| Stadia Maps | `https://tiles.stadiamaps.com/styles/alidade_smooth.json?api_key={api_key}` | `api_key` |

The admin pastes the full provider URL with `{api_key}` literally in the URL string. This is the correct approach -- no need for separate "provider type" selection or URL template logic.

**MapLibre compatibility note:** MapLibre does NOT support `mapbox://` protocol URLs. Mapbox styles must use the HTTPS API URL format shown above. MapTiler styles are natively MapLibre-compatible (MapTiler sponsors MapLibre). Both return standard GL JSON style specs.

## Architecture: Where Changes Go

### Backend (3 files)

1. **`backend/app/settings/schemas.py`** -- Add `api_key: str | None = None` to `BasemapEntry` model. Update `validate_tile_url` to also accept URLs containing `{api_key}` (currently rejects URLs without `{z}/{x}/{y}` unless they end in `.json` or contain `/styles/`).

2. **`backend/app/settings/router.py`** -- In `get_basemaps()`, filter out basemaps where `{api_key}` is in the URL but `api_key` field is empty/None. Also strip the `api_key` value from the response (return `api_key: null` to non-admin callers so the actual key is not leaked to the browser).

3. **`backend/app/persistent_config.py`** -- No changes needed. `BasemapEntry` is stored as a list of dicts inside the existing `BASEMAPS` PersistentConfig. Adding a field to the dict is backward-compatible.

### Frontend (4-5 files)

1. **`frontend/src/api/settings.ts`** -- Add `api_key?: string` to `BasemapEntry` interface.

2. **`frontend/src/components/admin/settings/SettingsMapTab.tsx`** -- Add optional "API Key" input to the custom basemap add form. Show masked key display on existing custom basemaps that have one.

3. **`frontend/src/lib/basemap-utils.ts`** -- In `toMaplibreStyle()`, interpolate `{api_key}` in the URL before passing to MapLibre. The function already receives the basemap URL.

4. **`frontend/src/components/builder/BasemapPicker.tsx`** -- Filter logic change: currently filters on `b.enabled`. Add: also exclude basemaps where URL contains `{api_key}` but no key value is available.

5. **i18n files** -- Add labels for API key field, placeholder text, help text.

### Data Flow

```
Admin enters basemap:
  label: "Mapbox Streets"
  url: "https://api.mapbox.com/styles/v1/mapbox/streets-v12?access_token={api_key}"
  api_key: "pk.eyJ1..."

Stored in PersistentConfig (BASEMAPS) as:
  { id, label, url, enabled, is_preset: false, api_key: "pk.eyJ1..." }

Public GET /settings/basemaps/:
  - If url contains {api_key} AND api_key is empty -> EXCLUDE from response
  - If url contains {api_key} AND api_key is set -> INCLUDE, but strip api_key from response
  - Response URL has {api_key} already replaced: "...?access_token=pk.eyJ1..."

Frontend toMaplibreStyle() receives the resolved URL -> works as-is
```

## Key Design Decision: Server-Side vs Client-Side Interpolation

**Recommendation: Server-side interpolation** (Confidence: HIGH)

The public `/settings/basemaps/` endpoint should replace `{api_key}` in the URL before returning it. Reasons:

1. **Security**: API keys never reach the browser as separate values. The resolved URL is no different from any other tile URL the browser fetches.
2. **Simplicity**: `toMaplibreStyle()` and `BasemapPicker` need zero changes for interpolation logic. The URL they receive is already complete.
3. **Consistency**: Viewer/embed maps use the same public endpoint and need resolved URLs too.

The admin `/settings/all/` endpoint still returns the raw `{api_key}` placeholder URL + the `api_key` field so the admin UI can display/edit them.

## Security Considerations

| Concern | Approach |
|---------|----------|
| Key exposure to non-admins | Server-side interpolation means key is embedded in URL, same as any authenticated tile URL. The `api_key` field itself is never in the public response. |
| Key masking in admin UI | Show `pk.eyJ...***` pattern (first 8 chars + dots). Full value editable but not displayed. |
| Key rotation | Admin updates the key field, saves. Basemap URLs resolve with new key immediately (30s cache TTL on PersistentConfig). |
| Audit trail | Existing `log_action` in `PersistentConfig.set()` already captures old/new values on basemap changes. |

**Note on tile URL exposure:** Once the browser fetches tiles, the API key is visible in network requests regardless of approach. This is inherent to client-side map rendering and is how all map applications work. Provider keys should be scoped/restricted on the provider side (domain restrictions, usage caps).

## URL Validation Update

Current `validate_tile_url` in `schemas.py` rejects URLs that don't match the tile/style patterns. Need to update to also accept URLs containing `{api_key}` in query params. The check should still validate the base URL structure.

Specifically, a URL like `https://api.mapbox.com/styles/v1/mapbox/streets-v12?access_token={api_key}` currently fails because it doesn't end in `.json`, doesn't contain `/styles/` in the path, and doesn't have `{z}/{x}/{y}`. Fix: treat URLs with recognized style paths (containing `/styles/` anywhere, or ending in `style.json` with query params) as valid.

Actually, looking more carefully: `https://api.maptiler.com/maps/streets-v2/style.json?key={api_key}` DOES end with `.json` when you strip the query string. And Mapbox URLs like `https://api.mapbox.com/styles/v1/mapbox/streets-v12?access_token={api_key}` DO contain `/styles/` in the path. So the existing validator likely already passes these. Verify during implementation.

## Common Pitfalls

### 1. Forgetting to filter in ALL basemap consumers
The public endpoint does the filtering, but if any component fetches basemaps from the admin settings response (which returns all basemaps), it could show broken basemaps. Verify all map components use `useBasemaps()` (the public hook), not the admin settings data.

### 2. Breaking existing basemaps on schema change
Adding `api_key` as optional with default `None` is backward-compatible. Existing stored basemaps without the field will deserialize with `api_key=None`. No migration needed.

### 3. MapLibre style JSON internal references
When a Mapbox/MapTiler style JSON is fetched, it contains internal URLs for sprites, glyphs, and tile sources that also need the API key. These URLs are relative to the style URL and MapLibre resolves them automatically using the same base URL (which includes the query params). This is standard behavior -- no special handling needed.

### 4. URL validation false negatives
The `{api_key}` placeholder must not interfere with URL validation. Since it appears in query params (not path structure), and the path-based checks (`/styles/`, `.json`) operate on the path portion, this should be fine.

## Sources

### Primary (HIGH confidence)
- Codebase: `backend/app/settings/schemas.py`, `backend/app/settings/router.py`, `backend/app/persistent_config.py`
- Codebase: `frontend/src/lib/basemap-utils.ts`, `frontend/src/components/builder/BasemapPicker.tsx`, `frontend/src/components/admin/settings/SettingsMapTab.tsx`
- MapTiler docs: https://docs.maptiler.com/cloud/api/maps/
- Mapbox Styles API: https://docs.mapbox.com/api/maps/styles/
- MapLibre migration guide: https://maplibre.org/maplibre-gl-js/docs/guides/mapbox-migration-guide/
