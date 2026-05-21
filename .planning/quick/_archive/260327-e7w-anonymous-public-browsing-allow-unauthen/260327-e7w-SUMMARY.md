---
phase: 260327-e7w
plan: 01
type: quick
subsystem: auth, frontend, backend
tags: [anonymous-access, public-browsing, route-protection, auth-dependency]
dependency_graph:
  requires: []
  provides: [anonymous-browse-datasets, anonymous-browse-collections, anonymous-view-map, public-route-tree]
  affects: [frontend-routing, backend-auth-deps, navbar-ui]
tech_stack:
  added: []
  patterns: [get_optional_user, User|None type annotation, route tree split, inline login prompt]
key_files:
  created:
    - frontend/src/components/auth/AuthPrompt.tsx
  modified:
    - backend/app/datasets/router.py
    - backend/app/collections/router.py
    - backend/app/collections/service.py
    - backend/app/maps/router.py
    - frontend/src/App.tsx
    - frontend/src/components/layout/Navbar.tsx
    - frontend/src/i18n/locales/en/auth.json
    - frontend/src/i18n/locales/es/auth.json
    - frontend/src/i18n/locales/fr/auth.json
    - frontend/src/i18n/locales/de/auth.json
decisions:
  - Anonymous users get 404 (not 401) for non-public resources — avoids leaking resource existence
  - audit log skipped for anonymous requests — anonymous browsing should not produce per-request audit records
  - Route split: AppLayout wraps both public and protected subtrees; ProtectedRoute wraps only protected routes
  - UserMenu returns early with Sign In button when user is null — no dropdown rendered for anonymous
metrics:
  duration: 20 min
  completed: 2026-03-27
  tasks_completed: 2
  files_changed: 10
---

# Phase 260327-e7w Plan 01: Anonymous Public Browsing Summary

**One-liner:** Backend read endpoints accept anonymous requests via `get_optional_user`; frontend route tree split so search, dataset detail, and collections render without auth; navbar shows "Sign In" for anonymous users.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Backend — switch read endpoints to get_optional_user | 830853ea | datasets/router.py, collections/router.py, collections/service.py, maps/router.py |
| 2 | Frontend — split route tree, AuthPrompt, navbar anonymous state | 1dec05ec | App.tsx, AuthPrompt.tsx, Navbar.tsx, 4x auth.json |

## What Was Built

### Backend Changes

**datasets/router.py:**
- `get_single_dataset`: switched to `get_optional_user`; anonymous users get 404 on non-public/non-published datasets; audit log skipped for anonymous
- `list_related_datasets`: switched to `get_optional_user`; `get_user_roles` skipped when user is None (empty set passed)
- `get_dataset_rows_endpoint`: switched to `get_optional_user`; inline anonymous visibility check
- `list_attributes_endpoint`: switched to `get_optional_user`; inline anonymous visibility check

**collections/router.py:**
- Added `get_optional_user` import
- `list_collections_endpoint`: switched to `User | None`; skips admin cache path for anonymous; `get_user_roles` returns empty set for anonymous
- `get_collection_endpoint`: switched to `User | None`
- `get_collection_datasets_endpoint`: switched to `User | None`

**collections/service.py:**
- Updated type signatures for `get_collection_datasets`, `compute_collection_extent`, `get_collection_dataset_count` to accept `User | None` — these pass user and user_roles directly to `apply_visibility_filter` which already handles None

**maps/router.py:**
- `get_map_endpoint`: switched to `User | None`; anonymous users blocked on non-public maps with 404

### Frontend Changes

**frontend/src/App.tsx:**
- Restructured route tree: public routes (index, datasets/:id, collections, collections/:id) moved outside `<ProtectedRoute>` but still inside `<AppLayout>`
- Protected routes (settings, import, maps, admin) remain inside `<ProtectedRoute>`

**frontend/src/components/auth/AuthPrompt.tsx** (new):
- Reusable inline sign-in prompt with `useTranslation('auth')` namespace
- Preserves post-login redirect via `state={{ from: location.pathname }}`

**frontend/src/components/layout/Navbar.tsx:**
- `UserMenu`: added `useTranslation('auth')` as `tAuth`; early return renders a "Sign In" button (outline variant) when `!user`
- `MobileNav`: added `useTranslation('auth')` as `tAuth`; appended Sign In link after the `{user && ...}` create section for anonymous users

**Locale files:**
- Added `signInTo` key to all 4 locale auth.json files (en, es, fr, de)

## Verification Notes

- TypeScript compiles with no errors (`tsc --noEmit` clean)
- Python syntax valid on all 4 modified backend files (`ast.parse` clean)
- Backend unit tests (no DB required) pass: 55/55
- DB-connected tests cannot run in this environment (no Docker DB available) — this is a pre-existing environment constraint, not a code issue

## Deviations from Plan

### Auto-fixed Issues

None — plan executed exactly as written with one minor deviation documented below.

### Deviation 1 — RouteErrorBoundary and NotFoundPage not present in codebase

**Found during:** Task 2
**Issue:** The plan template showed `<RouteErrorBoundary />` and `<NotFoundPage />` in the target route tree, but neither component exists in the codebase.
**Fix:** Removed `errorElement` props and the catch-all `<Route path="*">` since the referenced components don't exist. The route split (public/protected boundary) is fully implemented; error boundary additions can be a separate task.
**Files modified:** frontend/src/App.tsx

## Known Stubs

None — all endpoints return real data for public resources.

## Self-Check: PASSED

- SUMMARY.md: FOUND
- AuthPrompt.tsx: FOUND
- Commit 830853ea (Task 1): FOUND
- Commit 1dec05ec (Task 2): FOUND
