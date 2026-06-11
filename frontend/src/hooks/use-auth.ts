import { useCallback, useEffect } from 'react';
import { queryKeys } from '@/lib/query-keys';
import { useNavigate } from 'react-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/auth-store';
import { login as apiLogin, getMe } from '@/api/auth';
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
      const userResponse = await getMe();
      setAuth(
        tokenResponse.access_token,
        tokenResponse.refresh_token,
        tokenResponse.expires_in,
        userResponse,
      );
    },
    [setAuth, queryClient],
  );

  const logout = useCallback(() => {
    // BUG-021: clear the ['auth','me'] cache on logout so a subsequent login
    // does not see the previous user's cached identity.
    queryClient.removeQueries({ queryKey: queryKeys.auth.me });
    storeLogout();
    navigate('/login');
  }, [storeLogout, navigate, queryClient]);

  return { token, user, isAdmin, isEditor, login, logout };
}
