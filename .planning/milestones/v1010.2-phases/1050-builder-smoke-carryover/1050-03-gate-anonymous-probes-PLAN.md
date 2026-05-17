---
phase: 1050-builder-smoke-carryover
plan: 03
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/search/hooks/use-saved-searches.ts
  - frontend/src/components/admin/AIStatusCard.tsx
  - frontend/src/components/admin/settings/SettingsAITab.tsx
  - frontend/src/components/search/hooks/__tests__/use-saved-searches.test.ts
autonomous: true
requirements: [SMOKE-10]

must_haves:
  truths:
    - "Loading /login fresh (no cookies, no token in geolens-auth) fires zero requests to /api/auth/me/, /api/auth/me/permissions/, /api/admin/ai-status/, /api/search/saved/, /api/auth/refresh/"
    - "After a successful login the same hooks fire normally — gating is on isAuthenticated, not blanket-disabled"
    - "Admin-only /api/admin/ai-status/ only fires when user.is_admin is truthy (not just on any authed page)"
    - "No 401-error console entries on the /login route in a fresh-stack Playwright MCP run"
  artifacts:
    - path: "frontend/src/components/search/hooks/use-saved-searches.ts"
      provides: "Token-gated React Query hook (enabled: !!token)"
      contains: "enabled: !!token"
    - path: "frontend/src/components/admin/AIStatusCard.tsx"
      provides: "useAIStatus() called with { enabled: !!token && isAdmin }"
      contains: "useAIStatus.*enabled"
    - path: "frontend/src/components/admin/settings/SettingsAITab.tsx"
      provides: "useAIStatus() called with { enabled: !!token && isAdmin }"
      contains: "useAIStatus.*enabled"
  key_links:
    - from: "use-saved-searches.ts:useQuery"
      to: "useAuthStore((s) => s.token)"
      via: "enabled gate"
      pattern: "enabled:\\s*!!token"
    - from: "AIStatusCard.tsx + SettingsAITab.tsx"
      to: "useAIStatus({ enabled: !!token && isAdmin })"
      via: "consumer-side admin gate"
      pattern: "enabled:\\s*!!token\\s*&&\\s*isAdmin"
---

<objective>
Visiting `/login` unauthenticated stops firing 401-error console noise to `/api/auth/me/`, `/api/auth/me/permissions/`, `/api/admin/ai-status/`, `/api/search/saved/`, `/api/auth/refresh/`. Closes SF-06.

Purpose: Per SF-06 evidence (`browser_console_messages` Pass A, 2026-05-17): visiting `/login` while unauthenticated fires 4–5 401-noise requests. The `/api/admin/ai-status/` probe from an anonymous page is especially suspicious — an admin endpoint should not be hit unless the user is admin-authed. Per CONTEXT.md decision: preferred fix is per-hook `enabled: isAuthenticated` (so the network never fires), NOT a global error-handler suppressor. Admin probe must additionally gate on `user.is_admin`.

Note (from PATTERNS.md): 2 of the 5 hooks are ALREADY correctly gated and serve as the analog:
- `use-auth.ts:20-27` — `enabled: !!token` ✓
- `use-permissions.ts:7-15` — `enabled: !!token` ✓

The other 3 surfaces need fixing:
- `use-admin.ts:186-194` — `useAIStatus` exposes `{ enabled?: boolean }` opt-in BUT its consumers (`AIStatusCard.tsx:16`, `SettingsAITab.tsx:44`) call it without `enabled` → fires on any mount.
- `use-saved-searches.ts:9-15` — `useSavedSearches` has NO `enabled` gate.
- `/api/auth/refresh/` — the 401 noise comes from the auth-refresh path; verify it's already cookie-gated and not a separate fix needed.

Output:
- `frontend/src/components/search/hooks/use-saved-searches.ts` — add `enabled: !!token` gate via `useAuthStore` selector
- `frontend/src/components/admin/AIStatusCard.tsx` — pass `{ enabled: !!token && isAdmin }` to `useAIStatus`
- `frontend/src/components/admin/settings/SettingsAITab.tsx` — same as AIStatusCard
- `frontend/src/components/search/hooks/__tests__/use-saved-searches.test.ts` — test asserting hook is disabled when token is null
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/phases/1050-builder-smoke-carryover/1050-CONTEXT.md
@.planning/phases/1050-builder-smoke-carryover/1050-PATTERNS.md
@.planning/milestones/v1010.1-phases/1049-mcp-smoke-verification/1049-SMOKE-FINDINGS.md

@frontend/src/hooks/use-auth.ts
@frontend/src/hooks/use-permissions.ts
@frontend/src/hooks/use-admin.ts
@frontend/src/hooks/use-ai-availability.ts
@frontend/src/components/search/hooks/use-saved-searches.ts
@frontend/src/components/admin/AIStatusCard.tsx
@frontend/src/components/admin/settings/SettingsAITab.tsx
@frontend/src/stores/auth-store.ts

<interfaces>
<!-- Existing gate patterns. Executor copies these shapes. -->

From use-auth.ts:20-27 (token gate — analog #1):
```typescript
const token = useAuthStore((s) => s.token);
const meQuery = useQuery({
  queryKey: queryKeys.auth.me,
  queryFn: getMe,
  enabled: !!token,
  retry: false,
  staleTime: 5 * 60 * 1000,
  meta: { skipGlobalError: true },
});
```

From use-permissions.ts:7-15 (token gate via store selector — analog #2):
```typescript
export function usePermissions() {
  const token = useAuthStore((s) => s.token);
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.auth.permissions,
    queryFn: getMyPermissions,
    enabled: !!token,
    staleTime: 60_000,
  });
  // ...
}
```

From use-ai-availability.ts:5-16 (consumer-side admin gate — analog #4, the GOOD reference for AIStatusCard/SettingsAITab fix):
```typescript
export function useAIAvailability() {
  const token = useAuthStore((s) => s.token);
  const aiStatus = useAIStatus({ enabled: !!token });
  const { can } = usePermissions();
  // ...
}
```

From use-admin.ts:186-194 (current useAIStatus signature — DO NOT change the hook):
```typescript
export function useAIStatus(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.admin.aiStatus,
    queryFn: getAIStatus,
    staleTime: 60_000,
    gcTime: 5 * 60_000,
    enabled: options?.enabled,
  });
}
```

From auth-store.ts:5-15, 77:
```typescript
interface AuthState {
  token: string | null;        // !!token is the "is authenticated" gate
  user: UserResponse | null;
  isAdmin: () => boolean;      // selector for the admin gate
  isEditor: () => boolean;
}
isAdmin: () => get().user?.roles.includes('admin') ?? false,
```

Decision (locked per CONTEXT.md + PATTERNS.md): change CONSUMERS (`AIStatusCard`, `SettingsAITab`) to always pass `{ enabled: !!token && isAdmin }`, NOT the hook default. This preserves the hook's documented caller-controlled contract.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Gate useSavedSearches on !!token</name>
  <files>frontend/src/components/search/hooks/use-saved-searches.ts, frontend/src/components/search/hooks/__tests__/use-saved-searches.test.ts</files>
  <read_first>
    - frontend/src/components/search/hooks/use-saved-searches.ts (full file — confirm current shape; no enabled gate)
    - frontend/src/hooks/use-permissions.ts:1-30 (analog — the exact gate-via-selector pattern to copy)
    - frontend/src/stores/auth-store.ts:1-90 (confirm `useAuthStore((s) => s.token)` selector shape)
    - frontend/src/components/search/hooks/__tests__/use-saved-searches.test.ts (full file if exists — locate conventions; if missing, create alongside in the SAME directory the hook lives)
    - .planning/phases/1050-builder-smoke-carryover/1050-PATTERNS.md (Plan 03 — Analog #2)
  </read_first>
  <behavior>
    - Test 1 (NEW): When `useAuthStore.getState().token === null`, `useSavedSearches` does NOT fire the `getSavedSearches` request (i.e. the React Query `enabled` is false).
    - Test 2 (NEW): When `useAuthStore.setState({ token: 'fake' })`, the query fires.
    - Test 3 (regression): Existing test cases for the hook's return shape continue to pass.
  </behavior>
  <action>
    In `frontend/src/components/search/hooks/use-saved-searches.ts`:

    1. Add the import for `useAuthStore` if not already present:
       ```typescript
       import { useAuthStore } from '@/stores/auth-store';
       ```

    2. Inside the hook function (before the `useQuery({...})` call), add:
       ```typescript
       const token = useAuthStore((s) => s.token);
       ```

    3. In the `useQuery({...})` config object, add `enabled: !!token` as a sibling of `queryKey` / `queryFn`. Preserve any existing `staleTime` / `gcTime` options.

    4. If the hook accepts caller `options` (e.g. `useSavedSearches({ enabled })`), AND-combine: `enabled: !!token && (options?.enabled ?? true)`.

    Add tests to `frontend/src/components/search/hooks/__tests__/use-saved-searches.test.ts` (create the file if missing — match the directory convention from `use-permissions.test.tsx` or `use-quicklook.test.ts`):
    - "does not fire request when token is null" — set `useAuthStore.setState({ token: null, user: null })`, render hook, assert `fetch`/mock spy not called (or `result.current.isFetching === false` immediately after mount with `isPending: true` and no network).
    - "fires request when token is present" — set token, render, assert mock called.
    - Use the existing test prototype from `frontend/src/components/auth/__tests__/EditorRoute.test.tsx:34,38` for the auth-store state manipulation.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npm run test -- --run src/components/search/hooks/__tests__/use-saved-searches.test.ts && npm run typecheck</automated>
  </verify>
  <acceptance_criteria>
    - `grep -n "enabled: !!token" frontend/src/components/search/hooks/use-saved-searches.ts` returns ≥ 1 hit.
    - `grep -n "useAuthStore" frontend/src/components/search/hooks/use-saved-searches.ts` returns ≥ 1 hit.
    - New tests in `use-saved-searches.test.ts` pass.
    - Typecheck exits 0.
  </acceptance_criteria>
  <done>
    `useSavedSearches` gated on `!!token`; new tests assert the gate behavior; typecheck clean.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Gate useAIStatus consumers on { enabled: !!token && isAdmin }</name>
  <files>frontend/src/components/admin/AIStatusCard.tsx, frontend/src/components/admin/settings/SettingsAITab.tsx</files>
  <read_first>
    - frontend/src/components/admin/AIStatusCard.tsx (full file — locate `useAIStatus()` call at line ~16)
    - frontend/src/components/admin/settings/SettingsAITab.tsx (full file — locate `useAIStatus()` call at line ~44)
    - frontend/src/hooks/use-admin.ts:180-200 (useAIStatus signature — DO NOT modify)
    - frontend/src/hooks/use-ai-availability.ts:1-30 (consumer-side gate analog — the GOOD pattern to copy)
    - frontend/src/stores/auth-store.ts:5-90 (confirm `isAdmin` selector shape: `useAuthStore((s) => s.isAdmin())`)
    - .planning/phases/1050-builder-smoke-carryover/1050-PATTERNS.md (Plan 03 — Analog #3 + #4)
  </read_first>
  <behavior>
    - Test 1 (manual/runtime verification in Plan 06): Loading any admin page with `token === null` fires 0 requests to `/api/admin/ai-status/`.
    - Test 2 (manual/runtime verification in Plan 06): Loading any admin page with `token !== null` but `user.is_admin === false` fires 0 requests to `/api/admin/ai-status/`.
    - Test 3 (manual/runtime verification in Plan 06): Loading the admin dashboard with `token !== null` AND `user.is_admin === true` fires the ai-status request normally.
    - No new unit tests required if existing AIStatusCard / SettingsAITab tests cover the consumer call sites; if not, add a smoke render test that asserts `useAIStatus` was called with `{ enabled: false }` when admin guard fails.
  </behavior>
  <action>
    In `frontend/src/components/admin/AIStatusCard.tsx` (at the `useAIStatus()` call ~line 16):

    1. Above the `useAIStatus(...)` call, add:
       ```typescript
       const token = useAuthStore((s) => s.token);
       const isAdmin = useAuthStore((s) => s.isAdmin());
       ```
       Add the import `import { useAuthStore } from '@/stores/auth-store';` at the top if not already present.

    2. Change `const aiStatus = useAIStatus();` to:
       ```typescript
       const aiStatus = useAIStatus({ enabled: !!token && isAdmin });
       ```

    In `frontend/src/components/admin/settings/SettingsAITab.tsx` (at the `useAIStatus()` call ~line 44):

    1. Apply the same two changes (import + selector reads + enabled pass).

    DO NOT modify `frontend/src/hooks/use-admin.ts` — the hook's signature already accepts `options?: { enabled?: boolean }`; the fix is consumer-side per the locked decision in CONTEXT.md / PATTERNS.md.

    Verify by re-grep:
    - `grep -n "useAIStatus()" frontend/src/components/admin/` should return 0 hits (no consumer calls it without options).
    - `grep -n "useAIStatus({" frontend/src/components/admin/` should return ≥ 2 hits (AIStatusCard + SettingsAITab).
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/frontend && npm run typecheck && npm run test -- --run src/components/admin/ src/hooks/__tests__/use-ai-availability.test.tsx</automated>
  </verify>
  <acceptance_criteria>
    - `grep -rn "useAIStatus()" frontend/src/components/admin/` returns 0 hits.
    - `grep -rn "useAIStatus({" frontend/src/components/admin/` returns ≥ 2 hits.
    - Each consumer (AIStatusCard, SettingsAITab) imports `useAuthStore`.
    - Typecheck exits 0.
    - Existing admin component tests continue to pass; existing `use-ai-availability.test.tsx` continues to pass (the hook itself is unchanged).
  </acceptance_criteria>
  <done>
    Both admin consumers of `useAIStatus` pass `{ enabled: !!token && isAdmin }`; no anonymous-page admin probe possible; typecheck clean.
  </done>
</task>

</tasks>

<verification>
- `/api/admin/ai-status/` fires 0 requests on `/login` (verified in Plan 06 CTRL-01 via Playwright MCP).
- `/api/search/saved/` fires 0 requests on `/login`.
- `/api/auth/me/` and `/api/auth/me/permissions/` continue to be gated on `!!token` (no change — existing behavior).
- `/api/auth/refresh/` console-error noise: investigate during the live MCP re-verify (likely already cookie-gated; if it still fires noise, capture as a Plan 06 finding and defer or fix inline depending on scope).
</verification>

<success_criteria>
1. `useSavedSearches` gated on `!!token`.
2. `AIStatusCard` and `SettingsAITab` both pass `{ enabled: !!token && isAdmin }` to `useAIStatus`.
3. `use-admin.ts` `useAIStatus` signature unchanged.
4. Typecheck clean; existing admin + auth-availability tests pass.
5. New `use-saved-searches.test.ts` tests cover the token-gate behavior.
</success_criteria>

<output>
Create `.planning/phases/1050-builder-smoke-carryover/1050-03-SUMMARY.md` when done — record:
- Hooks modified: `use-saved-searches.ts` (added gate); consumers updated: `AIStatusCard.tsx`, `SettingsAITab.tsx`.
- Confirmation that `use-admin.ts` was NOT modified.
- Confirmation that `use-auth.ts` and `use-permissions.ts` were NOT modified (already correctly gated).
- Any deferred follow-ups (e.g. if `/api/auth/refresh/` console noise turns out to need a separate fix).
</output>
