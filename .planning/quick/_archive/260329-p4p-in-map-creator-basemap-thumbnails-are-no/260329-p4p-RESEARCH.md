# Quick Task 260329-p4p: Basemap Thumbnail Replacement - Research

**Researched:** 2026-03-29
**Domain:** Static asset management, basemap thumbnails
**Confidence:** HIGH

## Summary

The BasemapPicker component at `frontend/src/components/builder/BasemapPicker.tsx` uses a `basemapThumbnail()` function that returns inline SVG data URIs -- colored rectangles with grid lines that barely differentiate basemaps. The task replaces these with static PNG screenshots for the 4 built-in basemaps and adds a map icon fallback for custom basemaps.

**Primary recommendation:** Capture 4 PNG screenshots manually (browser screenshot of tile services), store in `frontend/src/assets/basemaps/`, use Vite static imports, and replace the `basemapThumbnail()` function with an import-based lookup.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Use static PNG screenshots shipped as assets for the 4 built-in basemaps
- Pre-captured screenshots: crisp, fast, zero runtime cost
- Generic map icon fallback for admin-added basemaps (no thumbnail_url field, no auto-capture)
- Keep 4-column grid layout
- Increase thumbnail size slightly for better visibility
- Labels stay small (current 9px is fine)

### Claude's Discretion
- Screenshot capture method and resolution for the static PNGs
- Exact thumbnail dimensions
- Generic fallback icon design
</user_constraints>

## Current Component Structure

**File:** `frontend/src/components/builder/BasemapPicker.tsx`

The component:
- Imports `useBasemaps` hook which returns `BasemapEntry[]` from the settings API
- `basemapThumbnail(id: string)` maps 4 preset IDs to inline SVG data URIs, with a gray grid default
- Thumbnails are used in two places: collapsed row (24x24 `w-6 h-6`) and expanded grid (`w-full aspect-square`)
- Grid is `grid-cols-4 gap-1.5` with 9px labels

**4 built-in basemap IDs and tile sources:**

| ID | Tile URL | Type |
|----|----------|------|
| `openfreemap-positron` | `https://tiles.openfreemap.org/styles/positron` | Vector style JSON |
| `openfreemap-dark` | `https://tiles.openfreemap.org/styles/dark` | Vector style JSON |
| `openstreetmap` | `https://tile.openstreetmap.org/{z}/{x}/{y}.png` | Raster XYZ |
| `openfreemap-bright` | `https://tiles.openfreemap.org/styles/bright` | Vector style JSON |

## Screenshot Capture Method

**Recommended approach:** Use browser DevTools to capture screenshots from the live tile services. Open each style URL in a browser, zoom to a recognizable area (e.g., western Europe or eastern US at zoom 4-5 showing land/water/roads), and take a cropped screenshot.

**Resolution:** 320x320 pixels -- renders crisp at 160x160 CSS pixels on 2x displays. The grid thumbnails are roughly 50-60px wide in the 4-column layout, so 320px source is more than sufficient. Compress PNGs with a tool like `pngquant` or TinyPNG to keep file size under 30KB each.

**Capture URLs for browser:**
- Positron: `https://tiles.openfreemap.org/styles/positron/#5/40/-74`
- Dark: `https://tiles.openfreemap.org/styles/dark/#5/40/-74`
- Bright: `https://tiles.openfreemap.org/styles/bright/#5/40/-74`
- OSM: `https://tile.openstreetmap.org/5/9/12.png` (single tile at z5 -- or use an OSM viewer)

Alternatively, use a headless MapLibre screenshot tool, but manual capture is simpler for 4 images.

## Static Asset Strategy

**Vite static imports (recommended):**

The project has no existing `src/assets/` directory. Create `frontend/src/assets/basemaps/` and use Vite's standard static import pattern:

```typescript
import positronThumb from '@/assets/basemaps/positron.png';
import darkThumb from '@/assets/basemaps/dark.png';
import osmThumb from '@/assets/basemaps/osm.png';
import brightThumb from '@/assets/basemaps/bright.png';
```

Vite resolves these imports to hashed URLs at build time (e.g., `/assets/positron-abc123.png`), providing cache-busting and tree-shaking. This is the standard Vite pattern -- no configuration needed.

**Why not `public/` folder:** Public folder files are served as-is without hashing. Since these are small images bundled with the component, `src/assets/` imports are the better convention -- they get cache-busting, are type-safe, and are only included if actually imported.

## Fallback Icon for Custom Basemaps

**Recommended:** Use a Lucide icon (`Globe` or `Map`) rendered as an inline SVG, or a simple custom SVG showing a stylized map. Since the existing project uses `lucide-react` extensively, the simplest approach:

```typescript
import { Globe } from 'lucide-react';

// For the fallback, render the icon directly instead of an <img>
// Or generate a data URI from a simple SVG
```

However, since the current code uses `<img src={...}>` for thumbnails, the cleanest approach is a static fallback SVG data URI that looks like a map/globe icon rather than the current gray grid. This avoids conditional rendering between `<img>` and `<Icon>`.

**Simple fallback SVG (globe/map icon):**

```typescript
const FALLBACK_THUMBNAIL = `data:image/svg+xml,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="160" viewBox="0 0 160 160">' +
  '<rect fill="#e5e7eb" width="160" height="160" rx="4"/>' +
  '<circle cx="80" cy="72" r="36" fill="none" stroke="#9ca3af" stroke-width="2"/>' +
  '<ellipse cx="80" cy="72" rx="16" ry="36" fill="none" stroke="#9ca3af" stroke-width="1.5"/>' +
  '<line x1="44" y1="72" x2="116" y2="72" stroke="#9ca3af" stroke-width="1.5"/>' +
  '<line x1="80" y1="36" x2="80" y2="108" stroke="#9ca3af" stroke-width="1.5"/>' +
  '<text x="80" y="132" text-anchor="middle" font-size="12" fill="#9ca3af" font-family="sans-serif">Map</text>' +
  '</svg>'
)}`;
```

This renders a globe with latitude/longitude lines -- clearly reads as "map" at small sizes.

## Implementation Plan

### Refactored `basemapThumbnail()` function:

```typescript
import positronThumb from '@/assets/basemaps/positron.png';
import darkThumb from '@/assets/basemaps/dark.png';
import osmThumb from '@/assets/basemaps/osm.png';
import brightThumb from '@/assets/basemaps/bright.png';

const BUILTIN_THUMBNAILS: Record<string, string> = {
  'openfreemap-positron': positronThumb,
  'openfreemap-dark': darkThumb,
  'openstreetmap': osmThumb,
  'osm-standard': osmThumb,  // legacy alias
  'openfreemap-bright': brightThumb,
};

const FALLBACK_THUMBNAIL = `data:image/svg+xml,...`; // globe SVG above

export function basemapThumbnail(id: string): string {
  return BUILTIN_THUMBNAILS[id] ?? FALLBACK_THUMBNAIL;
}
```

### Thumbnail size increase:
Current collapsed: `w-6 h-6` (24px). Consider bumping to `w-8 h-8` (32px).
Current expanded grid: `w-full aspect-square` -- already fills the column. The grid items use `p-1` padding. Could increase gap from `gap-1.5` to `gap-2` for breathing room.

## Common Pitfalls

### PNG file size
**What goes wrong:** Uncompressed 320x320 PNGs can be 200KB+ each.
**How to avoid:** Run through `pngquant --quality=65-80` or similar. Target under 30KB per image. The 4 images should total under 120KB.

### Vite import types
**What goes wrong:** TypeScript may not recognize `.png` imports without a type declaration.
**How to avoid:** Vite's `vite/client` types (included by default in `tsconfig.json` via `"types": ["vite/client"]`) already declare `*.png` modules returning `string`. Verify this exists in the project's tsconfig. If not, add a `src/vite-env.d.ts` with `/// <reference types="vite/client" />`.

### OSM tile screenshot
**What goes wrong:** OSM raster tiles are 256x256 per tile. A single tile at z5 may not look great as a thumbnail.
**How to avoid:** Use a map viewer (e.g., openstreetmap.org) to capture a 320x320 crop showing a recognizable area, not a single raw tile.

## Sources

- `frontend/src/components/builder/BasemapPicker.tsx` -- current implementation (read directly)
- `frontend/src/lib/basemap-utils.ts` -- basemap ID constants and style resolution
- `backend/app/persistent_config.py` -- built-in basemap definitions with URLs
- Vite static asset handling: standard `import` pattern, no config needed (HIGH confidence from Vite docs)
