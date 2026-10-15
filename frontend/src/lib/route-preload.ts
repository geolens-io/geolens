import { matchRoutes, type RouteObject } from 'react-router';
import { useAuthStore } from '@/stores/auth-store';

type Access = 'user' | 'editor' | 'admin';

interface PreloadHandle {
  preload?: () => Promise<unknown>;
  requires?: Access;
}

/** Route `handle` that lets bootstrap start a lazy route's chunk early. */
export function preload(load: () => Promise<unknown>): PreloadHandle {
  return { preload: load };
}

/** Route `handle` for a guard route: its subtree is only preloaded for a persisted user with this access. */
export function requires(access: Access): PreloadHandle {
  return { requires: access };
}

function asHandle(handle: unknown): PreloadHandle {
  return typeof handle === 'object' && handle !== null ? (handle as PreloadHandle) : {};
}

// The token is not persisted, but the user and session id are, and they are
// what a reload restores before the refresh returns.
function persistedUserHolds(access: Access): boolean {
  const { user, sessionId } = useAuthStore.getState();
  if (!user || !sessionId) return false;
  if (access === 'user') return true;
  if (access === 'admin') return user.roles.includes('admin');
  return user.roles.includes('admin') || user.roles.includes('editor');
}

/**
 * Starts the chunk downloads for the routes matching `location`, unless a
 * guard on the way would turn the visitor away. The module cache dedupes the
 * later lazy() load. A failed prefetch is swallowed so that load still retries
 * and reports through the route error boundary.
 */
export function preloadMatchedRoutes(
  routes: RouteObject[],
  location: { pathname: string },
): void {
  const handles = (matchRoutes(routes, location) ?? []).map(({ route }) => asHandle(route.handle));
  if (handles.some((h) => h.requires && !persistedUserHolds(h.requires))) return;
  for (const { preload: load } of handles) {
    if (typeof load !== 'function') continue;
    try {
      load().catch(() => {});
    } catch {
      // A synchronous throw must not block bootstrap either.
    }
  }
}
