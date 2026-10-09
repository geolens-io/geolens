/**
 * Cross-tab notice that a cookie session started or ended.
 *
 * Messages carry only the session id and, for a sign-in, its place in
 * cookie-write order, never a credential: a receiving tab recovers its own
 * access token from the shared refresh cookie. Where `BroadcastChannel` is
 * unavailable, tabs do not sync and each one finds out on its next refresh.
 */
export interface AuthMessage {
  type: 'login' | 'logout';
  sessionId: string;
  /** From takeSignInOrder, on a login whose cookie write it numbered. */
  order?: number;
}

const CHANNEL_NAME = 'geolens-auth';

let channel: BroadcastChannel | null | undefined;

function getChannel(): BroadcastChannel | null {
  if (channel === undefined) {
    try {
      channel = typeof BroadcastChannel === 'function' ? new BroadcastChannel(CHANNEL_NAME) : null;
    } catch {
      channel = null;
    }
  }
  return channel;
}

function isAuthMessage(data: unknown): data is AuthMessage {
  if (typeof data !== 'object' || data === null) return false;
  const { type, sessionId } = data as Record<string, unknown>;
  return (type === 'login' || type === 'logout') && typeof sessionId === 'string';
}

export function postAuthMessage(message: AuthMessage): void {
  try {
    getChannel()?.postMessage(message);
  } catch {
    // A closed or unavailable channel only costs the cross-tab notice.
  }
}

/** Listen for other tabs' messages; the sender never receives its own. */
export function onAuthMessage(handler: (message: AuthMessage) => void): () => void {
  const target = getChannel();
  if (!target) return () => {};
  const listener = (event: MessageEvent) => {
    if (isAuthMessage(event.data)) handler(event.data);
  };
  target.addEventListener('message', listener);
  return () => target.removeEventListener('message', listener);
}
