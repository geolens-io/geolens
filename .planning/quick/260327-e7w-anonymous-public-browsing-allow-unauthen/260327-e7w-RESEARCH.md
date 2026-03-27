# Quick Task: Anonymous Public Browsing - Research

**Researched:** 2026-03-27
**Domain:** Frontend route protection + backend auth dependency scoping
**Confidence:** HIGH

## Summary

The task requires two coordinated changes: (1) frontend route restructuring so search, dataset detail, collections, and map viewer pages render without authentication, and (2) backend endpoint changes so several read-only endpoints accept anonymous requests.

The frontend currently wraps ALL app pages inside a single `<ProtectedRoute>` in `App.tsx`. The cleanest approach is to split the route tree into public and protected subtrees, both sharing `<AppLayout>`. The backend has inconsistent anonymous support -- search and some dataset endpoints already use `get_optional_user`, but the single-dataset GET, collections list/detail, maps list, and map detail endpoints require `get_current_active_user` and will 401 anonymous requests.

**Primary recommendation:** Split the route tree in App.tsx into public routes (search, dataset detail, collections, collection detail) and protected routes (settings, import, maps management, admin). Backend read endpoints for datasets, collections, and maps need `get_optional_user` with visibility filtering.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Use **inline login prompts** -- replace restricted action buttons/areas with compact "Sign in to [action]" links
- No modals, no redirects -- keep the user in their current browsing context
- Actions that trigger inline prompts: edit, upload, delete, save, share, export
- **Public routes:** Search/explore, dataset detail, collection detail, public map viewer
- **Protected routes remain:** Admin, upload/ingest, user settings, any write/management pages
- **Full read-only view** for anonymous users on map viewer
- All public layers render, popups work, legend visible
- Hidden controls: edit, save, share, export buttons
- No reduced/preview mode

### Claude's Discretion
- Implementation approach for ProtectedRoute bypass (wrapper component vs route config)
- Exact placement and styling of inline login prompts
</user_constraints>

## Current Architecture

### Route Structure (App.tsx)
All app pages are nested under a single `<ProtectedRoute>` wrapper:

```
<Route element={<RootLayout />}>
  /login, /register, /oauth/callback, /m/:token    <-- public (outside ProtectedRoute)
  <Route element={<ProtectedRoute />}>              <-- EVERYTHING else requires auth
    <Route element={<AppLayout />}>
      /                   (SearchPage)
      /datasets/:id       (DatasetPage)
      /collections        (CollectionsPage)
      /collections/:id    (CollectionDetailPage)
      /settings           (SettingsPage)
      <Route element={<EditorRoute />}>
        /import            (ImportPage)
        /maps              (MapsPage)
        /maps/:id          (MapBuilderPage)
      </Route>
      <Route element={<AdminRoute />}>
        /admin/*
      </Route>
    </Route>
  </Route>
</Route>
```

### ProtectedRoute Component
Simple guard: checks `useAuthStore.token`, redirects to `/login` with `state.from` if null. Saves redirect target to `sessionStorage` for post-login navigation.

### apiFetch() -- Already Anonymous-Safe
The `apiFetch()` client already handles missing tokens gracefully:
- Line 63: `if (token) { headers.set('Authorization', ...) }` -- skips auth header when no token
- 401 response handler calls `logout()` which is a no-op when already logged out (clears null values)
- No changes needed to apiFetch itself

### Auth Hooks Used in Pages
| Hook | What it provides | Pages using it |
|------|-----------------|----------------|
| `useAuthStore(s => s.token)` | Token presence check | SearchPage (gates SavedSearches) |
| `useAuthStore(s => s.isEditor())` | Editor role check | DatasetPage, CollectionsPage, CollectionDetailPage |
| `useAuthStore(s => s.isAdmin())` | Admin role check | DatasetPage, CollectionDetailPage |
| `useAuth()` | Full auth context (user, logout) | Navbar (CreateMenu, UserMenu, MobileNav) |
| `usePermissions()` | Capability checks (`can()`) | Navbar (CreateMenu, UserMenu, MobileNav) |
| `useDatasetEditCapabilities()` | Field-level edit checks | DatasetPage |

### Navbar Auth Usage
- `CreateMenu`: returns null when `!user` -- already safe
- `UserMenu`: always renders (should show "Sign in" for anonymous)
- `MobileNav`: gates create actions on `user` presence -- already safe
- Nav links: Maps link gated on `can('edit_metadata')` -- already safe

## Backend Endpoints Requiring Changes

Endpoints that currently require authentication but need anonymous access:

| Endpoint | Current Dep | Needs | Impact |
|----------|------------|-------|--------|
| `GET /datasets/{id}` | `get_current_active_user` | `get_optional_user` | Must handle `user=None` in visibility check and audit log |
| `GET /catalog/collections/` | `get_current_active_user` | `get_optional_user` | Must handle `user=None` in role lookup |
| `GET /catalog/collections/{id}` | `get_current_active_user` | `get_optional_user` | Same as above |
| `GET /catalog/collections/{id}/datasets` | `get_current_active_user` | `get_optional_user` | Visibility filter already handles None |
| `GET /maps/` | `get_current_active_user` | `get_optional_user` | Must filter to public maps only for anon |
| `GET /maps/{id}` | `get_current_active_user` | `get_optional_user` | Must check map visibility for anon |

Endpoints already supporting anonymous (no changes needed):
- `GET /search/datasets` -- uses `get_optional_user`
- `GET /datasets/dcat/` -- uses `get_optional_user`
- `GET /datasets/{id}/quicklook` -- uses `get_optional_user`
- `GET /tiles/*` -- uses `get_optional_user`
- `GET /maps/shared/{token}` -- uses `get_optional_user`

### Backend Pitfall: check_dataset_access()
The `check_dataset_access()` function signature requires `user: User` (not optional). For anonymous access to public datasets, the caller must skip this function when user is None and instead directly check `record.visibility == 'public'` and `record.record_status == 'published'`.

### Backend Pitfall: Audit Logging
The dataset detail endpoint logs `dataset.view` with `user_id=user.id`. For anonymous users, either skip the audit log or use a sentinel value. Skipping is simpler and matches the principle that anonymous browsing shouldn't create per-request audit records.

## Frontend Implementation Plan

### Recommended Approach: Split Route Tree
Move public-browsable routes outside `<ProtectedRoute>` but still inside `<AppLayout>`:

```tsx
<Route element={<AppLayout />}>
  {/* Public routes -- no auth required */}
  <Route index element={<SearchPage />} />
  <Route path="datasets/:id" element={<DatasetPage />} />
  <Route path="collections" element={<CollectionsPage />} />
  <Route path="collections/:id" element={<CollectionDetailPage />} />

  {/* Protected routes -- auth required */}
  <Route element={<ProtectedRoute />}>
    <Route path="settings" element={<SettingsPage />} />
    <Route element={<EditorRoute />}>
      <Route path="import" element={<ImportPage />} />
      <Route path="maps" element={<MapsPage />} />
      <Route path="maps/:id" element={<MapBuilderPage />} />
    </Route>
    <Route element={<AdminRoute />}>
      {/* ...admin routes... */}
    </Route>
  </Route>
  <Route path="*" element={<NotFoundPage />} />
</Route>
```

This is cleaner than adding a "public" flag to ProtectedRoute because it requires zero changes to the ProtectedRoute component itself and makes the public/protected boundary visible in the route tree.

### Auth-Gated UI Elements by Page

**SearchPage:**
- `SavedSearches` component: already gated on `token` (line 135: `token ? <SavedSearches /> : null`)
- Upload link in empty state: gate on token presence

**DatasetPage (heaviest lift):**
- `isEditor`/`isAdmin` checks already gate all edit actions -- when anonymous, both return false
- Actions gated on `isEditor`: edit title, reupload, VRT create, data tab editing
- Actions gated on `isAdmin`: delete, publication status
- Need: replace hidden buttons with "Sign in to edit" / "Sign in to manage" inline prompts where appropriate
- `ConnectDropdown`, `AddToMapButton`: these are read-oriented (API URLs, QGIS connect) -- keep visible for anonymous

**CollectionsPage:**
- Create button gated on `isEditor` -- already hidden for anonymous
- Empty state CTA: gate on `isEditor`, show neutral message for anonymous

**CollectionDetailPage:**
- Edit/delete buttons gated on `isEditor`/`isAdmin` -- already hidden
- `CollectionMembershipManager`: gate on `isEditor`
- `handleRemoveDataset`: already gated (`isEditor ? handleRemoveDataset : undefined`)

**Navbar:**
- `CreateMenu`: returns null when `!user` -- safe
- `UserMenu`: should show "Sign in" button when `!user` instead of the user dropdown
- `MobileNav`: create section gated on `user` -- safe
- Maps nav link: gated on `can('edit_metadata')` -- hidden for anonymous, which is correct

### Inline Login Prompt Pattern
Create a small reusable component:

```tsx
function AuthPrompt({ action }: { action: string }) {
  return (
    <Link to="/login" className="text-sm text-primary hover:underline">
      Sign in to {action}
    </Link>
  );
}
```

Use in place of hidden edit buttons when `!token`. Keep it inline, no modals.

## Common Pitfalls

### Pitfall 1: 401 Cascade on Anonymous API Calls
**What goes wrong:** Backend endpoints that still use `get_current_active_user` return 401 for anonymous requests. The `apiFetch` 401 handler calls `logout()` and throws `ApiError('Unauthorized', 401)`, which surfaces as an error state in the UI.
**How to avoid:** Every backend read endpoint that a public page calls MUST be changed to `get_optional_user`. Audit the full call chain for each page.

### Pitfall 2: usePermissions Hook Returns False for Everything
**What goes wrong:** `usePermissions` only fetches when `!!token` is true. For anonymous users, `can()` always returns false. This is correct behavior but needs to be verified that no public page relies on `can()` returning true for read actions.
**How to avoid:** Public pages should use `useAuthStore(s => s.token)` for simple auth checks, not `usePermissions`.

### Pitfall 3: Navbar UserMenu Without User
**What goes wrong:** `UserMenu` currently assumes a user exists and renders a dropdown with username initial, settings link, etc. With no user, it renders a broken state.
**How to avoid:** Add an early return in `UserMenu` (or Navbar) that renders a "Sign in" button when `!user`.

### Pitfall 4: Post-Login Redirect from Public Pages
**What goes wrong:** User is browsing a public dataset page, clicks "Sign in to edit", logs in, but gets redirected to `/` instead of back to the dataset.
**How to avoid:** The inline "Sign in" links should use `<Link to="/login" state={{ from: location.pathname }}>` to preserve the redirect target. The existing login redirect machinery (sessionStorage + location.state.from) already handles this.

### Pitfall 5: Maps Page Scope
**What goes wrong:** The decision says "public map viewer" is public, but `/maps` (MapsPage) lists all user maps including private ones. Making `/maps` public would leak private map metadata.
**How to avoid:** Keep `/maps` and `/maps/:id` (MapBuilderPage) behind `EditorRoute` as they are now. The "public map viewer" refers to the existing `/m/:token` (PublicViewerPage) which is already public.

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection of:
  - `frontend/src/App.tsx` -- route tree
  - `frontend/src/components/auth/ProtectedRoute.tsx` -- guard logic
  - `frontend/src/api/client.ts` -- apiFetch anonymous handling
  - `frontend/src/stores/auth-store.ts` -- auth state shape
  - `frontend/src/hooks/use-auth.ts`, `use-permissions.ts` -- auth hooks
  - `frontend/src/components/layout/Navbar.tsx` -- nav auth gating
  - `frontend/src/pages/DatasetPage.tsx` -- edit action gating
  - `frontend/src/pages/CollectionsPage.tsx`, `CollectionDetailPage.tsx` -- collection auth
  - `backend/app/auth/dependencies.py` -- `get_optional_user` vs `get_current_active_user`
  - `backend/app/auth/visibility.py` -- anonymous visibility filter
  - `backend/app/datasets/router.py` -- dataset endpoint auth deps
  - `backend/app/collections/router.py` -- collection endpoint auth deps
  - `backend/app/maps/router.py` -- map endpoint auth deps

## Metadata

**Confidence breakdown:**
- Route restructuring: HIGH -- direct code inspection, clear pattern
- Backend changes needed: HIGH -- verified each endpoint's dependency
- UI gating: HIGH -- traced every `isEditor`/`isAdmin` usage in target pages
- Pitfalls: HIGH -- derived from actual code behavior

**Research date:** 2026-03-27
**Valid until:** 2026-04-10 (stable codebase, no upstream changes expected)
