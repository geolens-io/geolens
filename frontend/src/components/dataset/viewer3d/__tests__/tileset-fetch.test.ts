import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { makeTilesetFetch, resolveTilesetUrl } from '../tileset-fetch';

const ORIGIN = 'https://geolens.example';
const ID = '5a2cc880-122e-447f-b5fe-f76a24a1ae2c';
const OTHER_ID = '11111111-2222-3333-4444-555555555555';
const OWN = `/api/datasets/${ID}/tiles3d/`;

const rawFetch = vi.hoisted(() => vi.fn());
vi.mock('@/api/client', () => ({ authenticatedRawFetch: rawFetch }));

describe('resolveTilesetUrl', () => {
  it.each([
    [`${OWN}tileset.json`, `${OWN}tileset.json`],
    [`${ORIGIN}${OWN}tiles/0.glb?v=2`, `${OWN}tiles/0.glb`],
  ])('resolves %s', (raw, path) => {
    expect(resolveTilesetUrl(raw, ID, ORIGIN)?.pathname).toBe(path);
  });

  it.each([
    ['another origin', `https://evil.example${OWN}tileset.json`],
    ['a protocol-relative URL', `//evil.example${OWN}tileset.json`],
    ['a backslash-authority URL', `/\\evil.example${OWN}tileset.json`],
    ['an http downgrade', `http://geolens.example${OWN}tileset.json`],
    ['embedded credentials', `https://user:pw@geolens.example${OWN}tileset.json`],
    ['another dataset', `/api/datasets/${OTHER_ID}/tiles3d/tileset.json`],
    ['this dataset outside tiles3d', `/api/datasets/${ID}/copc/1/pointcloud.copc.laz`],
    ['an auth route', '/api/auth/me'],
    ['dot segments', `${OWN}../../../auth/me`],
    ['encoded dot segments', `${OWN}%2e%2e/%2E%2e/auth/me`],
    ['an encoded slash', `${OWN}..%2f..%2fauth/me`],
    ['an encoded backslash', `${OWN}..%5c..%5cauth`],
    ['a prefix lookalike', `/api/datasets/${ID}/tiles3d-evil/x`],
    ['a data URL', 'data:application/json,{}'],
    ['a javascript URL', 'javascript:alert(1)'],
    ['a relative path that resolves off the dataset', 'tiles/0.glb'],
    ['an empty string', ''],
  ])('refuses %s', (_label, raw) => {
    expect(resolveTilesetUrl(raw, ID, ORIGIN)).toBeNull();
  });
});

describe('makeTilesetFetch', () => {
  beforeEach(() => {
    vi.stubGlobal('location', { ...window.location, origin: ORIGIN, href: `${ORIGIN}/datasets/${ID}` });
    rawFetch.mockReset();
    rawFetch.mockResolvedValue(new Response('{}'));
  });
  afterEach(() => vi.unstubAllGlobals());

  it('sends an own-path request through the credentialed session fetch, as a path', async () => {
    const fetchTileset = makeTilesetFetch(ID);
    await fetchTileset(`${ORIGIN}${OWN}tileset.json`, { headers: { Range: 'bytes=0-9' } });
    expect(rawFetch).toHaveBeenCalledTimes(1);
    const [target, init] = rawFetch.mock.calls[0];
    expect(target).toBe(`${OWN}tileset.json`);
    expect(init).toMatchObject({ method: 'GET', credentials: 'same-origin' });
    expect(init.headers).toEqual({ Range: 'bytes=0-9' });
  });

  it('keeps the credential out of the URL', async () => {
    await makeTilesetFetch(ID)(`${OWN}tileset.json`);
    expect(rawFetch.mock.calls[0][0]).not.toMatch(/token|key|bearer/i);
  });

  it.each([
    `https://evil.example${OWN}tileset.json`,
    `//evil.example/x`,
    `/api/datasets/${OTHER_ID}/tiles3d/tileset.json`,
    `${OWN}../../auth/me`,
    `${OWN}%2e%2e/auth/me`,
  ])('refuses %s without any request', async (url) => {
    await expect(makeTilesetFetch(ID)(url)).rejects.toThrow(/refused/);
    expect(rawFetch).not.toHaveBeenCalled();
  });

  it('refuses a Request that names a hostile URL', async () => {
    await expect(
      makeTilesetFetch(ID)(new Request('https://evil.example/x')),
    ).rejects.toThrow(/refused/);
    expect(rawFetch).not.toHaveBeenCalled();
  });

  it('refuses a POST Request to an own-path URL', async () => {
    await expect(
      makeTilesetFetch(ID)(new Request(`${ORIGIN}${OWN}tileset.json`, { method: 'POST', body: 'x' })),
    ).rejects.toThrow(/refused/);
    expect(rawFetch).not.toHaveBeenCalled();
  });

  it('refuses redirects, which would carry the credential elsewhere', async () => {
    await makeTilesetFetch(ID)(`${OWN}tileset.json`);
    expect(rawFetch.mock.calls[0][1]).toMatchObject({ redirect: 'error' });
  });

  it('refuses methods other than GET and HEAD', async () => {
    await expect(makeTilesetFetch(ID)(`${OWN}tileset.json`, { method: 'POST' })).rejects.toThrow(/refused/);
    expect(rawFetch).not.toHaveBeenCalled();
  });

  it('returns the response of the session fetch, which renews on 401', async () => {
    const response = new Response('ok', { status: 200 });
    rawFetch.mockResolvedValue(response);
    await expect(makeTilesetFetch(ID)(`${OWN}tileset.json`)).resolves.toBe(response);
  });
});
