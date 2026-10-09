import { abortInflightRefresh, attemptRefresh, TRANSIENT_COOLDOWN_MS, tryRefresh } from '@/api/client';
import { onAuthMessage } from '@/lib/auth-channel';
import { compareSignInOrder, cookieAuthAvailable } from '@/lib/auth-transport';
import { isEmbedViewer } from '@/lib/embed-context';
import { readPersistedUser, SIGNED_OUT, useAuthStore } from '@/stores/auth-store';

/**
 * Get an access token for a session this tab knows of but holds no token for:
 * the one a previous page load left, or one another tab just signed in.
 *
 * A rejected refresh ends that session. A transient failure keeps it and tries
 * again once the refresh back-off has passed, so a session an outage left
 * without a token comes back on its own, even on a page that sends nothing.
 */
export async function restoreSession(): Promise<void> {
  if (isEmbedViewer()) return;
  const { token, sessionId, refreshToken } = useAuthStore.getState();
  if (token || (!sessionId && !refreshToken)) return;
  const outcome = await attemptRefresh();
  const current = useAuthStore.getState();
  if (current.sessionId !== sessionId || current.token) return;
  if (outcome === 'rejected') {
    current.logout();
  } else if (outcome === 'transient') {
    setTimeout(() => void restoreSession(), TRANSIENT_COOLDOWN_MS);
  }
}

const RENDER_BUDGET_MS = 4_000;

/**
 * restoreSession, but resolved after `budgetMs` at most, so an auth endpoint
 * that hangs delays the first render by that much rather than by the refresh's
 * own timeout. A refresh that lands later still signs the tab in, since every
 * route reads the token reactively.
 */
export function restoreSessionBeforeRender(budgetMs = RENDER_BUDGET_MS): Promise<void> {
  // The OAuth callback installs the session its redirect just issued, and a
  // refresh racing it would rotate that session's cookie underneath it.
  if (window.location.pathname === '/oauth/callback') return Promise.resolve();
  return Promise.race([
    restoreSession(),
    new Promise<void>((resolve) => {
      setTimeout(resolve, budgetMs);
    }),
  ]);
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
      const order = compareSignInOrder(message.order);
      if (order === 'newer') adoptSession(message.sessionId);
      // Sign-ins on the same clock tick can't be told apart. A refresh finds
      // out which one the cookie holds and switches to it without revoking.
      else if (order === 'tie') void tryRefresh();
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
