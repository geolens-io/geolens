import { create } from 'zustand';
import { persist, type PersistOptions } from 'zustand/middleware';
// Cyclic with '@/api/client' (it imports this store), which is safe here:
// neither module touches the other at import time, and a hoisted function
// declaration is initialized before either body runs.
import { abortInflightRefresh } from '@/api/client';
import { randomId } from '@/lib/random-id';
import type { UserResponse } from '@/types/api';

interface AuthState {
  token: string | null;
  refreshToken: string | null;
  expiresAt: number | null;
  user: UserResponse | null;
  /**
   * Bumped whenever the session changes identity: a sign-in, a logout, or
   * another tab installing or ending one. Work started under one session
   * captures it and refuses to write, refresh, resend or sign out once it has
   * moved, so a late result can neither revive an ended session nor act on a
   * newer one. A token refresh keeps it.
   *
   * In-memory and per-tab: it orders events within one tab's lifetime, so the
   * `storage` listener below bumps it for changes made by other tabs.
   */
  sessionEpoch: number;
  /**
   * Persisted identity of the installed session, shared by every tab. A new
   * value means a different sign-in rather than a refresh of the same one.
   */
  sessionId: string | null;
  /** Install a new session. `user` is null while its profile is still loading. */
  setAuth: (
    token: string,
    refreshToken: string | null,
    expiresIn: number,
    user: UserResponse | null,
  ) => void;
  setTokens: (token: string, refreshToken: string | null, expiresIn: number) => void;
  logout: () => void;
  isAdmin: () => boolean;
  isEditor: () => boolean;
}

/**
 * Persist schema version for the auth store.
 *
 * When the persisted shape (token / refreshToken / expiresAt / user) needs a
 * breaking change in a future plan, bump this number AND add a corresponding
 * `if (fromVersion < N)` block inside `migrate` that transforms the
 * persisted blob from `N - 1` to `N`. Each version step should be additive:
 * never remove an old `if` block, even after newer versions exist, so users
 * who skip multiple releases still upgrade cleanly.
 */
const PERSIST_VERSION = 1;

const persistConfig: PersistOptions<AuthState> = {
  name: 'geolens-auth',
  version: PERSIST_VERSION,
  /**
   * Forward migrations live here.
   *
   * Today we are at version 1 with no prior shape; legacy un-versioned blobs
   * (zustand treats them as `fromVersion === 0`) are accepted as-is so that
   * existing users do not lose their session on rollout. When you bump to
   * version 2, add:
   *
   *   if (fromVersion < 2) {
   *     // mutate persistedState into the v2 shape
   *   }
   *
   * Always return the (possibly mutated) state at the end — zustand's
   * middleware contract requires it.
   */
  migrate: (persistedState: unknown, fromVersion: number) => {
    if (fromVersion < PERSIST_VERSION) {
      // No transformations yet (version 1 is the baseline).
      // Future authors: add `if (fromVersion < 2) { ... }` blocks here.
    }
    return persistedState as AuthState;
  },
  // The persisted blob is untrusted: a `user` without the `roles` array every
  // role check reads throws during render instead of reaching the sign-in path.
  merge: (persistedState, currentState) => {
    const persisted = (persistedState ?? {}) as Partial<AuthState>;
    return {
      ...currentState,
      ...persisted,
      user: Array.isArray(persisted.user?.roles) ? persisted.user : null,
    };
  },
  /**
   * `partialize` makes the persisted surface explicit — only these auth fields
   * are written, never any transient UI state that might later be added.
   *
   * fix(#1302): the refresh token is no longer among them for a cookie-mode
   * session. It lives in an httpOnly cookie the browser attaches to /auth by
   * itself, which also subsumes what the cross-tab `storage` listener below
   * used to do for it — every tab shares one cookie jar, so rotation converges
   * without any JS-visible copy.
   *
   * fix(#1446): the condition is "is there a token in memory", not "is cookie
   * mode available". Two sessions legitimately still hold one, and stripping it
   * from storage before it is spent loses the session on the next reload:
   *   - a cross-origin deployment, which cannot use the cookie at all (see
   *     lib/auth-transport.ts) and keeps using body tokens indefinitely;
   *   - a pre-GH-1302 session mid-migration, whose legacy token is what the
   *     next refresh trades for a cookie. Zustand writes the persisted blob on
   *     its own after migrating a version-0 shape, so a tab closed before that
   *     refresh ran would otherwise come back with neither credential.
   * Once the migrating refresh spends it, `setTokens` stores null and it stops
   * being persisted for good.
   *
   * fix(#438) DATA-05 still applies to the ACCESS token, which stays in
   * localStorage for cross-tab convergence. Moving it to memory is tracked
   * separately in GH-1302's remaining acceptance criteria.
   */
  partialize: (state) =>
    ({
      token: state.token,
      ...(state.refreshToken ? { refreshToken: state.refreshToken } : {}),
      expiresAt: state.expiresAt,
      user: state.user,
      sessionId: state.sessionId,
    }) as unknown as AuthState,
};

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      refreshToken: null,
      expiresAt: null,
      user: null,
      sessionEpoch: 0,
      sessionId: null,
      setAuth: (token, refreshToken, expiresIn, user) =>
        set((state) => ({
          token,
          refreshToken,
          expiresAt: Date.now() + expiresIn * 1000,
          user,
          sessionId: randomId(),
          sessionEpoch: state.sessionEpoch + 1,
        })),
      setTokens: (token, refreshToken, expiresIn) =>
        set({
          token,
          refreshToken,
          expiresAt: Date.now() + expiresIn * 1000,
        }),
      logout: () =>
        set((state) => ({
          token: null,
          refreshToken: null,
          expiresAt: null,
          user: null,
          sessionId: null,
          sessionEpoch: state.sessionEpoch + 1,
        })),
      isAdmin: () => get().user?.roles.includes('admin') ?? false,
      isEditor: () => {
        const roles = get().user?.roles ?? [];
        return roles.includes('admin') || roles.includes('editor');
      },
    }),
    persistConfig,
  ),
);

/**
 * Cross-tab token sync.
 *
 * Originally this existed because refresh tokens were single-use and lived in
 * localStorage: a refresh in one tab left every OTHER tab holding a revoked
 * token, and the next request there logged the tab out (e.g. "saved a map →
 * logged out" with two tabs open). fix(#1302) moved the refresh token into a
 * cookie, which all tabs already share, so that half is handled by the browser.
 *
 * The listener still earns its place for the ACCESS token, which remains in
 * localStorage: rehydrating keeps every tab on the freshest access token and
 * propagates logout. The `storage` event fires only in the tabs that did NOT
 * make the change.
 */
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key !== persistConfig.name) return;
    const { token: previousToken, sessionId: previousSessionId } = useAuthStore.getState();
    void Promise.resolve(useAuthStore.persist.rehydrate()).then(() => {
      const { token, sessionId } = useAuthStore.getState();
      const loggedOut = !!previousToken && !token;
      if (loggedOut || sessionId !== previousSessionId) {
        // Rehydration replaced the session but cannot touch this tab's epoch,
        // so work in flight here would still write, refresh or sign out
        // against the session another tab just ended or replaced.
        useAuthStore.setState((s) => ({ sessionEpoch: s.sessionEpoch + 1 }));
        // The epoch only blocks the store write. Abort the request too, so the
        // browser never processes a response whose Set-Cookie could overwrite
        // the cookie of the session that replaced it.
        abortInflightRefresh();
      }
      // React only re-checks auth on its next render, so a tab another tab
      // signed out would keep showing protected chrome. Skip public auth
      // routes so this cannot loop.
      if (loggedOut) {
        const path = window.location.pathname;
        if (path !== '/login' && path !== '/register') {
          window.location.assign('/login');
        }
      }
    });
  });
}
