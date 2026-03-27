---
phase: 260327-e7w
verified: 2026-03-27T00:00:00Z
status: gaps_found
score: 6/7 must-haves verified
re_verification: false
gaps:
  - truth: "Anonymous user sees inline Sign in prompts where edit actions would be"
    status: partial
    reason: "AuthPrompt component is created and correct, but not wired anywhere — it is exported and unused. The plan notes it is 'available for future use', but the success criterion states anonymous users should see inline sign-in prompts where edit actions would be. Currently, edit actions are silently hidden rather than replaced with prompts."
    artifacts:
      - path: "frontend/src/components/auth/AuthPrompt.tsx"
        issue: "Component exists and is correct but has zero usages in the codebase"
    missing:
      - "Import and render AuthPrompt in at least one location where edit actions are conditionally hidden for anonymous users (e.g., DatasetPage header, CollectionsPage, or SearchPage empty state)"
  - truth: "Backend returns 200 for anonymous GET on public datasets, collections, maps"
    status: partial
    reason: "list_maps_endpoint intentionally kept behind get_current_active_user (per plan: Pitfall 5). However, AddToMapButton on DatasetPage renders unconditionally for non-table datasets including for anonymous users. This causes useMaps() to fire GET /api/maps without auth, getting a 401. The apiFetch client calls logout() on 401. While logout() is a no-op when already unauthenticated (token is already null), the 401 response still propagates as an ApiError, causing a console error. The plan's success criterion explicitly states 'No 401 cascade errors in browser console for anonymous browsing'."
    artifacts:
      - path: "frontend/src/components/dataset/AddToMapButton.tsx"
        issue: "Rendered unconditionally for all non-table datasets; useMaps() fires GET /api/maps without auth guard — produces 401 for anonymous users"
      - path: "frontend/src/pages/DatasetPage.tsx"
        issue: "Line 454: {!isTable && <AddToMapButton ... />} has no auth gate"
    missing:
      - "Guard AddToMapButton with isEditor check in DatasetPage (e.g., {!isTable && isEditor && <AddToMapButton ... />}) OR add enabled: !!token to useMaps inside AddToMapButton"
human_verification:
  - test: "Anonymous search renders public results"
    expected: "Visit / in incognito — search page loads, public+published datasets appear, no redirect to /login"
    why_human: "Requires running app and real backend with seeded public data"
  - test: "Anonymous dataset detail loads"
    expected: "Visit /datasets/:id for a public dataset in incognito — page renders, map/data visible, no 401 in console, edit buttons absent"
    why_human: "Requires running app and browser console inspection"
  - test: "AddToMapButton 401 in console"
    expected: "With gap as-is: console shows uncaught ApiError 401 when anonymous user views any non-table dataset. After fix: no error."
    why_human: "Requires browser console inspection"
  - test: "Protected routes redirect to login"
    expected: "/settings, /import, /maps, /admin all redirect to /login for anonymous user"
    why_human: "Requires running app"
  - test: "Sign in button visible in navbar for anonymous"
    expected: "Navbar shows 'Sign In' button (outline variant) instead of user dropdown"
    why_human: "Visual verification in browser"
---

# Phase 260327-e7w: Anonymous Public Browsing Verification Report

**Phase Goal:** Enable anonymous public browsing so unauthenticated users can search datasets, view dataset details, browse collections, and view public maps without logging in.
**Verified:** 2026-03-27
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | Anonymous user can load search page and see public dataset results | VERIFIED | App.tsx line 53: `<Route index element={<SearchPage />} />` is outside `<ProtectedRoute>` inside `<AppLayout>`; SearchPage uses `useSearchResults()` which fires without auth |
| 2 | Anonymous user can view a public dataset detail page | VERIFIED | App.tsx line 54: `<Route path="datasets/:id" element={<DatasetPage />} />` is outside `<ProtectedRoute>`; backend `get_single_dataset` switched to `get_optional_user` with inline public check (datasets/router.py:539) |
| 3 | Anonymous user can browse collections and view collection detail | VERIFIED | App.tsx lines 55-56: `collections` and `collections/:id` routes outside `<ProtectedRoute>`; collections/router.py uses `get_optional_user` at lines 178, 216, 375; service.py signatures updated to `User | None` at lines 178, 234, 278 |
| 4 | Anonymous user sees Sign in button in navbar instead of user dropdown | VERIFIED | Navbar.tsx UserMenu: early return when `!user` renders `<Button variant="outline" size="sm" asChild><Link to="/login">...<LogIn .../> {tAuth('signIn')}</Link></Button>`; MobileNav: `{!user && <><Separator /><Link to="/login">...</Link></>}` block present |
| 5 | Anonymous user sees inline Sign in prompts where edit actions would be | PARTIAL — FAILED | AuthPrompt.tsx exists and is correct (uses `useTranslation('auth')`, `state={{ from: location.pathname }}`, `t('signInTo', { action })`), but zero usages found in codebase. Edit actions are silently hidden (not replaced with prompts). |
| 6 | Protected routes (settings, import, maps, admin) still redirect to login | VERIFIED | App.tsx lines 59-93: `settings`, `import`, `maps`, `maps/:id`, and all `admin/*` routes are inside `<Route element={<ProtectedRoute />}>` which redirects to `/login` when no token |
| 7 | Backend returns 200 for anonymous GET on public datasets, collections, maps | PARTIAL — FAILED | Backend endpoints correctly return 200 for public resources. However, `list_maps_endpoint` (intentionally) still requires auth. `AddToMapButton` renders on DatasetPage for all non-table datasets without an auth gate — `useMaps()` fires GET /api/maps without auth for anonymous users, returning 401. The apiFetch client propagates this as an ApiError, violating the "no 401 cascade errors" success criterion. |

**Score:** 5/7 truths fully verified (2 partial failures)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/components/auth/AuthPrompt.tsx` | Reusable inline login prompt component | ORPHANED | File exists (18 lines), correct implementation with `useTranslation('auth')`, post-login redirect, `LogIn` icon. Exports `AuthPrompt`. Zero import sites. |
| `frontend/src/App.tsx` | Split route tree with public and protected subtrees | VERIFIED | Public routes (index, datasets/:id, collections, collections/:id) inside AppLayout but outside ProtectedRoute. Protected subtree wrapped in `<Route element={<ProtectedRoute />}>`. |
| `backend/app/datasets/router.py` | Anonymous-safe GET /datasets/{id} endpoint | VERIFIED | `get_optional_user` used at lines 427, 527, 626, 1004, 1019, 1797, 2038, 2194, 2257. Inline anonymous visibility checks at lines 539, 638, 1036, 1806, 2201. |
| `backend/app/collections/router.py` | Anonymous-safe collection list/detail/datasets endpoints | VERIFIED | `get_optional_user` at lines 178, 216, 375. `get_optional_user` imported at line 15. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `frontend/src/App.tsx` | `frontend/src/components/auth/ProtectedRoute.tsx` | Public routes outside ProtectedRoute wrapper | VERIFIED | Lines 53-56 are outside `<Route element={<ProtectedRoute />}>` (line 59). Pattern `Route index element SearchPage` present. |
| `frontend/src/components/auth/AuthPrompt.tsx` | `/login` | Link with location state for post-login redirect | VERIFIED (internal) / ORPHANED (usage) | Component correctly links to `/login` with `state={{ from: location.pathname }}`. Not imported anywhere. |
| `backend/app/datasets/router.py` | `backend/app/auth/dependencies.py` | `get_optional_user` dependency | VERIFIED | Imported at line 35, used at 9 endpoints. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| `SearchPage` | `data` from `useSearchResults()` | `apiFetch` → GET /api/search (no auth required) | Yes — no token needed, backend filters to public+published | FLOWING |
| `DatasetPage` | `dataset` from `useDataset(id)` | `apiFetch` → GET /api/datasets/:id (`get_optional_user`) | Yes — returns public+published for anonymous | FLOWING |
| `CollectionsPage` | `data` from `useCollections()` | `apiFetch` → GET /api/catalog/collections/ (`get_optional_user`) | Yes — service uses `apply_visibility_filter(user=None)` | FLOWING |
| `CollectionDetailPage` | `collection` from `useCollection(id)` | `apiFetch` → GET /api/catalog/collections/:id (`get_optional_user`) | Yes | FLOWING |
| `AddToMapButton` (on DatasetPage) | `data` from `useMaps()` | `apiFetch` → GET /api/maps (`get_current_active_user`) | No — 401 for anonymous | DISCONNECTED |

### Behavioral Spot-Checks

Step 7b: SKIPPED — requires running server to verify HTTP responses.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|---------|
| ANON-BROWSE | 260327-e7w PLAN | Anonymous users can browse public catalog without login | PARTIALLY SATISFIED | Core routing and backend changes verified. AuthPrompt truth partial. 401 cascade from AddToMapButton is a minor gap. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `frontend/src/components/auth/AuthPrompt.tsx` | 5 | Component exported but never imported | Warning | AuthPrompt satisfies no truth; "inline Sign in prompts" goal is unmet |
| `frontend/src/pages/DatasetPage.tsx` | 454 | `{!isTable && <AddToMapButton .../>}` — no auth gate | Blocker | `useMaps()` fires GET /api/maps (auth-required) for anonymous users, producing 401 error in console and ApiError propagation |

### Human Verification Required

#### 1. Anonymous Search Page

**Test:** Open `http://localhost:8080/` in an incognito browser window (no cookies/localStorage)
**Expected:** Search page renders with public+published dataset results visible; no redirect to `/login`; no 401 in browser console
**Why human:** Requires live app with seeded public data and browser console inspection

#### 2. Anonymous Dataset Detail

**Test:** Click a public dataset card from the search page in incognito
**Expected:** Dataset detail page loads completely — map/preview, metadata tabs, stats visible. Edit/delete/reupload buttons absent. "Add to Map" button present (gap: may produce console 401).
**Why human:** Requires browser console inspection to confirm no unintended 401s

#### 3. Navbar Sign In Button

**Test:** Verify navbar appearance for anonymous user
**Expected:** "Sign In" button (outline variant, LogIn icon) visible in top-right; no username/avatar dropdown
**Why human:** Visual verification

#### 4. Protected Route Redirects

**Test:** Navigate directly to `/settings`, `/import`, `/maps`, `/admin` in incognito
**Expected:** All four redirect to `/login` immediately; no page content rendered
**Why human:** Requires running app and navigation testing

### Gaps Summary

Two gaps block full goal achievement:

**Gap 1 — AuthPrompt is orphaned (Warning severity):** `frontend/src/components/auth/AuthPrompt.tsx` is a well-implemented component that is never imported or used. The task goal says "UI adapts to hide edit actions and show login prompt for restricted features." The plan acknowledged this gap inline ("AuthPrompt component is available for future use where we want to show 'Sign in to X' instead of simply hiding buttons"). The plan explicitly says "the existing hide-on-no-auth pattern satisfies the core requirement." This is therefore a design decision — hiding is acceptable, prompts are aspirational. **This gap is low-priority and consistent with the plan's stated intent.**

**Gap 2 — AddToMapButton produces 401 for anonymous users (Blocker severity):** `AddToMapButton` is rendered on every non-table dataset page for all users, including anonymous. It immediately fires `useMaps()` → GET `/api/maps` which requires authentication. For anonymous users this produces a 401, which is then surfaced as a console ApiError. The plan success criterion explicitly states "No 401 cascade errors in browser console for anonymous browsing." Fix: add `isEditor` (or `!!token`) gate in DatasetPage around `AddToMapButton`, or add `enabled: !!token` to the `useMaps` query inside `AddToMapButton`.

The backend changes, route tree restructuring, navbar anonymous state, and i18n keys are all correctly implemented and complete.

---

_Verified: 2026-03-27_
_Verifier: Claude (gsd-verifier)_
