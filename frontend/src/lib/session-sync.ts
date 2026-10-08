import { abortInflightRefresh, attemptRefresh } from '@/api/client';
import { onAuthMessage } from '@/lib/auth-channel';
import { cookieAuthAvailable } from '@/lib/auth-transport';
import { isEmbedViewer } from '@/lib/embed-context';
import { readPersistedUser, SIGNED_OUT, useAuthStore } from '@/stores/auth-store';

/**
 * Get an access token for a session this tab knows of but holds no token for:
 * the one a previous page load left, or one another tab just signed in.
 *
 * A rejected refresh ends that session. A transient failure keeps it, so the
 * next request that needs it, or the next reload, tries again.
 */
export async function restoreSession(): Promise<void> {
  if (isEmbedViewer()) return;
  const { token, sessionId, refreshToken } = useAuthStore.getState();
  if (token || (!sessionId && !refreshToken)) return;
  const outcome = await attemptRefresh();
  if (outcome === 'rejected' && useAuthStore.getState().sessionId === sessionId) {
    useAuthStore.getState().logout();
  }
}

/** Follow sign-ins and logouts made in other tabs. Returns the unsubscribe. */
export function wireSessionSync(): () => void {
  return onAuthMessage((message) => {
    // The embedded viewer stays out of the session; see isEmbedViewer.
    if (isEmbedViewer()) return;
    const { sessionId } = useAuthStore.getState();
    if (message.type === 'logout') {
      if (message.sessionId === sessionId) endSession();
    } else if (message.sessionId !== sessionId && cookieAuthAvailable()) {
      adoptSession(message.sessionId);
    }
  });
}

function endSession(): void {
  // The epoch bump only blocks this tab's store writes. Abort the refresh too,
  // so the browser never processes a response whose Set-Cookie could replace
  // the cookie of a later sign-in.
  abortInflightRefresh();
  useAuthStore.setState((state) => ({ ...SIGNED_OUT, sessionEpoch: state.sessionEpoch + 1 }));
  // Public pages show signed-in chrome until something re-renders them, and
  // skipping the auth routes keeps this from looping.
  const path = window.location.pathname;
  if (path !== '/login' && path !== '/register') window.location.assign('/login');
}

/**
 * The other tab's sign-in replaced the refresh cookie every tab shares, so
 * this tab's token belongs to a session it can no longer refresh. Drop it and
 * take a token for the new session from the cookie.
 */
function adoptSession(sessionId: string): void {
  abortInflightRefresh();
  useAuthStore.setState((state) => ({
    ...SIGNED_OUT,
    sessionId,
    user: readPersistedUser(sessionId),
    sessionEpoch: state.sessionEpoch + 1,
  }));
  void restoreSession();
}
