import { cookieAuthAvailable, readCsrfCookie, cookieAuthHeaders } from '@/lib/auth-transport';

// fix(#1302): the refresh token moved into an httpOnly cookie. These pin the
// two decisions that gate the flow: whether the cookie can work at all (it only
// replays to the origin that set it), and how the double-submit CSRF token is
// carried.

vi.mock('@/lib/constants', () => ({ API_BASE: '/api' }));

describe('cookieAuthAvailable', () => {
  it('is true for the default relative API base (same origin by construction)', () => {
    expect(cookieAuthAvailable()).toBe(true);
  });

  it('is true for an absolute base on this origin', async () => {
    vi.doMock('@/lib/constants', () => ({ API_BASE: `${window.location.origin}/api` }));
    vi.resetModules();
    const mod = await import('@/lib/auth-transport');
    expect(mod.cookieAuthAvailable()).toBe(true);
    vi.doUnmock('@/lib/constants');
    vi.resetModules();
  });

  it('is false for a cross-origin API base, which cannot replay the cookie', async () => {
    vi.doMock('@/lib/constants', () => ({ API_BASE: 'https://api.elsewhere.example/v1' }));
    vi.resetModules();
    const mod = await import('@/lib/auth-transport');
    expect(mod.cookieAuthAvailable()).toBe(false);
    vi.doUnmock('@/lib/constants');
    vi.resetModules();
  });
});

describe('readCsrfCookie', () => {
  afterEach(() => {
    document.cookie = 'geolens_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
  });

  it('returns null when the cookie is absent', () => {
    expect(readCsrfCookie()).toBeNull();
  });

  it('reads the token, and is not confused by neighbouring cookies', () => {
    document.cookie = 'other=first; path=/';
    document.cookie = 'geolens_csrf=csrf-value-123; path=/';
    expect(readCsrfCookie()).toBe('csrf-value-123');
  });
});

describe('cookieAuthHeaders', () => {
  afterEach(() => {
    document.cookie = 'geolens_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
  });

  it('opts in without a CSRF token before one exists (first login)', () => {
    expect(cookieAuthHeaders()).toEqual({ 'X-GeoLens-Auth-Mode': 'cookie' });
  });

  it('echoes the CSRF cookie back as a header once set', () => {
    document.cookie = 'geolens_csrf=csrf-value-123; path=/';
    expect(cookieAuthHeaders()).toEqual({
      'X-GeoLens-Auth-Mode': 'cookie',
      'X-CSRF-Token': 'csrf-value-123',
    });
  });

  it('sends nothing when cookie mode is unavailable, leaving the legacy call intact', async () => {
    vi.doMock('@/lib/constants', () => ({ API_BASE: 'https://api.elsewhere.example/v1' }));
    vi.resetModules();
    const mod = await import('@/lib/auth-transport');
    document.cookie = 'geolens_csrf=csrf-value-123; path=/';
    expect(mod.cookieAuthHeaders()).toEqual({});
    vi.doUnmock('@/lib/constants');
    vi.resetModules();
  });
});
