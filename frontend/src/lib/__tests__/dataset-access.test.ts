import type { DistributionResponse, RecordType } from '@/types/api';

// fix(#1877): isSameOriginAbsoluteUrl must compare canonical URL.origin
// values against getRuntimeApiBaseUrl() (reads API_BASE from lib/constants.ts)
// — each vi.doMock below exercises a different API_BASE per case.
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

describe('getDatasetAccessEndpoints', () => {
  it('derives no OGC, CSV or vector tile URL for an unknown record type', async () => {
    const { getDatasetAccessEndpoints } = await import('@/lib/dataset-access');
    const dataset = { id: 'ds-1', record_type: 'hologram_dataset' as RecordType, table_name: 'cloud', visibility: 'public' as const };

    expect(getDatasetAccessEndpoints(dataset, null)).toEqual({
      csvExportUrl: null,
      ogcFeaturesUrl: null,
      vectorTilesUrl: null,
    });
  });

  it('offers the vector tile URL for a public dataset only', async () => {
    const { getDatasetAccessEndpoints } = await import('@/lib/dataset-access');
    const base = { id: 'ds-1', record_type: 'vector_dataset' as RecordType, table_name: 'parks' };

    expect(getDatasetAccessEndpoints({ ...base, visibility: 'public' }, 'https://catalog.example.com/api').vectorTilesUrl)
      .toContain('/tiles/data.parks/{z}/{x}/{y}.pbf');
    for (const visibility of ['internal', 'restricted', 'private'] as const) {
      expect(getDatasetAccessEndpoints({ ...base, visibility }, 'https://catalog.example.com/api').vectorTilesUrl).toBeNull();
    }
  });

  it('keeps an externally hosted vector tile distribution on a non-public dataset', async () => {
    const { getDatasetAccessEndpoints } = await import('@/lib/dataset-access');
    const dataset = { id: 'ds-1', record_type: 'vector_dataset' as RecordType, table_name: 'parks', visibility: 'private' as const };
    const dist = (url: string) => ({ distribution_type: 'vector_tiles', url }) as DistributionResponse;

    expect(
      getDatasetAccessEndpoints(dataset, 'https://catalog.example.com/api', [
        dist('/tiles/data.parks/{z}/{x}/{y}.pbf'),
        dist('https://tiles.example.org/{z}/{x}/{y}.pbf'),
      ]).vectorTilesUrl,
    ).toBe('https://tiles.example.org/{z}/{x}/{y}.pbf');
    expect(
      getDatasetAccessEndpoints(dataset, 'https://catalog.example.com/api', [
        dist('https://partner.example/api/tiles/data.parks/{z}/{x}/{y}.pbf'),
      ]).vectorTilesUrl,
    ).toBe('https://partner.example/api/tiles/data.parks/{z}/{x}/{y}.pbf');
  });
});
