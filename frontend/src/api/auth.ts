import { API_BASE } from '@/lib/constants';
import { signalWithTimeout } from '@/lib/abort';
import { AUTH_MODE_HEADER, cookieAuthAvailable, cookieAuthHeaders, takeSignInOrder, withCookieWrite } from '@/lib/auth-transport';
import { useAuthStore } from '@/stores/auth-store';
import { abortInflightRefresh, apiFetch, isCredentialRejected, retryAfterMs, safeFetch, ApiError } from './client';
import { translateApiErrorDetail } from '@/lib/error-map';
import type { TokenResponse, UserResponse, AuthConfigResponse, MessageResponse, SignupResponse, MyApiKeyResponse, ApiKeyCreateResponse, ApiKeyScope, OAuthProviderPublic, UserQuotaUsage } from '@/types/api';

const LOGIN_TIMEOUT_MS = 30_000;

/** A session as issued, numbered in cookie-write order by takeSignInOrder. */
type OrderedTokens = TokenResponse & { order: number };

export async function login(
  username: string,
  password: string,
): Promise<OrderedTokens> {
  // Never overtake a logout still in flight: it revokes every refresh token for
  // the user and deletes the cookies, so landing after this login would revoke
  // the new session's row or erase its cookie. Bounded by logoutSession's own
  // 3s timeout, and only waits when one is pending.
  await awaitPendingLogout();
  // A refresh still running, such as a page load's recovery that outlived its
  // render budget, would apply its Set-Cookie over the one this login issues.
  abortInflightRefresh();

  // Route is /auth/login (no trailing slash) so the POST body is
  // preserved without a 307 redirect.
  return withCookieWrite(async () => {
    const response = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      // Opt into the httpOnly refresh cookie. The response's
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
 * tab started the sign-in with, for this browser's session cookie. The callback
 * can't set the cookie itself: its redirect runs outside the cross-tab cookie
 * lock, so a refresh another tab already sent could land afterwards and restore
 * the previous session's cookie.
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
 * End the session on the server, not just in this tab. The endpoint revokes the
 * refresh-token rows and bumps token_version; the refresh credential is an
 * httpOnly cookie JS cannot touch, so a client-side logout would leave a live
 * cookie and server row behind. Only the server's `Set-Cookie` can clear it.
 *
 * Deliberately a plain fetch rather than `apiFetch`, reading the bearer token
 * synchronously so the request is in flight before the caller tears down local
 * state. `apiFetch` awaits a proactive refresh BEFORE dispatching when the
 * access token is near expiry; if the caller stopped waiting, that refresh would
 * install a rotated cookie while the logout POST went out with no Authorization
 * header, leaving exactly the live credential this call exists to revoke.
 */
/**
 * The in-flight revocation, tracked so a new login cannot overtake it. Logout
 * revokes every refresh token for the user and deletes the cookies, so a request
 * landing after a fresh login would revoke the new session's row and a delayed
 * response would erase its cookie.
 */
// A Set, not a single slot: concurrent teardown paths (a terminal getMe 401 and
// a login-catch, say) can each dispatch a revocation, and last-write-wins would
// let awaitPendingLogout return while the older request still holds the user
// lock server-side.
const pendingLogouts = new Set<Promise<void>>();

/** Wait for every in-flight logout revocation to settle. */
export async function awaitPendingLogout(): Promise<void> {
  while (pendingLogouts.size > 0) {
    await Promise.allSettled([...pendingLogouts]);
  }
}

export async function logoutSession(): Promise<void> {
  const { token, refreshToken } = useAuthStore.getState();
  // Carry the cookie-mode headers too: when the access token has aged out, the
  // refresh credential authenticates this call and the cookie transport requires
  // the double-submit CSRF token.
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
    // Callers dispatch this without awaiting, so a user who clicks Logout and
    // closes the tab would otherwise have the request cancelled at unload, leaving
    // the refresh row and cookie alive. keepalive prevents that; the request is far
    // inside its 64KB budget.
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
  // The body carries expires_at and scope as well as name, so the UI can mint
  // an expiring, scoped key.
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
  await apiFetch(`/auth/api-keys/${encodeURIComponent(keyId)}`, { method: 'DELETE' });
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

/**
 * Redeem an operator's single-use trust link so this browser counts as one the
 * account has signed in with before. Sent from this origin so the browser's
 * device cookies ride along for the server's per-browser cap.
 */
export async function rememberThisBrowser(token: string): Promise<void> {
  const response = await fetch(
    `${API_BASE}/auth/login/device-trust?token=${encodeURIComponent(token)}`,
    // The header shows the server this came from the app, not a cross-site form.
    { method: 'POST', credentials: 'same-origin', headers: { [AUTH_MODE_HEADER]: 'cookie' } },
  );
  if (!response.ok) {
    let detail: unknown;
    try {
      const body = await response.json();
      detail = body.detail;
    } catch { /* ignore */ }
    throw new Error(translateApiErrorDetail(detail, response.status));
  }
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
    // This call bypasses apiFetch, so it needs its own request bound: without it
    // a hang stalls anything awaiting a refresh (logout) and leaves tryRefresh's
    // inflight singleton un-cleared (`finally` never runs), wedging every later
    // refresh for the life of the tab.
    //
    // The caller's signal is composed in so a logout can abandon an in-flight
    // refresh outright: an aborted response is never processed, so its
    // `Set-Cookie` cannot overwrite a cookie issued by a later login.
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
    // tryRefresh's 429 back-off branch checks `err instanceof ApiError`; a plain
    // Error would skip the pause before the next attempt.
    const error = new ApiError(translateApiErrorDetail(undefined, response.status), response.status);
    if (response.status === 429) error.retryAfterMs = retryAfterMs(response);
    throw error;
  }

  return { ...((await response.json()) as TokenResponse), order };
}
