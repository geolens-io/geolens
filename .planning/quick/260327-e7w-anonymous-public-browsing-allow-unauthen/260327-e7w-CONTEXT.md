# Quick Task 260327-e7w: Anonymous Public Browsing - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Task Boundary

Allow unauthenticated users to browse/search public datasets and view public maps without login. Backend already supports it (visibility filter returns public+published for anonymous). Frontend needs ProtectedRoute bypass for search, dataset detail, collections, and maps pages — UI adapts to hide edit actions and show login prompt for restricted features.

</domain>

<decisions>
## Implementation Decisions

### Navigation & Auth Prompts
- Use **inline login prompts** — replace restricted action buttons/areas with compact "Sign in to [action]" links
- No modals, no redirects — keep the user in their current browsing context
- Actions that trigger inline prompts: edit, upload, delete, save, share, export

### Route Scoping
- **Public routes:** Search/explore, dataset detail, collection detail, public map viewer
- Full browse experience available without login
- **Protected routes remain:** Admin, upload/ingest, user settings, any write/management pages

### Map Viewer Access
- **Full read-only view** for anonymous users
- All public layers render, popups work, legend visible
- Hidden controls: edit, save, share, export buttons
- No reduced/preview mode — anonymous users get the same visual experience minus write actions

### Claude's Discretion
- Implementation approach for ProtectedRoute bypass (wrapper component vs route config)
- Exact placement and styling of inline login prompts

</decisions>

<specifics>
## Specific Ideas

- Backend already handles anonymous access via visibility filter (returns public+published)
- ProtectedRoute component needs conditional bypass for designated public pages
- apiFetch() should work without auth token for public endpoints
- UI components should check auth state to conditionally render edit actions vs login prompts

</specifics>
