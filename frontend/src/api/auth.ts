import { API_BASE } from '@/lib/constants';
import { cookieAuthAvailable, cookieAuthHeaders } from '@/lib/auth-transport';
import { useAuthStore } from '@/stores/auth-store';
import { apiFetch, safeFetch } from './client';
import { translateApiErrorDetail } from '@/lib/error-map';
import type { TokenResponse, UserResponse, AuthConfigResponse, MessageResponse, SignupResponse, MyApiKeyResponse, ApiKeyCreateResponse, ApiKeyScope, OAuthProviderPublic, UserQuotaUsage } from '@/types/api';

export async function login(
  username: string,
  password: string,
): Promise<TokenResponse> {
  // SP-11: route is /auth/login (no trailing slash) so the POST body is
  // preserved without a 307 redirect.
  const response = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    // fix(#1302): opt into the httpOnly refresh cookie. The response's
    // refresh_token is null in that mode, so nothing token-shaped reaches
    // localStorage.
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', ...cookieAuthHeaders() },
    credentials: 'same-origin',
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

  return response.json() as Promise<TokenResponse>;
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

  await safeFetch(`${API_BASE}/auth/logout/`, {
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
 * fix(#1302): in cookie mode the credential rides in the httpOnly cookie and
 * `refreshToken` is null, so the body is omitted entirely.
 *
 * The one exception is the transition: a session that logged in before this
 * shipped still holds a localStorage refresh token. Sending it once, under the
 * cookie-mode header, lets the backend rotate it and hand back a cookie instead
 * — the session migrates in place rather than being logged out.
 */
const REFRESH_TIMEOUT_MS = 30_000;

export async function refreshAccessToken(
  refreshToken: string | null,
): Promise<TokenResponse> {
  const headers: Record<string, string> = { ...cookieAuthHeaders() };
  if (refreshToken) headers['Content-Type'] = 'application/json';

  const response = await fetch(`${API_BASE}/auth/refresh/`, {
    method: 'POST',
    headers,
    credentials: 'same-origin',
    // fix(#1446): this call bypasses apiFetch, so it never inherited the
    // fix(#438) DATA-04 request bound and could hang forever. That stalls
    // anything awaiting a refresh (logout, most visibly), and worse, leaves
    // tryRefresh's inflight singleton un-cleared — its `finally` never runs —
    // which wedges every later refresh for the life of the tab.
    signal: AbortSignal.timeout(REFRESH_TIMEOUT_MS),
    ...(refreshToken ? { body: JSON.stringify({ refresh_token: refreshToken }) } : {}),
  });

  if (!response.ok) {
    throw new Error(translateApiErrorDetail(undefined, response.status));
  }

  return response.json() as Promise<TokenResponse>;
}
