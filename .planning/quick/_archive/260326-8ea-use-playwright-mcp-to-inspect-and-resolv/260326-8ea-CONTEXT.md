# Quick Task 260326-8ea: Fix map console errors (outline-width) - Context

**Gathered:** 2026-03-26
**Status:** Ready for planning

<domain>
## Task Boundary

Fix console errors on map page caused by invalid `outline-width` paint property in layer data. Three errors cascade: unknown paint prop → addLayer failure → setPaintProperty on non-existing layer.

URL: http://localhost:8080/maps/9ae7d08a-6e68-482c-a044-cdf07ab53412
Source: `frontend/src/components/builder/map-sync.ts`

</domain>

<decisions>
## Implementation Decisions

### Fix Scope
- Targeted fix: add `outline-width` and `outline-color` (non-prefixed) to `CUSTOM_PAINT_PROPS` set
- Do NOT add a general safety net that strips unknown props — keep it explicit

### Data Migration
- Both frontend + backend migration for long-term robustness
- Frontend: tolerate both `outline-width` and `_outline-width` forms in stripCustomProps and outline layer creation
- Backend: Alembic migration to normalize `outline-width` → `_outline-width` and `outline-color` → `_outline-color` in map_layers paint JSON

### Error Handling
- Wrap `addLayer` in try-catch; if it fails, skip `finalizeLayer` and log a warning
- Prevents cascading "Cannot style non-existing layer" errors

</decisions>

<specifics>
## Specific Ideas

- Error source: layer `15bafb2c-68e0-4d06-9a33-af6c71386ca7` has `outline-width` in paint JSON (missing `_` prefix)
- `CUSTOM_PAINT_PROPS` at map-sync.ts:9 only contains `_outline-width`, `_outline-color` (with underscore)
- `stripCustomProps` at map-sync.ts:101 passes `outline-width` through to MapLibre
- `finalizeLayer` at map-sync.ts:116 doesn't guard against addLayer failure
- Outline layer creation (map-sync.ts:276-289) reads `_outline-width` — should also check `outline-width` as fallback

</specifics>
