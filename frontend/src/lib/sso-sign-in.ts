import { API_BASE } from '@/lib/constants';
import { readSessionStorage, removeSessionStorage, writeSessionStorage } from '@/lib/storage';

const NONCE_KEY = 'geolens-sso-nonce';

function randomNonce(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

/**
 * The URL that starts an SSO sign-in bound to this tab.
 *
 * The nonce stays in this tab's sessionStorage and travels with the sign-in;
 * the callback page completes only a sign-in that hands the same value back.
 */
export function ssoSignInUrl(flow: 'oauth' | 'saml', slug: string): string {
  const nonce = randomNonce();
  writeSessionStorage(NONCE_KEY, nonce);
  return `${API_BASE}/auth/${flow}/${encodeURIComponent(slug)}/login?nonce=${nonce}`;
}

/** The nonce this tab started its sign-in with, removed so it is used once. */
export function takeSsoNonce(): string | null {
  const nonce = readSessionStorage(NONCE_KEY);
  removeSessionStorage(NONCE_KEY);
  return nonce;
}

/** Equal strings, compared without stopping at the first difference. */
export function nonceMatches(expected: string, received: string): boolean {
  if (expected.length !== received.length) return false;
  let difference = 0;
  for (let i = 0; i < expected.length; i += 1) {
    difference |= expected.charCodeAt(i) ^ received.charCodeAt(i);
  }
  return difference === 0;
}
