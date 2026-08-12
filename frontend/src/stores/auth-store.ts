import { create } from 'zustand';
import { persist, type PersistOptions } from 'zustand/middleware';
import { cookieAuthAvailable } from '@/lib/auth-transport';
import type { UserResponse } from '@/types/api';

interface AuthState {
  token: string | null;
  refreshToken: string | null;
  expiresAt: number | null;
  user: UserResponse | null;
  /**
   * fix(#1446): bumped on every logout so a refresh that was already in flight
   * can tell its session ended and decline to write rotated tokens back. Without
   * it, a slow refresh resolving after teardown re-populates the store (and
   * localStorage), signing the browser back in on the login page.
   *
   * In-memory and per-tab: deliberately absent from `partialize`, since it
   * orders events within one tab's lifetime and means nothing across reloads.
   * Cross-tab logout therefore cannot propagate through the persisted blob —
   * the `storage` listener below bumps it explicitly instead.
   */
  sessionEpoch: number;
  setAuth: (
    token: string,
    refreshToken: string | null,
    expiresIn: number,
    user: UserResponse,
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
  /**
   * `partialize` makes the persisted surface explicit — only these auth fields
   * are written, never any transient UI state that might later be added.
   *
   * fix(#1302): the refresh token is no longer among them. It now lives in an
   * httpOnly cookie the browser attaches to /auth/refresh/ by itself, which
   * also subsumes what the cross-tab `storage` listener below used to do for it
   * — every tab shares one cookie jar, so rotation converges without any
   * JS-visible copy. `refreshToken` survives in the in-memory shape only so a
   * pre-GH-1302 blob can be rehydrated once and handed to the migrating
   * refresh; it is never written back.
   *
   * fix(#438) DATA-05 still applies to the ACCESS token, which stays in
   * localStorage for cross-tab convergence. Moving it to memory is tracked
   * separately in GH-1302's remaining acceptance criteria.
   *
   * A deployment whose API sits on a different origin cannot use the cookie
   * (see lib/auth-transport.ts), so it keeps persisting the refresh token
   * rather than losing its session on every reload.
   */
  partialize: (state) =>
    ({
      token: state.token,
      ...(cookieAuthAvailable() ? {} : { refreshToken: state.refreshToken }),
      expiresAt: state.expiresAt,
      user: state.user,
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
      setAuth: (token, refreshToken, expiresIn, user) =>
        set({
          token,
          refreshToken,
          expiresAt: Date.now() + expiresIn * 1000,
          user,
        }),
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
    const hadToken = !!useAuthStore.getState().token;
    void Promise.resolve(useAuthStore.persist.rehydrate()).then(() => {
      // fix(#438): DATA-09 — when another tab logs out, rehydrating clears this
      // tab's token, but React only re-checks auth on its next render, so the
      // tab kept showing protected chrome. On a present→absent transition, send
      // it to /login. Skip if already on a public auth route so we don't loop.
      const stillLoggedIn = !!useAuthStore.getState().token;
      if (hadToken && !stillLoggedIn) {
        // fix(#1446): another tab logged out. Rehydration clears this tab's
        // token but cannot touch its epoch, which is per-tab — so a refresh
        // already in flight here would still see a matching epoch and write
        // its rotated tokens back, resurrecting the session the other tab just
        // ended (and re-persisting it for every tab). Bump on the
        // present->absent transition so that write is refused.
        useAuthStore.setState((s) => ({ sessionEpoch: s.sessionEpoch + 1 }));
        const path = window.location.pathname;
        if (path !== '/login' && path !== '/register') {
          window.location.assign('/login');
        }
      }
    });
  });
}
