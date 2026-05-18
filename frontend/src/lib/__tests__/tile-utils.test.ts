import { buildClusterTileUrl, buildSignedTileUrl } from '@/lib/tile-utils';

describe('buildSignedTileUrl', () => {
  const mockToken = { sig: 'abc123', exp: 1700000000, scope: 'ds_test' };

  it('appends sig/exp/scope query params when token is provided', () => {
    const url = buildSignedTileUrl('my_table', mockToken, 'https://tiles.example.com');
    expect(url).toBe(
      'https://tiles.example.com/tiles/data.my_table/{z}/{x}/{y}.pbf?sig=abc123&exp=1700000000&scope=ds_test',
    );
  });

  it('returns clean URL without query params when token is null', () => {
    const url = buildSignedTileUrl('my_table', null, 'https://tiles.example.com');
    expect(url).toBe('https://tiles.example.com/tiles/data.my_table/{z}/{x}/{y}.pbf');
  });

  it('uses custom tileBaseUrl when provided', () => {
    const url = buildSignedTileUrl('tbl', mockToken, 'https://cdn.example.com/');
    expect(url).toContain('https://cdn.example.com/tiles/data.tbl/');
  });

  it('uses window.location.origin/api when tileBaseUrl is not provided', () => {
    const url = buildSignedTileUrl('tbl', mockToken);
    expect(url).toContain(`${window.location.origin}/api/tiles/data.tbl/`);
  });

  it('uses window.location.origin/api when tileBaseUrl is null', () => {
    const url = buildSignedTileUrl('tbl', null, null);
    expect(url).toBe(`${window.location.origin}/api/tiles/data.tbl/{z}/{x}/{y}.pbf`);
  });

  it('appends _v param when tileVersion is provided with token', () => {
    const url = buildSignedTileUrl('tbl', mockToken, 'https://cdn.example.com', '2026-03-20T12:00:00Z');
    expect(url).toContain('sig=abc123');
    expect(url).toContain('_v=2026-03-20T12%3A00%3A00Z');
  });

  it('appends _v param when tileVersion is provided without token', () => {
    const url = buildSignedTileUrl('tbl', null, 'https://cdn.example.com', '2026-03-20T12:00:00Z');
    expect(url).toBe('https://cdn.example.com/tiles/data.tbl/{z}/{x}/{y}.pbf?_v=2026-03-20T12%3A00%3A00Z');
  });

  it('omits _v param when tileVersion is null', () => {
    const url = buildSignedTileUrl('tbl', mockToken, 'https://cdn.example.com', null);
    expect(url).not.toContain('_v=');
  });

  it('omits _v param when tileVersion is undefined', () => {
    const url = buildSignedTileUrl('tbl', mockToken, 'https://cdn.example.com');
    expect(url).not.toContain('_v=');
  });

  it('appends cols= when extraCols is provided', () => {
    const url = buildSignedTileUrl('tbl', null, 'https://cdn.example.com', null, ['economy']);
    expect(url).toBe('https://cdn.example.com/tiles/data.tbl/{z}/{x}/{y}.pbf?cols=economy');
  });

  it('sorts and dedupes cols for stable cache keys', () => {
    const url1 = buildSignedTileUrl('tbl', null, 'https://cdn.example.com', null, ['b', 'a', 'a']);
    const url2 = buildSignedTileUrl('tbl', null, 'https://cdn.example.com', null, ['a', 'b']);
    expect(url1).toBe(url2);
    expect(url1).toContain('cols=a%2Cb');
  });

  it('omits cols= when extraCols is empty / null / undefined', () => {
    const url1 = buildSignedTileUrl('tbl', null, 'https://cdn.example.com', null, []);
    const url2 = buildSignedTileUrl('tbl', null, 'https://cdn.example.com', null, null);
    const url3 = buildSignedTileUrl('tbl', null, 'https://cdn.example.com');
    expect(url1).not.toContain('cols=');
    expect(url2).not.toContain('cols=');
    expect(url3).not.toContain('cols=');
  });

  it('combines cols with signed params', () => {
    const url = buildSignedTileUrl('tbl', mockToken, 'https://cdn.example.com', null, ['pop']);
    expect(url).toContain('sig=abc123');
    expect(url).toContain('cols=pop');
  });
});

describe('buildClusterTileUrl', () => {
  const mockToken = { sig: 'abc123', exp: 1700000000, scope: 'ds_test' };

  it('targets the cluster tile endpoint with cluster options and signed params', () => {
    const url = buildClusterTileUrl('my_table', mockToken, 'https://tiles.example.com', null, {
      clusterRadius: 64,
      clusterMaxZoom: 12,
    });

    expect(url).toBe(
      'https://tiles.example.com/tiles/clusters/data.my_table/{z}/{x}/{y}.pbf?sig=abc123&exp=1700000000&scope=ds_test&cluster_radius=64&cluster_max_zoom=12',
    );
  });

  it('supports public or embed-token cluster tiles without signed params', () => {
    const url = buildClusterTileUrl('my_table', null, 'https://tiles.example.com', 'v1', {
      clusterRadius: 48,
      clusterMaxZoom: 14,
    });

    expect(url).toBe(
      'https://tiles.example.com/tiles/clusters/data.my_table/{z}/{x}/{y}.pbf?cluster_radius=48&cluster_max_zoom=14&_v=v1',
    );
  });
});
