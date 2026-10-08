import type { TokenResponse, UserResponse } from '@/types/api';

const user = { id: 'u1', username: 'someone', roles: ['editor'] } as unknown as UserResponse;

function accessToken(family: string): string {
  return `header.${btoa(JSON.stringify({ sub: user.id, sid: family }))}.signature`;
}

function familyOf(token: string | null | undefined): string | null {
  const payload = token?.split('.')[1];
  return payload ? (JSON.parse(atob(payload)) as { sid: string }).sid : null;
}

function reply(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

/**
 * The API and the one refresh cookie every tab of the browser shares. Profile
 * requests wait for `releaseProfiles`, and `holdSignIn` holds the next sign-in
 * response until its release is called.
 */
function fakeServer() {
  const revoked = new Set<string>();
  let releaseProfiles!: () => void;
  const profiles = new Promise<void>((resolve) => {
    releaseProfiles = resolve;
  });
  let signInGate: Promise<void> | null = null;
  const server = {
    cookie: null as string | null,
    revoked,
    issued: 0,
    releaseProfiles,
    holdSignIn(): () => void {
      let release!: () => void;
      signInGate = new Promise((resolve) => {
        release = resolve;
      });
      return release;
    },
  };
  const issue = (family: string): TokenResponse => ({
    access_token: accessToken(family),
    refresh_token: null,
    token_type: 'bearer',
    expires_in: 900,
  });
  vi.stubGlobal('fetch', async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const bearer = new Headers(init?.headers).get('Authorization')?.replace(/^Bearer /, '');
    if (url.endsWith('/auth/login') || url.endsWith('/auth/oauth/exchange/')) {
      const gate = signInGate;
      signInGate = null;
      await gate;
      // A sign-in takes time on the clock every tab shares.
      vi.setSystemTime(Date.now() + 5);
      server.issued += 1;
      server.cookie = `family-${server.issued}`;
      return reply(issue(server.cookie));
    }
    if (url.endsWith('/auth/refresh/')) {
      if (!server.cookie || revoked.has(server.cookie)) return reply({ detail: 'expired' }, 401);
      return reply(issue(server.cookie));
    }
    if (url.endsWith('/auth/me/')) {
      await profiles;
      const family = familyOf(bearer);
      return family && !revoked.has(family) ? reply(user) : reply({ detail: 'expired' }, 401);
    }
    if (url.endsWith('/auth/logout/session/')) {
      const family = familyOf(bearer);
      if (family) revoked.add(family);
      return reply({ message: 'ok' });
    }
    throw new Error(`unexpected request ${url}`);
  });
  return server;
}

/**
 * Web Locks across tabs: one holder at a time, granted in request order. A
 * request whose signal aborts before it is granted never runs.
 */
function fakeLocks() {
  let tail: Promise<unknown> = Promise.resolve();
  const locks = {
    request: (_name: string, options: { signal?: AbortSignal }, callback: () => Promise<unknown>) => {
      const held = tail.then(() => {
        if (options.signal?.aborted) throw new DOMException('aborted', 'AbortError');
        return callback();
      });
      tail = held.catch(() => {});
      return held;
    },
  };
  Object.defineProperty(navigator, 'locks', { value: locks, configurable: true });
}

/**
 * A fresh copy of the app's auth modules: one browser tab. `login` returns
 * once the password request has released the cookie lock and `install` is
 * the step after it; `sso` installs under the lock and returns the rest of
 * the sign-in.
 */
async function openTab() {
  vi.resetModules();
  const auth = await import('@/api/auth');
  const { completeSignIn } = await import('@/lib/sign-in');
  const { wireSessionSync } = await import('@/lib/session-sync');
  const { useAuthStore } = await import('@/stores/auth-store');
  return {
    login: () => auth.login('someone', 'secret'),
    install: completeSignIn,
    sso: () => auth.exchangeSignInCode('code', 'nonce', (session) => ({ done: completeSignIn(session) })),
    state: () => useAuthStore.getState(),
    close: wireSessionSync(),
  };
}

type Tab = Awaited<ReturnType<typeof openTab>>;

describe('two tabs signing in at the same moment', () => {
  let server: ReturnType<typeof fakeServer>;
  let earlier: Tab;
  let later: Tab;

  beforeEach(async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    window.localStorage.clear();
    window.history.replaceState({}, '', '/login');
    fakeLocks();
    server = fakeServer();
    earlier = await openTab();
    later = await openTab();
  });

  afterEach(() => {
    earlier.close();
    later.close();
    Reflect.deleteProperty(navigator, 'locks');
    vi.unstubAllGlobals();
    vi.useRealTimers();
    window.localStorage.clear();
    window.history.replaceState({}, '', '/');
  });

  /** Deliver the notices, then the profiles, then whatever those set off. */
  async function finish(signIns: Array<Promise<unknown>>): Promise<void> {
    await vi.advanceTimersByTimeAsync(0);
    server.releaseProfiles();
    await Promise.allSettled(signIns);
    await vi.advanceTimersByTimeAsync(10);
  }

  function expectBothOnLaterSession(): void {
    expect(server.cookie).toBe('family-2');
    expect(server.revoked.has('family-2')).toBe(false);
    expect(familyOf(later.state().token)).toBe('family-2');
    // The earlier tab moves onto the session the cookie now holds.
    expect(familyOf(earlier.state().token)).toBe('family-2');
    expect(earlier.state().sessionId).toBe(later.state().sessionId);
  }

  it('ignores an earlier password sign-in announced after the later one installed', async () => {
    const [first, second] = await Promise.all([earlier.login(), later.login()]);
    const signIns = [earlier.install(first), later.install(second)];

    await finish(signIns);

    expectBothOnLaterSession();
  });

  it('ignores an earlier SSO sign-in announced after the later one installed', async () => {
    const [first, second] = await Promise.all([earlier.sso(), later.sso()]);

    await finish([first.done, second.done]);

    expectBothOnLaterSession();
  });

  it('keeps a password sign-in when an earlier one is announced while its request is open', async () => {
    const first = earlier.install(await earlier.login());
    const release = server.holdSignIn();
    const pending = later.login();
    // The earlier notice arrives mid-request, and the tab adopts that session.
    await vi.advanceTimersByTimeAsync(0);
    release();
    const second = later.install(await pending);

    await finish([first, second]);

    expectBothOnLaterSession();
  });

  it('orders the sign-ins by the clock where storage is unavailable', async () => {
    const denied = () => {
      throw new DOMException('denied', 'SecurityError');
    };
    vi.stubGlobal('localStorage', { getItem: denied, setItem: denied, removeItem: denied });

    const [first, second] = await Promise.all([earlier.login(), later.login()]);
    await finish([earlier.install(first), later.install(second)]);

    expectBothOnLaterSession();
  });
});
