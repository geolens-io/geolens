import { API_BASE } from '@/lib/constants';
import { translateError } from '@/lib/error-map';
import { useAuthStore } from '@/stores/auth-store';
import { refreshAccessToken } from './auth';

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

// Mutex to prevent concurrent refresh requests
let refreshPromise: Promise<void> | null = null;

async function tryRefresh(): Promise<boolean> {
  const { refreshToken } = useAuthStore.getState();
  if (!refreshToken) return false;

  if (refreshPromise) {
    await refreshPromise;
    return !!useAuthStore.getState().token;
  }

  refreshPromise = (async () => {
    try {
      const tokens = await refreshAccessToken(refreshToken);
      useAuthStore.getState().setTokens(
        tokens.access_token,
        tokens.refresh_token,
        tokens.expires_in,
      );
    } catch {
      // Refresh failed -- will fall through to logout
    }
  })();

  try {
    await refreshPromise;
  } finally {
    refreshPromise = null;
  }

  return !!useAuthStore.getState().token;
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  // Proactively refresh if token expires within 30 seconds
  const { token: currentToken, expiresAt } = useAuthStore.getState();
  if (currentToken && expiresAt && Date.now() > expiresAt - 30_000) {
    await tryRefresh();
  }

  const token = useAuthStore.getState().token;
  const headers = new Headers(options.headers);

  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  if (!headers.has('Content-Type') && !(options.body instanceof URLSearchParams) && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    // Attempt token refresh before logging out
    const refreshed = await tryRefresh();
    if (refreshed) {
      // Retry original request with new token
      const newToken = useAuthStore.getState().token;
      const retryHeaders = new Headers(options.headers);
      if (newToken) {
        retryHeaders.set('Authorization', `Bearer ${newToken}`);
      }
      if (!retryHeaders.has('Content-Type') && !(options.body instanceof URLSearchParams) && !(options.body instanceof FormData)) {
        retryHeaders.set('Content-Type', 'application/json');
      }
      const retry = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers: retryHeaders,
      });
      if (retry.ok) {
        if (retry.status === 204) return undefined as T;
        return retry.json() as Promise<T>;
      }
      // Retry also failed -- fall through to logout
    }
    useAuthStore.getState().logout();
    throw new ApiError('Unauthorized', 401);
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (body.detail) {
        detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      // body not JSON, use statusText
    }
    throw new ApiError(translateError(detail), response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}
