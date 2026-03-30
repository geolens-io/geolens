# Quick Task 260330-qey: Public Users Should See Public Maps - Research

**Researched:** 2026-03-30
**Domain:** Auth guards, maps routing (backend + frontend)
**Confidence:** HIGH

## Summary

The task requires making the `/maps` page accessible to anonymous users, showing only public maps. All the required patterns already exist in the codebase -- optional auth, public tile URLs, and anonymous-aware UI. The changes are surgical: swap one auth dependency in the backend, move one route outside the auth guard in the frontend, and conditionally hide editor-only UI for anonymous users.

**Primary recommendation:** Swap `get_current_active_user` to `get_optional_user` on the backend list endpoint, add anonymous filtering in the service, move the frontend `/maps` route outside `ProtectedRoute`/`EditorRoute`, and link map cards to `/maps/:id` (which already supports anonymous access for public maps).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Use the existing `/maps` page -- no new route or gallery page
- When not logged in, the `/maps` page should show public maps
- When logged in, existing behavior continues (own maps + internal + public)
- Fully anonymous -- no login required to browse `/maps`
- The `/maps` route must be accessible without authentication
- Full interactive viewer -- reuse the existing PublicViewerPage experience
- Public users can zoom, pan, click features, see legend, toggle layers

### Claude's Discretion
- How to handle the click-through from map card to viewer (share token generation vs direct map access)
- Whether to show a reduced header/nav for anonymous users
</user_constraints>

## Findings

### 1. Backend `GET /maps/` Auth

**Current state:** Line 177 of `router.py` uses `Depends(get_current_active_user)` which returns 401 for anonymous requests.

**Fix:** Change to `Depends(get_optional_user)` and make `user` type `User | None`.

The `get_optional_user` dependency (auth/dependencies.py:44-85) already exists and returns `None` for anonymous requests without raising errors. It's used on `GET /maps/{map_id}` and `GET /maps/{map_id}/thumbnail/`.

**Confidence: HIGH** -- pattern is identical to existing endpoints.

### 2. Backend `list_maps` Service - Anonymous Filtering

**Current state:** `list_maps()` in service.py (line 154) accepts `user_id` and `user_roles`. The `_apply_vis_filter` inner function handles admin, authenticated, and a "no user context" legacy fallback -- but the legacy fallback just passes through without filtering, which is wrong for anonymous users.

**Fix:** Add an anonymous case to `_apply_vis_filter`:
```python
def _apply_vis_filter(stmt):
    if is_admin:
        return stmt
    if user_id is not None:
        return stmt.where(
            or_(
                Map.created_by == user_id,
                Map.visibility.in_(["internal", "public"]),
            )
        )
    # Anonymous -- public maps only
    return stmt.where(Map.visibility == "public")
```

The `get_maps_for_dataset` function (line 956) already implements this exact pattern correctly at line 1007: `stmt.where(Map.visibility == "public")` when `user_id is None`.

**Router change:** When `user is None`, pass `user_id=None` and `user_roles=set()` to `list_maps()`.

**Confidence: HIGH** -- the identical anonymous filter pattern exists in `get_maps_for_dataset`.

### 3. Frontend Route Protection

**Current state:** In `App.tsx`, the `/maps` route is nested under two guards:
```
<ProtectedRoute>          // redirects to /login if no token
  <EditorRoute>           // shows "forbidden" if user lacks editor role
    <Route path="maps">   // MapsPage
```

**Fix:** Move `<Route path="maps" element={<MapsPage />} />` to the public routes section (alongside `/`, `/collections`, `/datasets/:id`). This makes it accessible without authentication.

The `AppLayout` (which provides Navbar + footer) already handles anonymous users gracefully -- the Navbar already shows a "Sign In" button when `user` is null and conditionally hides editor-only nav items.

**Confidence: HIGH** -- the Search page and Collections page already work this way.

### 4. Frontend MapsPage Component

**Current state:** `MapsPage.tsx` does not directly reference auth state. It calls `useMaps()` which calls `listMaps()` which uses `apiFetch()`.

**Issue:** `apiFetch()` uses `authenticatedFetch()` which attaches a Bearer token if available, but calls `useAuthStore.getState().logout()` and throws on 401. For anonymous users hitting an endpoint that returns 200 (not 401), this works fine -- `authenticatedFetch` adds no token when none exists, and the request proceeds normally.

**No change needed in MapsPage.tsx for basic functionality.** The `apiFetch` client will send the request without a token, and the backend (once updated) will return public maps.

**Conditional UI changes needed:**
- Hide the "Create Map" button and "New Map" dialog for anonymous users
- Hide the delete button on map cards for anonymous users
- Hide the visibility filter dropdown for anonymous users (they can only see public)
- Hide the "private"/"internal" options in visibility filter, or hide the filter entirely

**Confidence: HIGH** -- `apiFetch` already works without a token (it just doesn't attach one).

### 5. Map Card Click-Through (Claude's Discretion)

**Current state:** Both `MapCard.tsx` and `MapCardGrid.tsx` link to `/maps/${map.id}` (the MapBuilder page).

**The MapBuilder route** (`/maps/:id`) is behind `ProtectedRoute + EditorRoute`, so anonymous users would be redirected to login.

**However**, the backend `GET /maps/{map_id}` endpoint (router.py line 247) already uses `get_optional_user` and correctly returns public maps to anonymous users (line 264-268).

**Decision for click-through:** Two options:

**Option A (Recommended): Link to `/maps/:id` but add a read-only viewer route.** Create a new route `/maps/:id/view` (or just make `/maps/:id` work as read-only for anonymous users). This requires extracting the viewer from MapBuilderPage or reusing PublicViewerPage with a map ID.

**Option B: Auto-generate share tokens for public maps and link to `/m/:token`.** This adds complexity (every public map needs a share token) and goes against the existing model where share tokens are explicit opt-in.

**Recommended approach:** Route anonymous users from map cards to a public map viewer. The simplest path is to make the `GET /maps/{map_id}` API already works for anonymous users. The frontend just needs a viewer page that loads a map by ID instead of by share token. The `PublicViewerPage` already does 90% of this -- it just needs to accept a map ID path.

The cleanest approach: add a route `/maps/:id` that renders PublicViewerPage-like behavior for anonymous users. Since MapBuilderPage is behind auth guards, add a separate public-accessible route that reuses ViewerMap. The map card can always link to `/maps/:id`; authenticated users get the builder, anonymous users get a read-only viewer.

**Confidence: MEDIUM** -- multiple valid approaches, recommendation based on minimal changes.

### 6. PublicViewerPage Reuse

**Current state:** `PublicViewerPage` fetches data via `useSharedMap(token)` which calls `GET /maps/shared/{token}`. This returns a `SharedMapResponse` with pre-computed `tile_url` per layer (using `/tiles/public/` prefix for public datasets).

**The MapBuilder** fetches via `useMap(id)` which calls `GET /maps/{id}`. This returns a `MapResponse` with layer metadata but no `tile_url` -- the ViewerMap builds tile URLs from `table_name` using `buildSignedTileUrl()`.

**Key difference:** SharedMapResponse includes `tile_url` per layer; MapResponse includes `dataset_table_name` per layer. The ViewerMap already handles both paths.

**For anonymous map viewing**, the ViewerMap's `buildSignedTileUrl` will produce URLs like `/api/tiles/data.{table}/{z}/{x}/{y}.pbf` without any auth params (since `tokenMap` will be empty for anonymous users). This should work for public datasets since the tile endpoint should serve public data without auth.

**Recommendation:** Create a lightweight `PublicMapViewerPage` that:
1. Fetches map via `GET /maps/{id}` (already supports anonymous)
2. Transforms `MapResponse` layers to the format ViewerMap expects
3. Renders ViewerMap in full-screen mode (like PublicViewerPage)

**Confidence: HIGH** -- the backend endpoint and ViewerMap both support this already.

### 7. Frontend Auth Guards

**ProtectedRoute** (`components/auth/ProtectedRoute.tsx`): Checks `useAuthStore.token`. If absent, saves current path to sessionStorage and redirects to `/login`. Pure redirect guard, no API calls.

**EditorRoute** (`components/auth/EditorRoute.tsx`): Checks `useAuthStore.isEditor()`. If false, renders a "forbidden" message inline. No redirect.

**Pattern for conditional UI:** The app already uses `useAuth()` hook to get `user` (or null) and `usePermissions()` hook to check `can('edit_metadata')`. The Navbar already does this:
```tsx
{can('edit_metadata') && <NavLink to="/maps">Maps</NavLink>}
```

The Navbar Maps link is currently hidden for anonymous users. It needs to be shown always.

**Confidence: HIGH** -- existing patterns are clear and consistent.

### 8. Navbar Maps Link Visibility

**Current state:** Both desktop nav (line 337-339) and mobile nav (line 238-240) conditionally show the Maps link:
```tsx
{can('edit_metadata') && (
  <NavLink to="/maps">Maps</NavLink>
)}
```

**Fix:** Show the Maps link unconditionally (remove the `can('edit_metadata')` guard).

**Confidence: HIGH** -- straightforward.

## Architecture Pattern

### Change Map

| Layer | File | Change |
|-------|------|--------|
| Backend router | `backend/app/maps/router.py` | `list_maps_endpoint`: change `get_current_active_user` to `get_optional_user`, handle `user=None` |
| Backend service | `backend/app/maps/service.py` | `list_maps()`: fix anonymous fallback to filter `visibility == "public"` |
| Frontend routing | `frontend/src/App.tsx` | Move `/maps` route from inside `ProtectedRoute/EditorRoute` to public section; add a public `/maps/:id` viewer route |
| Frontend navbar | `frontend/src/components/layout/Navbar.tsx` | Show Maps nav link unconditionally |
| Frontend MapsPage | `frontend/src/pages/MapsPage.tsx` | Conditionally hide create/delete/visibility-filter for anonymous |
| Frontend MapCard | `frontend/src/components/maps/MapCard.tsx` | Conditionally hide delete button for anonymous |
| Frontend MapCardGrid | `frontend/src/components/maps/MapCardGrid.tsx` | Conditionally hide delete button for anonymous |
| Frontend viewer | New or extended component | Public map viewer page for anonymous `/maps/:id` access |

### Click-Through Recommendation

For anonymous users clicking a map card, route to a public viewer at `/maps/:id`. Implementation:

1. Keep `/maps/:id` (MapBuilderPage) inside the auth guard for editing
2. Add a new route like `/maps/:id/view` outside the auth guard that renders a read-only ViewerMap
3. In the map cards, detect auth state: link to `/maps/:id` for authenticated users, `/maps/:id/view` for anonymous
4. Or simpler: add the `/maps/:id` route at the public level with a component that renders either MapBuilderPage (if authenticated with editor role) or a read-only viewer (if anonymous)

**Simplest approach:** Since MapBuilderPage is complex and the viewer UX for anonymous users should match PublicViewerPage, create a thin wrapper component that decides: authenticated editor -> MapBuilderPage, anonymous -> PublicMapViewer. Register it outside the auth guard.

## Common Pitfalls

### Pitfall 1: apiFetch Logout on 401
**What goes wrong:** If the backend returns 401 for any reason during an anonymous session, `apiFetch` calls `logout()` and throws. This is harmless when no user is logged in but could be confusing.
**How to avoid:** Ensure the backend `list_maps` endpoint never returns 401 for anonymous users. Using `get_optional_user` guarantees this.

### Pitfall 2: Tile Access for Public Datasets
**What goes wrong:** Map tiles require authentication. Anonymous users see a map listing but tiles fail to load.
**How to avoid:** The tile endpoint must serve public datasets without auth. Verify the `/api/tiles/` endpoint supports unauthenticated access for public data. The share token flow uses `/tiles/public/` prefix which may have separate nginx routing.

### Pitfall 3: MapBuilderPage vs Viewer Confusion
**What goes wrong:** Anonymous user clicks a map card, gets redirected to login because MapBuilderPage is behind auth.
**How to avoid:** Map card links must resolve to a route that works for anonymous users. Either change the link target based on auth state or register a route handler that dispatches appropriately.

### Pitfall 4: Visibility Filter Confusion
**What goes wrong:** Anonymous user sees "private"/"internal" options in the visibility filter dropdown, selects one, gets zero results.
**How to avoid:** Hide or disable the visibility filter for anonymous users, or lock it to "public" only.

## Sources

### Primary (HIGH confidence)
- `backend/app/maps/router.py` -- current auth dependencies on all endpoints
- `backend/app/maps/service.py` -- `list_maps()` and `get_maps_for_dataset()` visibility logic
- `backend/app/auth/dependencies.py` -- `get_optional_user` vs `get_current_active_user`
- `frontend/src/App.tsx` -- route guard structure
- `frontend/src/components/auth/ProtectedRoute.tsx` -- token check guard
- `frontend/src/components/auth/EditorRoute.tsx` -- editor role guard
- `frontend/src/pages/MapsPage.tsx` -- maps page component
- `frontend/src/pages/PublicViewerPage.tsx` -- public viewer reference
- `frontend/src/components/viewer/ViewerMap.tsx` -- tile URL construction
- `frontend/src/components/layout/Navbar.tsx` -- nav link visibility
- `frontend/src/api/client.ts` -- apiFetch anonymous behavior
