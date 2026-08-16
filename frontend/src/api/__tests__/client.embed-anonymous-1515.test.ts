/**
 * fix(#1515): the embedded viewer must not spend the viewer's session.
 *
 * The emitted snippet now carries `allow-same-origin`, so the frame shares the
 * GeoLens origin and therefore the persisted auth store. Without this, an embed
 * on a third-party page would run every request as whoever is signed in, and a
 * 401 inside that frame would refresh or destroy their login.
 *
 * The store is seeded with a real-looking session in every case here, so a test
 * that passes because there was no token to send would be a false green: the
 * non-embed cases assert the header IS sent from the same setup.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { apiFetch } from '@/api/client';
import { buildEmbedSrc } from '@/components/builder/SharePanel';
import { isEmbedViewer } from '@/lib/embed-context';
import { useAuthStore } from '@/stores/auth-store';

const TOKEN = 'seeded-session-token';

function setUrl(pathname: string, search: string): void {
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { ...window.location, pathname, search, href: `http://localhost${pathname}${search}` },
  });
}

function lastRequestHeaders(): Headers {
  const call = vi.mocked(globalThis.fetch).mock.calls.at(-1)!;
  return new Headers((call[1] as RequestInit).headers);
}

beforeEach(() => {
  useAuthStore.setState({
    token: TOKEN,
    refreshToken: null,
    // Far future, so the proactive-refresh branch is not what is under test.
    expiresAt: Date.now() + 60 * 60 * 1000,
    user: null,
  });
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  useAuthStore.setState({ token: null, refreshToken: null, expiresAt: null, user: null });
});

describe('embed mode is anonymous (#1515)', () => {
  it('sends no Authorization from the embedded viewer', async () => {
    setUrl('/m/share-token-abc', '?embed=true');
    await apiFetch('/maps/shared/share-token-abc');
    expect(lastRequestHeaders().has('Authorization')).toBe(false);
  });

  it('still sends Authorization everywhere else (counterfactual for the case above)', async () => {
    setUrl('/maps/some-id', '');
    await apiFetch('/maps/some-id');
    expect(lastRequestHeaders().get('Authorization')).toBe(`Bearer ${TOKEN}`);
  });

  it('a plain share link without embed=true keeps the session', async () => {
    setUrl('/m/share-token-abc', '');
    await apiFetch('/maps/shared/share-token-abc');
    expect(lastRequestHeaders().get('Authorization')).toBe(`Bearer ${TOKEN}`);
  });

  it('embed=true on a non-embed path does not disable auth', async () => {
    setUrl('/datasets/xyz', '?embed=true');
    await apiFetch('/datasets/xyz');
    expect(lastRequestHeaders().get('Authorization')).toBe(`Bearer ${TOKEN}`);
  });

  // Pins the producer to the predicate. buildEmbedSrc is the only thing that
  // builds this URL shape, so if its path or `embed` flag ever changes, the
  // client would silently go back to sending the session and only an
  // end-to-end run would notice.
  it('recognizes the URL buildEmbedSrc actually produces', () => {
    const src = buildEmbedSrc({
      shareToken: 'abc123',
      embedTokenRaw: 'tok-456',
      origin: 'https://geolens.example.com',
    });
    const url = new URL(src);
    setUrl(url.pathname, url.search);
    expect(isEmbedViewer()).toBe(true);
  });

  it('a 401 inside an embed does not clear the session', async () => {
    setUrl('/m/share-token-abc', '?embed=true');
    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response('{"detail":"nope"}', {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    await expect(apiFetch('/maps/shared/share-token-abc')).rejects.toMatchObject({ status: 401 });

    // The viewer's login survives, and no refresh was attempted: one request.
    expect(useAuthStore.getState().token).toBe(TOKEN);
    expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledTimes(1);
  });
});
