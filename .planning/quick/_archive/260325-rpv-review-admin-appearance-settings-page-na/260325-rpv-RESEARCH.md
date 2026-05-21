# Admin Appearance Settings Page - Review Research

**Researched:** 2026-03-25
**Domain:** Basemap licensing, admin UX, custom basemap flexibility
**Confidence:** HIGH

## Summary

The Appearance settings page has two significant issues and several easy-win gaps.

**Critical licensing problem:** The Stamen Terrain preset (via Stadia Maps) requires authentication for production use -- unauthenticated requests get strict rate limits and eventual 429 blocks. The CARTO basemaps are technically restricted to enterprise customers and non-profit grantees for commercial use, though they currently work without keys. OpenStreetMap tiles have a best-effort usage policy that explicitly warns commercial apps may be blocked without notice. All three maps in the app disable `attributionControl={false}` -- meaning zero basemap attribution is displayed, violating all four providers' terms.

**Primary recommendation:** Replace Stamen Terrain with a truly free basemap (OpenFreeMap), add an attribution field to the basemap model, and restore MapLibre's `AttributionControl`. Rename the tab from "Appearance" to "Map" or "Map Settings" to more accurately describe its content (basemaps + default view).

## 1. Licensing Assessment

### Preset Basemaps

| Basemap | Provider | License Status | API Key | Attribution Required | Risk |
|---------|----------|---------------|---------|---------------------|------|
| CARTO Positron | CARTO | Enterprise/grantee only for commercial | No (works without) | Yes - "CARTO" link | MEDIUM - technically requires enterprise license for commercial use, but tiles serve without auth |
| CARTO Dark Matter | CARTO | Same as above | No | Yes - "CARTO" link | MEDIUM |
| OpenStreetMap | OSM Foundation | ODbL, free but best-effort | No | Yes - "(c) OpenStreetMap contributors" | LOW - free but access can be withdrawn; no SLA |
| Stamen Terrain | Stadia Maps | Requires auth for production | YES (or domain auth) | Yes - Stadia Maps attribution | HIGH - will get 429 rate-limited in production |

**Confidence:** HIGH -- verified via official docs from each provider.

### Key Finding: Attribution Missing

All three map components (`BuilderMap`, `DatasetMap`, `ViewerMap`) set `attributionControl={false}`. This violates every basemap provider's terms:
- OSM: "Display attribution clearly on your map"
- CARTO: "visibly credit CARTO with a link"
- Stadia: standard attribution required

### Recommendation

1. **Remove Stamen Terrain** as a preset -- it will fail in production without Stadia Maps auth
2. **Replace with OpenFreeMap** (`https://tiles.openfreemap.org/styles/positron` and `/styles/bright`) -- no API key, no registration, no limits, truly free
3. **Keep CARTO basemaps** -- they work without auth and are widely used in OSS projects; risk is low in practice for a self-hosted tool, but document the licensing caveat
4. **Keep OpenStreetMap** -- free under ODbL, standard in the industry
5. **Re-enable `AttributionControl`** on all maps or add a persistent attribution bar

## 2. Page Naming

"Appearance" is imprecise. The page manages:
- Basemap selection (which tile layers are available)
- Map defaults (initial center/zoom)

It does NOT manage visual appearance (theme, colors, branding). There is already a separate user-facing "Appearance" section under user settings for theme selection -- this creates confusion.

| Platform | Equivalent Admin Page Name |
|----------|---------------------------|
| ArcGIS Online | "Basemaps" (dedicated section) |
| QGIS Server (Lizmap) | "Baselayers" tab |
| GeoServer | N/A (no basemap admin) |
| GeoNode | "Map Settings" |
| Most web GIS tools | "Map" or "Map Settings" |

**Recommendation:** Rename to **"Map"** in the sidebar. The section headings inside (Basemap Presets, Custom Basemaps, Default Map View) already describe the content clearly. "Map" is short, accurate, and does not collide with the user-level "Appearance" theme picker.

## 3. Custom Basemap Flexibility

### What Works Now

- GL style JSON URLs (`.json` suffix) -- covers MapTiler, OpenFreeMap, CARTO, Protomaps, any MapLibre-compatible style
- XYZ/TMS raster URLs (`{z}/{x}/{y}`) -- covers OSM, Stadia, Thunderforest, ESRI raster tiles, custom tile servers

### What Cannot Be Used

| Format/Service | Why It Fails | Impact |
|----------------|-------------|--------|
| Services requiring API keys | No `{key}` / `{access_token}` template var | Cannot use Mapbox, MapTiler, Thunderforest, Stadia, ESRI without manually embedding keys in URL |
| TileJSON endpoints | URLs like `https://api.maptiler.com/tiles/v3/tiles.json` don't end in `.json` style format | Rejected -- TileJSON != GL style JSON |
| WMTS | XML-based protocol, not URL template | Out of scope for MapLibre direct use |
| WMS | Same as WMTS | Out of scope |

### Biggest Gap: No API Key Support

Many commercial basemap services (MapTiler, Mapbox, Thunderforest, Stadia) use URLs like:
```
https://api.maptiler.com/maps/streets-v2/style.json?key={api_key}
```

Without an API key/token field, users must manually paste the full URL including their key. This is functional but has UX and security downsides:
- Keys are visible in the settings form to all admins
- Keys are stored in the basemaps JSON blob in the DB (not in secrets management)
- No hint in the UI that API key substitution exists

**Recommendation for now:** This is acceptable as-is. Most self-hosted GIS deployments use free basemaps. Adding a separate API key field is a nice-to-have, not a blocker.

## 4. Easy-Win Enhancements

Ordered by impact-to-effort ratio:

### 4a. Add Attribution Field to BasemapEntry (HIGH impact, LOW effort)

Add an `attribution` string field to the basemap model. Populate it for presets:
- CARTO: `"(c) <a href='https://carto.com/'>CARTO</a>, (c) <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors"`
- OSM: `"(c) <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors"`

For custom basemaps, add an optional "Attribution" text input in the add form. Re-enable `AttributionControl` on maps (MapLibre renders it natively).

### 4b. Rename Tab to "Map" (HIGH clarity, TRIVIAL effort)

Change sidebar label and i18n key from "Appearance" to "Map". Prevents confusion with user-level theme settings.

### 4c. Replace Stamen Terrain Preset (HIGH impact, LOW effort)

Swap Stamen Terrain for OpenFreeMap Bright:
```
id: "openfreemap-bright"
label: "OpenFreeMap Bright"
url: "https://tiles.openfreemap.org/styles/bright"
```

OpenFreeMap is truly free (no API key, no registration, no rate limits, open source).

Other good free alternatives:
- OpenFreeMap Liberty: `https://tiles.openfreemap.org/styles/liberty`
- OpenFreeMap Positron: `https://tiles.openfreemap.org/styles/positron` (similar to CARTO Positron)

### 4d. Basemap Preview Thumbnail (MEDIUM impact, MEDIUM effort)

Show a small static map thumbnail next to each basemap in the list. Could use a hardcoded center/zoom to fetch a single tile as a preview. This helps admins visually identify which basemap they are toggling.

### 4e. Help Text for Custom URL Format (LOW effort)

The placeholder text shows `https://tiles.example.com/{z}/{x}/{y}.png` but does not mention GL style JSON support. Add a brief help line:
> "Enter an XYZ tile URL with {z}/{x}/{y} placeholders, or a MapLibre GL style JSON URL ending in .json"

### 4f. Map Defaults Preview (MEDIUM impact, MEDIUM effort)

The i18n keys `mapDefaults.preview` and `mapDefaults.useCurrentView` exist but the component does not render a preview map or a "use current view" button. Adding a small preview map with "Set from this view" would make configuring map defaults much more intuitive than manually entering lat/lng/zoom numbers.

## 5. Minor Issues

- **`basemap-utils.ts` hardcoded glyphs URL:** `https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf` is used for XYZ raster basemaps. This is MapLibre's demo server -- fine for raster-only maps (no labels rendered), but could break if MapLibre removes it. Low risk since raster basemaps don't need glyphs.
- **No drag-to-reorder for custom basemaps:** Basemaps appear in insertion order. Not a problem with few basemaps, but worth noting for completeness.

## Sources

### Primary (HIGH confidence)
- [OSM Tile Usage Policy](https://operations.osmfoundation.org/policies/tiles/) - official policy, read in full
- [Stadia Maps Authentication](https://docs.stadiamaps.com/authentication/) - confirms API key required for production
- [CARTO Basemaps FAQ](https://docs.carto.com/faqs/carto-basemaps) - enterprise/grantee restriction confirmed
- [CARTO basemap-styles LICENSE](https://github.com/CartoDB/basemap-styles/blob/master/LICENSE.md) - BSD-3/CC-BY-4 for styles only, not tile hosting
- [OpenFreeMap](https://github.com/hyperknot/openfreemap) - no API key, no limits, fully open source

### Secondary (MEDIUM confidence)
- GIS platform naming conventions (ArcGIS, GeoNode, Lizmap) - from documentation review
