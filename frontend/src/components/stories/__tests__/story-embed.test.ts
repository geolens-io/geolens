import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { apiFetch } from '@/api/client';
import { isEmbedViewer } from '@/lib/embed-context';
import { useAuthStore } from '@/stores/auth-store';
import { storyEmbedCode, storyEmbedSrc } from '../story-embed';

const original = window.location;

function setPath(pathname: string): void {
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { ...original, pathname, search: '', href: `http://localhost${pathname}` },
  });
}

beforeEach(() => {
  useAuthStore.setState({ token: 'seeded-session-token', expiresAt: Date.now() + 3_600_000 });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { headers: { 'Content-Type': 'application/json' } })));
});

afterEach(() => {
  Object.defineProperty(window, 'location', { configurable: true, value: original });
  vi.unstubAllGlobals();
  useAuthStore.setState({ token: null, expiresAt: null });
});

function sentAuthorization(): boolean {
  const init = vi.mocked(globalThis.fetch).mock.calls.at(-1)![1] as RequestInit;
  return new Headers(init.headers).has('Authorization');
}

it('reads the story on the page the snippet frames as an anonymous reader', async () => {
  const url = new URL(storyEmbedSrc('https://geolens.example.com', 'story-1'));
  setPath(url.pathname);
  expect(isEmbedViewer()).toBe(true);
  await apiFetch('/stories/story-1');
  expect(sentAuthorization()).toBe(false);
});

it.each(['/stories/story-1', '/stories/story-1/edit', '/stories/story-1/embedded', '/stories/embed'])(
  'keeps the session on %s',
  async (pathname) => {
    setPath(pathname);
    expect(isEmbedViewer()).toBe(false);
    await apiFetch('/stories/story-1');
    expect(sentAuthorization()).toBe(true);
  },
);

// The router decodes each segment and ignores case, so these all render the embed page.
it.each([
  '/STORIES/Story-1/EMBED',
  '/stories/story-1/embed/',
  '/stories/story-1/%65mbed',
  '/stories/story-1/%45MBE%64/',
  '/%73tories/story%2D1/embed',
  '/stories/%E0%A4%A/embed',
])('reads %s as the embed page, without the session', async (pathname) => {
  setPath(pathname);
  expect(isEmbedViewer()).toBe(true);
  await apiFetch('/stories/story-1');
  expect(sentAuthorization()).toBe(false);
});

it.each([
  ['/M/share-token', '?embed=true', true],
  ['/%6d/share-token', '?embed=true', true],
  ['/%6d/share-token', '', false],
  ['/stories/story-1/%2Fembed', '', false],
])('reads the map embed the same way: %s%s', (pathname, search, embedded) => {
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { ...original, pathname, search, href: `http://localhost${pathname}${search}` },
  });
  expect(isEmbedViewer()).toBe(embedded);
});

it('escapes the title into the accessible name of the frame', () => {
  const code = storyEmbedCode({ origin: 'https://geolens.example.com', storyId: 'story-1', title: 'A <b>"bold"</b> & more' });
  const iframe = new DOMParser().parseFromString(code, 'text/html').querySelector('iframe')!;
  expect(iframe.getAttribute('title')).toBe('A <b>"bold"</b> & more');
  expect(iframe.getAttribute('src')).toBe('https://geolens.example.com/stories/story-1/embed');
  expect(iframe.getAttribute('sandbox')).toBe('allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox');
});

it('delegates fullscreen, so a video block inside the embedded story can use it', () => {
  const code = storyEmbedCode({ origin: 'https://geolens.example.com', storyId: 'story-1', title: 'Rivers' });
  const iframe = new DOMParser().parseFromString(code, 'text/html').querySelector('iframe')!;
  expect(iframe.getAttribute('allow')).toBe('fullscreen');
  expect(iframe.hasAttribute('allowfullscreen')).toBe(true);
});
