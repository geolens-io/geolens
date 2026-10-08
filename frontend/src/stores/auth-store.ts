import { create } from 'zustand';
import { createJSONStorage, persist, type PersistOptions } from 'zustand/middleware';
import { postAuthMessage } from '@/lib/auth-channel';
import { randomId } from '@/lib/random-id';
import { readStorage, removeStorage, writeStorage } from '@/lib/storage';
import type { UserResponse } from '@/types/api';

interface AuthState {
  /** Held in memory only; a reload recovers it from the refresh cookie. */
  token: string | null;
  /**
   * Set only for a body-token session (an API mounted on another origin or
   * path, where the refresh cookie cannot reach it) and for the one refresh
   * that migrates a legacy stored token. Held in memory only, so a reload ends
   * a body-token session.
   */
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
   * cross-tab handlers in lib/session-sync.ts bump it for other tabs' changes.
   */
  sessionEpoch: number;
  /**
   * Identity of the installed session. A new value means a different sign-in
   * rather than a refresh of the same one. Persisted for a cookie session, where
   * it marks a session the next page load can recover.
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

export const SIGNED_OUT = {
  token: null,
  refreshToken: null,
  expiresAt: null,
  user: null,
  sessionId: null,
} as const;

/**
 * Persist schema version for the auth store.
 *
 * A breaking change to the persisted shape bumps this number and adds an
 * `if (fromVersion < N)` block to `migrate` that turns the `N - 1` shape into
 * the `N` one. Keep every block, so a user who skipped releases still upgrades.
 */
const PERSIST_VERSION = 2;
const STORAGE_KEY = 'geolens-auth';

interface PersistedAuth {
  sessionId: string | null;
  user: UserResponse | null;
}

/** The persisted user, if it belongs to `sessionId` and has the roles array role checks read. */
export function readPersistedUser(sessionId: string): UserResponse | null {
  const raw = readStorage(STORAGE_KEY);
  try {
    const state = raw ? (JSON.parse(raw) as { state?: Partial<PersistedAuth> }).state : undefined;
    if (state?.sessionId !== sessionId) return null;
    return Array.isArray(state.user?.roles) ? state.user : null;
  } catch {
    return null;
  }
}

const persistConfig: PersistOptions<AuthState, PersistedAuth> = {
  name: STORAGE_KEY,
  version: PERSIST_VERSION,
  // Zustand migrates only a blob that carries a version, so one written before
  // versioning reads as version 0 and gets its tokens dropped like any other.
  storage: createJSONStorage(
    () => ({ getItem: readStorage, setItem: writeStorage, removeItem: removeStorage }),
    {
      reviver: (key, value) =>
        key === '' && typeof value === 'object' && value !== null && !('version' in value)
          ? { ...value, version: 0 }
          : value,
    },
  ),
  migrate: (persistedState: unknown, fromVersion: number) => {
    const state = (persistedState ?? {}) as Record<string, unknown>;
    if (fromVersion < 2) {
      // Versions 0 and 1 stored the access token, and a body-token session its
      // refresh token too. The access token is dropped. A legacy refresh token
      // is carried into memory for the refresh that runs on load, and the
      // write zustand makes after a migration leaves it out of storage.
      const legacyToken = typeof state.token === 'string' ? state.token : null;
      const legacyRefresh = typeof state.refreshToken === 'string' ? state.refreshToken : null;
      const sessionId =
        typeof state.sessionId === 'string'
          ? state.sessionId
          : legacyToken || legacyRefresh
            ? randomId()
            : null;
      return {
        sessionId,
        user: (state.user as UserResponse | null | undefined) ?? null,
        ...(legacyRefresh ? { refreshToken: legacyRefresh } : {}),
      } as PersistedAuth;
    }
    return state as unknown as PersistedAuth;
  },
  // The persisted blob is untrusted: only these fields are read from it, and a
  // `user` without the `roles` array every role check reads would throw during
  // render instead of reaching the sign-in path.
  merge: (persistedState, currentState) => {
    const persisted = (persistedState ?? {}) as Partial<PersistedAuth> & { refreshToken?: unknown };
    return {
      ...currentState,
      sessionId: typeof persisted.sessionId === 'string' ? persisted.sessionId : null,
      user: Array.isArray(persisted.user?.roles) ? persisted.user : null,
      ...(typeof persisted.refreshToken === 'string' ? { refreshToken: persisted.refreshToken } : {}),
    };
  },
  // Never a token. A session holding its refresh token in memory cannot
  // outlive the page, so nothing about it is persisted.
  partialize: (state) =>
    state.refreshToken
      ? { sessionId: null, user: null }
      : { sessionId: state.sessionId, user: state.user },
};

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      ...SIGNED_OUT,
      sessionEpoch: 0,
      setAuth: (token, refreshToken, expiresIn, user) => {
        const sessionId = randomId();
        set((state) => ({
          token,
          refreshToken,
          expiresAt: Date.now() + expiresIn * 1000,
          user,
          sessionId,
          sessionEpoch: state.sessionEpoch + 1,
        }));
        // Every tab shares the cookie this sign-in just replaced.
        if (!refreshToken) postAuthMessage({ type: 'login', sessionId });
      },
      setTokens: (token, refreshToken, expiresIn) =>
        set({
          token,
          refreshToken,
          expiresAt: Date.now() + expiresIn * 1000,
        }),
      logout: () => {
        const { sessionId, refreshToken } = get();
        set((state) => ({ ...SIGNED_OUT, sessionEpoch: state.sessionEpoch + 1 }));
        if (sessionId && !refreshToken) postAuthMessage({ type: 'logout', sessionId });
      },
      isAdmin: () => get().user?.roles.includes('admin') ?? false,
      isEditor: () => {
        const roles = get().user?.roles ?? [];
        return roles.includes('admin') || roles.includes('editor');
      },
    }),
    persistConfig,
  ),
);
