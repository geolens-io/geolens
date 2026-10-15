import { describe, expect, it, vi } from 'vitest';
import type { RouteObject } from 'react-router';
import { preload, preloadMatchedRoutes } from './route-preload';

function routes(load: () => Promise<unknown>): RouteObject[] {
  return [
    { path: '/', children: [{ path: 'datasets/:id', handle: preload(load) }, { path: 'plain' }] },
  ];
}

describe('preloadMatchedRoutes', () => {
  it('starts the loader of the matched route', () => {
    const load = vi.fn(() => Promise.resolve());
    preloadMatchedRoutes(routes(load), { pathname: '/datasets/7' });
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('does nothing for a path with no match or no handle', () => {
    const load = vi.fn(() => Promise.resolve());
    preloadMatchedRoutes(routes(load), { pathname: '/nowhere/at/all' });
    preloadMatchedRoutes(routes(load), { pathname: '/plain' });
    expect(load).not.toHaveBeenCalled();
  });

  it('swallows a rejected or throwing loader', () => {
    expect(() =>
      preloadMatchedRoutes(routes(() => Promise.reject(new Error('chunk'))), { pathname: '/datasets/1' }),
    ).not.toThrow();
    expect(() =>
      preloadMatchedRoutes(
        routes(() => {
          throw new Error('sync');
        }),
        { pathname: '/datasets/1' },
      ),
    ).not.toThrow();
  });
});
