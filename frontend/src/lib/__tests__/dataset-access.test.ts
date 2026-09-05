// fix(#1877 codex round 1): isSameOriginAbsoluteUrl compares an absolute
// distribution url against getRuntimeApiBaseUrl() (which reads API_BASE from
// lib/constants.ts). A raw string-prefix compare treated a protocol-relative
// base, a different host casing, or an explicit default port as a mismatch
// even when they name the same origin as the parsed URL.origin would show —
// each vi.doMock below mirrors auth-transport.test.ts's established pattern
// for exercising a different API_BASE per case.
describe('isSameOriginAbsoluteUrl (#1877)', () => {
  afterEach(() => {
    vi.doUnmock('@/lib/constants');
    vi.resetModules();
  });

  it('matches a protocol-relative API_BASE against an absolute same-origin distribution url', async () => {
    vi.doMock('@/lib/constants', () => ({ API_BASE: `//${window.location.host}/api` }));
    vi.resetModules();
    const mod = await import('@/lib/dataset-access');

    const sameOriginUrl = `${window.location.protocol}//${window.location.host}/api/datasets/1/export?format=gpkg`;
    expect(mod.isSameOriginAbsoluteUrl(sameOriginUrl)).toBe(true);
  });

  it('matches a distribution url with different host casing than the configured API_BASE', async () => {
    vi.doMock('@/lib/constants', () => ({ API_BASE: 'https://api.example.com/api' }));
    vi.resetModules();
    const mod = await import('@/lib/dataset-access');

    expect(
      mod.isSameOriginAbsoluteUrl('HTTPS://API.Example.COM/api/datasets/1/export?format=gpkg'),
    ).toBe(true);
  });

  it('matches a distribution url carrying an explicit default port the configured API_BASE omits', async () => {
    vi.doMock('@/lib/constants', () => ({ API_BASE: 'https://api.example.com/api' }));
    vi.resetModules();
    const mod = await import('@/lib/dataset-access');

    expect(
      mod.isSameOriginAbsoluteUrl('https://api.example.com:443/api/datasets/1/export?format=gpkg'),
    ).toBe(true);
  });

  it('still treats a genuinely different origin as external', async () => {
    vi.doMock('@/lib/constants', () => ({ API_BASE: 'https://api.example.com/api' }));
    vi.resetModules();
    const mod = await import('@/lib/dataset-access');

    expect(mod.isSameOriginAbsoluteUrl('https://evil.example.com/api/datasets/1/export?format=gpkg')).toBe(false);
  });

  it('still treats a same-origin url mounted outside the API path prefix as external', async () => {
    vi.doMock('@/lib/constants', () => ({ API_BASE: 'https://api.example.com/api' }));
    vi.resetModules();
    const mod = await import('@/lib/dataset-access');

    expect(mod.isSameOriginAbsoluteUrl('https://api.example.com/other/datasets/1/export?format=gpkg')).toBe(false);
  });

  it('returns false for a relative url (no origin to compare)', async () => {
    vi.doMock('@/lib/constants', () => ({ API_BASE: 'https://api.example.com/api' }));
    vi.resetModules();
    const mod = await import('@/lib/dataset-access');

    expect(mod.isSameOriginAbsoluteUrl('/datasets/1/export?format=gpkg')).toBe(false);
  });
});
