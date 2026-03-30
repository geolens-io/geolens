# Quick Task 260330-qey: Public users should be able to see public maps - Context

**Gathered:** 2026-03-30
**Status:** Ready for planning

<domain>
## Task Boundary

As a public user, I should be able to see public maps.

</domain>

<decisions>
## Implementation Decisions

### Discovery Surface
- Use the existing `/maps` page — no new route or gallery page
- When not logged in, the `/maps` page should show public maps
- When logged in, existing behavior continues (own maps + internal + public)

### Access Without Auth
- Fully anonymous — no login required to browse `/maps`
- The `/maps` route must be accessible without authentication

### Map Interaction Depth
- Full interactive viewer — reuse the existing PublicViewerPage experience
- Public users can zoom, pan, click features, see legend, toggle layers

### Claude's Discretion
- How to handle the click-through from map card to viewer (share token generation vs direct map access)
- Whether to show a reduced header/nav for anonymous users

</decisions>

<specifics>
## Specific Ideas

- The `/maps` page currently requires auth — needs to become optionally authenticated
- Backend `GET /maps/` endpoint needs to support anonymous access, returning only public maps
- Map cards should link to the full viewer for anonymous users

</specifics>
