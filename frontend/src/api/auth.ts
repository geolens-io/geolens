import { API_BASE } from '@/lib/constants';
import { signalWithTimeout } from '@/lib/abort';
import { AUTH_MODE_HEADER, cookieAuthAvailable, cookieAuthHeaders, takeSignInOrder, withCookieWrite } from '@/lib/auth-transport';
import { useAuthStore } from '@/stores/auth-store';
import { abortInflightRefresh, apiFetch, isCredentialRejected, safeFetch, ApiError } from './client';
import { translateApiErrorDetail } from '@/lib/error-map';
import type { TokenResponse, UserResponse, AuthConfigResponse, MessageResponse, SignupResponse, MyApiKeyResponse, ApiKeyCreateResponse, ApiKeyScope, OAuthProviderPublic, UserQuotaUsage } from '@/types/api';

const LOGIN_TIMEOUT_MS = 30_000;

/** A session as issued, numbered in cookie-write order by takeSignInOrder. */
export type OrderedTokens = TokenResponse & { order: number };

export async function login(
  username: string,
  password: string,
): Promise<OrderedTokens> {
  // fix(#1446): never overtake a logout still in flight. It revokes every
  // refresh token for the user and deletes the cookies, so landing after this
  // login would revoke the new session's row or erase its cookie. Bounded by
  // logoutSession's own 3s timeout, and only waits when one is actually
  // pending.
  await awaitPendingLogout();
  // A refresh still running, such as a page load's recovery that outlived its
  // render budget, would apply its Set-Cookie over the one this login issues.
  abortInflightRefresh();

  // SP-11: route is /auth/login (no trailing slash) so the POST body is
  // preserved without a 307 redirect.
  return withCookieWrite(async () => {
    const response = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      // fix(#1302): opt into the httpOnly refresh cookie. The response's
      // refresh_token is null in that mode, so nothing token-shaped reaches
      // localStorage.
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', ...cookieAuthHeaders() },
      credentials: 'same-origin',
      // Bounded like refresh and the SSO exchange: this request holds the
      // cross-tab cookie lock, and a pending SSO code expires while it waits.
      signal: AbortSignal.timeout(LOGIN_TIMEOUT_MS),
      body: new URLSearchParams({ username, password }),
    });

    if (!response.ok) {
      let detail: unknown;
      try {
        const body = await response.json();
        detail = body.detail;
      } catch {
        // body not JSON
      }
      throw new Error(translateApiErrorDetail(detail, response.status));
    }

    try {
      const issued = { ...((await response.json()) as TokenResponse), order: takeSignInOrder() };
      // A refresh queued behind this login, such as one adopting another
      // tab's earlier sign-in, would otherwise take the lock next and spend
      // the cookie this login just set before the session is installed.
      abortInflightRefresh();
      return issued;
    } catch (err) {
      // The 2xx already set the refresh and CSRF cookies, so a body this tab
      // cannot use, a timeout included, must not leave that session behind.
      // A rejection ends every session; anything else ends only the one the
      // cookie now holds, before the lock is released.
      if (isCredentialRejected(err)) void logoutSession().catch(() => {});
      else await revokeCookieSession().catch(() => {});
      throw err;
    }
  });
}

const EXCHANGE_TIMEOUT_MS = 30_000;

/**
 * Trade the one-time code an SSO callback redirected with, and the nonce this
 * tab started the sign-in with, for this browser's session cookie. The callback can't set that cookie itself: its redirect
 * runs outside the cross-tab cookie lock, so a refresh another tab already
 * sent could land afterwards and put the previous session's cookie back.
 *
 * `install` receives the issued session while the lock is still held, so a
 * sign-in another tab completes later also installs later. It should return
 * promptly: the lock is released when it returns.
 */
export async function exchangeSignInCode<T>(
  code: string,
  nonce: string,
  install: (session: OrderedTokens) => T,
): Promise<T> {
  await awaitPendingLogout();
  abortInflightRefresh();
  return withCookieWrite(async () => {
    const response = await fetch(`${API_BASE}/auth/oauth/exchange/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', [AUTH_MODE_HEADER]: 'cookie' },
      credentials: 'same-origin',
      signal: AbortSignal.timeout(EXCHANGE_TIMEOUT_MS),
      body: JSON.stringify({ code, nonce }),
    });
    if (!response.ok) {
      throw new ApiError(translateApiErrorDetail(undefined, response.status), response.status);
    }
    try {
      return install({ ...((await response.json()) as TokenResponse), order: takeSignInOrder() });
    } catch (err) {
      // The exchange already set this browser's cookie. End that session
      // before releasing the lock, so no tab is left on a cookie this one
      // never installed.
      await revokeCookieSession().catch(() => {});
      useAuthStore.getState().logout();
      throw err;
    }
  });
}

/** Revoke the family the refresh cookie holds and clear both cookies. */
async function revokeCookieSession(): Promise<void> {
  await safeFetch(`${API_BASE}/auth/logout/session/`, {
    method: 'POST',
    headers: cookieAuthHeaders(),
    credentials: 'same-origin',
    signal: AbortSignal.timeout(LOGOUT_TIMEOUT_MS),
  });
}

export async function getMe(): Promise<UserResponse> {
  return apiFetch<UserResponse>('/auth/me/');
}

const LOGOUT_TIMEOUT_MS = 3_000;

/**
 * fix(#1446): end the session on the server, not just in this tab.
 *
 * The endpoint has always revoked the refresh-token rows and bumped
 * token_version, but nothing in the SPA ever called it — clearing localStorage
 * was enough to strand the browser. fix(#1302) removed that property: the
 * refresh credential is now an httpOnly cookie JS cannot touch, so a purely
 * client-side logout would leave a live cookie (and its server row) behind for
 * the remainder of its lifetime. Only the server's `Set-Cookie` can clear it.
 *
 * Deliberately a plain fetch rather than `apiFetch`, reading the bearer token
 * synchronously so the request is fully formed and in flight before the caller
 * tears down local state. Routing it through `apiFetch` looked appealing (its
 * 401 path can refresh from the cookie and retry) but is wrong here: when the
 * access token sits inside the proactive-refresh window, `apiFetch` awaits a
 * refresh BEFORE dispatching. If the caller stopped waiting during that
 * window, the refresh still installed a rotated cookie while the logout POST
 * then went out with no Authorization header at all — leaving exactly the live
 * credential this call exists to revoke.
 */
/**
 * fix(#1446): the in-flight revocation, tracked so a new login cannot overtake
 * it. Logout revokes EVERY refresh token for the user and deletes the cookies,
 * so a request that lands after a fresh login would revoke the new session's
 * row, and a delayed response would erase its cookie.
 */
// fix(#1446): a Set, not a single slot. Concurrent teardown paths can each
// dispatch a revocation (a terminal getMe 401 and a login-catch, say), and
// last-write-wins would let awaitPendingLogout return while the older request
// is still holding the user lock server-side — free to revoke rows a new
// sign-in just created.
const pendingLogouts = new Set<Promise<void>>();

/** Wait for every in-flight logout revocation to settle. */
export async function awaitPendingLogout(): Promise<void> {
  while (pendingLogouts.size > 0) {
    await Promise.allSettled([...pendingLogouts]);
  }
}

export async function logoutSession(): Promise<void> {
  const { token, refreshToken } = useAuthStore.getState();
  // fix(#1446): carry the cookie-mode headers too. When the access token has
  // aged out, the refresh credential authenticates this call server-side, and
  // the cookie transport requires the double-submit CSRF token.
  const headers: Record<string, string> = { ...cookieAuthHeaders() };
  if (token) headers.Authorization = `Bearer ${token}`;

  // A split-origin deployment has no usable cookie and keeps its refresh token
  // in the store, so present that instead — otherwise an expired access token
  // means logout 401s and the session outlives it there.
  const body = !cookieAuthAvailable() && refreshToken
    ? JSON.stringify({ refresh_token: refreshToken })
    : undefined;
  if (body) headers['Content-Type'] = 'application/json';

  const request = safeFetch(`${API_BASE}/auth/logout/`, {
    method: 'POST',
    headers,
    credentials: 'same-origin',
    signal: AbortSignal.timeout(LOGOUT_TIMEOUT_MS),
    // fix(#1446): callers dispatch this without awaiting, so a user who clicks
    // Logout and immediately closes or navigates the tab would otherwise have
    // the request cancelled at unload — local state already cleared, refresh
    // row and cookie still alive. keepalive is built for exactly this, and the
    // request is far inside its 64KB budget.
    keepalive: true,
    ...(body ? { body } : {}),
  });

  // Callers dispatch without awaiting, so this is what lets a subsequent login
  // wait for the revocation to settle rather than race it.
  const settled = request.then(
    () => undefined,
    () => undefined,
  );
  pendingLogouts.add(settled);
  void settled.then(() => {
    pendingLogouts.delete(settled);
  });

  await request;
}

/** Revoke a captured family without sending or modifying a newer login's cookies. */
export async function revokeCurrentSession(accessToken: string): Promise<void> {
  await safeFetch(`${API_BASE}/auth/logout/session/`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${accessToken}` },
    credentials: 'omit',
    signal: AbortSignal.timeout(LOGOUT_TIMEOUT_MS),
    keepalive: true,
  });
}

export async function registerUser(data: {
  username: string;
  password: string;
  email: string;
}): Promise<SignupResponse> {
  const response = await fetch(`${API_BASE}/auth/register/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!response.ok) {
    let detail: unknown;
    try {
      const body = await response.json();
      detail = body.detail;
    } catch { /* ignore */ }
    throw new Error(translateApiErrorDetail(detail, response.status));
  }
  return response.json() as Promise<SignupResponse>;
}

export async function getAuthConfig(): Promise<AuthConfigResponse> {
  const response = await fetch(`${API_BASE}/auth/config/`);
  if (!response.ok) {
    throw new Error(translateApiErrorDetail(undefined, response.status));
  }
  return response.json() as Promise<AuthConfigResponse>;
}

export async function listMyApiKeys(): Promise<MyApiKeyResponse[]> {
  const data = await apiFetch<{ items: MyApiKeyResponse[]; total: number }>('/auth/api-keys/');
  return data.items;
}

export async function createMyApiKey(
  name: string,
  options: { scope?: ApiKeyScope; expiresAt?: string | null } = {},
): Promise<ApiKeyCreateResponse> {
  // fix(#875): this mirror sent only { name }. expires_at has been accepted by
  // ApiKeyCreateRequest since #821 and was never threaded, so the UI could not
  // mint an expiring key at all; threading scope on top of that omission would
  // have left the mirror half-wired.
  return apiFetch<ApiKeyCreateResponse>('/auth/api-keys/', {
    method: 'POST',
    body: JSON.stringify({
      name,
      scope: options.scope ?? 'full',
      ...(options.expiresAt ? { expires_at: options.expiresAt } : {}),
    }),
  });
}

export async function revokeMyApiKey(keyId: string): Promise<void> {
  await apiFetch(`/auth/api-keys/${keyId}`, { method: 'DELETE' });
}

export async function getMyPermissions(): Promise<{ permissions: Record<string, boolean> }> {
  return apiFetch('/auth/me/permissions/');
}

export async function getMyUsage(): Promise<UserQuotaUsage> {
  return apiFetch<UserQuotaUsage>('/auth/me/usage/');
}

export async function getOAuthProviders(): Promise<OAuthProviderPublic[]> {
  try {
    const response = await fetch(`${API_BASE}/auth/oauth/providers/`);
    if (!response.ok) return [];
    return (await response.json()) as OAuthProviderPublic[];
  } catch {
    return [];
  }
}

export async function verifyEmail(token: string): Promise<MessageResponse> {
  const response = await fetch(`${API_BASE}/auth/verify-email/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  });
  if (!response.ok) {
    let detail: unknown;
    try {
      const body = await response.json();
      detail = body.detail;
    } catch { /* ignore */ }
    throw new Error(translateApiErrorDetail(detail, response.status));
  }
  return response.json() as Promise<MessageResponse>;
}

export async function resendVerification(email: string): Promise<MessageResponse> {
  const response = await fetch(`${API_BASE}/auth/resend-verification/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  });
  if (!response.ok) {
    let detail: unknown;
    try {
      const body = await response.json();
      detail = body.detail;
    } catch { /* ignore */ }
    throw new Error(translateApiErrorDetail(detail, response.status));
  }
  return response.json() as Promise<MessageResponse>;
}

/**
 * In cookie mode the credential rides in the httpOnly cookie and
 * `refreshToken` is null, so the body is omitted entirely.
 *
 * The one exception is the transition: a session that logged in before the
 * cookie flow left a refresh token in storage, which the auth store moves into
 * memory on load. Sending it once, under the cookie-mode header, lets the
 * backend rotate it and hand back a cookie instead, so the session migrates in
 * place rather than being logged out.
 */
const REFRESH_TIMEOUT_MS = 30_000;

export async function refreshAccessToken(
  refreshToken: string | null,
  abortSignal?: AbortSignal,
): Promise<TokenResponse & { order?: number }> {
  const send = () => fetch(`${API_BASE}/auth/refresh/`, {
    method: 'POST',
    // Read under the lock: a refresh another tab finished while this one
    // waited has rotated the CSRF cookie this header must match.
    headers: {
      ...cookieAuthHeaders(),
      ...(refreshToken ? { 'Content-Type': 'application/json' } : {}),
    },
    credentials: 'same-origin',
    // fix(#1446): this call bypasses apiFetch, so it never inherited the
    // fix(#438) DATA-04 request bound and could hang forever. That stalls
    // anything awaiting a refresh (logout, most visibly), and worse, leaves
    // tryRefresh's inflight singleton un-cleared — its `finally` never runs —
    // which wedges every later refresh for the life of the tab.
    //
    // The caller's signal is composed in so a logout can abandon an in-flight
    // refresh outright. That matters beyond saving a request: an aborted
    // response is never processed, so its `Set-Cookie` cannot land and
    // overwrite a cookie issued by a later login.
    signal: signalWithTimeout(abortSignal, REFRESH_TIMEOUT_MS),
    ...(refreshToken ? { body: JSON.stringify({ refresh_token: refreshToken }) } : {}),
  });
  let order: number | undefined;
  const response = await withCookieWrite(async () => {
    const sent = await send();
    // A migrating session's refresh announces it to other tabs like a sign-in.
    if (refreshToken && sent.ok) order = takeSignInOrder();
    return sent;
  }, abortSignal);

  if (!response.ok) {
    // fix(#1849): tryRefresh's 429 back-off branch checks `err instanceof
    // ApiError`, so a plain Error here made that branch dead code — a
    // rate-limited refresh never got the pause before the next attempt.
    throw new ApiError(translateApiErrorDetail(undefined, response.status), response.status);
  }

  return { ...((await response.json()) as TokenResponse), order };
}
