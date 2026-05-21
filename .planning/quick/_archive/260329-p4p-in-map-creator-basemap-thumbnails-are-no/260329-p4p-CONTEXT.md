# Quick Task 260329-p4p: Basemap thumbnails are not descriptive or useful - Context

**Gathered:** 2026-03-29
**Status:** Ready for planning

<domain>
## Task Boundary

In map creator, basemap thumbnails are not descriptive or useful. Current thumbnails are inline SVGs showing colored rectangles with grid lines — they barely differentiate basemaps visually.

</domain>

<decisions>
## Implementation Decisions

### Thumbnail Source
- Use static PNG screenshots shipped as assets for the 4 built-in basemaps (openfreemap-positron, openfreemap-dark, openstreetmap, openfreemap-bright)
- Pre-captured screenshots: crisp, fast, zero runtime cost

### Custom Basemap Handling
- Generic map icon fallback for admin-added basemaps without pre-baked thumbnails
- No thumbnail_url field or auto-capture — keep it simple

### Layout & Density
- Keep 4-column grid layout
- Increase thumbnail size slightly for better visibility
- Labels stay small (current 9px is fine)

### Claude's Discretion
- Screenshot capture method and resolution for the static PNGs
- Exact thumbnail dimensions
- Generic fallback icon design

</decisions>

<specifics>
## Specific Ideas

- Replace `basemapThumbnail()` inline SVG function with static image imports
- 4 built-in basemaps need screenshots: positron, dark, openstreetmap, bright
- Fallback SVG should be a recognizable map/globe icon, not just a gray grid

</specifics>
