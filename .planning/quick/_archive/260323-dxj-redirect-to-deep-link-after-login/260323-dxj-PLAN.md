---
phase: quick-260323-dxj
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/auth/ProtectedRoute.tsx
  - frontend/src/components/auth/LoginForm.tsx
  - frontend/src/pages/LoginPage.tsx
  - frontend/src/pages/OAuthCallbackPage.tsx
  - frontend/src/components/auth/__tests__/ProtectedRoute.test.tsx
  - frontend/src/components/auth/__tests__/LoginForm.test.tsx
autonomous: true
requirements: [DEEP-LINK-REDIRECT]

must_haves:
  truths:
    - "Unauthenticated user visiting /datasets/123 is redirected to /login, then returned to /datasets/123 after login"
    - "Unauthenticated user visiting /admin/settings is redirected to /login, then returned to /admin/settings after login"
    - "Direct visit to /login with no prior deep link navigates to / after login"
    - "OAuth callback respects the saved redirect target"
  artifacts:
    - path: "frontend/src/components/auth/ProtectedRoute.tsx"
      provides: "Passes current location as state.from when redirecting to /login"
    - path: "frontend/src/components/auth/LoginForm.tsx"
      provides: "Reads location.state.from and navigates there after login instead of /"
    - path: "frontend/src/pages/LoginPage.tsx"
      provides: "Passes location state through to LoginForm and redirects authenticated users to state.from"
    - path: "frontend/src/pages/OAuthCallbackPage.tsx"
      provides: "Reads returnTo from sessionStorage to redirect after OAuth"
  key_links:
    - from: "ProtectedRoute.tsx"
      to: "LoginPage.tsx"
      via: "Navigate state={{ from: location.pathname + location.search }}"
      pattern: "state.*from.*location"
    - from: "LoginForm.tsx"
      to: "location.state.from"
      via: "useLocation to read redirect target"
      pattern: "navigate\\(.*from.*\\|\\|.*/"
---

<objective>
Preserve the user's intended URL when redirecting to login, and navigate back to that URL after successful authentication (both local login and OAuth).

Purpose: Users sharing or bookmarking deep links (e.g. /datasets/abc, /admin/settings, /maps/xyz) currently lose their destination after login -- they always land on /. This is a standard UX expectation.

Output: Updated auth guard and login components that round-trip the intended URL through the login flow.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@frontend/src/components/auth/ProtectedRoute.tsx
@frontend/src/components/auth/LoginForm.tsx
@frontend/src/pages/LoginPage.tsx
@frontend/src/pages/OAuthCallbackPage.tsx
@frontend/src/components/auth/__tests__/ProtectedRoute.test.tsx
@frontend/src/components/auth/__tests__/LoginForm.test.tsx
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Pass intended URL through login redirect and restore after login</name>
  <files>
    frontend/src/components/auth/ProtectedRoute.tsx,
    frontend/src/components/auth/LoginForm.tsx,
    frontend/src/pages/LoginPage.tsx,
    frontend/src/pages/OAuthCallbackPage.tsx,
    frontend/src/components/auth/__tests__/ProtectedRoute.test.tsx,
    frontend/src/components/auth/__tests__/LoginForm.test.tsx
  </files>
  <behavior>
    - ProtectedRoute: unauthenticated user at /datasets/abc is redirected to /login with state.from="/datasets/abc"
    - ProtectedRoute: unauthenticated user at /admin/settings?tab=auth is redirected to /login with state.from="/admin/settings?tab=auth"
    - LoginForm: after successful login, navigates to location.state.from if present, otherwise /
    - LoginForm: does NOT navigate to external URLs passed via state.from (security: ignore absolute URLs starting with http)
    - LoginPage: already-authenticated user redirects to state.from if present, otherwise /
  </behavior>
  <action>
    1. **ProtectedRoute.tsx**: Import `useLocation`. When token is null, pass `state={{ from: location.pathname + location.search }}` to the Navigate element. Keep `replace` behavior.

    2. **LoginForm.tsx**: Import `useLocation`. In handleSubmit, after successful `await login(...)`, read `(location.state as { from?: string })?.from`. If it exists and starts with `/` (not an absolute URL), navigate there. Otherwise navigate to `/`. Keep `{ replace: true }` on navigate.

    3. **LoginPage.tsx**: Update the already-authenticated redirect (`if (token)`) to read `location.state?.from` and Navigate there instead of always `/`. This handles the case where a user is already logged in but arrives at /login with a from state (edge case but consistent).

    4. **OAuthCallbackPage.tsx**: Before the OAuth redirect to the backend happens, the intended URL is lost because OAuth goes through an external flow. To handle this: In ProtectedRoute, also save `from` to `sessionStorage.setItem('geolens-login-redirect', from)` when redirecting to /login. In OAuthCallbackPage, after successful auth, read `sessionStorage.getItem('geolens-login-redirect')`, navigate there if it starts with `/`, then `sessionStorage.removeItem('geolens-login-redirect')`. Also in LoginForm on successful login, `sessionStorage.removeItem('geolens-login-redirect')` to clean up.

    5. **ProtectedRoute.test.tsx**: Add test that unauthenticated user is redirected with from state preserved. Render with initialEntries=['/datasets/abc'], verify navigation to /login occurs (existing test), and add a new test that verifies the Navigate element receives the from state. Use a test route at /login that reads and displays location.state.from.

    6. **LoginForm.test.tsx**: Add test that after login, navigates to location.state.from. Render LoginForm inside MemoryRouter with location state `{ from: '/datasets/abc' }`, submit form, assert navigation target. Add test that state.from starting with 'http' is ignored (navigates to / instead).
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npx vitest run --reporter=verbose src/components/auth/__tests__/ProtectedRoute.test.tsx src/components/auth/__tests__/LoginForm.test.tsx</automated>
  </verify>
  <done>
    - ProtectedRoute passes from state with full path+search when redirecting to /login
    - LoginForm navigates to from after login, falls back to /
    - LoginPage redirects authenticated users to from if present
    - OAuthCallbackPage reads redirect target from sessionStorage
    - External URLs in from are rejected (security)
    - All new tests pass
  </done>
</task>

</tasks>

<verification>
- Run full auth test suite: `cd frontend && npx vitest run src/components/auth/__tests__/`
- Manual smoke test: visit /admin/settings while logged out, login, confirm redirect to /admin/settings
</verification>

<success_criteria>
- Unauthenticated deep link visits redirect to /login then back to original URL after login
- Direct /login visits still go to / after login
- OAuth flow preserves redirect target via sessionStorage
- No external URL redirect vulnerability
- All existing and new tests pass
</success_criteria>

<output>
After completion, create `.planning/quick/260323-dxj-redirect-to-deep-link-after-login/260323-dxj-SUMMARY.md`
</output>
