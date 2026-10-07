import { getMe, revokeCurrentSession } from '@/api/auth';
import { isCredentialRejected } from '@/api/client';
import { useAuthStore } from '@/stores/auth-store';
import type { TokenResponse } from '@/types/api';

export type IssuedSession = Pick<TokenResponse, 'access_token' | 'refresh_token' | 'expires_in'>;

/**
 * `current` when the issued session is the one this tab is signed in with;
 * `superseded` when a logout or another sign-in replaced it first.
 */
export type SignInOutcome = 'current' | 'superseded';

/**
 * Install a just-issued session and load its profile.
 *
 * A session another logout or sign-in replaced before the profile arrived is
 * revoked by its own credential and never written back. Only a rejected
 * credential ends the session (and the returned promise rejects); a profile
 * that failed for any other reason leaves the valid session signed in, and
 * the app's profile query loads it later.
 *
 * `onInstalled` runs after the token is installed and before the profile is
 * requested.
 */
export async function completeSignIn(
  issued: IssuedSession,
  onInstalled?: () => Promise<void> | void,
): Promise<SignInOutcome> {
  const accessToken = issued.access_token;
  useAuthStore.getState().setAuth(accessToken, issued.refresh_token ?? null, issued.expires_in, null);
  const epoch = useAuthStore.getState().sessionEpoch;
  const isCurrent = () => useAuthStore.getState().sessionEpoch === epoch;
  const discard = () => {
    void revokeCurrentSession(accessToken).catch(() => {});
  };

  try {
    await onInstalled?.();
    const user = await getMe();
    if (!isCurrent()) {
      discard();
      return 'superseded';
    }
    useAuthStore.setState({ user });
    return 'current';
  } catch (err) {
    if (!isCurrent()) {
      discard();
      return 'superseded';
    }
    if (!isCredentialRejected(err)) return 'current';
    discard();
    useAuthStore.getState().logout();
    throw err;
  }
}
