import { API_BASE } from '@/lib/constants';
import { translateApiErrorDetail } from '@/lib/error-map';
import { useAuthStore } from '@/stores/auth-store';
import { refreshAccessToken } from './auth';
import i18n from '@/i18n/i18n';

// fix(#438): DATA-04 — a request whose socket hangs used to spin forever and
// stall the polling loop that issued it. 30s comfortably covers a slow catalog
// query while still freeing a wedged loop. Applied to apiFetch (JSON) only;
// streaming and blob-download callers manage their own longer-lived signals.
const REQUEST_TIMEOUT_MS = 30_000;

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

// fix(#628): once a request 401s AND the follow-up refresh cannot produce a
// working token, the session is conclusively dead — every surface in the app
// is about to fail the same way (silent 403 tiles, quiet query errors, generic
// toasts). Instead of letting each surface invent its own failure UX, clear
// the session once and notify a single app-level handler (the signed-out
// dialog host). The latch is keyed on the dead refresh token's value: the
// burst of concurrent in-flight failures all captured the same token, so they
// collapse to one notification, while the next session (refresh tokens
// rotate, so its token is always new) notifies again.
let sessionExpiredHandler: (() => void) | null = null;
let lastNotifiedRefreshToken: string | null = null;

/** Register the app-level signed-out handler. Returns an unregister fn. */
export function onSessionExpired(handler: () => void): () => void {
  sessionExpiredHandler = handler;
  return () => {
    if (sessionExpiredHandler === handler) sessionExpiredHandler = null;
  };
}

export function notifySessionExpired(deadRefreshToken: string): void {
  if (deadRefreshToken === lastNotifiedRefreshToken) return;
  lastNotifiedRefreshToken = deadRefreshToken;
  useAuthStore.getState().logout();
  sessionExpiredHandler?.();
}

export async function tryRefresh(): Promise<boolean> {
  const { refreshToken } = useAuthStore.getState();
  if (!refreshToken) return false;

  if (inflightRefresh) {
    await inflightRefresh;
    return !!useAuthStore.getState().token;
  }

  // The singleton MUST be cleared synchronously when the IIFE settles —
  // not in the outer try/finally — so a third caller that arrives between
  // resolution and the outer finally can't observe `inflightRefresh === null`
  // and kick off a second refresh cycle. WR-02 (1045-REVIEW.md).
  const promise = (async () => {
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
    } finally {
      inflightRefresh = null;
    }
  })();
  inflightRefresh = promise;

  await promise;
  return !!useAuthStore.getState().token;
}

/**
 * Fetch wrapper that converts `TypeError: Failed to fetch` (offline / DNS
 * failure / CORS preflight error) into an ApiError with status 0 (RES-N1).
 * Without this, network failures propagate as opaque unhandled rejections
 * through every TanStack Query and the UI shows "Failed to fetch" literally.
 */
export async function safeFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init);
  } catch (err) {
    // TypeError is what browsers throw for network-layer failures
    // (offline, DNS unresolvable, CORS preflight blocked, etc.). Other
    // errors (e.g. AbortError) should bubble through unchanged.
    if (err instanceof TypeError) {
      // fix(#438): UX-10 — was hardcoded English; this is one of the errors a
      // non-English user is most likely to hit.
      throw new ApiError(i18n.t('common:errors.networkUnavailable'), 0);
    }
    // fix(#438): DATA-04 — a timeout-triggered abort becomes a normalized
    // ApiError; a caller-initiated AbortError still bubbles unchanged.
    if (err instanceof DOMException && err.name === 'TimeoutError') {
      throw new ApiError(i18n.t('common:errors.requestTimeout'), 0);
    }
    throw err;
  }
}

/**
 * BUG-035: Shared refresh-aware fetch core that returns the RAW Response.
 *
 * Streaming/download helpers (AI SSE streams, blob exports) can't go through
 * apiFetch because they need the live Response/ReadableStream/Blob rather than
 * a parsed JSON body. Previously they issued a bare `fetch()` with a possibly
 * stale JWT, so a stream/download issued as the FIRST request after a long idle
 * hit a hard 401 with no retry. This core applies the SAME proactive-refresh +
 * 401→tryRefresh→retry machinery as authenticatedFetch while leaving the
 * response body untouched, so callers keep their streaming semantics.
 *
 * `target` is a fully-qualified URL or absolute path (already including
 * API_BASE) — unlike authenticatedFetch, the caller owns URL construction.
 */
export async function authenticatedRawFetch(
  target: string,
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

  const response = await safeFetch(target, {
    ...options,
    headers: buildHeaders(),
  });

  if (response.status === 401) {
    // fix(#628): only a session that existed can expire. A real session always
    // holds a refresh token; an anonymous 401 (or the transient token-only
    // state mid-login) must not raise the signed-out prompt. Captured BEFORE
    // tryRefresh so every concurrent failure holds the same dead token.
    const sessionRefreshToken = useAuthStore.getState().refreshToken;
    const refreshed = await tryRefresh();
    if (refreshed) {
      const retry = await safeFetch(target, {
        ...options,
        headers: buildHeaders(),
      });
      // BUG-016: only treat a retry that is STILL 401 as an auth failure.
      // Non-auth errors (403, 404, 422, 500, …) must be returned to the
      // caller so they can be handled normally — not silently converted into
      // a spurious logout.
      if (retry.status !== 401) return retry;
    }
    if (sessionRefreshToken) {
      notifySessionExpired(sessionRefreshToken);
    } else {
      useAuthStore.getState().logout();
    }
    // fix(#438): UX-10 — was hardcoded English.
    throw new ApiError(i18n.t('common:errors.unauthorized'), 401);
  }

  return response;
}

async function authenticatedFetch(
  path: string,
  options: RequestInit = {},
  prepareHeaders?: (headers: Headers) => void,
): Promise<Response> {
  return authenticatedRawFetch(`${API_BASE}${path}`, options, prepareHeaders);
}

/**
 * Fetch wrapper that converts auth/network/HTTP errors into ApiError.
 *
 * When `expected404` is set, a 404 response resolves to `null` instead
 * of throwing — for endpoints where 404 is a normal/handled outcome
 * (e.g. share-token lookup with a possibly-invalid token). The caller's
 * TypeScript signature should reflect the nullable shape.
 *
 * Important: `expected404` does NOT bypass the 401→refresh→retry flow in
 * `authenticatedFetch`. The quiet path only fires AFTER `authenticatedFetch`
 * returns a final response with status 404. Other error statuses (403, 410,
 * 500, …) still throw ApiError normally.
 */
export async function apiFetch<T>(
  path: string,
  options: RequestInit & { expected404?: boolean } = {},
): Promise<T> {
  const { expected404, ...fetchOptions } = options;

  // fix(#438): DATA-04 — bound the request. Compose with any caller signal so
  // an explicit cancel still works; whichever fires first wins.
  const timeoutSignal = AbortSignal.timeout(REQUEST_TIMEOUT_MS);
  fetchOptions.signal = fetchOptions.signal
    ? AbortSignal.any([fetchOptions.signal, timeoutSignal])
    : timeoutSignal;

  const response = await authenticatedFetch(path, fetchOptions, (headers) => {
    if (!headers.has('Content-Type') && !(fetchOptions.body instanceof URLSearchParams) && !(fetchOptions.body instanceof FormData)) {
      headers.set('Content-Type', 'application/json');
    }
  });

  if (response.status === 404 && expected404) {
    return null as T;
  }

  if (!response.ok) {
    let detailRaw: unknown = undefined;

    let body: { detail?: unknown } | undefined;
    try {
      body = await response.json();
    } catch {
      // Non-JSON failures use the localized status category below.
    }

    if (body?.detail !== undefined) {
      detailRaw = body.detail;
    }

    throw new ApiError(
      translateApiErrorDetail(detailRaw, response.status),
      response.status,
      detailRaw,
    );
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
    throw new ApiError(translateApiErrorDetail(undefined, response.status), response.status);
  }

  return response.blob();
}
