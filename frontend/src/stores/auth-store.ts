import { create } from 'zustand';
import { persist, type PersistOptions } from 'zustand/middleware';
import type { UserResponse } from '@/types/api';

interface AuthState {
  token: string | null;
  refreshToken: string | null;
  expiresAt: number | null;
  user: UserResponse | null;
  setAuth: (token: string, refreshToken: string, expiresIn: number, user: UserResponse) => void;
  setTokens: (token: string, refreshToken: string, expiresIn: number) => void;
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
};

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      refreshToken: null,
      expiresAt: null,
      user: null,
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
      logout: () => set({ token: null, refreshToken: null, expiresAt: null, user: null }),
      isAdmin: () => get().user?.roles.includes('admin') ?? false,
      isEditor: () => {
        const roles = get().user?.roles ?? [];
        return roles.includes('admin') || roles.includes('editor');
      },
    }),
    persistConfig,
  ),
);
