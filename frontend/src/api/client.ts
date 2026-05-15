import { API_BASE } from '@/lib/constants';
import { translateError } from '@/lib/error-map';
import { useAuthStore } from '@/stores/auth-store';
import { refreshAccessToken } from './auth';

export class ApiError extends Error {
  status: number;
  body?: unknown;

  constructor(message: string, status: number, body?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

// SP-09: module-level in-flight singleton. Concurrent 401s AND the proactive
// timer in use-auth.ts (which now also calls tryRefresh) collapse to one
// /auth/refresh/ POST per refresh cycle. Cleared in finally so the next
// expiration starts fresh.
let inflightRefresh: Promise<void> | null = null;

export async function tryRefresh(): Promise<boolean> {
  const { refreshToken } = useAuthStore.getState();
  if (!refreshToken) return false;

  if (inflightRefresh) {
    await inflightRefresh;
    return !!useAuthStore.getState().token;
  }

  inflightRefresh = (async () => {
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
    await inflightRefresh;
  } finally {
    inflightRefresh = null;
  }

  return !!useAuthStore.getState().token;
}

/**
 * Fetch wrapper that converts `TypeError: Failed to fetch` (offline / DNS
 * failure / CORS preflight error) into an ApiError with status 0 (RES-N1).
 * Without this, network failures propagate as opaque unhandled rejections
 * through every TanStack Query and the UI shows "Failed to fetch" literally.
 */
async function safeFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init);
  } catch (err) {
    // TypeError is what browsers throw for network-layer failures
    // (offline, DNS unresolvable, CORS preflight blocked, etc.). Other
    // errors (e.g. AbortError) should bubble through unchanged.
    if (err instanceof TypeError) {
      throw new ApiError('Network unavailable — check your connection', 0);
    }
    throw err;
  }
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

  const response = await safeFetch(`${API_BASE}${path}`, {
    ...options,
    headers: buildHeaders(),
  });

  if (response.status === 401) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      const retry = await safeFetch(`${API_BASE}${path}`, {
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
    let detail: string = response.statusText;
    let detailRaw: unknown = undefined;
    try {
      const body = await response.json();
      if (body.detail !== undefined) {
        detailRaw = body.detail;
        detail =
          typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      // body not JSON, use statusText
    }
    throw new ApiError(translateError(detail), response.status, detailRaw);
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
