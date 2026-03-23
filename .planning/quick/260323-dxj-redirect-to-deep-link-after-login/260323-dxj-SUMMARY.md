---
phase: quick-260323-dxj
plan: 01
subsystem: auth
tags: [react-router, deep-link, login-redirect, sessionStorage]

requires:
  - phase: none
    provides: existing ProtectedRoute + LoginForm + OAuthCallbackPage
provides:
  - deep link preservation through login flow (local + OAuth)
  - sessionStorage-based redirect for OAuth external flows
affects: [auth, login, oauth]

tech-stack:
  added: []
  patterns: [location.state.from for login redirect, sessionStorage for OAuth redirect persistence]

key-files:
  created: []
  modified:
    - frontend/src/components/auth/ProtectedRoute.tsx
    - frontend/src/components/auth/LoginForm.tsx
    - frontend/src/pages/LoginPage.tsx
    - frontend/src/pages/OAuthCallbackPage.tsx
    - frontend/src/components/auth/__tests__/ProtectedRoute.test.tsx
    - frontend/src/components/auth/__tests__/LoginForm.test.tsx

key-decisions:
  - "Use location.state.from for in-app redirect and sessionStorage for OAuth external flow persistence"
  - "Reject absolute URLs in state.from to prevent open redirect vulnerability"

patterns-established:
  - "Login redirect: ProtectedRoute sets state.from, LoginForm reads it post-login"
  - "OAuth redirect: sessionStorage key geolens-login-redirect bridges external OAuth flow"

requirements-completed: [DEEP-LINK-REDIRECT]

duration: 2min
completed: 2026-03-23
---

# Quick Task 260323-dxj: Deep Link Redirect After Login Summary

**Preserve user's intended URL through login flow using location.state.from and sessionStorage for OAuth**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-23T14:04:48Z
- **Completed:** 2026-03-23T14:07:01Z
- **Tasks:** 1
- **Files modified:** 6

## Accomplishments
- ProtectedRoute passes current path+search as state.from when redirecting unauthenticated users to /login
- LoginForm navigates to state.from after successful login, with fallback to /
- LoginPage redirects already-authenticated users to state.from if present
- OAuthCallbackPage reads redirect target from sessionStorage after external OAuth flow
- External URLs in state.from are rejected (open redirect prevention)
- 5 new tests added covering deep link, query string, external URL rejection, and sessionStorage cleanup

## Task Commits

1. **Task 1: Pass intended URL through login redirect and restore after login** - `b63aa5e4` (feat)

## Files Created/Modified
- `frontend/src/components/auth/ProtectedRoute.tsx` - Added useLocation, state.from, and sessionStorage persistence
- `frontend/src/components/auth/LoginForm.tsx` - Read state.from post-login, clean sessionStorage
- `frontend/src/pages/LoginPage.tsx` - Redirect authenticated users to state.from
- `frontend/src/pages/OAuthCallbackPage.tsx` - Read redirect from sessionStorage after OAuth
- `frontend/src/components/auth/__tests__/ProtectedRoute.test.tsx` - Tests for from state and sessionStorage
- `frontend/src/components/auth/__tests__/LoginForm.test.tsx` - Tests for redirect, fallback, external URL rejection

## Decisions Made
- Used React Router's location.state.from pattern (standard approach) for passing redirect target through login
- Added sessionStorage key `geolens-login-redirect` specifically for OAuth flows where state is lost through external redirect
- Reject any state.from not starting with `/` to prevent open redirect attacks

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

---
*Phase: quick-260323-dxj*
*Completed: 2026-03-23*

## Self-Check: PASSED
