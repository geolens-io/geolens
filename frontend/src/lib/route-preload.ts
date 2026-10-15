import { matchRoutes, type RouteObject } from 'react-router';

interface PreloadHandle {
  preload: () => Promise<unknown>;
}

/** Route `handle` that lets bootstrap start a lazy route's chunk early. */
export function preload(load: () => Promise<unknown>): PreloadHandle {
  return { preload: load };
}

function isPreloadHandle(handle: unknown): handle is PreloadHandle {
  return typeof (handle as PreloadHandle | undefined)?.preload === 'function';
}

/**
 * Starts the chunk downloads for the routes matching `location`. The module
 * cache dedupes the later lazy() load. A failed prefetch is swallowed so that
 * load still retries and reports through the route error boundary.
 */
export function preloadMatchedRoutes(
  routes: RouteObject[],
  location: { pathname: string },
): void {
  const matches = matchRoutes(routes, location) ?? [];
  for (const { route } of matches) {
    if (!isPreloadHandle(route.handle)) continue;
    try {
      route.handle.preload().catch(() => {});
    } catch {
      // A synchronous throw must not block bootstrap either.
    }
  }
}
