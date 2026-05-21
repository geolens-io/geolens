---
phase: 260330-qey
verified: 2026-03-30T23:35:00Z
status: passed
score: 5/5 must-haves verified
re_verification: false
---

# Task 260330-qey: Public Maps Access Verification Report

**Task Goal:** As a public user, I should be able to see public maps
**Verified:** 2026-03-30T23:35:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Anonymous user can visit /maps and see a list of public maps | VERIFIED | `/maps` route is outside ProtectedRoute in App.tsx (line 57); backend GET /maps/ uses `get_optional_user` (router.py line 177); anonymous path calls `list_maps` with `user_id=None` |
| 2 | Anonymous user can click a map card and view it in the interactive viewer | VERIFIED | `/maps/:id` route is outside ProtectedRoute in App.tsx (line 58); `MapViewerGate` dispatches to `PublicMapViewerPage` for non-editors; `PublicMapViewerPage` loads via `useMap(id)` and renders `ViewerMap` full-screen |
| 3 | Anonymous user cannot see Create Map button, delete buttons, or visibility filter | VERIFIED | MapsPage wraps Create button in `{isEditor && ...}` (line 116-121); visibility Select in `{isEditor && ...}` (line 152-167); delete buttons only rendered when `onDelete` prop is provided (MapCard line 97, MapCardGrid line 90); `onDelete` passed as `isEditor ? handleDeleteClick : undefined` in MapsPage |
| 4 | Logged-in users see same behavior as before (own + internal + public maps, full controls) | VERIFIED | Backend `_apply_vis_filter` in service.py still returns `owner + internal + public` when `user_id is not None` (lines 186-192); `isEditor()` from auth store enables controls for authenticated editors; `MapViewerGate` routes editors to `MapBuilderPage` |
| 5 | Maps nav link is visible to all users in the navbar | VERIFIED | Desktop NavLink to `/maps` at Navbar.tsx line 335 — unconditional, no `can()` guard; mobile NavLink to `/maps` at line 237 — also unconditional |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/maps/router.py` | list_maps_endpoint with optional auth | VERIFIED | `user: User \| None = Depends(get_optional_user)` at line 177; anonymous branch sets `uid=None, user_roles=set()` |
| `backend/app/maps/service.py` | Anonymous visibility filter in list_maps | VERIFIED | `_apply_vis_filter` returns `stmt.where(Map.visibility == "public")` when `user_id is None` (lines 193-194) |
| `frontend/src/App.tsx` | Public /maps route outside auth guards | VERIFIED | Lines 57-58: `<Route path="maps" ...>` and `<Route path="maps/:id" ...>` are inside `<AppLayout>` but outside `<ProtectedRoute>` |
| `frontend/src/pages/MapsPage.tsx` | Conditional UI hiding editor controls for anonymous | VERIFIED | `isEditor = useAuthStore(s => s.isEditor())` at line 43; Create button, visibility filter, dialogs, empty state action all gated on `isEditor` |
| `frontend/src/components/maps/MapCard.tsx` | Conditional delete button | VERIFIED | `onDelete?` optional prop (line 22); delete button wrapped in `{onDelete && (...)}` (line 97) |
| `frontend/src/components/maps/MapCardGrid.tsx` | Conditional delete button | VERIFIED | Uses `MapCardProps` from MapCard (reuses optional `onDelete`); delete button wrapped in `{onDelete && (...)}` (line 90) |
| `frontend/src/pages/MapViewerGate.tsx` | Gate dispatching editor vs anonymous | VERIFIED | 13-line gate component; `isEditor ? <MapBuilderPage /> : <PublicMapViewerPage />` |
| `frontend/src/pages/PublicMapViewerPage.tsx` | Read-only map viewer for anonymous | VERIFIED | Uses `useMap(id)`, transforms layers via `toSharedLayer()`, renders `ViewerMap` + `LayerLegend`; full loading/error states |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `frontend/src/pages/MapsPage.tsx` | `/api/maps/` | `useMaps` hook -> `apiFetch` | VERIFIED | `useMaps` called at line 66; resolves to `listMaps()` in api/maps.ts which calls `apiFetch('/maps/')` |
| `frontend/src/App.tsx` | `MapsPage` | public Route outside ProtectedRoute | VERIFIED | `<Route path="maps" element={<MapsPage />} />` at line 57, inside `<AppLayout>` but before `<ProtectedRoute>` block |
| `backend/app/maps/router.py` | `backend/app/maps/service.py` | `list_maps` call with user_id=None for anonymous | VERIFIED | Lines 185-201: when `user is None`, calls `list_maps(db, ..., user_id=None, user_roles=set(), ...)` |
| `frontend/src/components/maps/MapCard.tsx` | `/maps/:id` | Link to map viewer | VERIFIED | Two `<Link to={'/maps/${map.id}'}` elements at lines 34-49 and 55-60 |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|-------------------|--------|
| `MapsPage.tsx` | `data` (from `useMaps`) | `listMaps()` -> `apiFetch('/maps/')` -> `list_maps_endpoint` -> `list_maps()` DB query | Yes — SQLAlchemy query on `Map` table with visibility filter | FLOWING |
| `PublicMapViewerPage.tsx` | `data` (from `useMap(id)`) | `getMap(id)` -> `apiFetch('/maps/{id}')` -> `get_map_endpoint` -> `get_map_with_layers()` DB query | Yes — SQLAlchemy query on `Map` + `MapLayer` + `Dataset` + `Record` | FLOWING |
| `ViewerMap` (within PublicMapViewerPage) | tile URLs | `buildSignedTileUrl(layer.table_name, null)` | Yes — produces `/api/tiles/data.{table_name}/{z}/{x}/{y}.pbf` without auth params; valid for public datasets | FLOWING |

### Behavioral Spot-Checks

Step 7b: SKIPPED for frontend components (requires running browser). Backend Python imports are verifiable without server:

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| TypeScript compiles without errors | `npx tsc --noEmit` | No output (success) | PASS |
| Commits documented in SUMMARY exist | `git log --oneline` | `02fff7c0` and `c4cddc12` both present | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| PUBLIC-MAPS | 260330-qey-PLAN.md | Anonymous access to public maps listing and viewer | SATISFIED | All 5 truths verified; backend and frontend changes confirmed |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `PublicMapViewerPage.tsx` | 15-17 | Comment says `tile_url` is a "placeholder" | Info | Not a stub — comment accurately describes that ViewerMap ignores `tile_url` and builds URLs from `table_name`. Verified: `buildSignedTileUrl` handles null token correctly (returns plain URL). |

No blockers or warnings found. The one "placeholder" mention is in a code comment explaining intentional design, not a stub implementation.

### Human Verification Required

The following behaviors require manual browser testing to confirm end-to-end:

#### 1. Anonymous /maps page renders public maps

**Test:** Open `http://localhost:8080/maps` in an incognito window (no auth cookies)
**Expected:** Page loads without redirect to /login; shows list of public maps; no "Create Map" button; no visibility filter dropdown
**Why human:** Visual rendering and absence of UI elements cannot be verified statically

#### 2. Map card click-through loads read-only viewer

**Test:** While anonymous, click any map card on the /maps page
**Expected:** Navigates to `/maps/{id}`; map renders with zoom/pan; LayerLegend appears; no edit controls visible
**Why human:** Interactive map rendering requires browser + MapLibre GL execution

#### 3. Non-public map returns 404 for anonymous

**Test:** While anonymous, manually navigate to the URL of a private or internal map (e.g., `/maps/{private-map-id}`)
**Expected:** Viewer shows "Map not found" error state, not the map content
**Why human:** Requires knowing a specific non-public map ID to test access control

#### 4. Authenticated editor sees MapBuilderPage

**Test:** Log in as an editor, navigate to `/maps/{any-map-id}`
**Expected:** Full MapBuilderPage with layer panel, edit controls — not the read-only viewer
**Why human:** Requires auth flow and MapBuilderPage UI verification

### Gaps Summary

No gaps found. All automated checks passed.

---

_Verified: 2026-03-30T23:35:00Z_
_Verifier: Claude (gsd-verifier)_
