# Quick Task 260318-i0y: Spatial filter technical debt - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Task Boundary

Address two technical debt items from the spatial filter panel implementation:

1. **Save map viewport across open/close** — The panel's mini-map resets to `{lon: 0, lat: 20, zoom: 1}` every time the panel opens. Save the last viewport (center + zoom) and restore it on reopen. Use a ref or zustand field — no need to persist to URL/localStorage.

2. **Backend arbitrary geometry support** — Currently backend only supports bbox via `ST_MakeEnvelope`. When the user draws a polygon, the frontend extracts a bbox from it (losing precision). Add `ST_Intersects`/`ST_Within` with `ST_GeomFromGeoJSON` so polygon geometry can be sent directly to the backend. Frontend should send the actual GeoJSON geometry when a polygon is drawn, and fall back to bbox for rectangles.

</domain>

<decisions>
## Implementation Decisions

- Viewport persistence: use a ref (not store/URL) since it's ephemeral UI state
- Backend geometry: accept optional `geometry` GeoJSON param alongside existing `bbox`. When `geometry` is provided, use it instead of bbox for spatial filtering.
- Frontend: send `geometry` param when polygon is drawn, `bbox` when rectangle is drawn
- Remove the dashed bbox overlay for polygon mode once backend accepts actual geometry (no longer misleading)

</decisions>
