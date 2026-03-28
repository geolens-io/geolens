import { useCallback, useEffect } from 'react';
import { queryKeys } from '@/lib/query-keys';
import { useNavigate } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { useAuthStore } from '@/stores/auth-store';
import { login as apiLogin, getMe, refreshAccessToken } from '@/api/auth';

export function useAuth() {
  const navigate = useNavigate();
  const token = useAuthStore((s) => s.token);
  const user = useAuthStore((s) => s.user);
  const expiresAt = useAuthStore((s) => s.expiresAt);
  const isAdmin = useAuthStore((s) => s.isAdmin());
  const isEditor = useAuthStore((s) => s.isEditor());
  const setAuth = useAuthStore((s) => s.setAuth);
  const storeLogout = useAuthStore((s) => s.logout);

  // Validate token on mount by fetching current user
  useQuery({
    queryKey: queryKeys.auth.me,
    queryFn: getMe,
    enabled: !!token,
    retry: false,
    staleTime: 5 * 60 * 1000,
    meta: { skipGlobalError: true },
  });

  // Proactive refresh: refresh 60 seconds before expiry
  useEffect(() => {
    if (!expiresAt || !token) return;

    const delay = expiresAt - 60_000 - Date.now();
    if (delay <= 0) return;

    const timer = setTimeout(async () => {
      const { refreshToken } = useAuthStore.getState();
      if (!refreshToken) return;
      try {
        const tokens = await refreshAccessToken(refreshToken);
        useAuthStore.getState().setTokens(
          tokens.access_token,
          tokens.refresh_token,
          tokens.expires_in,
        );
      } catch {
        // Will be handled by 401 interceptor on next request
      }
    }, delay);

    return () => clearTimeout(timer);
  }, [token, expiresAt]);

  const login = useCallback(
    async (username: string, password: string) => {
      const tokenResponse = await apiLogin(username, password);
      // Temporarily set token so getMe can use it
      useAuthStore.setState({ token: tokenResponse.access_token });
      const userResponse = await getMe();
      setAuth(
        tokenResponse.access_token,
        tokenResponse.refresh_token,
        tokenResponse.expires_in,
        userResponse,
      );
    },
    [setAuth],
  );

  const logout = useCallback(() => {
    storeLogout();
    navigate('/login');
  }, [storeLogout, navigate]);

  return { token, user, isAdmin, isEditor, login, logout };
}
