import { useCallback, useEffect } from 'react';
import { queryKeys } from '@/lib/query-keys';
import { useNavigate } from 'react-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/auth-store';
import { login as apiLogin, getMe, logoutSession } from '@/api/auth';
import { tryRefresh } from '@/api/client';

export function useAuth() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const token = useAuthStore((s) => s.token);
  const user = useAuthStore((s) => s.user);
  const expiresAt = useAuthStore((s) => s.expiresAt);
  const isAdmin = useAuthStore((s) => s.isAdmin());
  const isEditor = useAuthStore((s) => s.isEditor());
  const setAuth = useAuthStore((s) => s.setAuth);
  const storeLogout = useAuthStore((s) => s.logout);

  // Validate token on mount by fetching current user.
  const meQuery = useQuery({
    queryKey: queryKeys.auth.me,
    queryFn: getMe,
    enabled: !!token,
    retry: false,
    staleTime: 5 * 60 * 1000,
    meta: { skipGlobalError: true },
  });

  const userRoleKey = user?.roles.join('\0') ?? '';
  const meRoleKey = meQuery.data?.roles.join('\0') ?? '';

  useEffect(() => {
    if (!token || !meQuery.data) return;
    if (user?.id === meQuery.data.id && userRoleKey === meRoleKey) return;
    useAuthStore.setState({ user: meQuery.data });
  }, [token, meQuery.data, user?.id, userRoleKey, meRoleKey]);

  // Proactive refresh: refresh 60 seconds before expiry. Routes through the
  // shared tryRefresh() mutex in api/client.ts so a concurrent 401-driven
  // refresh and this timer collapse to a single /auth/refresh/ POST (SP-09).
  useEffect(() => {
    if (!expiresAt || !token) return;

    const delay = expiresAt - 60_000 - Date.now();
    if (delay <= 0) return;

    const timer = setTimeout(() => {
      // tryRefresh swallows errors and returns boolean; the 401 interceptor
      // on the next request will handle a failed refresh.
      void tryRefresh();
    }, delay);

    return () => clearTimeout(timer);
  }, [token, expiresAt]);

  const login = useCallback(
    async (username: string, password: string) => {
      const tokenResponse = await apiLogin(username, password);
      // Temporarily set token so getMe can use it
      useAuthStore.setState({ token: tokenResponse.access_token });
      // BUG-021: invalidate the ['auth','me'] cache so a new login never shows
      // the previous user's stale identity. Must happen BEFORE setAuth so the
      // meQuery re-fetch races the new token, not the old cached data.
      await queryClient.invalidateQueries({ queryKey: queryKeys.auth.me });
      // Drop the previous user's cached permissions too (usePermissions caches
      // ['auth','permissions'] with a 60s staleTime). Without this, a no-upload
      // viewer logging in right after an uploader would read the uploader's
      // stale capabilities. Remove (not invalidate) so capability gates fail
      // closed until the new user's permissions are fetched.
      queryClient.removeQueries({ queryKey: queryKeys.auth.permissions });
      let userResponse;
      try {
        userResponse = await getMe();
      } catch (err) {
        // fix(#1446): login already installed the refresh cookie. Bailing out
        // with only a store reset would leave that credential live while the
        // UI reports a failed sign-in, so revoke it before surfacing the error.
        await logoutSession().catch(() => {});
        useAuthStore.getState().logout();
        throw err;
      }
      setAuth(
        tokenResponse.access_token,
        // fix(#1302): null in cookie mode — the refresh token arrived as an
        // httpOnly cookie and is never held in JS.
        tokenResponse.refresh_token ?? null,
        tokenResponse.expires_in,
        userResponse,
      );
    },
    [setAuth, queryClient],
  );

  const logout = useCallback(async () => {
    // fix(#1446): revoke server-side BEFORE tearing down local state. The
    // request needs the bearer token that storeLogout is about to clear, and
    // since fix(#1302) the refresh cookie can only be removed by the server's
    // Set-Cookie. A failure here (offline, or a session already dead) must not
    // trap the user in a session they asked to leave, so the local teardown
    // runs either way.
    try {
      await logoutSession();
    } catch {
      // Intentionally swallowed — see above.
    }
    // BUG-021: clear the ['auth','me'] cache on logout so a subsequent login
    // does not see the previous user's cached identity.
    queryClient.removeQueries({ queryKey: queryKeys.auth.me });
    // Also drop cached permissions so capability gates (e.g. the catalog import
    // CTA) fail closed for the next anonymous/lower-privilege session.
    queryClient.removeQueries({ queryKey: queryKeys.auth.permissions });
    storeLogout();
    navigate('/login');
  }, [storeLogout, navigate, queryClient]);

  return { token, user, isAdmin, isEditor, login, logout };
}
