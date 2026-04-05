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
    } catch (err) {
      // If rate-limited, wait before giving up so the next attempt isn't also blocked
      if (err instanceof ApiError && err.status === 429) {
        await new Promise((r) => setTimeout(r, 2000));
      }
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

async function authenticatedFetch(
  path: string,
  options: RequestInit = {},
  prepareHeaders?: (headers: Headers) => void,
): Promise<Response> {
  // Proactively refresh if token expires within 30 seconds
  const { token: currentToken, expiresAt } = useAuthStore.getState();
  if (currentToken && expiresAt && Date.now() > expiresAt - 30_000) {
    await tryRefresh();
  }

  function buildHeaders(): Headers {
    const headers = new Headers(options.headers);
    const token = useAuthStore.getState().token;
    if (token) {
      headers.set('Authorization', `Bearer ${token}`);
    }
    prepareHeaders?.(headers);
    return headers;
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: buildHeaders(),
  });

  if (response.status === 401) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      const retry = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers: buildHeaders(),
      });
      if (retry.ok) return retry;
    }
    useAuthStore.getState().logout();
    throw new ApiError('Unauthorized', 401);
  }

  return response;
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await authenticatedFetch(path, options, (headers) => {
    if (!headers.has('Content-Type') && !(options.body instanceof URLSearchParams) && !(options.body instanceof FormData)) {
      headers.set('Content-Type', 'application/json');
    }
  });

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

export async function apiFetchBlob(
  path: string,
  options: RequestInit = {},
): Promise<Blob> {
  const response = await authenticatedFetch(path, options, (headers) => {
    if (!headers.has('Accept')) {
      headers.set('Accept', 'image/*');
    }
  });

  if (!response.ok) {
    throw new ApiError(response.statusText, response.status);
  }

  return response.blob();
}
