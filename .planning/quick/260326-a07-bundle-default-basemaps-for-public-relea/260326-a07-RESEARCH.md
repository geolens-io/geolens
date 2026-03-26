# Quick Task 260326-a07: Bundle Default Basemaps for Public Release - Research

**Researched:** 2026-03-26
**Domain:** Basemap licensing / open-source distribution
**Confidence:** HIGH

## Summary

The current four default basemaps have a significant licensing issue: **CARTO's hosted tile service (basemaps.cartocdn.com) is officially restricted to enterprise customers and non-profit grantees**. While the tiles technically load without authentication, CARTO's LICENSE.md and FAQ explicitly state the hosted service is "not available for free public use." Distributing these URLs as defaults in an MIT/Apache project exposes downstream users to potential ToS violations.

OpenStreetMap's tile usage policy explicitly says software should **not hardcode tile.openstreetmap.org** as a default. OpenFreeMap is the safest default -- MIT-licensed, no API keys, no usage limits, commercial use permitted.

**Primary recommendation:** Replace CARTO tile URLs with OpenFreeMap equivalents (Positron and Dark Matter styles are available and verified). Keep OSM raster as an option but add a comment noting the tile usage policy. Add Mapbox and MapTiler as API-key-gated options.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- GeoLens is open-source under MIT/Apache license
- Bundled basemaps must allow redistribution and commercial use by downstream users
- Any provider whose terms restrict commercial use or redistribution is disqualified
- Keep the current 4 defaults: CARTO Positron, CARTO Dark Matter, OpenStreetMap raster, OpenFreeMap Bright (unless licensing is problematic)
- Use MapLibre's built-in AttributionControl
- Consider Mapbox and MapTiler as API-key-gated options

### Claude's Discretion
- Which basemaps are safe to bundle vs. need replacement
- Specific attribution strings
- Whether additional free providers are worth including

### Deferred Ideas (OUT OF SCOPE)
- None specified
</user_constraints>

## Licensing Analysis by Provider

### CARTO (basemaps.cartocdn.com) -- PROBLEMATIC

| Aspect | Finding | Confidence |
|--------|---------|------------|
| Style code license | BSD 3-Clause (code) + CC BY 4.0 (design) -- open source | HIGH |
| Hosted tile service | **Restricted to enterprise customers and non-profit grantees** | HIGH |
| API key required | No (tiles load without auth, but ToS restricts usage) | HIGH |
| Commercial use | Requires enterprise license | HIGH |
| Source | [LICENSE.md](https://github.com/CartoDB/basemap-styles/blob/master/LICENSE.md), [CARTO FAQ](https://docs.carto.com/faqs/carto-basemaps) |

**Verdict:** The style definitions are open source, but **the hosted tile service at basemaps.cartocdn.com is not free for public use**. The LICENSE.md explicitly states: "access to CARTO's basemap tile services is restricted to CARTO enterprise customers and Non-Profit GRANTS only and is not available for free public use." Bundling these URLs as defaults in an MIT/Apache project would put downstream commercial users in violation of CARTO's terms.

**Action required:** Remove CARTO tile URLs from defaults. The Positron and Dark Matter *styles* (BSD/CC-BY) can be used with alternative tile backends (e.g., OpenFreeMap, self-hosted OpenMapTiles).

### OpenStreetMap (tile.openstreetmap.org) -- USE WITH CAUTION

| Aspect | Finding | Confidence |
|--------|---------|------------|
| Data license | ODbL (data) + CC BY-SA 2.0 (cartography) | HIGH |
| Tile server policy | Not for hardcoding as default in distributed software | HIGH |
| API key required | No | HIGH |
| Bulk/heavy use | Prohibited -- must not prefetch, must cache 7+ days | HIGH |
| User-Agent | Must send unique User-Agent per application | HIGH |
| Source | [OSM Tile Policy](https://operations.osmfoundation.org/policies/tiles/) |

**Key quotes from policy:**
- "Avoid hard-coding the tile URL; allow switching without needing a software update"
- Must provide "a clear, unique User-Agent string that names your app"
- Bulk downloading and offline use are prohibited and will be "blocked without notice"

**Verdict:** OSM tile policy discourages hardcoding their URL as a default in distributed software. However, GeoLens already makes basemaps configurable via admin settings, so this is more of a "default" concern than a hardcoding concern. Keeping OSM as a default is borderline acceptable if the admin can change it, but it is not ideal since every fresh GeoLens install would hit tile.openstreetmap.org by default.

**Recommendation:** Keep as an available preset but consider not enabling by default, or move to last position behind OpenFreeMap styles.

### OpenFreeMap -- SAFE

| Aspect | Finding | Confidence |
|--------|---------|------------|
| License | MIT (project code) | HIGH |
| Tile usage | Free, no limits, no API key, no registration | HIGH |
| Commercial use | Explicitly permitted | HIGH |
| Attribution | "OpenFreeMap (c) OpenMapTiles Data from OpenStreetMap" (automatic in MapLibre) | HIGH |
| Sustainability | Donation-funded, no SLA | MEDIUM |
| Source | [openfreemap.org](https://openfreemap.org/), [GitHub](https://github.com/hyperknot/openfreemap) |

**Verdict:** The safest default for an open-source project. No licensing restrictions, no API keys, commercial use permitted. The only risk is long-term availability since it is donation-funded with no SLA. However, since GeoLens basemaps are admin-configurable, this is acceptable.

**Available styles (all verified):**
- `https://tiles.openfreemap.org/styles/positron` -- light theme, valid GL style JSON v8
- `https://tiles.openfreemap.org/styles/dark` -- dark theme (background `rgb(12,12,12)`), valid GL style JSON v8
- `https://tiles.openfreemap.org/styles/bright` -- already in use, valid GL style JSON v8

### Mapbox -- API-KEY-GATED OPTION

| Aspect | Finding | Confidence |
|--------|---------|------------|
| License | Proprietary ToS | HIGH |
| API key required | Yes, always | HIGH |
| Free tier | 50,000 map loads/month (web), 25,000 MAU (mobile) | HIGH |
| Commercial use | Allowed within ToS and usage limits | HIGH |
| Open-source bundling | Can reference as option, user supplies their own key | HIGH |
| Source | [Mapbox Pricing](https://www.mapbox.com/pricing), [Mapbox ToS](https://www.mapbox.com/legal/tos) |

**Verdict:** Cannot be a default (requires API key). Safe to include as an API-key-gated option where the admin provides their own Mapbox access token. The free tier is generous enough for development and small deployments.

### MapTiler -- API-KEY-GATED OPTION

| Aspect | Finding | Confidence |
|--------|---------|------------|
| License | Proprietary ToS | HIGH |
| API key required | Yes, always | HIGH |
| Free tier | 100,000 tile requests/month | HIGH |
| Commercial use | Allowed within ToS and usage limits | HIGH |
| Open-source support | Founding member of MapLibre community | MEDIUM |
| Source | [MapTiler Pricing](https://www.maptiler.com/cloud/pricing/) |

**Verdict:** Same as Mapbox -- safe as API-key-gated option, cannot be a default.

### Stadia Maps -- NOT RECOMMENDED

| Aspect | Finding | Confidence |
|--------|---------|------------|
| Commercial use | Requires paid subscription | HIGH |
| Free tier | Registration required, low-volume/non-commercial only | HIGH |
| Source | [Stadia Pricing](https://stadiamaps.com/pricing) |

**Verdict:** Not suitable as a default or easy add-on. Skip.

## Recommended Default Basemap Configuration

Replace the current 4 defaults with:

| ID | Label | URL | Type | Why |
|----|-------|-----|------|-----|
| `openfreemap-positron` | OpenFreeMap Positron | `https://tiles.openfreemap.org/styles/positron` | GL JSON | Replaces CARTO Positron; MIT, free, no key |
| `openfreemap-dark` | OpenFreeMap Dark Matter | `https://tiles.openfreemap.org/styles/dark` | GL JSON | Replaces CARTO Dark Matter; MIT, free, no key |
| `openfreemap-bright` | OpenFreeMap Bright | `https://tiles.openfreemap.org/styles/bright` | GL JSON | Already present; MIT, free, no key |
| `openstreetmap` | OpenStreetMap | `https://tile.openstreetmap.org/{z}/{x}/{y}.png` | Raster XYZ | Widely recognized; keep as option, borderline per policy |

### API-Key-Gated Options (future)

These would only appear when admin configures the corresponding API key:

| Provider | Key Setting | Style URL Pattern |
|----------|-------------|-------------------|
| Mapbox | `mapbox_access_token` | `mapbox://styles/mapbox/streets-v12` (etc.) |
| MapTiler | `maptiler_api_key` | `https://api.maptiler.com/maps/streets-v2/style.json?key={key}` |

## Attribution Requirements

| Provider | Required Attribution | Auto in MapLibre? |
|----------|---------------------|-------------------|
| OpenFreeMap | OpenFreeMap (c) OpenMapTiles Data from OpenStreetMap | Yes (in GL style JSON) |
| OpenStreetMap | (c) OpenStreetMap contributors | Must set on raster source |
| Mapbox | (c) Mapbox (c) OpenStreetMap contributors | Yes (in GL style JSON) |
| MapTiler | (c) MapTiler (c) OpenStreetMap contributors | Yes (in GL style JSON) |

Current attribution strings in `persistent_config.py` are correct for OSM. The CARTO attributions will be replaced with OpenFreeMap equivalents. For GL style JSON basemaps, attribution is embedded in the style spec and MapLibre's AttributionControl displays it automatically -- no `attribution` field needed in the basemap entry for these.

## Common Pitfalls

### Pitfall 1: CARTO tiles work without auth so devs assume they are free
**What goes wrong:** CARTO does not enforce API keys, so developers assume basemaps.cartocdn.com is a public service. It is not -- their ToS restricts it to enterprise/grant customers.
**How to avoid:** Do not bundle CARTO tile URLs. Use OpenFreeMap which serves the same Positron/Dark Matter styles under MIT.

### Pitfall 2: OSM tile server is not for production defaults
**What goes wrong:** Every GeoLens install hits tile.openstreetmap.org, potentially generating significant traffic from a single distributed software project.
**How to avoid:** Use OpenFreeMap as primary defaults. Keep OSM as a recognized fallback option that admins can enable.

### Pitfall 3: Theme-aware basemap IDs must be updated
**What goes wrong:** `basemap-utils.ts` hardcodes `LIGHT_PRESET_ID = 'carto-positron'` and `DARK_PRESET_ID = 'carto-dark-matter'`. Changing basemap IDs without updating these constants breaks theme-aware basemap switching.
**How to avoid:** Update both the backend defaults and the frontend preset ID constants together.

## Code Changes Required

### 1. Backend: `persistent_config.py` (~line 430)
Replace CARTO entries with OpenFreeMap equivalents. Update IDs, labels, URLs, and attribution strings.

### 2. Frontend: `basemap-utils.ts` (lines 4-5)
Update preset constants:
```typescript
export const LIGHT_PRESET_ID = 'openfreemap-positron';
export const DARK_PRESET_ID = 'openfreemap-dark';
```

### 3. Frontend: `basemap-utils.ts` (lines 7-11)
Update legacy key mapping to include old CARTO IDs:
```typescript
const LEGACY_KEY_MAP: Record<string, string> = {
  positron: 'openfreemap-positron',
  'dark-matter': 'openfreemap-dark',
  voyager: 'openfreemap-positron',
  'carto-positron': 'openfreemap-positron',
  'carto-dark-matter': 'openfreemap-dark',
};
```

### 4. OpenFreeMap style URLs (VERIFIED)
Both URLs confirmed to return valid MapLibre GL style JSON (version 8):
- `https://tiles.openfreemap.org/styles/positron` -- light theme, valid
- `https://tiles.openfreemap.org/styles/dark` -- dark theme (background `rgb(12,12,12)`), valid
- `https://tiles.openfreemap.org/styles/bright` -- already in use, valid

## Open Questions

1. **Existing user migrations** -- Users who have saved maps with `carto-positron` or `carto-dark-matter` basemap IDs will need the legacy key mapping to resolve correctly. The LEGACY_KEY_MAP update handles this for the frontend.

2. **Admin-configured CARTO basemaps** -- Admins who have explicitly configured CARTO URLs in their settings should not be affected (their custom config persists). Only the defaults change.

## Sources

### Primary (HIGH confidence)
- [CARTO basemap-styles LICENSE.md](https://github.com/CartoDB/basemap-styles/blob/master/LICENSE.md) - Hosted tile service restriction confirmed
- [CARTO Basemaps FAQ](https://docs.carto.com/faqs/carto-basemaps) - Enterprise-only confirmed
- [OSM Tile Usage Policy](https://operations.osmfoundation.org/policies/tiles/) - No hardcoding, User-Agent required
- [OpenFreeMap](https://openfreemap.org/) - MIT, free, no limits confirmed
- [OpenFreeMap GitHub](https://github.com/hyperknot/openfreemap) - License confirmed
- [Mapbox Pricing](https://www.mapbox.com/pricing) - Free tier limits
- [MapTiler Pricing](https://www.maptiler.com/cloud/pricing/) - Free tier limits

### Secondary (MEDIUM confidence)
- [Stadia Maps Pricing](https://stadiamaps.com/pricing) - Commercial requires paid plan
