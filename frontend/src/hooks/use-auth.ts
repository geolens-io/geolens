import { useCallback, useEffect } from 'react';
import { queryKeys } from '@/lib/query-keys';
import { useNavigate } from 'react-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/auth-store';
import { login as apiLogin, getMe, logoutSession } from '@/api/auth';
import { abortInflightRefresh, tryRefresh } from '@/api/client';
import { completeSignIn } from '@/lib/sign-in';

export function useAuth() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const token = useAuthStore((s) => s.token);
  const user = useAuthStore((s) => s.user);
  const expiresAt = useAuthStore((s) => s.expiresAt);
  const isAdmin = useAuthStore((s) => s.isAdmin());
  const isEditor = useAuthStore((s) => s.isEditor());
  const storeLogout = useAuthStore((s) => s.logout);

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

  // Refresh 60 seconds before expiry, through the shared tryRefresh() mutex so
  // a concurrent 401-driven refresh collapses to a single /auth/refresh/ POST.
  useEffect(() => {
    if (!expiresAt || !token) return;

    const delay = expiresAt - 60_000 - Date.now();
    if (delay <= 0) return;

    const timer = setTimeout(() => {
      // tryRefresh swallows errors; the next request's 401 interceptor handles
      // a failed refresh.
      void tryRefresh();
    }, delay);

    return () => clearTimeout(timer);
  }, [token, expiresAt]);

  const login = useCallback(
    async (username: string, password: string) => {
      const tokenResponse = await apiLogin(username, password);
      await completeSignIn(tokenResponse, async () => {
        // Runs once the new token is installed, so a new login never shows
        // the previous user's cached identity.
        await queryClient.invalidateQueries({ queryKey: queryKeys.auth.me });
        // Remove (not invalidate) the previous user's cached permissions so
        // capability gates fail closed until the new user's are fetched.
        queryClient.removeQueries({ queryKey: queryKeys.auth.permissions });
      });
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    // Revoke server-side BEFORE tearing down local state: the request needs
    // the bearer token storeLogout is about to clear, and only the server's
    // Set-Cookie can remove the refresh cookie. Dispatched, not awaited:
    // logoutSession reads the token synchronously, so the request is in
    // flight with its credential before teardown, and waiting would hold the
    // user on an authenticated screen while the network stalls.
    // Abandon any in-flight refresh first: its Set-Cookie would otherwise
    // overwrite a new session's cookie with the token being revoked.
    abortInflightRefresh();
    void logoutSession().catch(() => {
      // Offline or session already dead; local teardown must proceed anyway.
    });
    // Drop cached identity and permissions so capability gates fail closed for
    // the next anonymous or lower-privilege session.
    queryClient.removeQueries({ queryKey: queryKeys.auth.me });
    queryClient.removeQueries({ queryKey: queryKeys.auth.permissions });
    storeLogout();
    navigate('/login');
  }, [storeLogout, navigate, queryClient]);

  return { token, user, isAdmin, isEditor, login, logout };
}
