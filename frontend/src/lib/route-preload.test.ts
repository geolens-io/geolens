import { describe, expect, it, vi } from 'vitest';
import type { RouteObject } from 'react-router';
import { useAuthStore } from '@/stores/auth-store';
import type { UserResponse } from '@/types/api';
import { preload, preloadMatchedRoutes, requires } from './route-preload';

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

describe('preloadMatchedRoutes behind guards', () => {
  const load = vi.fn(() => Promise.resolve());
  const guarded: RouteObject[] = [
    {
      path: '/',
      children: [
        {
          handle: requires('user'),
          children: [
            { path: 'settings', handle: preload(load) },
            {
              handle: requires('admin'),
              children: [
                { path: 'admin/users', handle: preload(load) },
                {
                  handle: requires('capability'),
                  children: [{ path: 'admin/settings', handle: preload(load) }],
                },
              ],
            },
          ],
        },
      ],
    },
  ];

  function signIn(roles: string[] | null) {
    useAuthStore.setState(
      roles
        ? { user: { roles } as UserResponse, sessionId: 'sid' }
        : { user: null, sessionId: null },
    );
    load.mockClear();
  }

  it('skips a protected path for a signed-out visitor', () => {
    signIn(null);
    preloadMatchedRoutes(guarded, { pathname: '/settings' });
    expect(load).not.toHaveBeenCalled();
  });

  it('skips an admin path for a signed-in user who is not an admin', () => {
    signIn(['viewer']);
    preloadMatchedRoutes(guarded, { pathname: '/admin/users' });
    expect(load).not.toHaveBeenCalled();
  });

  it('starts a protected path for a signed-in user', () => {
    signIn(['viewer']);
    preloadMatchedRoutes(guarded, { pathname: '/settings' });
    expect(load).toHaveBeenCalledTimes(1);
  });

  it('skips a capability-gated path even for an admin', () => {
    signIn(['admin']);
    preloadMatchedRoutes(guarded, { pathname: '/admin/settings' });
    expect(load).not.toHaveBeenCalled();
  });

  it('starts an admin path for an admin', () => {
    signIn(['admin']);
    preloadMatchedRoutes(guarded, { pathname: '/admin/users' });
    expect(load).toHaveBeenCalledTimes(1);
  });
});
