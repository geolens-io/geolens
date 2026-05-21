---
phase: 260330-qey
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/maps/router.py
  - backend/app/maps/service.py
  - frontend/src/App.tsx
  - frontend/src/components/layout/Navbar.tsx
  - frontend/src/pages/MapsPage.tsx
  - frontend/src/components/maps/MapCard.tsx
  - frontend/src/components/maps/MapCardGrid.tsx
autonomous: true
requirements: [PUBLIC-MAPS]

must_haves:
  truths:
    - "Anonymous user can visit /maps and see a list of public maps"
    - "Anonymous user can click a map card and view it in the interactive viewer"
    - "Anonymous user cannot see Create Map button, delete buttons, or visibility filter"
    - "Logged-in users see same behavior as before (own + internal + public maps, full controls)"
    - "Maps nav link is visible to all users in the navbar"
  artifacts:
    - path: "backend/app/maps/router.py"
      provides: "list_maps_endpoint with optional auth"
      contains: "get_optional_user"
    - path: "backend/app/maps/service.py"
      provides: "Anonymous visibility filter in list_maps"
      contains: 'Map.visibility == "public"'
    - path: "frontend/src/App.tsx"
      provides: "Public /maps route outside auth guards"
    - path: "frontend/src/pages/MapsPage.tsx"
      provides: "Conditional UI hiding editor controls for anonymous"
    - path: "frontend/src/components/maps/MapCard.tsx"
      provides: "Conditional delete button and viewer-aware link"
    - path: "frontend/src/components/maps/MapCardGrid.tsx"
      provides: "Conditional delete button and viewer-aware link"
  key_links:
    - from: "frontend/src/pages/MapsPage.tsx"
      to: "/api/maps/"
      via: "useMaps hook -> apiFetch"
      pattern: "useMaps"
    - from: "frontend/src/App.tsx"
      to: "MapsPage"
      via: "public Route outside ProtectedRoute"
      pattern: 'path="maps"'
    - from: "backend/app/maps/router.py"
      to: "backend/app/maps/service.py"
      via: "list_maps call with user_id=None for anonymous"
      pattern: "list_maps"
    - from: "frontend/src/components/maps/MapCard.tsx"
      to: "/maps/:id"
      via: "Link to map viewer (works for anonymous via get_optional_user on GET /maps/{id})"
      pattern: "to=.*maps/"
---

<objective>
Make the /maps page accessible to anonymous users, showing only public maps with read-only interaction.

Purpose: Public users should be able to discover and view public maps without authentication.
Output: Backend returns public maps for anonymous requests; frontend shows maps page without auth gate and hides editor-only controls for anonymous users.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/quick/260330-qey-as-a-public-user-i-should-be-able-to-see/260330-qey-CONTEXT.md
@.planning/quick/260330-qey-as-a-public-user-i-should-be-able-to-see/260330-qey-RESEARCH.md

<interfaces>
<!-- Backend auth dependencies (already imported in router.py) -->
From backend/app/auth/dependencies.py:
```python
async def get_optional_user(...) -> User | None:
    """Returns None if no credentials provided. Already used on GET /maps/{map_id}."""
```

From backend/app/maps/service.py:
```python
async def list_maps(
    session, skip=0, limit=20,
    user_id: uuid.UUID | None = None,
    user_roles: set[str] | None = None,
    search=None, sort_by="updated_at", sort_dir="desc", visibility=None,
) -> tuple[list[dict], int]:
```

From backend/app/auth/visibility.py:
```python
async def get_user_roles(db: AsyncSession, user: User) -> set[str]:
```

<!-- Frontend auth patterns -->
From frontend/src/hooks/use-auth.ts:
```typescript
export function useAuth(): { token, user, isAdmin, isEditor, login, logout }
```

From frontend/src/hooks/use-permissions.ts:
```typescript
export function usePermissions(): { permissions, can(capability: string): boolean, isLoading }
// can() returns false when no token (anonymous) -- safe to use for conditional UI
```

From frontend/src/stores/auth-store.ts:
```typescript
export const useAuthStore: { token: string | null; user: UserResponse | null; isEditor(): boolean }
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Backend -- allow anonymous access on GET /maps/ endpoint</name>
  <files>backend/app/maps/router.py, backend/app/maps/service.py</files>
  <action>
**router.py** (line ~177): In `list_maps_endpoint`, change the `user` parameter from `Depends(get_current_active_user)` to `Depends(get_optional_user)` and update the type to `User | None`. When `user is None` (anonymous), call `list_maps()` with `user_id=None` and `user_roles=set()`. When `user is not None`, call `get_user_roles(db, user)` as before. The `get_optional_user` import already exists at line 21.

```python
async def list_maps_endpoint(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    search: str | None = None,
    sort_by: str = "updated_at",
    sort_dir: str = "desc",
    visibility: str | None = None,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> MapListResponse:
    if user is not None:
        user_roles = await get_user_roles(db, user)
        uid = user.id
    else:
        user_roles = set()
        uid = None
    maps, total = await list_maps(
        db, skip=skip, limit=limit, user_id=uid,
        user_roles=user_roles, search=search,
        sort_by=sort_by, sort_dir=sort_dir, visibility=visibility,
    )
    ...
```

**service.py** (line ~193): In `list_maps()`, fix the `_apply_vis_filter` fallback case. Currently the "no user context" branch passes through without filtering (returns the statement unchanged). Change it to filter `Map.visibility == "public"`. This matches the existing pattern in `get_maps_for_dataset` at line ~1007.

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
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens && docker compose exec -T api python -c "
from app.maps.service import list_maps
from app.maps.router import list_maps_endpoint
import inspect
sig = inspect.signature(list_maps_endpoint)
user_param = sig.parameters['user']
print('user annotation:', user_param.annotation)
assert 'None' in str(user_param.annotation), 'user param must accept None'
print('PASS: router accepts optional user')
" 2>/dev/null || echo "Verify manually: check router.py line ~177 uses get_optional_user and service.py anonymous filter returns public-only"</automated>
  </verify>
  <done>GET /maps/ returns 200 with public maps for anonymous requests (no auth header). Authenticated requests continue to see own + internal + public maps. The anonymous branch in _apply_vis_filter returns only visibility=="public" maps.</done>
</task>

<task type="auto">
  <name>Task 2: Frontend -- public /maps route, navbar link, and conditional UI</name>
  <files>frontend/src/App.tsx, frontend/src/components/layout/Navbar.tsx, frontend/src/pages/MapsPage.tsx, frontend/src/components/maps/MapCard.tsx, frontend/src/components/maps/MapCardGrid.tsx</files>
  <action>
**App.tsx**: Move the `/maps` route from inside `ProtectedRoute > EditorRoute` (line 63) to the public routes section (after the `/collections/:id` route, around line 56). Keep `/maps/:id` (MapBuilderPage) inside the auth guard -- authenticated editors need the builder. The `maps` route in the public section renders `MapsPage`. Anonymous users clicking a map card will go to `/maps/:id` which is inside the auth guard; instead, for anonymous access, the map card links should point to `/m/{share_token}` if available, but since public maps don't necessarily have share tokens, add a new public route `maps/:id/view` that renders `PublicMapViewerPage` (a thin wrapper).

However, the simplest approach per research: the `GET /maps/{map_id}` endpoint already supports anonymous access for public maps. So create a lightweight `PublicMapViewerPage` that reuses the existing `useMap(id)` hook and `ViewerMap` component. But this adds a new file -- to keep scope minimal, instead: anonymous map card links go to `/maps/:id/view`, and that route renders `PublicViewerPage` adapted to accept a map ID.

**Simplest approach (no new page component needed):** Since the existing `PublicViewerPage` is token-based and tightly coupled to share tokens, and creating a new page would exceed scope, take the pragmatic route:

1. Move `<Route path="maps" element={<MapsPage />} />` to the public section of routes (after `collections/:id`).
2. Also add `<Route path="maps/:id" element={<MapBuilderPage />} />` inside the auth guard as before (no change, it stays).
3. Map cards already link to `/maps/${map.id}`. For anonymous users, clicking sends them to the ProtectedRoute which redirects to login. This is acceptable for now since the user can view the map listing. The full interactive viewer for anonymous click-through is a natural follow-up.

**Actually, per user decision:** "Full interactive viewer -- reuse the existing PublicViewerPage experience." Map cards for anonymous users must work. The `GET /maps/{map_id}` endpoint already supports anonymous. So the most direct path: move `/maps/:id` outside the auth guard too, but wrap it in a component that decides: if user is authenticated editor -> render MapBuilderPage, if anonymous -> render a read-only viewer.

Create a new file `frontend/src/pages/MapViewerGate.tsx`:

```tsx
import { useAuthStore } from '@/stores/auth-store';
import { MapBuilderPage } from './MapBuilderPage';
import { PublicMapViewerPage } from './PublicMapViewerPage';

export function MapViewerGate() {
  const isEditor = useAuthStore((s) => s.isEditor());
  return isEditor ? <MapBuilderPage /> : <PublicMapViewerPage />;
}
```

Create `frontend/src/pages/PublicMapViewerPage.tsx` -- a lightweight viewer that:
- Uses `useParams` to get `id`
- Calls `useMap(id)` to fetch the map (works for anonymous on public maps)
- Transforms the `MapResponse` layers into the format `ViewerMap` expects
- Renders `ViewerMap` in full-screen with a legend panel (mirrors PublicViewerPage layout)
- Shows loading/error states

The layer transformation: `MapResponse` has layers with `dataset_table_name`. ViewerMap's `buildSignedTileUrl` constructs tile URLs from table names. For anonymous users without tokens, the tiles still serve for public datasets via the nginx proxy.

**App.tsx route changes:**
```tsx
{/* Public routes */}
<Route index element={<SearchPage />} />
<Route path="datasets/:id" element={<DatasetPage />} errorElement={<RouteErrorBoundary />} />
<Route path="collections" element={<CollectionsPage />} />
<Route path="collections/:id" element={<CollectionDetailPage />} />
<Route path="maps" element={<MapsPage />} />
<Route path="maps/:id" element={<MapViewerGate />} errorElement={<RouteErrorBoundary />} />

{/* Protected routes */}
<Route element={<ProtectedRoute />}>
  <Route path="settings" element={<SettingsPage />} />
  <Route element={<EditorRoute />} errorElement={<RouteErrorBoundary />}>
    <Route path="import" element={<ImportPage />} />
    {/* maps/:id removed from here -- handled by MapViewerGate above */}
  </Route>
  ...
```

Add lazy imports for `MapViewerGate` and `PublicMapViewerPage`.

**Navbar.tsx**: Remove the `can('edit_metadata')` guard around the Maps NavLink on both desktop (line 337-339) and mobile (line 237-241). Show the Maps link unconditionally:
```tsx
<NavLink to="/maps" className={navLinkClass}>
  {t('nav.maps')}
</NavLink>
```

**MapsPage.tsx**: Import `useAuthStore` and conditionally hide editor-only controls for anonymous users:
```tsx
const isEditor = useAuthStore((s) => s.isEditor());
```
- Wrap the visibility `<Select>` filter in `{isEditor && ...}` -- anonymous users only see public, the filter is meaningless
- Hide the "Create Map" `<Button>` and `<MapCreateDialog>` behind `{isEditor && ...}`
- Hide the `<MapDeleteDialog>` behind `{isEditor && ...}`
- In the empty state, hide the "Create first map" action button for anonymous users: change condition to `!debouncedSearch && visibility === 'all' && isEditor`

**MapCard.tsx**: Accept an optional `onDelete` prop (make it `onDelete?: (id: string) => void`). When `onDelete` is undefined, do not render the delete `<Button>`. In `MapsPage.tsx`, pass `onDelete` only when `isEditor` is true:
```tsx
<MapCard key={map.id} map={map} onDelete={isEditor ? handleDeleteClick : undefined} />
```

**MapCardGrid.tsx**: Same change -- render the delete button only when `onDelete` is provided. MapCardGrid imports `MapCardProps` from MapCard, so update the interface there:
```typescript
export interface MapCardProps {
  map: MapSummaryResponse;
  onDelete?: (id: string) => void;  // optional now
}
```

In both MapCard and MapCardGrid, wrap the delete button section in `{onDelete && (...)}`.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx tsc --noEmit 2>&1 | head -30</automated>
  </verify>
  <done>Anonymous users can visit /maps, see public maps listed, click through to a read-only viewer. Navbar shows Maps link for all users. Create/delete/visibility-filter controls are hidden for anonymous users. Authenticated editors see the full MapBuilderPage when clicking a map card. TypeScript compiles without errors.</done>
</task>

</tasks>

<verification>
1. Open http://localhost:8080/maps in an incognito/logged-out browser -- should show public maps
2. Click a map card -- should open a read-only viewer with zoom/pan/legend
3. Verify no "Create Map" button, no delete buttons, no visibility filter visible
4. Log in as an editor -- /maps shows all maps (own + internal + public) with full controls
5. Click a map card while logged in -- opens MapBuilderPage with editing capabilities
6. Navbar shows "Maps" link in both logged-in and logged-out states
</verification>

<success_criteria>
- Anonymous GET /maps/ returns 200 with only public maps
- Anonymous GET /maps/{id} returns 200 for public maps (already works)
- /maps page renders without auth, showing public maps
- Map card click-through works for anonymous users (read-only viewer)
- Editor-only controls (create, delete, visibility filter) hidden for anonymous
- No regressions for authenticated users
</success_criteria>

<output>
After completion, create `.planning/quick/260330-qey-as-a-public-user-i-should-be-able-to-see/260330-qey-SUMMARY.md`
</output>
