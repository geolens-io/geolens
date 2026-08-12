import { API_BASE } from '@/lib/constants';
import { cookieAuthHeaders } from '@/lib/auth-transport';
import { apiFetch } from './client';
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
 * Routed through apiFetch deliberately: if the access token has aged out, the
 * 401 path refreshes from the cookie and retries, so logout still lands.
 *
 * fix(#1446): bounded well below apiFetch's 30s default. The caller blocks on
 * this before tearing down local state, so a blackholed connection would
 * otherwise leave someone looking signed-in for half a minute after clicking
 * Logout.
 */
const LOGOUT_TIMEOUT_MS = 3_000;

export async function logoutSession(): Promise<void> {
  await apiFetch<void>('/auth/logout/', { method: 'POST', timeoutMs: LOGOUT_TIMEOUT_MS });
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
