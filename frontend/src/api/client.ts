import { API_BASE } from '@/lib/constants';
import { cookieAuthAvailable } from '@/lib/auth-transport';
import { isEmbedViewer } from '@/lib/embed-context';
import { translateApiErrorDetail } from '@/lib/error-map';
import { useAuthStore } from '@/stores/auth-store';
import { logoutSession, refreshAccessToken } from './auth';
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
let inflightRefresh: Promise<boolean> | null = null;
let inflightRefreshAbort: AbortController | null = null;

/**
 * fix(#1446): abandon any refresh still in flight, so its response — and the
 * `Set-Cookie` riding on it — is never processed. Called when the session ends
 * deliberately, where a rotated cookie arriving after a subsequent login would
 * silently replace the new session's credential with a revoked one.
 */
export function abortInflightRefresh(): void {
  inflightRefreshAbort?.abort();
  inflightRefreshAbort = null;
}

// fix(#628): once a request 401s AND the follow-up refresh cannot produce a
// working token, the session is conclusively dead — every surface in the app
// is about to fail the same way (silent 403 tiles, quiet query errors, generic
// toasts). Instead of letting each surface invent its own failure UX, clear
// the session once and notify a single app-level handler (the signed-out
// dialog host). The latch is keyed on the dead session's ACCESS token: the
// burst of concurrent in-flight failures all captured the same value, so they
// collapse to one notification, while the next session notifies again.
//
// fix(#1302): this used to latch on the refresh token, which is no longer
// visible to JS. The access token has the same two properties the latch needs —
// stable across a failure burst, and different for every session, since it
// rotates on each refresh.
let sessionExpiredHandler: (() => void) | null = null;
let lastNotifiedSessionKey: string | null = null;

/** Register the app-level signed-out handler. Returns an unregister fn. */
export function onSessionExpired(handler: () => void): () => void {
  sessionExpiredHandler = handler;
  return () => {
    if (sessionExpiredHandler === handler) sessionExpiredHandler = null;
  };
}

export function notifySessionExpired(deadSessionKey: string): void {
  if (deadSessionKey === lastNotifiedSessionKey) return;
  lastNotifiedSessionKey = deadSessionKey;
  // fix(#1446): the refresh that got us here may have failed transiently — a
  // 429, a 5xx, a dropped connection — in which case the refresh cookie and
  // its server-side row are still perfectly valid behind a UI that now says
  // "signed out". Since fix(#1302) that credential is httpOnly, so clearing
  // the store cannot touch it. Dispatch a best-effort revocation on the way
  // out. logoutSession issues a plain fetch, so this cannot recurse back
  // through the 401 interceptor that called us.
  abortInflightRefresh();
  void logoutSession().catch(() => {});
  useAuthStore.getState().logout();
  sessionExpiredHandler?.();
}

export async function tryRefresh(): Promise<boolean> {
  const { refreshToken, token } = useAuthStore.getState();
  // fix(#1302): in cookie mode the credential is invisible to JS, so a stored
  // refresh token is no longer proof a session exists — an access token is.
  // `refreshToken` is still consulted because a pre-GH-1302 session carries one
  // for exactly one migrating refresh, and because cross-origin deployments
  // never leave cookie mode's starting gate.
  if (!refreshToken && !(token && cookieAuthAvailable())) return false;

  // fix(#1849): the outcome of the in-flight refresh IS the answer here, not
  // whatever token happens to be sitting in the store — see the fix note on
  // the IIFE's return values below.
  if (inflightRefresh) {
    return await inflightRefresh;
  }

  // The singleton MUST be cleared synchronously when the IIFE settles —
  // not in the outer try/finally — so a third caller that arrives between
  // resolution and the outer finally can't observe `inflightRefresh === null`
  // and kick off a second refresh cycle. WR-02 (1045-REVIEW.md).
  // fix(#1446): a logout can land while this request is in flight — most
  // easily when logout itself triggers the proactive refresh and then stops
  // waiting on it. Writing the rotated tokens afterwards would re-populate the
  // store and localStorage, signing the browser back in while it sits on
  // /login. Capture the epoch now and refuse the write if it moved.
  const epochAtStart = useAuthStore.getState().sessionEpoch;

  // fix(#1446): the epoch guard stops a late refresh writing to the store, but
  // it cannot stop the BROWSER applying that response's Set-Cookie — which
  // could overwrite a cookie a later login already issued, killing the new
  // session. Aborting the request means the response is never processed at
  // all, so the stale cookie never lands.
  const controller = new AbortController();
  inflightRefreshAbort = controller;

  // fix(#1849): report whether a NEW token actually got stored, not whether
  // some token — possibly the stale one this refresh was trying to replace —
  // still sits in the store. The old `!!token` check was true on a failed
  // refresh too, so the caller retried the original request with a dead
  // token instead of going straight to the logout path.
  //
  // fix(#1862 review P2): captured here, before the attempt, so a failure
  // below can tell "nothing changed" from "a peer tab changed it". The
  // access token also lives in localStorage (auth-store.ts's cross-tab
  // `storage` listener), so a PEER tab's successful refresh can rehydrate a
  // new token into this tab's store while this attempt is still in flight —
  // most easily during the 429 backoff wait. `token` is that pre-attempt
  // value from the destructure above.
  const promise = (async (): Promise<boolean> => {
    try {
      const tokens = await refreshAccessToken(refreshToken, controller.signal);
      if (useAuthStore.getState().sessionEpoch !== epochAtStart) return false;
      // fix(#1302): null in cookie mode, which also clears the legacy
      // localStorage token once the migrating refresh has spent it.
      useAuthStore.getState().setTokens(
        tokens.access_token,
        tokens.refresh_token ?? null,
        tokens.expires_in,
      );
      return true;
    } catch (err) {
      // If rate-limited, wait before giving up so the next attempt isn't also blocked
      if (err instanceof ApiError && err.status === 429) {
        await new Promise((r) => setTimeout(r, 2000));
      }
      // fix(#1862 review P2): our own attempt failed, but if a peer tab's
      // refresh landed a different token while we waited, the session IS
      // live — just not because of anything this attempt did. Reporting
      // failure here would make the caller treat a peer's valid replacement
      // as a terminal session death and log out (and revoke) the session
      // that tab just refreshed.
      const currentToken = useAuthStore.getState().token;
      if (currentToken && currentToken !== token) {
        return true;
      }
      // Refresh failed -- will fall through to logout
      return false;
    } finally {
      inflightRefresh = null;
      if (inflightRefreshAbort === controller) inflightRefreshAbort = null;
    }
  })();
  inflightRefresh = promise;

  return await promise;
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
  // fix(#1515): the embedded viewer does not participate in the session. See
  // isEmbedViewer's docstring — the share token is the capability, and once the
  // frame is same-origin an embed on a third-party page would otherwise run as
  // whoever is signed in, and could sign them out.
  const embedded = isEmbedViewer();

  // Proactively refresh if token expires within 30 seconds
  const { token: currentToken, expiresAt } = useAuthStore.getState();
  if (!embedded && currentToken && expiresAt && Date.now() > expiresAt - 30_000) {
    await tryRefresh();
  }

  function buildHeaders(): Headers {
    const headers = new Headers(options.headers);
    const token = embedded ? null : useAuthStore.getState().token;
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
    // fix(#1515): an embed never sent a session, so a 401 here is the share or
    // embed token failing to authorize — not an expired login. Returning it
    // keeps the viewer's own error handling and, more importantly, keeps a
    // frame on someone else's page from refreshing or destroying the session
    // of whoever is signed in.
    if (embedded) return response;

    // fix(#628): only a session that existed can expire; an anonymous 401 must
    // not raise the signed-out prompt. Captured BEFORE tryRefresh so every
    // concurrent failure holds the same dead value.
    // fix(#1302): keyed on the access token now that the refresh token is a
    // cookie. Every real session has one, and it is cleared on logout.
    const deadSessionKey = useAuthStore.getState().token;
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
    if (deadSessionKey) {
      notifySessionExpired(deadSessionKey);
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
  options: RequestInit & { expected404?: boolean; timeoutMs?: number } = {},
): Promise<T> {
  const { expected404, timeoutMs, ...fetchOptions } = options;

  // fix(#438): DATA-04 — bound the request. Compose with any caller signal so
  // an explicit cancel still works; whichever fires first wins. `timeoutMs`
  // raises the deadline for endpoints whose legitimate worst case exceeds the
  // default (a caller signal alone can only shorten it, never extend it).
  const timeoutSignal = AbortSignal.timeout(timeoutMs ?? REQUEST_TIMEOUT_MS);
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
